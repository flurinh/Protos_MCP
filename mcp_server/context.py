"""
Server context management for Protos MCP Server.

This module defines the ServerContext that holds all shared state including
ProtosPaths, EntityRegistry, processors, and configuration.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Any

# Add protos to path if needed
protos_path = Path(__file__).parent.parent / "protos" / "src"
if protos_path.exists() and str(protos_path) not in sys.path:
    sys.path.insert(0, str(protos_path))

try:
    from protos.io.paths import ProtosPaths
    from protos.io.entity_registry import EntityRegistry
    from protos.core.base_processor import BaseProcessor
except ImportError as e:
    print(f"Error importing Protos: {e}", file=sys.stderr)
    print(f"Attempted to import from: {protos_path}", file=sys.stderr)
    raise

from .config import ServerConfig
from .core.exceptions import ProcessorInitializationError


@dataclass
class ServerContext:
    """Central server state management."""
    
    paths: ProtosPaths
    entity_registry: EntityRegistry
    processors: Dict[str, BaseProcessor]
    config: ServerConfig
    
    @classmethod
    def initialize(cls, config: Optional[ServerConfig] = None) -> 'ServerContext':
        """Initialize all core components."""
        if config is None:
            config = ServerConfig()
        
        # Set environment variables for Protos
        os.environ["PROTOS_DATA_ROOT"] = str(config.data_root.absolute())
        os.environ["PROTOS_REF_DATA_ROOT"] = str(config.data_root.absolute())
        
        print(f"Initializing ServerContext with data root: {config.data_root}", file=sys.stderr)
        
        try:
            # Initialize ProtosPaths
            paths = ProtosPaths(
                data_root=str(config.data_root.absolute())
            )
            
            # Initialize EntityRegistry
            entity_registry = EntityRegistry(paths=paths)
            
            # Create context
            context = cls(
                paths=paths,
                entity_registry=entity_registry,
                processors={},
                config=config
            )
            
            print(f"ServerContext initialized successfully", file=sys.stderr)
            return context
            
        except Exception as e:
            raise ProcessorInitializationError(
                "ServerContext",
                f"Failed to initialize core components: {str(e)}"
            )
    
    def get_processor(self, processor_type: str) -> Optional[BaseProcessor]:
        """Get processor instance from cache."""
        return self.processors.get(processor_type)
    
    def set_processor(self, processor_type: str, processor: BaseProcessor):
        """Store processor instance in cache."""
        self.processors[processor_type] = processor
    
    def clear_processor_cache(self):
        """Clear all cached processors."""
        self.processors.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics."""
        return {
            "data_root": str(self.config.data_root),
            "cached_processors": list(self.processors.keys()),
            "cache_enabled": self.config.cache_enabled,
            "entity_count": len(self.entity_registry.list_entities()) if hasattr(self.entity_registry, 'list_entities') else 0
        }