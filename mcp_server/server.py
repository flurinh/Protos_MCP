"""
Base MCP Server implementation with core functionality and dynamic model loading.
Located in: Protos_MCP/mcp_server/server.py
"""
from mcp.server.fastmcp import FastMCP, Context as ToolContext
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import os
import sys
import pandas as pd
from typing import Dict, Any, Optional, List
import asyncio

# --- Relative imports for modules within the mcp_server package ---
from .models import (  # Use ".models" for relative import
    MCPModelBase, OllamaMCPModel, ClaudeMCPModel,
    OLLAMA_BASE_URL as DEFAULT_OLLAMA_URL_FROM_MODELS,
    DEFAULT_OLLAMA_MODEL_NAME as DEFAULT_OLLAMA_MODEL_FROM_MODELS
)


@dataclass
class ModelInitConfig:
    """Configuration for initializing a model within the lifespan."""
    model_id: str
    model_type: str
    params: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ProtosContext:
    """Typed context for our protos application"""
    processors: Dict[str, Any] = field(default_factory=dict)
    initialized: bool = False
    base_path: Optional[str] = None
    data: Dict[str, pd.DataFrame] = field(default_factory=dict)
    sequences: Dict[str, Dict[str, str]] = field(default_factory=dict)
    datasets: Dict[str, List[str]] = field(default_factory=dict)
    models: Dict[str, MCPModelBase] = field(default_factory=dict)

@asynccontextmanager
async def protos_lifespan(server_instance: 'BaseMCPServer') -> AsyncIterator[ProtosContext]:
    """
    Manage protos lifecycle with persistent state.
    Models are initialized based on configurations added to the server_instance.
    """
    print("Initializing protos context and dynamically configured models...", file=sys.stderr)
    context = ProtosContext()

    context.base_path = os.getenv("PROTOS_BASE_PATH")
    if context.base_path:
        os.makedirs(context.base_path, exist_ok=True)
        context.initialized = True
        print(f"Protos base path set to: {context.base_path}", file=sys.stderr)
    else:
        print("Warning: PROTOS_BASE_PATH not set. `list_files` may require explicit paths.", file=sys.stderr)

    for model_config in server_instance.get_model_init_configs():
        model_to_add: Optional[MCPModelBase] = None
        print(f"Lifespan: Attempting to initialize model_id='{model_config.model_id}', type='{model_config.model_type}'", file=sys.stderr)

        if model_config.model_type == "ollama":
            model_to_add = OllamaMCPModel(
                model_id=model_config.model_id,
                ollama_model_name=model_config.params.get("ollama_model_name", DEFAULT_OLLAMA_MODEL_FROM_MODELS),
                ollama_base_url=model_config.params.get("ollama_base_url", DEFAULT_OLLAMA_URL_FROM_MODELS),
                default_params=model_config.params.get("default_params", {})
            )
            print(f"  Ollama model '{model_config.params.get('ollama_model_name', DEFAULT_OLLAMA_MODEL_FROM_MODELS)}' configured for id '{model_config.model_id}'.", file=sys.stderr)

        elif model_config.model_type == "claude":
            claude_api_key = model_config.params.get("anthropic_api_key", os.getenv("ANTHROPIC_API_KEY"))
            claude_model_name_param = model_config.params.get("claude_model_name", "claude-3-haiku-20240307") # Default if not in params
            if not claude_api_key and model_config.params.get("require_key", True):
                 print(f"  WARNING: Claude model '{model_config.model_id}' requires ANTHROPIC_API_KEY, but not found.", file=sys.stderr)
            model_to_add = ClaudeMCPModel(
                model_id=model_config.model_id,
                anthropic_api_key=claude_api_key,
                claude_model_name=claude_model_name_param
            )
            print(f"  Claude model '{claude_model_name_param}' configured for id '{model_config.model_id}'.", file=sys.stderr)

        if model_to_add:
            context.models[model_to_add.model_id] = model_to_add
        else:
            print(f"  Warning: Unknown model type '{model_config.model_type}' for id '{model_config.model_id}'. Skipping.", file=sys.stderr)

    startup_tasks = [model._startup() for model in context.models.values()]
    if startup_tasks:
        await asyncio.gather(*startup_tasks)
    print(f"Lifespan: Initialized and started {len(context.models)} models.", file=sys.stderr)

    try:
        yield context
    finally:
        print("Cleaning up protos resources and shutting down models...", file=sys.stderr)
        shutdown_tasks = [model._shutdown() for model in context.models.values()]
        if shutdown_tasks:
            await asyncio.gather(*shutdown_tasks)
        print("All models shut down.", file=sys.stderr)


class BaseMCPServer:
    def __init__(self, server_name="ProtosMCPServer"):
        self._model_init_configs: List[ModelInitConfig] = []
        self.mcp = FastMCP(server_name, lifespan=lambda s: protos_lifespan(self))
        self._register_base_tools()

    def _register_base_tools(self):
        @self.mcp.tool()
        def list_available_models(ctx: ToolContext) -> Dict[str, Dict[str, Any]]:
            protos_ctx: ProtosContext = ctx.request_context.lifespan_context
            available_models = {}
            for model_id, model_instance in protos_ctx.models.items():
                details = "N/A"
                if hasattr(model_instance, 'ollama_model_name'): # Check specific attribute
                    details = getattr(model_instance, 'ollama_model_name')
                elif hasattr(model_instance, 'claude_model_name'): # Check specific attribute
                    details = getattr(model_instance, 'claude_model_name')

                available_models[model_id] = {
                    "type": model_instance.__class__.__name__,
                    "ready": model_instance.is_ready() if hasattr(model_instance, 'is_ready') else False,
                    "details": details
                }
            return available_models

        @self.mcp.tool(name="invoke_llm")
        async def invoke_llm_tool(
            ctx: ToolContext,
            model_id: str,
            messages: List[Dict[str, str]],
            temperature: Optional[float] = None,
            max_tokens: Optional[int] = None,
            **kwargs: Any
        ) -> Dict[str, str]:
            protos_ctx: ProtosContext = ctx.request_context.lifespan_context
            model = protos_ctx.models.get(model_id)

            if not model:
                return {"role": "system", "content": f"Error: Model with ID '{model_id}' not found."}

            is_ready = model.is_ready() if hasattr(model, 'is_ready') else True # Assume ready if method missing
            if not is_ready:
                return {"role": "system", "content": f"Error: Model '{model_id}' is not ready."}

            if not isinstance(messages, list) or not all(isinstance(m, dict) and "role" in m and "content" in m for m in messages):
                return {"role": "system", "content": "Error: 'messages' must be a list of dictionaries with 'role' and 'content' keys."}

            model_params = {"temperature": temperature, "max_tokens": max_tokens, **kwargs}
            model_params = {k: v for k, v in model_params.items() if v is not None}

            try:
                response_message = await model.generate_response_async(
                    messages,
                    **model_params
                )
                return response_message
            except Exception as e:
                print(f"Error invoking LLM '{model_id}': {e}", file=sys.stderr)
                return {"role": "system", "content": f"Error during model invocation: {str(e)}"}

        # Example: Add list_files tool directly here or ensure protos_tools.py handles it
        @self.mcp.tool()
        def list_files(ctx: ToolContext, directory: Optional[str] = None) -> str:
            # (Implementation from previous versions - ensure protos_ctx.base_path is handled)
            protos_ctx: ProtosContext = ctx.request_context.lifespan_context
            # ... (rest of list_files implementation)
            if not protos_ctx.initialized and directory is None:
                 return "Error: Server context not fully initialized for default path, and no specific directory provided. Set PROTOS_BASE_PATH or provide a directory."
            try:
                target_directory = directory
                if target_directory is None:
                    if protos_ctx.base_path: target_directory = protos_ctx.base_path
                    else: return "Error: No directory specified and no default base_path configured."
                elif not os.path.isabs(target_directory):
                    if protos_ctx.base_path: target_directory = os.path.join(protos_ctx.base_path, target_directory)
                    else: return f"Error: Relative path '{directory}' provided, but no base_path is configured."
                target_directory = os.path.abspath(target_directory)
                if not os.path.exists(target_directory): return f"Error: Directory {target_directory} does not exist"
                if not os.path.isdir(target_directory): return f"Error: {target_directory} is not a directory"
                items = os.listdir(target_directory)
                subdirs = sorted([item + "/" for item in items if os.path.isdir(os.path.join(target_directory, item))])
                files = sorted([item for item in items if os.path.isfile(os.path.join(target_directory, item))])
                results = [f"Contents of {target_directory}:"]
                if subdirs: results.append("\nDirectories:"); results.extend(subdirs)
                if files: results.append("\nFiles:"); results.extend(files)
                if not subdirs and not files: results.append("\nDirectory is empty")
                return "\n".join(results)
            except Exception as e: return f"Failed to list files: {str(e)}"


    def add_model(self, model_id: str, model_type: str, **params: Any):
        """Registers a model configuration to be initialized by the server's lifespan manager."""
        self._model_init_configs.append(
            ModelInitConfig(model_id=model_id, model_type=model_type, params=params)
        )
        print(f"BaseMCPServer: Queued model for init: id='{model_id}', type='{model_type}' with params: {params}", file=sys.stderr)

    def get_model_init_configs(self) -> List[ModelInitConfig]:
        return self._model_init_configs

    def register_tool_fn(self, func, name: Optional[str] = None): # Renamed to avoid conflict
        """Allows registering additional tools on the MCP instance."""
        self.mcp.tool(name=name)(func)

    def run(self):
        if not self._model_init_configs:
            print("Warning: No models have been added to the server via `add_model()`.", file=sys.stderr)
        print(f"Starting {self.mcp} MCP Server...", file=sys.stderr)
        self.mcp.run()