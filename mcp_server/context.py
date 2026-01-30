"""
Server context management for Protos MCP Server.

This module defines the ServerContext that holds all shared state including
ProtosPaths, EntityRegistry, processors, and configuration.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Any, Union

# Add protos to path if needed
protos_path = Path(__file__).parent.parent / "protos" / "src"
if protos_path.exists() and str(protos_path) not in sys.path:
    sys.path.insert(0, str(protos_path))

try:
    import protos
    from protos.io.paths import ProtosPaths, get_protos_paths, reset_protos_data
    from protos.io.core import BaseProcessor, EntityRegistry, get_registry
except ImportError as e:
    print(f"Error importing Protos: {e}", file=sys.stderr)
    print(f"Attempted to import from: {protos_path}", file=sys.stderr)
    raise

from .config import ServerConfig
from .core.exceptions import ProcessorInitializationError
from .core.session import SessionState
from .core.tool_catalog import ToolCatalog
from .core.rate_limiter import RateLimiter, RateLimitConfig
from .core.logging_config import get_logger, log_server_event

logger = get_logger("context")


@dataclass
class ServerContext:
    """Central server state management with lazy Protos initialization."""

    config: ServerConfig
    processors: Dict[str, BaseProcessor] = field(default_factory=dict)
    session_state: SessionState = field(default_factory=SessionState)
    tool_catalog: ToolCatalog = field(default_factory=ToolCatalog)
    rate_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(RateLimitConfig.default()))
    _paths: Optional[ProtosPaths] = field(default=None, init=False, repr=False)
    _entity_registry: Optional[EntityRegistry] = field(default=None, init=False, repr=False)
    _protos_ready: bool = field(default=False, init=False, repr=False)

    @classmethod
    def initialize(cls, config: Optional[ServerConfig] = None) -> "ServerContext":
        """Prepare a server context without touching the filesystem."""

        if config is None:
            config = ServerConfig()

        context = cls(config=config)
        context._apply_environment()

        logger.info(
            "ServerContext created (lazy initialization)",
            extra={"data_root": str(context.config.data_root)}
        )

        return context

    def _apply_environment(self) -> None:
        """Propagate the configured data root to environment variables."""

        absolute_root = self.config.data_root
        os.environ["PROTOS_DATA_ROOT"] = str(absolute_root)
        os.environ["PROTOS_REF_DATA_ROOT"] = str(absolute_root)

    def ensure_protos_ready(self) -> None:
        """Materialize Protos singletons on first use."""

        if self._protos_ready:
            return

        try:
            logger.info(
                "Initializing Protos subsystem",
                extra={"data_root": str(self.config.data_root)}
            )

            protos.set_data_path(str(self.config.data_root))
            self._paths = get_protos_paths()
            self._entity_registry = get_registry()

            self._protos_ready = True

        except Exception as exc:  # noqa: BLE001
            raise ProcessorInitializationError(
                "ServerContext",
                f"Failed to initialize core components: {exc}"
            ) from exc

    @property
    def paths(self) -> ProtosPaths:
        """Access ProtosPaths, triggering lazy initialization if needed."""

        self.ensure_protos_ready()
        assert self._paths is not None  # For type checkers; ensure_protos_ready guards this
        return self._paths

    @property
    def entity_registry(self) -> EntityRegistry:
        """Access EntityRegistry, triggering lazy initialization if needed."""

        self.ensure_protos_ready()
        assert self._entity_registry is not None
        return self._entity_registry

    @property
    def is_protos_ready(self) -> bool:
        """Whether Protos has been initialized for this context."""

        return self._protos_ready

    def update_data_root(self, new_root: Union[str, Path]) -> None:
        """Reconfigure the data root before any Protos initialization occurs."""

        if self._protos_ready or self.processors:
            raise RuntimeError(
                "Cannot change Protos data root after initialization. Restart the server to apply a new path."
            )

        self.config.set_data_root(new_root)
        self._apply_environment()

        # Ensure any pre-initialized handles are cleared
        self._paths = None
        self._entity_registry = None
        self._protos_ready = False
        self.clear_processor_cache()


    def get_processor(self, processor_type: str) -> Optional[BaseProcessor]:
        """Get processor instance from cache."""
        return self.processors.get(processor_type)

    def set_processor(self, processor_type: str, processor: BaseProcessor):
        """Store processor instance in cache."""
        self.processors[processor_type] = processor

    def clear_processor_cache(self):
        """Clear all cached processors."""
        self.processors.clear()

    @property
    def session(self) -> SessionState:
        """Access the current session state object."""

        return self.session_state

    def reset_session(self) -> None:
        """Reset recorded session artifacts and history."""

        self.session_state.reset()

    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics."""
        stats = {
            "data_root": str(self.config.data_root),
            "cached_processors": list(self.processors.keys()),
            "cache_enabled": self.config.cache_enabled,
            "initialized": self._protos_ready,
            "data_root_exists": self.config.data_root.exists(),
            "entity_count": 0,
            "session": self.session_state.snapshot(),
            "tool_catalog": {
                "tool_count": len(self.tool_catalog.to_dict()["tools"]),
                "groups": self.tool_catalog.list_groups(),
            },
            "rate_limits": self.rate_limiter.get_stats(),
        }

        if self._entity_registry and hasattr(self._entity_registry, "list_entities"):
            try:
                stats["entity_count"] = len(self._entity_registry.list_entities())
            except Exception:  # noqa: BLE001
                stats["entity_count"] = -1

        return stats

    def persist_tool_catalog(self) -> Optional[Path]:
        """Write the in-memory tool catalog to the configured path."""

        catalog_path = self.config.tool_catalog_path
        if catalog_path is None:
            return None

        data = self.tool_catalog.to_dict()
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        with catalog_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        return catalog_path

    def reset_data(
        self,
        *,
        wipe: bool = False,
        backup_registry: bool = True,
        reinstall_reference: bool = True,
    ):
        """Reset the shared Protos data root and registry."""

        self.ensure_protos_ready()

        reset_protos_data(
            wipe=wipe,
            backup_registry=backup_registry,
            reinstall_reference=reinstall_reference,
        )

        # Refresh cached handles after reset
        self._paths = get_protos_paths()
        self._entity_registry = get_registry()
        self.clear_processor_cache()
