"""Ollama-flavoured entry point for the Protos MCP server."""

import sys
from pathlib import Path

# Ensure repository root is on the path when executed directly
sys.path.insert(0, str(Path(__file__).parent))

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server


SERVER_NAME = "Protos MCP Server for Ollama"


def build_server() -> "FastMCP":
    """Construct the FastMCP server wired to the shared runtime."""

    config = ServerConfig()
    return create_server(SERVER_NAME, config=config)


mcp = build_server()


def main():
    """Run the server."""
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Protos MCP Server for Ollama")
        print("\nUsage:")
        print("  python ollama_server.py        # Run as MCP server")
        print("  mcp install ollama_server.py   # Install for Ollama integration")
        print("\nNote: Ensure Ollama is running and accessible at http://localhost:11434")
        return

    try:
        mcp.run()
    except KeyboardInterrupt:
        print("\nServer stopped by user", file=sys.stderr)
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
