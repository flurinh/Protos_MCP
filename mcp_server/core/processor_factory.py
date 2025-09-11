"""
Processor factory for creating and managing Protos processor instances.

This module provides a factory pattern for creating processors with
proper dependency injection and configuration.
"""

from typing import Dict, Type, Optional
import sys
from pathlib import Path

# Add protos to path if needed
protos_path = Path(__file__).parent.parent.parent / "protos" / "src"
if protos_path.exists() and str(protos_path) not in sys.path:
    sys.path.insert(0, str(protos_path))

try:
    from protos.core.base_processor import BaseProcessor
    from protos.processing.structure import StructureProcessor
    from protos.processing.sequence import SequenceProcessor
    from protos.processing.grn import GRNProcessor
    from protos.processing.property import PropertyProcessor
    from protos.processing.embedding import EmbeddingProcessor
    from protos.processing.ligand import LigandProcessor
    # Note: Graph processor may not exist, handle gracefully
    try:
        from protos.processing.graph import GraphProcessor
    except ImportError:
        GraphProcessor = None
except ImportError as e:
    print(f"Error importing Protos processors: {e}", file=sys.stderr)
    # Define placeholder classes for type hints
    BaseProcessor = object
    StructureProcessor = None
    SequenceProcessor = None
    GRNProcessor = None
    PropertyProcessor = None
    EmbeddingProcessor = None
    LigandProcessor = None
    GraphProcessor = None

from ..core.exceptions import ProcessorNotFoundError, ProcessorInitializationError


class ProcessorFactory:
    """Factory for creating processor instances."""
    
    # Registry of available processors
    _registry: Dict[str, Type[BaseProcessor]] = {}
    
    @classmethod
    def initialize_registry(cls):
        """Initialize the processor registry."""
        # Only register if imports were successful
        if StructureProcessor is not None:
            cls._registry = {
                "structure": StructureProcessor,
                "sequence": SequenceProcessor,
                "grn": GRNProcessor,
                "property": PropertyProcessor,
                "embedding": EmbeddingProcessor,
                "ligand": LigandProcessor
            }
            # Add graph processor if available
            if GraphProcessor is not None:
                cls._registry["graph"] = GraphProcessor
    
    @classmethod
    def create(cls, 
               processor_type: str, 
               paths,  # ProtosPaths instance
               config: Optional[Dict] = None) -> BaseProcessor:
        """
        Create processor with injected dependencies.
        
        Args:
            processor_type: Type of processor to create
            paths: ProtosPaths instance
            config: Optional processor-specific configuration
            
        Returns:
            Initialized processor instance
            
        Raises:
            ProcessorNotFoundError: If processor type is unknown
            ProcessorInitializationError: If processor creation fails
        """
        # Ensure registry is initialized
        if not cls._registry:
            cls.initialize_registry()
            
        if processor_type not in cls._registry:
            raise ProcessorNotFoundError(processor_type)
        
        processor_class = cls._registry[processor_type]
        if processor_class is None:
            raise ProcessorInitializationError(
                processor_type,
                "Processor class not available (import failed)"
            )
        
        try:
            # Create processor with correct parameters
            if processor_type == "embedding":
                # EmbeddingProcessor doesn't take paths parameter
                processor = processor_class(
                    name=f"{processor_type}_processor"
                )
            else:
                # All other processors take paths parameter
                processor = processor_class(
                    name=f"{processor_type}_processor",
                    paths=paths
                )
            
            # Apply any additional configuration
            if config:
                for key, value in config.items():
                    # Skip properties that can't be set directly
                    if processor_type == "embedding" and key == "model":
                        continue
                    if hasattr(processor, key):
                        try:
                            setattr(processor, key, value)
                        except AttributeError:
                            # Skip properties that can't be set
                            pass
            
            return processor
            
        except Exception as e:
            raise ProcessorInitializationError(
                processor_type,
                f"Failed to create processor: {str(e)}"
            )
    
    @classmethod
    def get_available_processors(cls) -> list:
        """Get list of available processor types."""
        if not cls._registry:
            cls.initialize_registry()
        return list(cls._registry.keys())
    
    @classmethod
    def register_processor(cls, processor_type: str, processor_class: Type[BaseProcessor]):
        """Register a custom processor type."""
        cls._registry[processor_type] = processor_class