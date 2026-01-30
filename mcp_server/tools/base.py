"""
Base class for all MCP tools.

This module provides the foundation for all tool implementations with
common functionality like error handling, response formatting, and
processor access.
"""

from typing import Dict, Any, Optional, List, Iterable, Callable, TypeVar
from abc import ABC
from contextlib import contextmanager
from functools import wraps
import inspect
import time
import traceback

from ..core.protos_manager import ProtosManager
from ..core.processor_factory import ProcessorFactory
from ..core.exceptions import ProtosMCPError, InvalidInputError
from ..core.session import SessionState
from ..core.tool_catalog import ToolCatalog
from ..core.logging_config import get_logger, log_tool_call
from ..core.response import (
    DataSummary,
    LLMResponse,
    check_payload_size,
    safe_response,
    truncate_list,
)
from ..config import LLMSafeLimits

logger = get_logger("tools")

# Type variable for decorator
F = TypeVar("F", bound=Callable[..., Any])


@contextmanager
def track_execution_time():
    """Context manager to track execution time in milliseconds."""
    start = time.perf_counter()
    result = {"execution_time_ms": None}
    try:
        yield result
    finally:
        result["execution_time_ms"] = int((time.perf_counter() - start) * 1000)


def with_performance_tracking(tool_name: Optional[str] = None) -> Callable[[F], F]:
    """Decorator that adds execution time tracking to tool responses.

    Adds 'execution_time_ms' to the response metadata if the response is a dict.
    Also logs the tool call with timing information.

    Args:
        tool_name: Optional tool name for logging. If not provided, uses function name.

    Usage:
        @server.tool()
        @with_performance_tracking()
        def my_tool(ctx, param: str) -> Dict:
            ...
    """
    def decorator(func: F) -> F:
        name = tool_name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            result = None
            error_msg = None
            try:
                result = func(*args, **kwargs)

                # Add timing to result if it's a dict (before returning)
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                if isinstance(result, dict):
                    result.setdefault("metadata", {})
                    result["metadata"]["execution_time_ms"] = elapsed_ms

                # Log successful call
                log_tool_call(
                    tool_name=name,
                    result_status="success",
                    execution_time_ms=elapsed_ms,
                )

                return result
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                error_msg = str(e)

                # Log failed call
                log_tool_call(
                    tool_name=name,
                    result_status="error",
                    execution_time_ms=elapsed_ms,
                    error=error_msg,
                )
                raise

        return wrapper  # type: ignore
    return decorator


class BaseTool(ABC):
    """Base class for all MCP tools."""
    
    def __init__(self, context):
        """
        Initialize with server context.

        Args:
            context: ServerContext instance
        """
        self.context = context
        self.manager = ProtosManager(context)

    @property
    def paths(self):
        """Lazy access to ProtosPaths via the shared context."""

        return self.context.paths

    @property
    def registry(self):
        """Lazy access to the EntityRegistry via the shared context."""

        return self.context.entity_registry

    @property
    def session(self) -> SessionState:
        """Convenience accessor for the shared session state."""

        return self.context.session

    @property
    def tool_catalog(self) -> ToolCatalog:
        """Access the shared tool catalog."""

        return self.context.tool_catalog

    def get_processor(self, processor_type: str):
        """
        Get processor instance from context.
        
        Args:
            processor_type: Type of processor needed
            
        Returns:
            Processor instance
        """
        return self.manager.get_processor(processor_type)

    # Session helpers --------------------------------------------------

    def record_session_artifact(
        self,
        *,
        tool_name: str,
        name: str,
        kind: str,
        processor_type: Optional[str] = None,
        summary: Optional[Dict[str, Any]] = None,
        tags: Optional[Iterable[str]] = None,
        handle: Optional[str] = None,
        label: Optional[str] = None,
        scope: Optional[str] = None,
        activate: bool = True,
    ) -> str:
        """Record a session artifact and return its handle."""

        artifact = self.session.record_artifact(
            name=name,
            kind=kind,
            processor_type=processor_type,
            summary=summary,
            tags=tags,
            source_tool=tool_name,
            handle=handle,
            label=label,
            scope=scope,
            activate=activate,
        )
        return artifact.handle

    def record_session_event(
        self,
        *,
        tool_name: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        handle: Optional[str] = None,
    ) -> None:
        """Store a history entry in the session state."""

        self.session.record_event(
            tool_name=tool_name,
            action=action,
            details=details,
            handle=handle,
        )

    # Tool metadata helpers --------------------------------------------

    @property
    def catalog_group(self) -> str:
        """Default metadata group name applied to registered tools."""

        return self.__class__.__name__.replace("Tools", "").lower() or "general"

    def register_tool_metadata(
        self,
        *,
        function,
        name: Optional[str] = None,
        group: Optional[str] = None,
        description: Optional[str] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        returns: Optional[Dict[str, Any]] = None,
        aliases: Optional[List[str]] = None,
        deprecated: bool = False,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Register metadata for a tool function in the catalog."""

        func_name = name or getattr(function, "__name__", None)
        if not func_name:
            return

        doc = description or inspect.getdoc(function) or ""
        metadata = {
            "name": func_name,
            "group": group or self.catalog_group,
            "description": doc,
            "parameters": parameters or [],
            "returns": returns or {},
            "aliases": aliases or [],
            "deprecated": deprecated,
            "tags": tags or [],
            "notes": notes,
        }
        self.tool_catalog.register(**metadata)
    
    def format_success(self, 
                      data: Any, 
                      metadata: Optional[Dict] = None,
                      message: Optional[str] = None) -> Dict:
        """
        Format successful response.
        
        Args:
            data: Main response data
            metadata: Optional metadata
            message: Optional success message
            
        Returns:
            Standardized success response
        """
        response = {
            "success": True,
            "data": data
        }
        
        if metadata:
            response["metadata"] = metadata
            
        if message:
            response["message"] = message
            
        return response
    
    def format_error(self, 
                    error: str, 
                    suggestion: Optional[str] = None,
                    error_type: Optional[str] = None) -> Dict:
        """
        Format error response.
        
        Args:
            error: Error message
            suggestion: Optional suggestion for resolution
            error_type: Optional error classification
            
        Returns:
            Standardized error response
        """
        response = {
            "success": False,
            "error": error
        }
        
        if suggestion:
            response["suggestion"] = suggestion
            
        if error_type:
            response["error_type"] = error_type
            
        return response
    
    def handle_error(self, e: Exception) -> Dict:
        """
        Handle exception and format error response.
        
        Args:
            e: Exception to handle
            
        Returns:
            Formatted error response
        """
        if isinstance(e, ProtosMCPError):
            return self.format_error(
                error=e.message,
                suggestion=e.suggestion,
                error_type=e.__class__.__name__
            )
        else:
            # For unexpected errors, include traceback in debug mode
            error_msg = str(e)
            if self.context.config.debug:
                error_msg += f"\n\nTraceback:\n{traceback.format_exc()}"
                
            return self.format_error(
                error=error_msg,
                suggestion="This is an unexpected error. Please check the logs.",
                error_type="UnexpectedError"
            )
    
    def validate_required_params(self, 
                               params: Dict[str, Any], 
                               required: List[str]) -> Optional[Dict]:
        """
        Validate required parameters are present.
        
        Args:
            params: Parameters to validate
            required: List of required parameter names
            
        Returns:
            Error response if validation fails, None if valid
        """
        missing = [p for p in required if p not in params or params[p] is None]
        
        if missing:
            return self.format_error(
                error=f"Missing required parameters: {', '.join(missing)}",
                suggestion=f"Please provide all required parameters: {', '.join(required)}"
            )
        
        return None
    
    def validate_processor_type(self, processor_type: str) -> Optional[Dict]:
        """
        Validate that processor type is available.
        
        Args:
            processor_type: Processor type to validate
            
        Returns:
            Error response if validation fails, None if valid
        """
        available_types = ProcessorFactory.get_available_processors()
        
        if processor_type not in available_types:
            return self.format_error(
                error=f"Invalid processor type: '{processor_type}'",
                suggestion=f"Valid processor types are: {', '.join(available_types)}",
                error_type="InvalidProcessorType"
            )
        
        return None
    
    def register(self, server):
        """
        Register tool methods with MCP server.

        Should be overridden by subclasses to register their specific tools.

        Args:
            server: FastMCP server instance
        """
        # To be implemented by subclasses
        pass

    # LLM-safe response helpers --------------------------------------------

    @property
    def llm_safe_mode(self) -> bool:
        """Check if LLM-safe mode is enabled."""
        return self.context.config.llm_safe_mode

    @property
    def llm_limits(self) -> LLMSafeLimits:
        """Get the configured LLM safety limits."""
        return self.context.config.llm_limits

    def should_include_data(self, data_type: str) -> bool:
        """
        Check if raw data should be included in response.

        In LLM-safe mode, only ligands/SMILES are included.
        In workflow mode (llm_safe_mode=False), all data is included.

        Args:
            data_type: Type of data (sequence, structure, embedding, ligand, etc.)

        Returns:
            True if raw data should be included
        """
        if not self.llm_safe_mode:
            return True  # Workflow mode - include everything

        # In LLM-safe mode, only ligands are small enough to include
        return data_type in ("ligand", "smiles", "molecule")

    def format_llm_response(
        self,
        summary: DataSummary,
        context_handle: Optional[str] = None,
        *,
        message: Optional[str] = None,
        include_data: Optional[Any] = None,
    ) -> Dict:
        """
        Format an LLM-safe success response.

        Args:
            summary: DataSummary describing the loaded data
            context_handle: Handle for retrieving full data later
            message: Optional success message
            include_data: Optional small data to include (only for ligands)

        Returns:
            Standardized success response
        """
        response = LLMResponse(
            success=True,
            summary=summary,
            context_handle=context_handle,
            message=message,
            data=include_data,
        )
        return response.to_dict()

    def format_safe_success(
        self,
        data: Any,
        metadata: Optional[Dict] = None,
        message: Optional[str] = None,
        max_bytes: Optional[int] = None,
    ) -> Dict:
        """
        Format success response with automatic size checking.

        If response exceeds max_bytes, it's truncated with a warning.

        Args:
            data: Main response data
            metadata: Optional metadata
            message: Optional success message
            max_bytes: Max response size (default from config)

        Returns:
            Standardized success response, possibly truncated
        """
        response = self.format_success(data, metadata, message)

        limit = max_bytes or self.llm_limits.max_response_bytes
        return safe_response(response, limit)

    def truncate_entity_list(
        self,
        entities: List[Any],
        max_items: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Truncate an entity list for LLM-safe return.

        Args:
            entities: List of entities to truncate
            max_items: Max items to return (default from config)

        Returns:
            Dict with items, count, truncated flag
        """
        limit = max_items or self.llm_limits.max_list_items
        return truncate_list(entities, limit)

    def get_sequence_preview(
        self,
        sequence: str,
        max_chars: Optional[int] = None,
    ) -> str:
        """
        Get a truncated preview of a sequence.

        Args:
            sequence: Full sequence string
            max_chars: Max characters (default from config)

        Returns:
            Truncated sequence with ... if needed
        """
        limit = max_chars or self.llm_limits.max_sequence_preview_chars
        if len(sequence) <= limit:
            return sequence
        return sequence[:limit] + "..."

    def check_response_size(self, data: Any) -> tuple[bool, int]:
        """
        Check if response data is within size limits.

        Args:
            data: Response data to check

        Returns:
            Tuple of (is_within_limit, size_in_bytes)
        """
        return check_payload_size(data, self.llm_limits.max_response_bytes)
