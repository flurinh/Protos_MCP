"""
Base MCP Server implementation with core functionality.
"""
from mcp.server.fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
import os
import sys
import pandas as pd
from typing import Dict, Any, Optional, List, Union, Tuple
from pathlib import Path

# Define context types for type safety
@dataclass
class ProtosContext:
    """Typed context for our protos application"""
    processors: Dict[str, Any]  # Store processor instances
    initialized: bool
    base_path: Optional[str]
    data: Dict[str, pd.DataFrame]  # Store data frames
    sequences: Dict[str, Dict[str, str]]  # Store sequences
    datasets: Dict[str, List[str]]  # Store datasets

# Lifespan management for our MCP server
@asynccontextmanager
async def protos_lifespan(server: FastMCP) -> AsyncIterator[ProtosContext]:
    """Manage protos lifecycle with persistent state"""
    # Initialize on startup
    print("Initializing protos context", file=sys.stderr)
    context = ProtosContext(
        processors={},
        initialized=False,
        base_path=None,
        data={},
        sequences={},
        datasets={}
    )

    try:
        yield context
    finally:
        # Cleanup on shutdown
        print("Cleaning up protos resources", file=sys.stderr)
        # Perform any necessary cleanup here

class BaseMCPServer:
    """
    Base class for MCP Servers with common functionality.
    """
    def __init__(self, server_name="ProtosMCPServer"):
        self.mcp = FastMCP(server_name, lifespan=protos_lifespan)
        self.register_tools()
        
    def register_tools(self):
        """Register basic tools that are common across all model backends"""
        # Basic system tools
        @self.mcp.tool()
        def say_hello() -> str:
            return "Hey there, this is the Protos MCP Server!"
            
        @self.mcp.tool()
        def import_protos(ctx: Context) -> str:
            """Import the protos library and verify it works"""
            try:
                import protos
                return f"Successfully imported protos library. Version: {protos.__version__ if hasattr(protos, '__version__') else 'unknown'}"
            except ImportError as e:
                return f"Failed to import protos: {str(e)}"
                
        @self.mcp.tool()
        def list_files(ctx: Context, directory: Optional[str] = None) -> str:
            """List files in a directory"""
            protos_ctx = ctx.request_context.lifespan_context
            
            if not protos_ctx.initialized:
                return "Error: You must initialize the folder structure first using initialize_folders"
                
            try:
                # Determine which directory to list
                if directory is None:
                    directory = protos_ctx.base_path
                else:
                    # If relative path, make it absolute
                    if not os.path.isabs(directory):
                        directory = os.path.join(protos_ctx.base_path, directory)
                        
                # Check if directory exists
                if not os.path.exists(directory):
                    return f"Error: Directory {directory} does not exist"
                    
                if not os.path.isdir(directory):
                    return f"Error: {directory} is not a directory"
                    
                # List files and directories
                files = []
                subdirs = []
                
                for item in os.listdir(directory):
                    item_path = os.path.join(directory, item)
                    if os.path.isdir(item_path):
                        subdirs.append(item)
                    else:
                        files.append(item)
                        
                # Format results
                results = [f"Contents of {directory}:"]
                
                if subdirs:
                    results.append("\nDirectories:")
                    for subdir in sorted(subdirs):
                        results.append(f"- {subdir}/")
                        
                if files:
                    results.append("\nFiles:")
                    for file in sorted(files):
                        results.append(f"- {file}")
                        
                if not subdirs and not files:
                    results.append("\nDirectory is empty")
                    
                return "\n".join(results)
            except Exception as e:
                return f"Failed to list files: {str(e)}"
                
    def run(self):
        """Run the MCP server"""
        self.mcp.run()

