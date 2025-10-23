#!/usr/bin/env python3
"""Recreate the sequence alignment demo using only MCP tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
import json
from typing import Any, Dict, List

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server


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

    converted_meta = _convert_payload(meta)

    if isinstance(converted_meta, dict):
        candidate = converted_meta.get("result", converted_meta)
        if isinstance(candidate, dict):
            payload = candidate
        else:
            payload = {"result": candidate}
    else:
        payload = {"result": converted_meta}

    if text_messages:
        payload = {**payload, "messages": text_messages}
    return payload


DEMO_SEQUENCES = {
    "SEQ_ALPHA": "MKTIIALSYIFCLVFADYKDDDDA",
    "SEQ_BETA": "GSHSMRYFYTAMSRPGRGEPRFIAVGYVDDMRFYQRS",
}


async def run_workflow() -> Dict[str, Any]:
    server = create_server(
        "Protos Sequence Alignment via Tools",
        config=ServerConfig(data_root=Path("data").resolve()),
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

        dataset_register = await call(
            "sequence_register_records",
            records=[
                {"name": name, "sequence": sequence}
                for name, sequence in DEMO_SEQUENCES.items()
            ],
            dataset_name="gpcr_demo",
            overwrite=True,
            metadata={"source": "tools_sequence_alignment"},
            materialize_entities=False,
        )

        dataset_load = await call(
            "load_sequence_dataset",
            dataset_name="gpcr_demo",
            include_sequences=True,
        )
        entities = dataset_load.get("data", {}).get("entities", [])
        sequence_ids = [entry.get("sequence_id") for entry in entities if entry]

        alignment = None
        if len(sequence_ids) >= 2:
            alignment = await call(
                "align_sequences_by_id",
                entity1=sequence_ids[0],
                entity2=sequence_ids[1],
                alignment_method="blosum62",
            )

        try:
            mmseqs = await call(
                "sequence_align_mmseqs",
                dataset_name="gpcr_demo",
            )
        except Exception as exc:  # noqa: BLE001
            mmseqs = {"success": False, "error": str(exc)}

        export_info = await call(
            "sequence_export_dataset",
            dataset_name="gpcr_demo",
            export_name="gpcr_demo_alignment",
            overwrite=True,
        )

        return {
            "data_root": data_root,
            "dataset_register": dataset_register,
            "dataset_load": dataset_load,
            "alignment": alignment,
            "mmseqs": mmseqs,
            "export": export_info,
        }


def main() -> None:
    result = asyncio.run(run_workflow())

    print("Sequence Alignment via MCP Tools")
    print("=" * 34)

    for key, value in result.items():
        print(f"\n--- {key} ---")
        print(value)


if __name__ == "__main__":
    main()
