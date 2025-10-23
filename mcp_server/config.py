"""
Configuration management for Protos MCP Server.

This module handles all configuration including data paths, processor defaults,
and server settings with smart fallback logic.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass, field


@dataclass
class ServerConfig:
    """Server configuration with smart defaults."""
    
    # Data management
    data_root: Optional[Path] = None
    cache_enabled: bool = True
    max_memory_mb: int = 4096
    
    # Processor defaults
    processor_defaults: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "structure": {
            "use_cache": True,
            "cache_format": "pkl"
        },
        "embedding": {
            "batch_size": 32,
            "models": "esm2"
        },
        "grn": {
            "min_sequence_identity": 0.25
        }
    })
    
    # Server settings
    debug: bool = False
    log_level: str = "INFO"

    def __post_init__(self):
        """Resolve data root and load any config files."""
        if self.data_root is None:
            self.data_root = self._resolve_data_root()
        else:
            self.data_root = self._normalize_path(self.data_root)

        # Try to load config file if it exists
        config_file = self.data_root / "mcp_server_config.json"
        if config_file.exists():
            self._load_from_file(config_file)

    def _resolve_data_root(self) -> Path:
        """Resolve data directory with fallback chain."""
        # 1. Environment override always wins (even if path doesn't yet exist)
        env_root = os.environ.get("PROTOS_DATA_ROOT")
        if env_root:
            return self._normalize_path(env_root)

        # 2. Repository default: protos/data relative to the project root
        return self.project_data_root()

    @staticmethod
    def project_data_root() -> Path:
        """Return the repository's protos/data directory."""

        repo_root = Path(__file__).resolve().parent.parent
        candidate = repo_root / "protos" / "data"
        try:
            return candidate.resolve()
        except FileNotFoundError:
            return candidate.absolute()

    @staticmethod
    def _normalize_path(path: Union[str, Path]) -> Path:
        """Convert provided path to an absolute, user-expanded Path."""

        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        try:
            return candidate.resolve()
        except FileNotFoundError:
            return candidate.absolute()

    def set_data_root(self, path: Union[str, Path]):
        """Update the configured data root without touching the filesystem."""

        self.data_root = self._normalize_path(path)

    def _load_from_file(self, config_path: Path):
        """Load configuration from JSON file."""
        try:
            with open(config_path, 'r') as f:
                config_dict = json.load(f)
                
            # Update configuration
            if "data_root" in config_dict:
                self.set_data_root(config_dict["data_root"])
            if "cache_enabled" in config_dict:
                self.cache_enabled = config_dict["cache_enabled"]
            if "max_memory_mb" in config_dict:
                self.max_memory_mb = config_dict["max_memory_mb"]
            if "processor_defaults" in config_dict:
                self.processor_defaults.update(config_dict["processor_defaults"])
            if "debug" in config_dict:
                self.debug = config_dict["debug"]
            if "log_level" in config_dict:
                self.log_level = config_dict["log_level"]
                
        except Exception as e:
            print(f"Warning: Failed to load config file: {e}")
    
    def save_to_file(self, config_path: Optional[Path] = None):
        """Save current configuration to file."""
        if config_path is None:
            config_path = self.data_root / "mcp_server_config.json"
            
        config_dict = {
            "data_root": str(self.data_root),
            "cache_enabled": self.cache_enabled,
            "max_memory_mb": self.max_memory_mb,
            "processor_defaults": self.processor_defaults,
            "debug": self.debug,
            "log_level": self.log_level
        }
        
        with open(config_path, 'w') as f:
            json.dump(config_dict, f, indent=2)
    
    def get_processor_config(self, processor_type: str) -> Dict[str, Any]:
        """Get configuration for a specific processor type."""
        return self.processor_defaults.get(processor_type, {})
