"""
Protos MCP Server for Ollama - Clean implementation leveraging Protos data management.

This server provides Model Context Protocol access to Protos functionality
with Ollama as the backend LLM.
"""

import sys
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator

# Add necessary paths
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
from mcp_server.context import ServerContext
from mcp_server.config import ServerConfig
from mcp_server.tools.entity.discovery import EntityDiscoveryTools
from mcp_server.tools.entity.operations import EntityOperationTools
from mcp_server.tools.dataset.operations import DatasetOperationTools
from mcp_server.tools.analysis.property import PropertyAnalysisTools
from mcp_server.tools.analysis.structure import StructureAnalysisTools
from mcp_server.tools.analysis.ligand import LigandAnalysisTools
from mcp_server.tools.analysis.grn import GRNAnalysisTools
from mcp_server.tools.analysis.sequence import SequenceAnalysisTools
from mcp_server.tools.guide import ProtoGuideTools


# Server lifespan management
@asynccontextmanager
async def protos_lifespan(server: FastMCP) -> AsyncIterator[ServerContext]:
    """Initialize Protos infrastructure on server startup."""
    print("Initializing Protos MCP Server for Ollama...", file=sys.stderr)
    
    try:
        # Load configuration
        config = ServerConfig()
        print(f"Data root resolved to: {config.data_root}", file=sys.stderr)
        
        # Initialize core components
        context = ServerContext.initialize(config)
        
        # Register all tools
        register_tools(server, context)
        
        print("Protos MCP Server for Ollama initialized successfully", file=sys.stderr)
        yield context
        
    except Exception as e:
        print(f"Failed to initialize server: {e}", file=sys.stderr)
        raise
    finally:
        print("Shutting down Protos MCP Server for Ollama...", file=sys.stderr)


def register_tools(server: FastMCP, context: ServerContext):
    """Register all tool categories with the server."""
    print("Registering tools...", file=sys.stderr)
    
    # Initialize tool instances
    tools = [
        ProtoGuideTools(context),  # Guide tools first for discoverability
        EntityDiscoveryTools(context),
        EntityOperationTools(context),
        DatasetOperationTools(context),
        PropertyAnalysisTools(context),
        StructureAnalysisTools(context),
        LigandAnalysisTools(context),
        GRNAnalysisTools(context),
        SequenceAnalysisTools(context),
        # More tools will be added here as implemented
    ]
    
    # Register each tool
    for tool in tools:
        tool.register(server)
        print(f"Registered {tool.__class__.__name__}", file=sys.stderr)


# Create the MCP server
mcp = FastMCP("Protos MCP Server for Ollama", lifespan=protos_lifespan)


# Basic test tool to verify server is working
@mcp.tool()
def get_server_info(ctx) -> dict:
    """Get information about the server and its configuration."""
    try:
        # Access the lifespan context properly
        if hasattr(ctx, 'lifespan_context'):
            context = ctx.lifespan_context
        elif hasattr(ctx, 'request_context') and hasattr(ctx.request_context, 'lifespan_context'):
            context = ctx.request_context.lifespan_context
        else:
            # Fallback if context structure is different
            return {
                "server": "Protos MCP Server for Ollama",
                "version": "0.1.0",
                "status": "running",
                "note": "Unable to access full context"
            }
        
        return {
            "server": "Protos MCP Server for Ollama",
            "version": "0.1.0",
            "stats": context.get_stats() if hasattr(context, 'get_stats') else {}
        }
    except Exception as e:
        return {
            "server": "Protos MCP Server for Ollama",
            "version": "0.1.0",
            "error": str(e)
        }


def main():
    """Run the server."""
    # Check if we're running via MCP
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Protos MCP Server for Ollama")
        print("\nUsage:")
        print("  python ollama_server.py        # Run as MCP server")
        print("  mcp install ollama_server.py   # Install for Ollama integration")
        print("\nNote: Ensure Ollama is running and accessible at http://localhost:11434")
        return
    
    # Run the server
    try:
        mcp.run()
    except KeyboardInterrupt:
        print("\nServer stopped by user", file=sys.stderr)
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()