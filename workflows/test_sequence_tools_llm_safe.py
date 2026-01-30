#!/usr/bin/env python3
"""
Test sequence tools with LLM-safe mode.

This workflow tests:
1. Current tool behavior (before migration)
2. Response sizes to verify they're within limits
3. That workflows still function correctly after migration

Run with: conda activate protos && python workflows/test_sequence_tools_llm_safe.py
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

# Test sequences - real GPCR sequences (truncated for testing)
TEST_SEQUENCES = {
    "ADRB2_HUMAN": "MGQPGNGSAFLLAPNRSHAPDHDVTQQRDEVWVVGMGIVMSLIVLAIVFGNVLVITAIAKFERLQTVTNYFITSLACADLVMGLAVVPFGAAHILMKMWTFGNFWCEFWTSIDVLCVTASIETLCVIAVDRYFAITSPFKYQSLLTKNKARVIILMVWIVSGLTSFLPIQMHWYRATHQEAINCYANETCCDFFTNQAYAIASSIVSFYVPLVIMVFVYSRVFQEAKRQLQKIDKSEGRFHVQNLSQVEQDGRTGHGLRRSSKFCLKEHKALKTLGIIMGTFTLCWLPFFIVNIVHVIQDNLIRKEVYILLNWIGYVNSGFNPLIYCRSPDFRIAFQELLCLRRSSLKAYGNGYSSNGNTGEQSGYHVEQEKENKLLCEDLPGTEDFVGHQGTVPSDNIDSQGRNCSTNDSLL",
    "DRD2_HUMAN": "MDPLNLSWYDDDLERQNWSRPFNGSDGKADRPHYNYYATLLTLLIAVIVFGNVLVCMAVSREKALQTTTNYLIVSLAVADLLVATLVMPWVVYLEVVGEWKFSRIHCDIFVTLDVMMCTASILNLCAISIDRYTAVAMPMLYNTRYSSKRRVTVMISIVWVLSFTISCPLLFGLNNADQNECIIANPAFVVYSSIVSFYVPFIVTLLVYIKIYIVLRRRRKRVNTKRSSRAFRAHLRAPLKGNCTHPEDMKLCTVIMKSNGSFPVNRRRVEAARRAQELEMEMLSSTSPPERTRYSPIPPSHHQLTLPDPSHHGLHSTPDSPAKPEKNGHAKDHPKIAKIFEIQTMPNGKTRTSLKTMSRRKLSQQKEKKATQMLAIVLGVFIICWLPFFITHILNIHCDCNIPPVLYSAFTWLGYVNSAVNPIIYTTFNIEFRKAFLKILHC",
    "HTR2A_HUMAN": "MDILCEENTSLSSTTNSLMQLNDDTRLYSNDFNSGEANTSDAFNWTVDSENRTNLSCEGCLSPSCLSLLHLQEKNWSALLTAVVIILTIAGNILVIMAVSLEKKLQNATNYFLMSLAIADMLLGFLVMPVSMLTILYGYRWPLPSKLCAVWIYLDVLFSTASIMHLCAISLDRYVAIQNPIHHSRFNSRTKAFLKIIAVWTISVGISMPIPVFGLQDDSKVFKEGSCLLADDNFVLIGSFVSFFIPLTIMVITYFLTIKSLQKEATLCVSDLGTRAKLASFSFLPQSSLSSEKLFQRSIHREPGSYTGRRTMQSISNEQKACKVLGIVFFLFVVMWCPFFITNIMAVICKESCNEDVIGALLNVFVWIGYLSSAVNPLVYTLFNKTYRSAFSRYIQCQYKENKKPLQLILVNTIPALAYKSSQLQMGQKKNSKQDAKTTDNDCSMVALGKQHSEEASKDNSDGVNEKVSCV",
}

# Smaller test set for quick operations
QUICK_TEST_SEQUENCES = {
    "SEQ_A": "MKTIIALSYIFCLVFADYKDDDDAAAFVVVLGMIVMSLIVLAIV",
    "SEQ_B": "MGQPGNGSAFLLAPNRSHAPDHDVTQQRDEVWVVGMGIVMSLIVLAIVFGNVLVITAI",
}


def _convert_payload(value: Any) -> Any:
    """Convert MCP response to Python dict."""
    text_attr = getattr(value, "text", None)
    if isinstance(text_attr, str) and text_attr:
        try:
            return json.loads(text_attr)
        except Exception:
            return text_attr

    if isinstance(value, list):
        converted = [_convert_payload(item) for item in value]
        if len(converted) == 1 and isinstance(converted[0], dict):
            return converted[0]
        return converted

    if isinstance(value, tuple):
        return tuple(_convert_payload(item) for item in value)

    if isinstance(value, dict):
        return {key: _convert_payload(val) for key, val in value.items()}

    return value


def _normalize_response(raw: Any) -> Dict[str, Any]:
    """Normalize MCP tool response."""
    if isinstance(raw, tuple) and len(raw) == 2:
        messages, meta = raw
    else:
        messages = []
        meta = raw

    text_messages: List[str] = []
    for msg in messages or []:
        text = getattr(msg, "text", None)
        if text:
            text_messages.append(text)

    meta_converted = _convert_payload(meta)

    if isinstance(meta_converted, dict):
        candidate = meta_converted.get("result", meta_converted)
        if isinstance(candidate, dict):
            payload = candidate
        else:
            payload = {"result": candidate}
    else:
        payload = {"result": meta_converted}

    if text_messages:
        payload = {**payload, "messages": text_messages}
    return payload


def estimate_response_size(response: Dict[str, Any]) -> int:
    """Estimate response size in bytes."""
    _, size = check_payload_size(response, max_bytes=1_000_000)
    return size


async def test_sequence_tools(llm_safe_mode: bool = True) -> Dict[str, Any]:
    """
    Test sequence tools with specified mode.

    Args:
        llm_safe_mode: If True, tools should return summaries only
    """
    data_root_path = (REPO_ROOT / "data").resolve()
    config = ServerConfig(data_root=data_root_path, llm_safe_mode=llm_safe_mode)

    print(f"\n{'='*60}")
    print(f"Testing with llm_safe_mode={llm_safe_mode}")
    print(f"{'='*60}")

    server = create_server(
        "Protos Sequence Tools Test",
        config=config,
    )

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
            return _normalize_response(response)

        # Initialize
        await call("config_initialize_data", reinstall_reference=True, refresh_registry=True)

        # --- Test 1: Register sequences ---
        print("\n1. Testing sequence_register_records...")
        register_result = await call(
            "sequence_register_records",
            records=[
                {"name": name, "sequence": seq}
                for name, seq in TEST_SEQUENCES.items()
            ],
            dataset_name="llm_safe_test_sequences",
            metadata={"source": "llm_safe_test"},
            overwrite=True,
        )
        results["tests"]["register"] = register_result.get("success", False)
        results["response_sizes"]["register"] = estimate_response_size(register_result)
        print(f"   Success: {results['tests']['register']}")
        print(f"   Response size: {results['response_sizes']['register']} bytes")

        # --- Test 2: List entities ---
        print("\n2. Testing list_sequence_entities...")
        list_result = await call("list_sequence_entities", limit=50)
        results["tests"]["list"] = list_result.get("success", False)
        results["response_sizes"]["list"] = estimate_response_size(list_result)
        entity_count = list_result.get("data", {}).get("total", 0)
        print(f"   Success: {results['tests']['list']}")
        print(f"   Entity count: {entity_count}")
        print(f"   Response size: {results['response_sizes']['list']} bytes")

        # --- Test 3: Load single sequence ---
        print("\n3. Testing load_sequence...")
        load_result = await call(
            "load_sequence",
            sequence_id="ADRB2_HUMAN",
            include_sequence=False,  # LLM-safe: don't include full sequence
        )
        results["tests"]["load_sequence"] = load_result.get("success", False)
        results["response_sizes"]["load_sequence"] = estimate_response_size(load_result)

        # Check if full sequence was returned (it shouldn't be in safe mode)
        data = load_result.get("data", {})
        has_full_sequence = "sequence" in data or "full_sequences" in data
        results["tests"]["load_sequence_safe"] = not has_full_sequence

        print(f"   Success: {results['tests']['load_sequence']}")
        print(f"   Full sequence returned: {has_full_sequence}")
        print(f"   Response size: {results['response_sizes']['load_sequence']} bytes")

        # --- Test 3b: Load with include_sequence=True (should be blocked in safe mode) ---
        print("\n3b. Testing load_sequence with include_sequence=True...")
        load_full_result = await call(
            "load_sequence",
            sequence_id="ADRB2_HUMAN",
            include_sequence=True,  # Request full sequence
        )
        results["response_sizes"]["load_sequence_full"] = estimate_response_size(load_full_result)
        data_full = load_full_result.get("data", {})
        has_full_in_response = "sequence" in data_full or "full_sequences" in data_full
        print(f"   Full sequence in response: {has_full_in_response}")
        print(f"   Response size: {results['response_sizes']['load_sequence_full']} bytes")

        # Explicit include_sequence=True requests are honored (for workflow use)
        # This is by design: defaults are safe, explicit requests are honored
        results["tests"]["include_sequence_honored"] = has_full_in_response

        # --- Test 4: Load dataset ---
        print("\n4. Testing load_sequence_dataset...")
        dataset_result = await call(
            "load_sequence_dataset",
            dataset_name="llm_safe_test_sequences",
            include_sequences=False,
        )
        results["tests"]["load_dataset"] = dataset_result.get("success", False)
        results["response_sizes"]["load_dataset"] = estimate_response_size(dataset_result)

        data = dataset_result.get("data", {})
        has_sequences_in_response = "sequences" in data and isinstance(data.get("sequences"), dict)
        results["tests"]["dataset_safe"] = not has_sequences_in_response

        print(f"   Success: {results['tests']['load_dataset']}")
        print(f"   Sequence count: {data.get('sequence_count', 0)}")
        print(f"   Full sequences returned: {has_sequences_in_response}")
        print(f"   Response size: {results['response_sizes']['load_dataset']} bytes")

        # --- Test 5: Alignment by ID ---
        print("\n5. Testing align_sequences_by_id...")
        align_result = await call(
            "align_sequences_by_id",
            entity1="ADRB2_HUMAN",
            entity2="DRD2_HUMAN",
            include_alignment=False,  # LLM-safe: don't include aligned sequences
        )
        results["tests"]["align"] = align_result.get("success", False)
        results["response_sizes"]["align"] = estimate_response_size(align_result)

        data = align_result.get("data", {})
        has_alignment_text = "alignment" in data and len(str(data.get("alignment", ""))) > 100
        results["tests"]["align_safe"] = not has_alignment_text

        print(f"   Success: {results['tests']['align']}")
        print(f"   Score: {data.get('score', 'N/A')}")
        print(f"   Identity: {data.get('identity', 'N/A')}")
        print(f"   Full alignment returned: {has_alignment_text}")
        print(f"   Response size: {results['response_sizes']['align']} bytes")

        # --- Test 6: Raw alignment (always returns full alignment) ---
        print("\n6. Testing align_sequences (raw)...")
        raw_align_result = await call(
            "align_sequences",
            sequence1=QUICK_TEST_SEQUENCES["SEQ_A"],
            sequence2=QUICK_TEST_SEQUENCES["SEQ_B"],
        )
        results["tests"]["align_raw"] = raw_align_result.get("success", False)
        results["response_sizes"]["align_raw"] = estimate_response_size(raw_align_result)
        print(f"   Success: {results['tests']['align_raw']}")
        print(f"   Response size: {results['response_sizes']['align_raw']} bytes")

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
    """Run tests in LLM-safe mode."""
    print("=" * 60)
    print("SEQUENCE TOOLS LLM-SAFE MODE TEST")
    print("=" * 60)

    # Test with LLM-safe mode ON (default for Claude)
    # Note: Can only run one server instance per process due to Protos singleton
    safe_results = await test_sequence_tools(llm_safe_mode=True)

    print("\n" + "=" * 60)
    if safe_results["passed"] == safe_results["total"]:
        print("[SUCCESS] All LLM-safe mode tests passed!")
    else:
        print(f"[PARTIAL] {safe_results['passed']}/{safe_results['total']} tests passed")
    print("=" * 60)

    return 0 if safe_results["passed"] == safe_results["total"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
