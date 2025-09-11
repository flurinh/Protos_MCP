"""Test script to verify all imports work correctly."""

import sys
from pathlib import Path

print("Python executable:", sys.executable)
print("Python version:", sys.version)
print("\nPython path:")
for p in sys.path:
    print(f"  {p}")

print("\n--- Testing imports ---")

# Test MCP import
try:
    from mcp.server.fastmcp import FastMCP
    print("✓ MCP import successful")
except ImportError as e:
    print(f"✗ MCP import failed: {e}")
    print("  Run: pip install mcp")

# Test Protos imports
try:
    from protos.io.paths import ProtosPaths
    print("✓ ProtosPaths import successful")
except ImportError as e:
    print(f"✗ ProtosPaths import failed: {e}")

try:
    from protos.io.entity_registry import EntityRegistry
    print("✓ EntityRegistry import successful")
except ImportError as e:
    print(f"✗ EntityRegistry import failed: {e}")

try:
    from protos.core.base_processor import BaseProcessor
    print("✓ BaseProcessor import successful")
except ImportError as e:
    print(f"✗ BaseProcessor import failed: {e}")

try:
    from protos.processing.structure import StructureProcessor
    print("✓ StructureProcessor import successful")
except ImportError as e:
    print(f"✗ StructureProcessor import failed: {e}")

print("\n--- Testing data directory ---")
import os
data_root = os.environ.get("PROTOS_DATA_ROOT", "Not set")
print(f"PROTOS_DATA_ROOT: {data_root}")
if data_root != "Not set":
    data_path = Path(data_root)
    print(f"Data directory exists: {data_path.exists()}")
    if data_path.exists():
        subdirs = [d.name for d in data_path.iterdir() if d.is_dir()]
        print(f"Subdirectories: {subdirs[:5]}...")  # Show first 5