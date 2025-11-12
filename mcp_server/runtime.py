"""Shared MCP server runtime utilities for Protos.

Provides a single entry point for building FastMCP servers that leverage
`ServerContext`, zero-config Protos processors, and the common tool suite.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Iterable, Optional
import sys

from mcp.server.fastmcp import FastMCP

from .context import ServerContext
from .config import ServerConfig
# Avoid heavyweight imports at module import time; import lazily in default_tools

ToolFactory = Callable[[ServerContext], Iterable]


def default_tools(context: ServerContext) -> Iterable:
    """Instantiate the standard tool suite for the given context."""

    from .tools.context import ContextTools
    from .tools.config import ConfigTools
    from .tools.guide import ProtoGuideTools
    from .tools.entity.discovery import EntityDiscoveryTools
    from .tools.entity.operations import EntityOperationTools
    from .tools.dataset.operations import DatasetOperationTools
    from .tools.loader import SequenceLoaderTools
    from .tools.sequence_workflow import SequenceWorkflowTools

    try:
        from .tools.model import ModelManagerTools
    except ImportError as exc:  # pragma: no cover - optional dependency
        ModelManagerTools = None
        print(f"ModelManagerTools unavailable: {exc}", file=sys.stderr)

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
            print(f"Skipping {attr}: {exc}", file=sys.stderr)

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

    tools.extend([
        SequenceLoaderTools(context),
        SequenceWorkflowTools(context),
    ])

    for tool_cls in optional_imports:
        tools.append(tool_cls(context))

    return tuple(tools)


def register_tools(server: FastMCP, context: ServerContext, tools: Optional[Iterable] = None) -> None:
    """Register the provided tools with the MCP server."""

    for tool in tools or default_tools(context):
        tool.register(server)
        print(f"Registered {tool.__class__.__name__}", file=sys.stderr)


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
        print(f"Initializing Protos MCP server with data root: {cfg.data_root}", file=sys.stderr)

        context = ServerContext.initialize(cfg)
        register_tools(server, context, tool_factory(context))

        try:
            yield context
        finally:
            print("Shutting down Protos MCP server", file=sys.stderr)

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
