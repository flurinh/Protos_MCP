#!/usr/bin/env python
"""
Claude MCP server runner.
"""
from .server import BaseMCPServer
from .protos_tools import register_protos_tools

def main():
    """Start the Claude MCP server"""
    # Create server instance
    server = BaseMCPServer(server_name="ClaudeProtosServer")
    
    # Register Protos tools
    register_protos_tools(server)
    
    # No need to register Claude model since it's built-in to MCP
    
    # Run the server
    print("Starting Claude Protos MCP server...")
    server.run()

if __name__ == "__main__":
    main()