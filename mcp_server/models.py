import httpx
import json
import asyncio
from typing import Dict, Any, List, Optional, Literal # Literal for roles
from abc import ABC, abstractmethod
from enum import Enum

# --- Define our own simple Message and Role structures ---
# These are not from mcp.models.schemas, as that path does not exist in the SDK.

# Using Literal for type hinting roles, or a simple Enum
RoleType = Literal["user", "assistant", "system", "tool"] # "tool" if you might need it

# For internal consistency, an Enum can still be useful
class InternalRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    # TOOL = "tool" # Add if needed for specific models

    def __str__(self):
        return self.value

# Message structure will be a dictionary
# e.g., {"role": "user", "content": "Hello"}
MessageType = Dict[str, str]


# --- Configuration ---
OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL_NAME = "llama3.2"


class MCPModelBase(ABC):
    """
    Abstract Base Class for MCP Models using simple dictionary-based messages.
    """
    def __init__(self, model_id: str, **kwargs):
        self.model_id = model_id
        self._is_initialized = False
        print(f"MCPModelBase: Initializing models with id='{model_id}'")

    @abstractmethod
    async def generate_response_async(
        self,
        messages: List[MessageType], # Expects a list of {"role": ..., "content": ...}
        **kwargs: Any
    ) -> MessageType: # Returns a {"role": ..., "content": ...}
        """
        Generates a response based on a list of messages.
        kwargs can be used for parameters like temperature, max_tokens, etc.
        """
        pass

    async def _startup(self):
        self._is_initialized = True
        print(f"MCPModelBase ({self.model_id}): Startup complete.")

    async def _shutdown(self):
        self._is_initialized = False
        print(f"MCPModelBase ({self.model_id}): Shutdown complete.")

    @abstractmethod
    def _mcp_to_llm_role(self, mcp_role: str) -> str: # mcp_role is now a string
        """
        Converts a string role to the LLM-specific role string.
        """
        pass

    def is_ready(self) -> bool:
        return self._is_initialized


class OllamaMCPModel(MCPModelBase):
    def __init__(
            self,
            model_id: str,
            ollama_model_name: str = DEFAULT_OLLAMA_MODEL_NAME,
            ollama_base_url: str = OLLAMA_BASE_URL,
            default_params: Optional[Dict[str, Any]] = None,
            **kwargs
    ):
        super().__init__(model_id=model_id, **kwargs)
        self.ollama_model_name = ollama_model_name
        self.api_url = f"{ollama_base_url.rstrip('/')}/api/chat"
        self._client: Optional[httpx.AsyncClient] = None
        self.default_params = default_params if default_params else {}
        print(f"OllamaMCPModel: Configured id='{model_id}', ollama_model='{ollama_model_name}', url='{self.api_url}'")

    async def _startup(self):
        if not self._client:
            self._client = httpx.AsyncClient(timeout=120.0)
        await super()._startup()
        print(f"OllamaMCPModel ({self.model_id}): HTTP client started.")

    async def _shutdown(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        await super()._shutdown()
        print(f"OllamaMCPModel ({self.model_id}): HTTP client shutdown.")

    def _mcp_to_llm_role(self, mcp_role: str) -> str: # mcp_role is a string
        # Ollama uses "user", "assistant", "system" directly
        if mcp_role in ["user", "assistant", "system"]:
            return mcp_role
        print(f"Warning: Unsupported role '{mcp_role}' for Ollama, defaulting to 'user'")
        return "user"

    async def generate_response_async(
        self,
        messages: List[MessageType],
        **kwargs: Any
    ) -> MessageType:
        if not self.is_ready() or not self._client:
            error_msg = f"OllamaMCPModel ({self.model_id}): Not initialized."
            print(error_msg)
            return {"role": InternalRole.SYSTEM.value, "content": error_msg}

        ollama_messages = []
        for mcp_message in messages:
            # Basic validation of the incoming message structure
            if "role" in mcp_message and "content" in mcp_message:
                ollama_messages.append({
                    "role": self._mcp_to_llm_role(mcp_message["role"]),
                    "content": mcp_message["content"]
                })
            else:
                print(f"Warning: Skipping malformed message: {mcp_message}")


        if not ollama_messages:
            return {"role": InternalRole.ASSISTANT.value, "content": "No valid input messages provided to Ollama."}

        request_specific_params = {key: value for key, value in kwargs.items() if value is not None}
        ollama_request_params = {**self.default_params, **request_specific_params}

        payload = {
            "models": self.ollama_model_name,
            "messages": ollama_messages,
            "stream": False,
            "options": ollama_request_params
        }

        try:
            response = await self._client.post(self.api_url, json=payload)
            response.raise_for_status()
            response_data = response.json()
            assistant_message_data = response_data.get("message", {})
            content = assistant_message_data.get("content", "")
            # Ollama's response format is directly {"role": "assistant", "content": "..."}
            # So, we can potentially return assistant_message_data directly if it matches our MessageType
            if "role" in assistant_message_data and "content" in assistant_message_data:
                return {"role": assistant_message_data["role"], "content": content}
            else: # Fallback if structure is unexpected
                return {"role": InternalRole.ASSISTANT.value, "content": content}

        except httpx.HTTPStatusError as e:
            error_content = f"Ollama API Error: {e.response.status_code} - {e.response.text}"
            print(error_content)
            return {"role": InternalRole.SYSTEM.value, "content": error_content}
        except httpx.RequestError as e:
            error_content = f"Ollama Request Error: {str(e)}"
            print(error_content)
            return {"role": InternalRole.SYSTEM.value, "content": error_content}
        except Exception as e:
            error_content = f"Unexpected error communicating with Ollama: {str(e)}"
            print(error_content)
            return {"role": InternalRole.SYSTEM.value, "content": error_content}


class ClaudeMCPModel(MCPModelBase):
    def __init__(self, model_id: str, anthropic_api_key: Optional[str] = None, claude_model_name: str = "claude-3-opus-20240229", **kwargs):
        super().__init__(model_id=model_id, **kwargs)
        self.anthropic_api_key = anthropic_api_key
        self.claude_model_name = claude_model_name
        self._client = None # Placeholder for actual Anthropic client
        if not self.anthropic_api_key:
            print(f"Warning: ClaudeMCPModel ({self.model_id}) initialized without an API key. Will be non-functional.")
        print(f"ClaudeMCPModel: Configured id='{model_id}', claude_model='{self.claude_model_name}'")

    async def _startup(self):
        # Placeholder for Anthropic client initialization
        # from anthropic import AsyncAnthropic
        # if self.anthropic_api_key:
        #    self._client = AsyncAnthropic(api_key=self.anthropic_api_key)
        # else:
        #    print(f"ClaudeMCPModel ({self.model_id}): API key not provided. Client not initialized.")
        await super()._startup()
        print(f"ClaudeMCPModel ({self.model_id}): (Placeholder) client state managed.")

    async def _shutdown(self):
        # Placeholder for Anthropic client shutdown
        # if self._client:
        #     await self._client.close() # If client has an async close
        #     self._client = None
        await super()._shutdown()
        print(f"ClaudeMCPModel ({self.model_id}): (Placeholder) client state managed.")

    def _mcp_to_llm_role(self, mcp_role: str) -> str:
        if mcp_role == InternalRole.USER.value:
            return "user"
        elif mcp_role == InternalRole.ASSISTANT.value:
            return "assistant"
        # Anthropic handles system prompts via a separate 'system' parameter, not in the messages list.
        print(f"Warning: Role '{mcp_role}' for Claude. System messages are handled differently. Defaulting to 'user' if not system.")
        return "user" # Or handle system messages by extracting them before this conversion

    async def generate_response_async(
        self,
        messages: List[MessageType],
        **kwargs: Any
    ) -> MessageType:
        if not self.is_ready():
            return {"role": InternalRole.SYSTEM.value, "content": f"ClaudeMCPModel ({self.model_id}): Not initialized."}
        if not self.anthropic_api_key: # Or `if not self._client:` in a real scenario
             return {"role": InternalRole.SYSTEM.value, "content": f"ClaudeMCPModel ({self.model_id}): Anthropic API key/client not available."}

        # Placeholder for actual Anthropic API call logic
        # anthropic_messages = []
        # system_prompt_content = None
        # for msg in messages:
        #     if msg["role"] == InternalRole.SYSTEM.value:
        #         system_prompt_content = msg["content"] # Use the last one
        #     elif msg["role"] in [InternalRole.USER.value, InternalRole.ASSISTANT.value]:
        #         anthropic_messages.append({"role": self._mcp_to_llm_role(msg["role"]), "content": msg["content"]})
        #
        # if not anthropic_messages:
        #     return {"role": InternalRole.ASSISTANT.value, "content": "No user/assistant messages for Claude."}
        #
        # try:
        # api_response = await self._client.messages.create(
        # models=self.claude_model_name,
        # system=system_prompt_content,
        # messages=anthropic_messages,
        # max_tokens=kwargs.get("max_tokens", 1024),
        # temperature=kwargs.get("temperature", 0.7)
        # )
        # content = api_response.content[0].text
        #     return {"role": InternalRole.ASSISTANT.value, "content": content}
        # except Exception as e:
        #     return {"role": InternalRole.SYSTEM.value, "content": f"Claude API Error: {str(e)}"}

        return {
            "role": InternalRole.ASSISTANT.value,
            "content": f"Claude models response (id: {self.model_id}) would appear here. Input: {len(messages)} messages. This is a placeholder."
        }