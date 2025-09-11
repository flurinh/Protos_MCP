#!/usr/bin/env python
"""
Unified runner for MCP server.
Located in: Protos_MCP/run.py
"""
import argparse
import sys
import os

# --- Add the project root to sys.path to allow mcp_server imports ---
# This ensures that 'from mcp_server.server import BaseMCPServer' works
# when run.py is executed from the Protos_MCP directory.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# ---

from mcp_server.server import BaseMCPServer
from mcp_server.protos_tools import register_protos_tools
from mcp_server.config import ( # Imports from mcp_server/config.py
    get_config,
    # get_data_path, # If used by runner
    OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL # This should be "llama3.2"
)

def main():
    parser = argparse.ArgumentParser(description="Run the Protos MCP server with different models")
    parser.add_argument(
        "--model",
        choices=["claude", "ollama"], # Keep choices simple
        default="claude", # Default to claude
        help="Primary model backend to use (default: claude)"
    )
    parser.add_argument(
        "--ollama-model",
        default=DEFAULT_OLLAMA_MODEL, # From mcp_server.config, should be "llama3.2"
        help=f"Ollama model name to use (default: {DEFAULT_OLLAMA_MODEL})"
    )
    parser.add_argument(
        "--ollama-url",
        default=OLLAMA_BASE_URL, # From mcp_server.config
        help=f"Ollama API URL (default: {OLLAMA_BASE_URL})"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        help="Model temperature (0.0-1.0). Applied if model supports it."
    )
    # --data-path argument can be used to set PROTOS_BASE_PATH environment variable if desired
    # parser.add_argument("--data-path", help="Path to Protos data directory")

    args = parser.parse_args()

    # Create server instance
    # Server name can be generic or reflect the primary model
    server_instance = BaseMCPServer(server_name=f"ProtosMCPServer-{args.model.capitalize()}")
    print(f"Using DEFAULT_OLLAMA_MODEL from config: {DEFAULT_OLLAMA_MODEL} for argparse default.")


    # --- Always add available models based on some logic or flags ---
    # Here, we'll add Ollama if specified or as a secondary option.
    # And Claude if specified or as a secondary option.

    # Configure and add Ollama model
    # You can decide if Ollama is always added, or only if args.model is "ollama"
    # For this example, let's add it if chosen, or make it always available
    # but let runner --model control the "primary" for naming/logging.

    # Check Ollama reachability only if it's going to be actively used or added
    ollama_model_to_use_in_runner = args.ollama_model # This will be "llama3.2" by default
    ollama_config_params = get_config("ollama").copy()
    if args.temperature is not None: # Apply general temperature if provided
        ollama_config_params["temperature"] = args.temperature

    try:
        import httpx
        try:
            # Quick check to see if Ollama server is responsive
            httpx.get(f"{args.ollama_url}/api/tags", timeout=5)
            print(f"Ollama server is responsive at {args.ollama_url}.")
            server_instance.add_model(
                model_id="ollama_main", # A consistent ID
                model_type="ollama",
                ollama_model_name=ollama_model_to_use_in_runner,
                ollama_base_url=args.ollama_url,
                default_params=ollama_config_params
            )
        except httpx.RequestError:
            print(f"WARNING: Could not connect to Ollama at {args.ollama_url}. Ollama model will not be available.", file=sys.stderr)
    except ImportError:
        print("WARNING: httpx package is required for Ollama support. Ollama model will not be available.", file=sys.stderr)

    # Configure and add Claude model
    # Similar logic: add if chosen, or make it always available.
    claude_config_params = get_config("claude").copy()
    if args.temperature is not None: # Apply general temperature if provided
         claude_config_params["temperature"] = args.temperature # Assuming Claude model handles 'temperature'

    server_instance.add_model(
        model_id="claude_main", # A consistent ID
        model_type="claude",
        # claude_model_name can be set here via another arg or from config
        # anthropic_api_key is typically handled by env var inside ClaudeMCPModel
        default_params=claude_config_params # Pass other params if needed
    )


    # Register Protos-specific tools
    # Pass the server.mcp attribute to the registration function
    if hasattr(server_instance, 'mcp'):
        register_protos_tools(server_instance.mcp)
    else:
        print("Error: server_instance.mcp not found. Cannot register protos_tools.", file=sys.stderr)


    print(f"Starting Protos MCP server (primary focus: {args.model})...")
    server_instance.run()

if __name__ == "__main__":
    main()