#!/usr/bin/env python3
"""Recreate the sequence ingestion/export workflow using only MCP tools."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server


def _normalize_response(raw: Tuple[Any, Any]) -> Dict[str, Any]:
    messages, meta = raw
    text_messages: List[str] = []
    for msg in messages or []:
        text = getattr(msg, "text", None)
        if text:
            text_messages.append(text)

    payload: Dict[str, Any] = {}
    if isinstance(meta, dict) and "result" in meta:
        payload = meta["result"]
    elif isinstance(meta, dict):
        payload = meta

    if text_messages:
        payload = {**payload, "messages": text_messages}
    return payload


async def run_workflow() -> Dict[str, Any]:
    server = create_server("Protos Workflow Runner", config=ServerConfig(data_root=Path("data").resolve()))
    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            return _normalize_response(response)

        # Ensure Protos data root is initialized
        data_root_info = await call("config_get_data_root")
        init_info = await call(
            "config_initialize_data",
            reinstall_reference=True,
            refresh_registry=True,
        )
        # Register sequences using in-memory records (no direct filesystem IO)
        single_register = await call(
            "sequence_register_records",
            records=[{"name": "SINGLE_SEQ", "sequence": "MPLNVSFTDLEK"}],
            dataset_name="single_sequence",
            metadata={"source": "tools_sequence_workflow"},
            overwrite=True,
        )

        dataset_register = await call(
            "sequence_register_records",
            records=[
                {"name": "SEQ_ALPHA", "sequence": "MKTIIALSYIFCLVFADYKDDDDA"},
                {"name": "SEQ_BETA", "sequence": "GSHSMRYFYTAMSRPGRGEPRFIAVGYVDDMRFYQRS"},
            ],
            dataset_name="demo_sequences",
            metadata={"source": "tools_sequence_workflow"},
            overwrite=True,
        )

        # Attempt to fetch GPCR dataset (may fail without network access)
        gpcr_download: Dict[str, Any]
        try:
            gpcr_download = await call(
                "sequence_download",
                identifier="uniprot:P30542,P07550,Q9Y5N6",
                name="gpcr_sequences",
                materialize_entities=False,
            )
        except Exception as exc:  # noqa: BLE001
            gpcr_download = {"success": False, "error": str(exc)}

        dataset_load = await call(
            "load_sequence_dataset",
            dataset_name="demo_sequences",
            include_sequences=True,
        )
        entities = dataset_load.get("data", {}).get("entities", [])
        sequence_ids = [entry.get("sequence_id") or entry.get("entity") for entry in entities if entry]

        alignment = None
        if len(sequence_ids) >= 2:
            alignment = await call(
                "align_sequences_by_id",
                entity1=sequence_ids[0],
                entity2=sequence_ids[1],
                alignment_method="blosum62",
            )

        export_full = await call(
            "sequence_export_dataset",
            dataset_name="demo_sequences",
            overwrite=True,
        )

        subset_export = None
        if sequence_ids:
            subset_export = await call(
                "sequence_export_dataset",
                dataset_name="demo_sequences",
                export_name="demo_sequences_subset",
                sequence_ids=[sequence_ids[-1]],
                overwrite=True,
            )

        single_export = None
        if sequence_ids:
            single_export = await call(
                "sequence_export_entity",
                sequence_id=sequence_ids[0],
                overwrite=True,
            )

        mutant_library = None
        conservation = None
        linkage = None
        if sequence_ids:
            try:
                mutant_library = await call(
                    "sequence_create_mutant_library",
                    base_sequence_id=sequence_ids[0],
                    mutation_map={"5": ["S", "T"], "10": ["K"]},
                    limit=3,
                    include_wildtype=True,
                    return_metadata=True,
                )
            except Exception as exc:  # noqa: BLE001
                mutant_library = {"success": False, "error": str(exc)}

            if mutant_library and mutant_library.get("success"):
                library_sequences = mutant_library.get("data", {}).get("library")
                if library_sequences:
                    conservation = await call(
                        "sequence_compute_conservation",
                        sequences=library_sequences,
                        include_dataframe=True,
                    )
                    linkage = await call(
                        "sequence_compute_linkage",
                        sequences=library_sequences,
                        top_k=3,
                    )

        gpcr_export = None
        if gpcr_download.get("success") and gpcr_download.get("data", {}).get("registered"):
            gpcr_entities = await call(
                "load_sequence_dataset",
                dataset_name=gpcr_download["data"]["registered"],
                include_sequences=True,
            )
            gpcr_sequences = gpcr_entities.get("data", {}).get("sequences")
            if gpcr_sequences:
                gpcr_export = await call(
                    "sequence_save_sequences",
                    sequences=gpcr_sequences,
                    output_file="gpcr_sequences_export",
                    dataset_name="gpcr_sequences_export",
                    materialize_entities=False,
                )

        return {
            "data_root": data_root_info,
            "single_register": single_register,
            "dataset_register": dataset_register,
            "gpcr_download": gpcr_download,
            "dataset_load": dataset_load,
            "alignment": alignment,
            "export_full": export_full,
            "subset_export": subset_export,
            "single_export": single_export,
            "mutant_library": mutant_library,
            "conservation": conservation,
            "linkage": linkage,
            "gpcr_export": gpcr_export,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Sequence Workflow via MCP Tools")
    print("================================\n")
    for key, value in result.items():
        print(f"--- {key} ---")
        print(value)
        print()

    export_dir = Path(result["data_root"]["data"]["data_root"]) / "sequence_output"
    if export_dir.exists():
        print(f"Files in {export_dir}:")
        for path in sorted(export_dir.iterdir()):
            print(f"  - {path.name}")
        print()


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
