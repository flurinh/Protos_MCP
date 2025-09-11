# Protos-MCP Server

This module provides the server implementation for Protos integration with the Model Context Protocol (MCP).

## Architecture

The server is organized with a clear separation of concerns:

1. **Base Server Layer** (`claude_server2.py`): Provides the foundation for MCP servers with common functionality
2. **Model Implementations** (`models.py`): Contains adapters for different LLM backends (Ollama, Claude)
3. **Generic Server** (`server.py`): Implements a configurable server that can use multiple models
4. **Protos Tools** (`protos_tools.py`): All Protos-specific tools and utilities
5. **Configuration** (`config.py`): Central place for configuration constants

## Usage

### Running with Claude

```bash
python -m mcp_server.run_claude_server
```

### Running with Ollama

Ensure Ollama is running locally:

```bash
ollama pull llama3  # or other model
python -m mcp_server.run_ollama_server
```

## Extending

To add a new model backend:

1. Implement a new model adapter in `models.py` by extending `mcp.model.Model`
2. Add model configuration in `config.py`
3. Update the `GenericMCPServer.add_model()` method in `server.py` to handle the new model type

To add new Protos tools:

1. Implement new tool functions in `protos_tools.py`
2. Register them in the `register_protos_tools()` function