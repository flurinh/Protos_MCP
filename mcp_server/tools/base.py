"""
Base class for all MCP tools.

This module provides the foundation for all tool implementations with
common functionality like error handling, response formatting, and
processor access.
"""

from typing import Dict, Any, Optional, List
from abc import ABC
import traceback

from ..core.protos_manager import ProtosManager
from ..core.processor_factory import ProcessorFactory
from ..core.exceptions import ProtosMCPError, InvalidInputError


class BaseTool(ABC):
    """Base class for all MCP tools."""
    
    def __init__(self, context):
        """
        Initialize with server context.
        
        Args:
            context: ServerContext instance
        """
        self.context = context
        self.paths = context.paths
        self.registry = context.entity_registry
        self.manager = ProtosManager(context)
    
    def get_processor(self, processor_type: str):
        """
        Get processor instance from context.
        
        Args:
            processor_type: Type of processor needed
            
        Returns:
            Processor instance
        """
        return self.manager.get_processor(processor_type)
    
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