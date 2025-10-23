"""Codex CLI entry point for the Protos MCP server."""

from pathlib import Path
import sys

# Ensure the repository root is importable when the file is executed directly.
sys.path.insert(0, str(Path(__file__).parent))

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server


SERVER_NAME = "Protos Codex Server"


def build_server():
    """Construct the FastMCP server wired to the shared runtime."""

    config = ServerConfig()
    return create_server(SERVER_NAME, config=config)


mcp = build_server()


def main():
    """Launch the server using FastMCP's standard runner."""

    if "--help" in sys.argv or "-h" in sys.argv:
        print("Protos Codex MCP Server")
        print("\nUsage:")
        print("  python codex_server.py                 # Run with STDIO transport")
        print("  python codex_server.py --sse           # Run with SSE transport")
        print("  python codex_server.py --http          # Run with streamable HTTP transport")
        print("  mcp install codex_server.py            # Install for MCP-compatible clients")
        return

    transport = "stdio"
    if "--sse" in sys.argv:
        transport = "sse"
    elif "--http" in sys.argv or "--streamable-http" in sys.argv:
        transport = "streamable-http"

    try:
        mcp.run(transport)
    except KeyboardInterrupt:
        print("\nServer stopped by user", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"Server error: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
