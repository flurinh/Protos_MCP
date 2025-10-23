"""
Custom exceptions for Protos MCP Server.

These exceptions provide clear, LLM-friendly error messages with
helpful suggestions for resolution.
"""

from typing import Optional


class ProtosMCPError(Exception):
    """Base exception for all Protos MCP errors."""
    
    def __init__(self, message: str, suggestion: Optional[str] = None):
        self.message = message
        self.suggestion = suggestion
        super().__init__(self.message)
    
    def to_dict(self):
        """Convert exception to dictionary for MCP response."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "suggestion": self.suggestion
        }


class ProcessorNotFoundError(ProtosMCPError):
    """Raised when a processor type is not recognized."""
    
    def __init__(self, processor_type: str):
        super().__init__(
            f"Unknown processor type: '{processor_type}'",
            f"Available processors: structure, sequence, grn, property, embedding, ligand, graph"
        )


class EntityNotFoundError(ProtosMCPError):
    """Raised when an entity cannot be found."""
    
    def __init__(self, entity_name: str, processor_type: Optional[str] = None):
        message = f"Entity '{entity_name}' not found"
        if processor_type:
            message += f" in {processor_type} processor"
        
        super().__init__(
            message,
            "Use 'entity_list_entities' to see available entities or 'download_entity' to fetch from external sources"
        )


class DatasetNotFoundError(ProtosMCPError):
    """Raised when a dataset cannot be found."""
    
    def __init__(self, dataset_name: str, processor_type: Optional[str] = None):
        message = f"Dataset '{dataset_name}' not found"
        if processor_type:
            message += f" in {processor_type} processor"
            
        super().__init__(
            message,
            "Use 'list_datasets' to see available datasets or 'create_dataset' to create a new one"
        )


class InvalidInputError(ProtosMCPError):
    """Raised when input parameters are invalid."""
    
    def __init__(self, parameter: str, issue: str, suggestion: Optional[str] = None):
        super().__init__(
            f"Invalid input for '{parameter}': {issue}",
            suggestion
        )


class ProcessorInitializationError(ProtosMCPError):
    """Raised when a processor cannot be initialized."""
    
    def __init__(self, processor_type: str, reason: str):
        super().__init__(
            f"Failed to initialize {processor_type} processor: {reason}",
            "Check that Protos is properly installed and data directory is accessible"
        )


class DataSerializationError(ProtosMCPError):
    """Raised when data cannot be serialized for MCP response."""
    
    def __init__(self, data_type: str, reason: str):
        super().__init__(
            f"Failed to serialize {data_type}: {reason}",
            "This may be due to data size or format. Try using a different output format."
        )
