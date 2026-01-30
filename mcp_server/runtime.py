"""Shared MCP server runtime utilities for Protos.

Provides a single entry point for building FastMCP servers that leverage
`ServerContext`, zero-config Protos processors, and the common tool suite.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Iterable, Optional

from mcp.server.fastmcp import FastMCP

from .context import ServerContext
from .config import ServerConfig
from .core.logging_config import get_logger, log_server_event
from .resources import register_all as register_resources_and_prompts

# Avoid heavyweight imports at module import time; import lazily in default_tools
logger = get_logger("runtime")

ToolFactory = Callable[[ServerContext], Iterable]


def default_tools(context: ServerContext) -> Iterable:
    """Instantiate the standard tool suite for the given context."""

    from .tools.context import ContextTools
    from .tools.config import ConfigTools
    from .tools.guide import ProtoGuideTools
    from .tools.entity.discovery import EntityDiscoveryTools
    from .tools.entity.operations import EntityOperationTools
    from .tools.dataset.operations import DatasetOperationTools
    from .tools.loader import SequenceLoaderTools, InputLoaderTools

    try:
        from .tools.model import ModelManagerTools
    except ImportError as exc:  # pragma: no cover - optional dependency
        ModelManagerTools = None
        logger.debug("ModelManagerTools unavailable", extra={"error": str(exc)})

    optional_imports = []
    for module_path, attr in [
        ("mcp_server.tools.analysis.embedding", "EmbeddingAnalysisTools"),
        ("mcp_server.tools.analysis.property", "PropertyAnalysisTools"),
        ("mcp_server.tools.analysis.structure", "StructureAnalysisTools"),
        ("mcp_server.tools.analysis.ligand", "LigandAnalysisTools"),
        ("mcp_server.tools.analysis.grn", "GRNAnalysisTools"),
        ("mcp_server.tools.analysis.sequence", "SequenceAnalysisTools"),
    ]:
        try:
            module = __import__(module_path, fromlist=[attr])
            optional_imports.append(getattr(module, attr))
        except ImportError as exc:  # pragma: no cover - optional dependency
            logger.debug(f"Skipping {attr}", extra={"error": str(exc)})

    tools = [
        ProtoGuideTools(context),
        ContextTools(context),
        ConfigTools(context),
        EntityDiscoveryTools(context),
        EntityOperationTools(context),
        DatasetOperationTools(context),
    ]

    if ModelManagerTools is not None:
        tools.append(ModelManagerTools(context))

    tools.append(SequenceLoaderTools(context))
    tools.append(InputLoaderTools(context))

    for tool_cls in optional_imports:
        tools.append(tool_cls(context))

    return tuple(tools)


def register_tools(server: FastMCP, context: ServerContext, tools: Optional[Iterable] = None) -> None:
    """Register the provided tools with the MCP server."""

    for tool in tools or default_tools(context):
        tool.register(server)
        logger.debug(f"Registered {tool.__class__.__name__}")

    # Auto-populate catalog from all registered MCP tools
    _sync_catalog_from_server(server, context)

    catalog_path = context.persist_tool_catalog()
    if catalog_path:
        logger.info("Tool catalog written", extra={"path": str(catalog_path)})


def _sync_catalog_from_server(server: FastMCP, context: ServerContext) -> None:
    """Populate tool catalog from FastMCP's registered tools."""
    tool_mgr = getattr(server, "_tool_manager", None)
    if not tool_mgr:
        return

    catalog = context.tool_catalog
    for name, tool in tool_mgr._tools.items():
        # Skip if already registered via explicit metadata
        if catalog.resolve(name) is not None:
            continue

        # Extract description from tool
        description = getattr(tool, "description", None) or ""
        if not description and hasattr(tool, "fn") and tool.fn.__doc__:
            description = tool.fn.__doc__.strip().split("\n")[0]

        # Parse parameters from JSON schema
        params_schema = getattr(tool, "parameters", {}) or {}
        properties = params_schema.get("properties", {})
        required = set(params_schema.get("required", []))
        parameters = []
        for param_name, param_info in properties.items():
            if param_name == "ctx":
                continue  # Skip context parameter
            param_entry = {"name": param_name, "type": param_info.get("type", "any")}
            if param_name not in required:
                param_entry["optional"] = True
            if "default" in param_info:
                param_entry["default"] = param_info["default"]
            parameters.append(param_entry)

        # Infer group from tool name prefix
        group = _infer_tool_group(name)

        catalog.register(
            name=name,
            group=group,
            description=description[:200] if description else "",
            parameters=parameters,
            returns={},
            aliases=[],
            deprecated=False,
            tags=_infer_tags(name, group),
            notes=None,
        )


def _infer_tool_group(name: str) -> str:
    """Infer tool group from name prefix or content."""
    # Check prefixes first
    prefixes = [
        ("context_", "context"),
        ("config_", "config"),
        ("dataset_", "dataset"),
        ("entity_", "entity"),
        ("download_", "entity"),
        ("load_", "load"),
        ("list_", "list"),
        ("save_", "save"),
        ("sequence_", "sequence"),
        ("structure_", "structure"),
        ("ligand_", "ligand"),
        ("grn_", "grn"),
        ("property_", "property"),
        ("embedding_", "embedding"),
        ("model_", "model"),
        ("guide_", "guide"),
        ("input_", "input"),
        ("align_", "sequence"),
        ("cluster_", "sequence"),
        ("calculate_", "analysis"),
        ("filter_", "analysis"),
        ("extract_", "analysis"),
        ("get_", "query"),
        ("create_", "create"),
        ("add_", "update"),
        ("assign_", "grn"),
        ("apply_", "analysis"),
        ("delete_", "entity"),
        ("describe_", "model"),
        ("export_", "export"),
        ("record_", "property"),
        ("merge_", "dataset"),
        ("register_", "loader"),
        ("search_", "query"),
        ("superimpose_", "structure"),
        ("translate_", "sequence"),
        ("find_", "query"),
    ]
    for prefix, group in prefixes:
        if name.startswith(prefix):
            return group

    # Check content keywords
    if "ligand" in name:
        return "ligand"
    if "structure" in name:
        return "structure"
    if "sequence" in name:
        return "sequence"
    if "property" in name:
        return "property"
    if "grn" in name:
        return "grn"

    return "misc"


def _infer_tags(name: str, group: str) -> list:
    """Infer tags from tool name."""
    tags = [group]
    if "grn" in name:
        tags.append("grn")
    if "sequence" in name or "align" in name:
        tags.append("sequence")
    if "structure" in name:
        tags.append("structure")
    if "ligand" in name:
        tags.append("ligand")
    if "property" in name:
        tags.append("property")
    if "dataset" in name:
        tags.append("dataset")
    if "load" in name or "list" in name:
        tags.append("query")
    if "download" in name or "register" in name:
        tags.append("loader")
    return list(set(tags))


def add_server_info_tool(server: FastMCP, label: str) -> None:
    """Attach a diagnostic tool that reports server and registry stats."""

    @server.tool()
    def get_server_info(ctx) -> dict:
        try:
            # FastMCP contexts expose lifespan context either directly or via request_context
            if hasattr(ctx, "lifespan_context"):
                context = ctx.lifespan_context
            elif hasattr(ctx, "request_context") and hasattr(ctx.request_context, "lifespan_context"):
                context = ctx.request_context.lifespan_context
            else:
                return {
                    "server": label,
                    "status": "running",
                    "note": "Context unavailable",
                }

            stats = context.get_stats() if hasattr(context, "get_stats") else {}
            return {
                "server": label,
                "status": "running",
                "stats": stats,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "server": label,
                "status": "error",
                "error": str(exc),
            }


def build_lifespan(
    *,
    config: Optional[ServerConfig] = None,
    tool_factory: Optional[ToolFactory] = None,
):
    """Create a lifespan context manager for FastMCP using ServerContext."""

    tool_factory = tool_factory or default_tools

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[ServerContext]:
        cfg = config or ServerConfig()
        log_server_event("startup", data_root=str(cfg.data_root))

        context = ServerContext.initialize(cfg)
        register_tools(server, context, tool_factory(context))

        # Register MCP resources and prompts (2025-06-18 best practices)
        register_resources_and_prompts(server, context)

        try:
            yield context
        finally:
            log_server_event("shutdown")

    return lifespan


def create_server(
    name: str,
    *,
    config: Optional[ServerConfig] = None,
    tool_factory: Optional[ToolFactory] = None,
) -> FastMCP:
    """Construct a FastMCP server wired to the shared Protos runtime."""

    lifespan = build_lifespan(config=config, tool_factory=tool_factory)
    server = FastMCP(name, lifespan=lifespan)
    add_server_info_tool(server, name)
    return server
