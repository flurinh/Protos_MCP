#!/usr/bin/env python3
"""Recreate the structure GRN annotation workflow using only MCP tools."""

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


STRUCTURE_IDS = ["3sn6", "5d5a", "6b73", "4daj"]
STRUCTURE_DATASET = "grn_annotation_structures"
CHAIN_DATASET_PREFIX = "grn_chain_dataset"
FILTERED_DATASET = "grn_chain_filtered"
FILTERED_STRUCTURE_DATASET = "grn_filtered_structures"
REFERENCE_SEQUENCE = "5d5a_chain_A"
REFERENCE_TABLE = "gpcrdb_ref"
PROTEIN_FAMILY = "gpcr_a"
ALIGNMENT_THRESHOLD = 1.0


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
        "Protos Structure GRN Annotation via Tools",
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

        download = await call(
            "download_entities",
            identifiers=STRUCTURE_IDS,
            processor_type="structure",
            dataset_name=STRUCTURE_DATASET,
            create_dataset=True,
            overwrite=False,
        )

        dataset_entities_resp = await call(
            "dataset_entities",
            name=STRUCTURE_DATASET,
            processor_type="structure",
        )
        structure_entities = dataset_entities_resp.get("data", {}).get("entities", []) or []
        if not structure_entities:
            raise RuntimeError("No structures registered; aborting GRN workflow")

        grn_pipeline = await call(
            "structure_prepare_grn_annotations",
            structure_ids=STRUCTURE_IDS,
            reference_table=REFERENCE_TABLE,
            protein_family=PROTEIN_FAMILY,
            reference_sequence_entity=REFERENCE_SEQUENCE,
            alignment_threshold=ALIGNMENT_THRESHOLD,
            chain_dataset_prefix=CHAIN_DATASET_PREFIX,
            filtered_sequence_dataset=FILTERED_DATASET,
            grn_table_name=f"{FILTERED_DATASET}_grn",
            column_name="grn",
        )
        grn_data = grn_pipeline.get("data", {}) if isinstance(grn_pipeline, dict) else {}
        grn_table_name = grn_data.get("grn_table") or f"{FILTERED_DATASET}_grn"
        apply_grn = grn_data.get("structure_annotation_summary")

        dataset_summary = await call(
            "load_sequence_dataset",
            dataset_name=grn_data.get("filtered_dataset", FILTERED_DATASET),
            include_sequences=False,
        )

        return {
            "data_root": data_root,
            "download": download,
            "structures": structure_entities,
            "grn_pipeline": grn_pipeline,
            "apply_grn": apply_grn,
            "sequence_dataset": dataset_summary,
            "grn_table": grn_table_name,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Structure GRN Annotation Workflow via MCP Tools")
    print("=" * 51)

    print("Structures:", result.get("structures"))
    pipeline = result.get("grn_pipeline", {}).get("data", {})
    if pipeline:
        print("Filtered GPCR-like chains:", pipeline.get("filtered_sequences"))
        metrics = pipeline.get("alignment_metrics") or {}
        if metrics:
            sample = list(metrics.items())[:5]
            print("Alignment metric sample (normalized score):", sample)
        print("Filtered sequence dataset:", pipeline.get("filtered_dataset"))
    apply_grn = result.get("apply_grn") or {}
    if apply_grn:
        print("Annotated residues per structure:", apply_grn.get("annotation_counts"))
        if apply_grn.get("skipped"):
            print("Skipped chains:", apply_grn.get("skipped"))
    dataset_info = result.get("sequence_dataset", {}).get("data", {})
    if dataset_info:
        print(
            "Filtered sequence dataset summary:",
            dataset_info.get("dataset_name"),
            "entities=",
            dataset_info.get("entity_count"),
        )
    print("GRN table:", result.get("grn_table"))


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
