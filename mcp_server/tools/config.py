"""Configuration tools for managing Protos MCP settings at runtime."""

import os
from pathlib import Path
from typing import Dict

from protos.io.paths import DEFAULT_GLOBAL_REGISTRY_FILENAME

from .base import BaseTool
from ..config import ServerConfig
from ..core.exceptions import InvalidInputError


class ConfigTools(BaseTool):
    """Expose runtime configuration helpers via MCP."""

    def register(self, server):
        """Register configuration-related tools."""

        @server.tool()
        def config_get_data_root(ctx) -> Dict:
            """Report the currently configured Protos data root."""

            try:
                data_root = self.context.config.data_root
                default_root = ServerConfig.project_data_root()
                env_override = os.environ.get("PROTOS_DATA_ROOT")

                marker_file = data_root / ".protos_initialized"
                registry_path = data_root / DEFAULT_GLOBAL_REGISTRY_FILENAME

                stats = self.context.get_stats()

                top_level = []
                if data_root.exists():
                    try:
                        top_level = sorted(p.name for p in data_root.iterdir())
                    except PermissionError:
                        top_level = ["<permission denied>"]

                payload = {
                    "data_root": str(data_root),
                    "is_default": data_root == default_root,
                    "environment_override": env_override,
                    "exists": data_root.exists(),
                    "initialized": self.context.is_protos_ready,
                    "reference_installed": marker_file.exists(),
                    "registry_path": str(registry_path),
                    "registry_exists": registry_path.exists(),
                    "top_level_entries": top_level,
                    "stats": stats,
                }

                return self.format_success(payload)

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def config_set_data_root(ctx, path: str) -> Dict:
            """Update the Protos data root before any processors are used."""

            try:
                if not path or not path.strip():
                    raise InvalidInputError(
                        "path",
                        "value cannot be empty",
                        "Provide an absolute or relative directory path",
                    )

                candidate = Path(path.strip()).expanduser()
                if not candidate.is_absolute():
                    candidate = (Path.cwd() / candidate).resolve()
                else:
                    candidate = candidate.resolve()

                if candidate.exists() and not candidate.is_dir():
                    raise InvalidInputError(
                        "path",
                        "must point to a directory",
                        "Choose an existing directory or a new directory name",
                    )

                if self.context.is_protos_ready:
                    raise InvalidInputError(
                        "path",
                        "cannot be changed after Protos initialization",
                        "Restart the server and set the path before invoking other tools",
                    )

                try:
                    self.context.update_data_root(candidate)
                except RuntimeError as exc:
                    raise InvalidInputError(
                        "path",
                        str(exc),
                        "Restart the server and configure the path before using other tools",
                    ) from exc

                return self.format_success(
                    {
                        "data_root": str(candidate),
                        "initialized": False,
                        "exists": candidate.exists(),
                    },
                    message="Protos data root updated. The directory will be initialized on first use.",
                )

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def config_initialize_data(
            ctx,
            reinstall_reference: bool = True,
            refresh_registry: bool = True,
        ) -> Dict:
            """Ensure the configured data root exists with the expected layout."""

            try:
                self.context.ensure_protos_ready()
                self.context.paths.reinitialize(
                    wipe=False,
                    reinstall_reference=reinstall_reference,
                )

                if refresh_registry:
                    self.registry.refresh()

                return self.format_success(
                    self.context.get_stats(),
                    metadata={
                        "reinstall_reference": reinstall_reference,
                        "registry_refreshed": refresh_registry,
                    },
                    message="Protos data root initialized.",
                )

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def config_reset_data(
            ctx,
            wipe: bool = False,
            reinstall_reference: bool = True,
            backup_registry: bool = True,
        ) -> Dict:
            """Reset the shared data directory and registry state."""

            try:
                self.context.reset_data(
                    wipe=wipe,
                    backup_registry=backup_registry,
                    reinstall_reference=reinstall_reference,
                )

                return self.format_success(
                    self.context.get_stats(),
                    metadata={
                        "wipe": wipe,
                        "reinstall_reference": reinstall_reference,
                        "backup_registry": backup_registry,
                    },
                    message="Protos data root reset.",
                )

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)
