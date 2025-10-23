#!/usr/bin/env python3
"""Property workflow demo implemented via MCP tools only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server


GPCR_IDS = ["3sn6", "5d5a", "6b73"]
LOCAL_GPCR_SEQUENCES = {
    "3sn6_chain_A": "MKTIIALSYIFCLVFADYKDDDDAAAFVVVLG",
    "5d5a_chain_A": "MNTSVYIFCLVFADVTDKDNRTLLGFFVASLL",
    "6b73_chain_A": "MKSVLIFCLVFADYKDDDAAGGMVLLVFVVIL",
}
TARGET_REFERENCE = "5d5a_chain_A"


def _convert_payload(value: Any) -> Any:
    text_attr = getattr(value, "text", None)
    if isinstance(text_attr, str) and text_attr:
        try:
            return json.loads(text_attr)
        except Exception:  # noqa: BLE001
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


async def run_workflow() -> Dict[str, Any]:
    data_root_path = (REPO_ROOT / "data").resolve()
    server = create_server(
        "Protos Property Workflow via Tools",
        config=ServerConfig(data_root=data_root_path),
    )
    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            return _normalize_response(response)

        data_root = await call("config_get_data_root")
        await call(
            "config_initialize_data",
            reinstall_reference=True,
            refresh_registry=True,
        )

        download_info = await call(
            "structure_download_batch",
            identifiers=GPCR_IDS,
            dataset_name="gpcr_structures",
            create_dataset=True,
            overwrite=False,
        )

        sequence_register = await call(
            "sequence_register_records",
            records=[
                {"name": name, "sequence": seq}
                for name, seq in LOCAL_GPCR_SEQUENCES.items()
            ],
            dataset_name="gpcr_sequences",
            metadata={"source": "tools_property_workflow"},
            materialize_entities=False,
            overwrite=True,
        )

        dataset_load = await call(
            "load_sequence_dataset",
            dataset_name="gpcr_sequences",
            include_sequences=True,
        )

        sequences = dataset_load.get("data", {}).get("sequences", {})
        if TARGET_REFERENCE not in sequences:
            raise RuntimeError(f"Reference sequence {TARGET_REFERENCE} missing from dataset")

        alignments: Dict[str, Dict[str, Any]] = {}
        for seq_id in sequences:
            result = await call(
                "align_sequences_by_id",
                entity1=seq_id,
                entity2=TARGET_REFERENCE,
                alignment_method="blosum62",
            )
            alignments[seq_id] = result.get("data", result)

        classifications: Dict[str, Dict[str, Any]] = {}
        for seq_id, alignment in alignments.items():
            score = alignment.get("score")
            if score is None:
                continue
            length = max(len(sequences.get(seq_id, "")), 1)
            normalized = score / length
            classifications[seq_id] = {
                "reference": TARGET_REFERENCE,
                "raw_score": score,
                "normalized_score": normalized,
            }

        sequence_rows = [
            {
                "scope": [{"format": "sequence", "name": seq_id}],
                "reference": data["reference"],
                "score": data["normalized_score"],
                "entity_name": seq_id,
            }
            for seq_id, data in classifications.items()
        ]

        seq_property_write = await call(
            "record_property_rows",
            dataset_name="gpcr_sequence_alignment",
            rows=sequence_rows,
            allow_create=True,
        )

        threshold = 0.35
        structure_rows = []
        for seq_id, data in classifications.items():
            structure_id, _, chain = seq_id.partition("_chain_")
            classification = (
                "reference"
                if seq_id == TARGET_REFERENCE
                else ("gpcr_like" if data["normalized_score"] >= threshold else "low_similarity")
            )
            structure_rows.append(
                {
                    "scope": [
                        {"format": "structure", "name": structure_id},
                        {"format": "sequence", "name": seq_id},
                    ],
                    "classification": classification,
                    "score": data["normalized_score"],
                    "entity_name": seq_id,
                    "chain": chain or None,
                }
            )

        struct_property_write = await call(
            "record_property_rows",
            dataset_name="gpcr_structure_chain_scores",
            rows=structure_rows,
            allow_create=True,
        )

        sample_sequence = next(iter(classifications))
        sequence_props = await call(
            "load_property_rows",
            dataset_name="gpcr_sequence_alignment",
            entity_name=sample_sequence,
            scope_format="sequence",
        )

        sample_structure = TARGET_REFERENCE.split("_chain_")[0]
        structure_props = await call(
            "load_property_rows",
            dataset_name="gpcr_structure_chain_scores",
            entity_name=sample_structure,
            scope_format="structure",
        )

        return {
            "data_root": data_root,
            "structure_download": download_info,
            "sequence_register": sequence_register,
            "dataset_load": dataset_load,
            "alignments": alignments,
            "classifications": classifications,
            "sequence_property_write": seq_property_write,
            "structure_property_write": struct_property_write,
            "sequence_properties": sequence_props,
            "structure_properties": structure_props,
        }


def main() -> None:
    result = asyncio.run(run_workflow())

    print("Property Workflow via MCP Tools")
    print("=" * 34)

    for key, value in result.items():
        print(f"\n--- {key} ---")
        print(value)


if __name__ == "__main__":
    main()

