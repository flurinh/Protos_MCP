"""
Protos manager for handling ProtosPaths and processor lifecycle.

This module provides centralized management of Protos components
with caching and lazy initialization.
"""

from typing import Dict, Optional, Any
from pathlib import Path

from .processor_factory import ProcessorFactory
from ..core.exceptions import ProcessorNotFoundError


class ProtosManager:
    """Manages ProtosPaths and processor lifecycle."""
    
    def __init__(self, context):
        """
        Initialize with server context.
        
        Args:
            context: ServerContext instance containing paths and config
        """
        self.context = context
        self._processor_cache: Dict[str, Any] = {}
    
    def get_processor(self, processor_type: str) -> Any:
        """
        Get or create processor instance.
        
        Uses cache if available, otherwise creates new instance.
        
        Args:
            processor_type: Type of processor (structure, sequence, etc.)
            
        Returns:
            Processor instance
            
        Raises:
            ProcessorNotFoundError: If processor type is unknown
        """
        # Check context cache first
        self.context.ensure_protos_ready()

        if processor := self.context.get_processor(processor_type):
            return processor
        
        # Check local cache
        if processor_type in self._processor_cache:
            return self._processor_cache[processor_type]
        
        # Create new processor
        processor = self._create_processor(processor_type)
        
        # Cache it
        self._processor_cache[processor_type] = processor
        self.context.set_processor(processor_type, processor)
        
        return processor
    
    def _create_processor(self, processor_type: str) -> Any:
        """Create a new processor instance."""
        # Get processor-specific config
        processor_config = self.context.config.get_processor_config(processor_type)
        
        # Create processor with factory
        processor = ProcessorFactory.create(
            processor_type=processor_type,
            config=processor_config
        )
        
        return processor
    
    def clear_cache(self, processor_type: Optional[str] = None):
        """
        Clear processor cache.
        
        Args:
            processor_type: Specific processor to clear, or None for all
        """
        if processor_type:
            self._processor_cache.pop(processor_type, None)
            if processor := self.context.get_processor(processor_type):
                self.context.processors.pop(processor_type, None)
        else:
            self._processor_cache.clear()
            self.context.clear_processor_cache()
    
    def get_data_path(self, processor_type: str, subdir: Optional[str] = None) -> Path:
        """
        Get data path for a processor type.
        
        Args:
            processor_type: Type of processor
            subdir: Optional subdirectory
            
        Returns:
            Path to processor data directory
        """
        path = self.context.paths.get_processor_path(processor_type)
        if subdir:
            path = path / subdir
        return path
    
    def ensure_directories(self):
        """Ensure all required directories exist."""
        # Reinitialize without wiping to create any missing layout pieces
        self.context.paths.reinitialize(wipe=False, reinstall_reference=False)
    
    def get_available_processors(self) -> list:
        """Get list of available processor types."""
        return ProcessorFactory.get_available_processors()
