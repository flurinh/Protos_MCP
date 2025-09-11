#!/usr/bin/env python
"""
Ollama MCP server runner.
"""
import httpx
from .server import BaseMCPServer
from .protos_tools import register_protos_tools

# Configuration
OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma3:1b"

def main():
    """Start the Ollama MCP server"""
    # Create server instance
    server = BaseMCPServer(server_name="OllamaProtosServer")
    
    # Register Protos tools
    register_protos_tools(server)
    print(DEFAULT_OLLAMA_MODEL)
    # Add Ollama model
    server.add_model(
        model_id="ollama-model",
        model_type="ollama",
        ollama_model_name=DEFAULT_OLLAMA_MODEL,
        ollama_base_url=OLLAMA_BASE_URL,
        default_params={"temperature": 0.7, "top_p": 0.9}
    )
    
    # Basic check to see if Ollama is accessible
    try:
        httpx.get(f"{OLLAMA_BASE_URL}/api/tags")  # Simple endpoint to check connection
        print(f"Successfully connected to Ollama at {OLLAMA_BASE_URL}.")
        print(f"Ensure model '{DEFAULT_OLLAMA_MODEL}' is pulled.")
    except:
        print(f"ERROR: Could not connect to Ollama at {OLLAMA_BASE_URL}. Is Ollama running?")
        print("If Ollama is running, ensure it's accessible and the URL is correct.")
        return
    
    # Run the server
    print("Starting Ollama Protos MCP server...")
    server.run()

if __name__ == "__main__":
    main()