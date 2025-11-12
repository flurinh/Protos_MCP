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
    from protos.io.core import BaseProcessor
except ImportError as e:  # pragma: no cover - catastrophic import failure
    print(f"Error importing Protos base processor: {e}", file=sys.stderr)
    BaseProcessor = object

def _safe_import(module: str, attr: str):
    try:
        mod = __import__(module, fromlist=[attr])
        return getattr(mod, attr)
    except ImportError:
        return None


StructureProcessor = _safe_import("protos.processing.structure", "StructureProcessor")
SequenceProcessor = _safe_import("protos.processing.sequence", "SequenceProcessor")
GRNProcessor = _safe_import("protos.processing.grn", "GRNProcessor")
PropertyProcessor = _safe_import("protos.processing.property", "PropertyProcessor")
EmbeddingProcessor = _safe_import("protos.processing.embedding", "EmbeddingProcessor")
MoleculeProcessor = _safe_import("protos.processing.molecule", "MoleculeProcessor")
GraphProcessor = _safe_import("protos.processing.graph", "GraphProcessor")

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
                "molecule": MoleculeProcessor
            }
            # Add graph processor if available
            if GraphProcessor is not None:
                cls._registry["graph"] = GraphProcessor
    
    @classmethod
    def create(cls,
               processor_type: str,
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
            # Create processor with zero-config constructor
            processor = processor_class(
                name=f"{processor_type}_processor"
            )
            
            # Apply any additional configuration
            if config:
                for key, value in config.items():
                    # Skip properties that can't be set directly
                    if processor_type == "embedding" and key == "models":
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
