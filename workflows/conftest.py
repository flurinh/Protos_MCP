"""Test utilities for workflow modules relying on a shared data root."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

try:
    from protos.io.paths import path_config
except ImportError:  # pragma: no cover - protos not available
    path_config = None  # type: ignore[assignment]


@pytest.fixture(scope="session", autouse=True)
def workflow_test_data_root() -> Path:
    """Ensure workflow executions use the repository's bundled test data."""

    repo_root = Path(__file__).resolve().parents[1]
    test_data_root = Path(__file__).resolve().parent.parent / "data"
    test_data_root.mkdir(parents=True, exist_ok=True)

    data_symlink = repo_root / "data"
    symlink_created = False
    if not data_symlink.exists():
        try:
            data_symlink.symlink_to(test_data_root)
            symlink_created = True
        except OSError:
            # Fallback: create the directory directly
            data_symlink.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PROTOS_DATA_ROOT", str(test_data_root))
    os.environ.setdefault("PROTOS_REF_DATA_ROOT", str(test_data_root))

    if path_config is not None:
        path_config._paths_instance = None  # type: ignore[attr-defined]

    yield test_data_root

    if path_config is not None:
        path_config._paths_instance = None  # type: ignore[attr-defined]

    if symlink_created and data_symlink.exists() and data_symlink.is_symlink():
        data_symlink.unlink()
