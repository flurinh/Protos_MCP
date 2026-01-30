#!/usr/bin/env python3
"""Test script to verify LLM-safe mode configuration and response builders."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_config():
    """Test ServerConfig with llm_safe_mode."""
    from mcp_server.config import ServerConfig, LLMSafeLimits

    # Test default config
    config = ServerConfig()
    print("=== ServerConfig Test ===")
    print(f"llm_safe_mode (default): {config.llm_safe_mode}")
    assert config.llm_safe_mode is True, "Default should be True"

    # Test limits
    limits = config.llm_limits
    print(f"max_sequence_preview_chars: {limits.max_sequence_preview_chars}")
    print(f"max_sequences_in_response: {limits.max_sequences_in_response}")
    print(f"max_response_bytes: {limits.max_response_bytes}")
    assert limits.max_sequence_preview_chars == 100
    assert limits.max_embedding_dimensions_shown == 0  # Never show embeddings

    # Test workflow mode (llm_safe_mode=False)
    workflow_config = ServerConfig(llm_safe_mode=False)
    print(f"\nWorkflow mode llm_safe_mode: {workflow_config.llm_safe_mode}")
    assert workflow_config.llm_safe_mode is False

    # Test limits serialization
    limits_dict = limits.to_dict()
    restored = LLMSafeLimits.from_dict(limits_dict)
    assert restored.max_sequence_preview_chars == limits.max_sequence_preview_chars
    print("\nConfig serialization: OK")

    print("\n[PASS] ServerConfig tests passed!")


def test_response_builders():
    """Test response builder utilities."""
    from mcp_server.core.response import (
        DataType,
        DataSummary,
        LLMResponse,
        build_structure_summary,
        build_sequence_summary,
        build_sequence_dataset_summary,
        build_embedding_summary,
        build_ligand_response,
        build_alignment_summary,
        truncate_list,
        check_payload_size,
    )

    print("\n=== Response Builder Tests ===")

    # Test structure summary
    struct_summary = build_structure_summary(
        name="5d5a",
        atom_count=12453,
        chains={"A": 342, "B": 289},
        ligands=["CAU", "SO4"],
        resolution=2.1,
    )
    print(f"\nStructure summary: {struct_summary.to_dict()}")
    assert struct_summary.data_type == DataType.STRUCTURE
    assert struct_summary.count == 12453
    assert "CAU" in struct_summary.statistics["ligands"]

    # Test sequence summary (should truncate)
    long_sequence = "M" * 500  # 500 amino acids
    seq_summary = build_sequence_summary(
        name="P30542",
        length=500,
        sequence=long_sequence,
        preview_length=100,
    )
    print(f"\nSequence summary: {seq_summary.to_dict()}")
    assert len(seq_summary.preview) == 103  # 100 + "..."
    assert seq_summary.preview.endswith("...")

    # Test sequence dataset summary
    sequences = {f"seq_{i}": "MKTIIALSYIFCLVFA" * 10 for i in range(50)}
    dataset_summary = build_sequence_dataset_summary(
        name="my_dataset",
        sequences=sequences,
        max_ids_shown=20,
    )
    print(f"\nDataset summary: {dataset_summary.to_dict()}")
    assert dataset_summary.count == 50
    assert len(dataset_summary.schema["sequence_ids"]) == 20
    assert dataset_summary.statistics["ids_truncated"] is True

    # Test embedding summary (should NEVER include vectors)
    emb_summary = build_embedding_summary(
        name="melanopsin_esm2",
        sequence_count=128,
        dimensions=2560,
        model_name="esm2_t36_3B",
    )
    print(f"\nEmbedding summary: {emb_summary.to_dict()}")
    assert emb_summary.preview is None  # No preview for embeddings
    assert emb_summary.schema["dimensions"] == 2560

    # Test ligand response (full data OK)
    ligand_resp = build_ligand_response(
        name="DOPAMINE_1",
        smiles="NCCc1ccc(O)c(O)c1",
        properties={"mw": 153.18, "logP": 0.84},
    )
    print(f"\nLigand response: {ligand_resp.to_dict()}")
    assert ligand_resp.data["smiles"] == "NCCc1ccc(O)c(O)c1"

    # Test alignment summary (no sequences)
    align_summary = build_alignment_summary(
        seq1_name="seq_A",
        seq2_name="seq_B",
        score=245.0,
        identity=0.87,
        length=342,
        gaps=15,
        method="blosum62",
    )
    print(f"\nAlignment summary: {align_summary.to_dict()}")
    assert align_summary.statistics["identity"] == 0.87
    assert align_summary.preview is None  # No aligned sequences

    # Test truncate_list
    big_list = list(range(100))
    truncated = truncate_list(big_list, max_items=25)
    print(f"\nTruncated list: showing {truncated['showing']}/{truncated['count']}")
    assert truncated["count"] == 100
    assert truncated["showing"] == 25
    assert truncated["truncated"] is True

    # Test payload size check
    small_data = {"name": "test", "value": 42}
    is_ok, size = check_payload_size(small_data, max_bytes=50_000)
    print(f"\nSmall payload: {size} bytes, OK={is_ok}")
    assert is_ok is True

    huge_data = {"sequences": {"seq_" + str(i): "M" * 1000 for i in range(100)}}
    is_ok, size = check_payload_size(huge_data, max_bytes=50_000)
    print(f"Large payload: {size} bytes, OK={is_ok}")
    assert is_ok is False

    print("\n[PASS] Response builder tests passed!")


def test_base_tool_helpers():
    """Test BaseTool LLM-safe helper methods."""
    from mcp_server.config import ServerConfig
    from mcp_server.context import ServerContext

    print("\n=== BaseTool Helper Tests ===")

    # Create a mock context
    config = ServerConfig(llm_safe_mode=True)
    context = ServerContext.initialize(config)

    # Import BaseTool and create instance
    from mcp_server.tools.base import BaseTool

    class TestTool(BaseTool):
        pass

    tool = TestTool(context)

    # Test llm_safe_mode property
    print(f"llm_safe_mode: {tool.llm_safe_mode}")
    assert tool.llm_safe_mode is True

    # Test should_include_data
    assert tool.should_include_data("ligand") is True  # Ligands OK
    assert tool.should_include_data("sequence") is False  # Sequences not OK
    assert tool.should_include_data("structure") is False
    assert tool.should_include_data("embedding") is False
    print("should_include_data: OK")

    # Test get_sequence_preview
    seq = "MKTIIALSYIFCLVFADYKDDDDAAAFVVVLGILLTTIVAGNVVVCIAVCERR"
    preview = tool.get_sequence_preview(seq, max_chars=30)
    print(f"Sequence preview: {preview}")
    assert len(preview) == 33  # 30 + "..."
    assert preview.endswith("...")

    # Test truncate_entity_list
    entities = [f"entity_{i}" for i in range(50)]
    result = tool.truncate_entity_list(entities, max_items=10)
    print(f"Truncated entities: {result['showing']}/{result['count']}")
    assert result["count"] == 50
    assert result["showing"] == 10

    # Test with workflow mode (llm_safe_mode=False)
    workflow_config = ServerConfig(llm_safe_mode=False)
    workflow_context = ServerContext.initialize(workflow_config)
    workflow_tool = TestTool(workflow_context)

    assert workflow_tool.llm_safe_mode is False
    assert workflow_tool.should_include_data("sequence") is True  # In workflow mode, everything OK
    print("Workflow mode: OK")

    print("\n[PASS] BaseTool helper tests passed!")


def main():
    """Run all tests."""
    print("Testing LLM-Safe Mode Infrastructure")
    print("=" * 50)

    try:
        test_config()
        test_response_builders()
        test_base_tool_helpers()

        print("\n" + "=" * 50)
        print("[SUCCESS] All tests passed!")
        print("\nPhase 1 & 2 complete:")
        print("  - llm_safe_mode added to ServerConfig")
        print("  - LLMSafeLimits dataclass with configurable limits")
        print("  - Response builders for all data types")
        print("  - BaseTool helpers for LLM-safe responses")
        print("\nNext steps:")
        print("  - Phase 3: Migrate individual tools to use these helpers")
        print("  - Start with sequence tools, test with workflows")

    except Exception as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
