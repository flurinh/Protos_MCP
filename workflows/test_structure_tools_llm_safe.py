#!/usr/bin/env python3
"""
Test structure tools with LLM-safe mode.

Run with: conda activate protos && python workflows/test_structure_tools_llm_safe.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server
from mcp_server.core.response import check_payload_size


TEST_STRUCTURES = ["5d5a", "3sn6"]


def norm(raw: Any) -> Dict[str, Any]:
    """Normalize MCP tool response."""
    if isinstance(raw, tuple) and len(raw) == 2:
        _, meta = raw
    else:
        meta = raw

    if isinstance(meta, dict):
        result = meta.get("result", meta)
        if isinstance(result, dict):
            return result

    if isinstance(meta, list):
        for item in meta:
            text = getattr(item, "text", None)
            if text:
                try:
                    return json.loads(text)
                except:
                    return {"raw_text": text}

    text = getattr(meta, "text", None)
    if text:
        try:
            return json.loads(text)
        except:
            return {"raw_text": text}

    return {"raw": str(meta)[:500]}


def estimate_response_size(response: Dict[str, Any]) -> int:
    """Estimate response size in bytes."""
    _, size = check_payload_size(response, max_bytes=1_000_000)
    return size


async def test_structure_tools(llm_safe_mode: bool = True) -> Dict[str, Any]:
    """Test structure tools with LLM-safe mode."""
    data_root_path = (REPO_ROOT / "data").resolve()
    config = ServerConfig(data_root=data_root_path, llm_safe_mode=llm_safe_mode)

    print(f"\n{'='*60}")
    print(f"Testing STRUCTURE tools with llm_safe_mode={llm_safe_mode}")
    print(f"{'='*60}")

    server = create_server("Protos Structure Tools Test", config=config)

    results: Dict[str, Any] = {
        "mode": "llm_safe" if llm_safe_mode else "workflow",
        "tests": {},
        "response_sizes": {},
    }

    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            return norm(response)

        # Initialize
        await call("config_initialize_data", reinstall_reference=True, refresh_registry=True)

        # --- Test 1: Download structures ---
        print("\n1. Testing download_entities (structures)...")
        download_result = await call(
            "download_entities",
            identifiers=TEST_STRUCTURES,
            processor_type="structure",
            dataset_name="llm_safe_test_structures",
            create_dataset=True,
            overwrite=False,
        )
        results["tests"]["download"] = download_result.get("success", False)
        results["response_sizes"]["download"] = estimate_response_size(download_result)
        print(f"   Success: {results['tests']['download']}")
        print(f"   Response size: {results['response_sizes']['download']} bytes")

        # --- Test 2: List structure entities ---
        print("\n2. Testing list_structure_entities...")
        list_result = await call("list_structure_entities", limit=50)
        results["tests"]["list"] = list_result.get("success", False)
        results["response_sizes"]["list"] = estimate_response_size(list_result)
        entity_count = list_result.get("data", {}).get("total", 0)
        print(f"   Success: {results['tests']['list']}")
        print(f"   Entity count: {entity_count}")
        print(f"   Response size: {results['response_sizes']['list']} bytes")

        # --- Test 3: Load single structure ---
        print("\n3. Testing load_structure (no atoms)...")
        load_result = await call(
            "load_structure",
            structure_id="5d5a",
            include_atoms=False,
        )
        results["tests"]["load_structure"] = load_result.get("success", False)
        results["response_sizes"]["load_structure"] = estimate_response_size(load_result)

        data = load_result.get("data", {})
        has_atom_preview = "atom_preview" in data
        results["tests"]["load_structure_safe"] = not has_atom_preview

        print(f"   Success: {results['tests']['load_structure']}")
        print(f"   Atom count: {data.get('atom_count', 'N/A')}")
        print(f"   Chains: {list(data.get('chains', {}).keys())}")
        print(f"   Atom preview returned: {has_atom_preview}")
        print(f"   Response size: {results['response_sizes']['load_structure']} bytes")

        # --- Test 3b: Load with include_atoms=True ---
        print("\n3b. Testing load_structure with include_atoms=True...")
        load_full_result = await call(
            "load_structure",
            structure_id="5d5a",
            include_atoms=True,
            max_atoms=50,  # Limit atoms
        )
        results["response_sizes"]["load_structure_full"] = estimate_response_size(load_full_result)
        data_full = load_full_result.get("data", {})
        has_atom_preview_full = "atom_preview" in data_full
        print(f"   Atom preview returned: {has_atom_preview_full}")
        print(f"   Response size: {results['response_sizes']['load_structure_full']} bytes")

        # In LLM-safe mode, should limit atom preview or warn
        if llm_safe_mode:
            # Check if preview is reasonably sized
            preview_size = estimate_response_size(data_full.get("atom_preview", {}))
            results["tests"]["atom_preview_limited"] = preview_size < 10000  # Under 10KB
            print(f"   Atom preview size: {preview_size} bytes")

        # --- Test 4: Load dataset ---
        # Use existing dataset since structures may already exist (skip download)
        print("\n4. Testing load_structure_dataset...")
        dataset_result = await call(
            "load_structure_dataset",
            dataset_name="smiles_docking_demo",  # Use existing dataset
            include_entities=True,
            include_summaries=False,  # Don't load full structures
        )
        results["tests"]["load_dataset"] = dataset_result.get("success", False)
        results["response_sizes"]["load_dataset"] = estimate_response_size(dataset_result)

        data = dataset_result.get("data", {})
        has_full_structures = "summaries" in data and len(data.get("summaries", [])) > 0
        results["tests"]["dataset_safe"] = not has_full_structures or llm_safe_mode is False

        print(f"   Success: {results['tests']['load_dataset']}")
        print(f"   Entity count: {data.get('entity_count', 0)}")
        print(f"   Full structures returned: {has_full_structures}")
        print(f"   Response size: {results['response_sizes']['load_dataset']} bytes")

        # --- Test 5: Collect chain sequences ---
        print("\n5. Testing structure_collect_chain_sequences...")
        chain_result = await call(
            "structure_collect_chain_sequences",
            structure_ids=["5d5a"],
            min_length=10,
        )
        results["tests"]["collect_chains"] = chain_result.get("success", False)
        results["response_sizes"]["collect_chains"] = estimate_response_size(chain_result)

        data = chain_result.get("data", {})
        chain_sequences = data.get("chain_sequences", {})

        # Check if full sequences are returned
        has_full_sequences = False
        for struct_id, chains in chain_sequences.items():
            for chain_id, chain_data in chains.items():
                seq = chain_data.get("sequence", "")
                if isinstance(seq, str) and len(seq) > 100:
                    has_full_sequences = True
                    break

        results["tests"]["chain_sequences_safe"] = not has_full_sequences

        print(f"   Success: {results['tests']['collect_chains']}")
        print(f"   Full sequences returned: {has_full_sequences}")
        print(f"   Response size: {results['response_sizes']['collect_chains']} bytes")

        # --- Test 6: Get structure chains ---
        print("\n6. Testing get_structure_chains...")
        chains_result = await call(
            "get_structure_chains",
            pdb_id="5d5a",  # Note: uses pdb_id not structure_id
        )
        results["tests"]["get_chains"] = chains_result.get("success", False)
        results["response_sizes"]["get_chains"] = estimate_response_size(chains_result)
        print(f"   Success: {results['tests']['get_chains']}")
        print(f"   Response size: {results['response_sizes']['get_chains']} bytes")

        # --- Summary ---
        print(f"\n{'='*60}")
        print("RESPONSE SIZE SUMMARY")
        print(f"{'='*60}")
        total_size = sum(results["response_sizes"].values())
        for name, size in sorted(results["response_sizes"].items(), key=lambda x: -x[1]):
            status = "OK" if size < 50000 else "LARGE"
            print(f"  {name:30s}: {size:>8} bytes [{status}]")
        print(f"  {'TOTAL':30s}: {total_size:>8} bytes")

        max_size = 50000
        large_responses = [k for k, v in results["response_sizes"].items() if v > max_size]
        if large_responses:
            print(f"\n  WARNING: {len(large_responses)} response(s) exceed {max_size} bytes")
            results["warnings"] = large_responses

        # Test pass/fail summary
        print(f"\n{'='*60}")
        print("TEST RESULTS")
        print(f"{'='*60}")
        passed = sum(1 for v in results["tests"].values() if v)
        total = len(results["tests"])
        for name, passed_test in results["tests"].items():
            status = "PASS" if passed_test else "FAIL"
            print(f"  {name:30s}: {status}")
        print(f"\n  Total: {passed}/{total} tests passed")

        results["passed"] = passed
        results["total"] = total

    return results


async def main():
    """Run structure tools tests."""
    print("=" * 60)
    print("STRUCTURE TOOLS LLM-SAFE MODE TEST")
    print("=" * 60)

    results = await test_structure_tools(llm_safe_mode=True)

    print("\n" + "=" * 60)
    if results["passed"] == results["total"]:
        print("[SUCCESS] All structure tools tests passed!")
    else:
        print(f"[PARTIAL] {results['passed']}/{results['total']} tests passed")
    print("=" * 60)

    return 0 if results["passed"] == results["total"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
