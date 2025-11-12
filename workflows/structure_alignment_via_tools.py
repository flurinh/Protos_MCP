#!/usr/bin/env python3
"""Recreate the structure alignment workflow using only MCP tools."""

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


DEMO_STRUCTURES = ["3sn6", "5d5a", "6b73"]
DATASET_NAME = "gpcr_structures"
ALIGNED_DATASET = "gpcr_alignment_aligned"
SUMMARY_DATASET_NAME = "gpcr_structure_alignment_properties"


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
        "Protos Structure Alignment Workflow via Tools",
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
            identifiers=DEMO_STRUCTURES,
            processor_type="structure",
            dataset_name=DATASET_NAME,
            create_dataset=True,
            overwrite=False,
        )

        downloaded: List[str] = []
        download_data = download.get("data", {})
        if isinstance(download_data, dict):
            downloaded = download_data.get("downloaded") or []

        dataset_entities = await call(
            "dataset_entities",
            name=DATASET_NAME,
            processor_type="structure",
        )
        dataset_list = dataset_entities.get("data", {}).get("entities", []) or []

        candidate_ids = [sid.upper() for sid in downloaded] or [sid.upper() for sid in dataset_list]

        available: List[str] = []
        for struct_id in candidate_ids:
            load_resp = await call("load_structure", structure_id=struct_id, include_atoms=False)
            if load_resp.get("success", True):
                available.append(struct_id)

        if len(available) < 2:
            raise RuntimeError(
                "Need at least two GPCR structures for alignment"
            )

        reference_id = available[0]
        export_dir = Path(data_root.get("data", {}).get("data_root", data_root_path))
        export_dir = export_dir / "structure" / "mmcif"

        alignment = await call(
            "structure_align_to_reference",
            reference_id=reference_id,
            structure_ids=available,
            method="cealign",
            atom_selection="CA",
            apply_transform=True,
            persist_aligned=True,
            export_aligned=True,
            export_directory=str(export_dir),
            save_dataset_name=ALIGNED_DATASET,
            include_reference_in_dataset=True,
            summary_name=f"{reference_id}_gpcr_alignment",
            property_table_name=SUMMARY_DATASET_NAME,
        )

        alignment_data = alignment.get("data", {})
        if not alignment.get("success", True):
            raise RuntimeError(
                f"structure_align_to_reference failed: {alignment.get('error')}"
            )

        aligned_dataset = alignment_data.get("aligned_dataset") or ALIGNED_DATASET
        dataset_stats = await call(
            "structure_dataset_stats",
            dataset_name=aligned_dataset,
            include_entities=True,
        )

        property_table = alignment_data.get("property_table")
        property_rows = None
        if property_table:
            property_rows = await call(
                "load_property_rows",
                dataset_name=property_table,
                limit=20,
            )

        summary_dataset = alignment_data.get("summary_dataset")
        summary_load = None
        if summary_dataset:
            summary_load = await call(
                "load_property_rows",
                dataset_name=summary_dataset,
                limit=20,
            )

        return {
            "data_root": data_root,
            "download": download,
            "available_structures": available,
            "reference_id": reference_id,
            "alignment": alignment,
            "aligned_dataset": dataset_stats,
            "property_rows": property_rows,
            "summary_rows": summary_load,
            "export_directory": str(export_dir),
            "alignment_data": alignment_data,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Structure Alignment Workflow via MCP Tools")
    print("=" * 45)

    for key in (
        "reference_id",
        "available_structures",
        "alignment",
        "aligned_dataset",
        "property_rows",
        "summary_rows",
    ):
        print(f"\n--- {key} ---")
        print(result.get(key))

    exported = result.get("alignment_data", {}).get("exported_files") or result.get("alignment", {}).get("data", {}).get("exported_files")
    if exported:
        print("\nExported aligned structures:")
        for name, path in exported.items():
            print(f"  {name} -> {path}")


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
