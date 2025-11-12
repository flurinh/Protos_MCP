#!/usr/bin/env python3
"""Recreate the GPCR chain workflow using only MCP tools."""

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


DEMO_STRUCTURES = ["3sn6", "5d5a", "6b73"]
CHAIN_LIMIT = 4


async def run_workflow() -> Dict[str, Any]:
    data_root_path = (REPO_ROOT / "data").resolve()
    server = create_server(
        "Protos Sequence Real Workflow via Tools",
        config=ServerConfig(data_root=data_root_path),
    )
    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            print(f"[DEBUG][RAW] {tool}: {response}", flush=True)
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
            dataset_name="gpcr_structures",
            create_dataset=True,
            overwrite=False,
        )

        dataset_entities_resp = await call(
            "dataset_entities",
            name="gpcr_structures",
            processor_type="structure",
        )

        if not dataset_entities_resp.get("success", True):
            raise RuntimeError(
                f"dataset_entities failed: {dataset_entities_resp.get('error')}"
            )

        print("[DEBUG] download_entities:", download, flush=True)
        print("[DEBUG] dataset_entities:", dataset_entities_resp, flush=True)

        downloaded_structures = download.get("data", {}).get("downloaded", []) or []
        dataset_structures = (
            dataset_entities_resp.get("data", {}).get("entities", []) or []
        )

        downloaded_structures = list(
            dict.fromkeys(downloaded_structures + dataset_structures)
        )

        print("[DEBUG] merged_structures:", downloaded_structures, flush=True)

        if not downloaded_structures:
            raise RuntimeError(
                "Dataset 'gpcr_structures' has no registered structures; ensure downloads succeed"
            )

        register_chains = await call(
            "structure_register_chain_sequences_from_dataset",
            dataset_name="gpcr_structures",
            dataset_prefix="gpcr_chain_dataset",
            create_dataset=True,
            overwrite=True,
        )

        chain_entities: List[str] = register_chains.get("data", {}).get("registered_entities", [])
        selected_entities = sorted(set(chain_entities))[:CHAIN_LIMIT]

        collected_sequences: Dict[str, str] = {}
        load_details: Dict[str, Any] = {}
        for entity in selected_entities:
            seq_payload = await call(
                "load_sequence",
                sequence_id=entity,
                include_sequence=True,
            )
            sequence_data = seq_payload.get("data", {})
            sequence = sequence_data.get("sequence")
            if sequence is None and "full_sequences" in sequence_data:
                for sub_id, seq in sequence_data["full_sequences"].items():
                    collected_sequences[f"{entity}_{sub_id}"] = seq
            elif sequence:
                collected_sequences[entity] = sequence
            load_details[entity] = sequence_data

        if len(collected_sequences) > CHAIN_LIMIT:
            collected_sequences = dict(list(collected_sequences.items())[:CHAIN_LIMIT])

        if not collected_sequences:
            raise RuntimeError("Chain sequence extraction produced no sequences; aborting workflow.")

        dataset_register = await call(
            "sequence_register_records",
            records=[
                {"name": name, "sequence": seq}
                for name, seq in collected_sequences.items()
            ],
            dataset_name="gpcr_chains_real",
            overwrite=True,
            metadata={"source": "tools_sequence_real_workflow"},
            materialize_entities=False,
        )

        dataset_load = await call(
            "load_sequence_dataset",
            dataset_name="gpcr_chains_real",
            include_sequences=True,
        )

        sequences = dataset_load.get("data", {}).get("sequences", {})
        seq_ids = list(sequences.keys())

        alignment = None
        if len(seq_ids) >= 2:
            alignment = await call(
                "align_sequences_by_id",
                entity1=seq_ids[0],
                entity2=seq_ids[1],
                alignment_method="blosum62",
            )

        mmseqs = await call(
            "sequence_align_mmseqs",
            dataset_name="gpcr_chains_real",
        )

        # Group by length to mirror the original workflow
        length_groups: Dict[int, List[str]] = {}
        for seq_id, seq in sequences.items():
            length_groups.setdefault(len(seq), []).append(seq_id)

        primary_subset = None
        conservation_subset = None
        linkage_subset = None
        if length_groups:
            primary_length, primary_ids = max(length_groups.items(), key=lambda item: len(item[1]))
            if len(primary_ids) >= 2:
                subset_map = {sid: sequences[sid] for sid in primary_ids}
                conservation_subset = await call(
                    "sequence_compute_conservation",
                    sequences=subset_map,
                )
                linkage_subset = await call(
                    "sequence_compute_linkage",
                    sequences=subset_map,
                    top_k=5,
                )
                primary_subset = {
                    "length": primary_length,
                    "ids": primary_ids,
                }

        mutant_results = None
        mutant_conservation = None
        mutant_linkage = None
        library_sequences: Dict[str, str] = {}

        if seq_ids:
            base_sequence_id = seq_ids[0]
            base_sequence = sequences[base_sequence_id]
            seq_len = len(base_sequence)

            pos_candidates = [5, 100, 150]
            normalized_positions: Dict[str, List[str]] = {}
            for pos, residues in zip(pos_candidates, (["S", "T"], ["K"], ["E"])):
                upper_bound = max(3, seq_len - 1)
                normalized = min(max(3, pos), upper_bound)
                normalized_positions[str(normalized)] = list(residues)

            mutant_results = await call(
                "sequence_create_mutant_library",
                base_sequence_id=base_sequence_id,
                mutation_map=normalized_positions,
                base_name=f"{base_sequence_id}_mut",
                include_wildtype=True,
                limit=10,
                register=True,
                dataset_name=f"{base_sequence_id}_mutants",
                materialize_entities=False,
                return_metadata=True,
            )

            library_sequences = mutant_results.get("data", {}).get("library", {})
            if library_sequences:
                mutant_conservation = await call(
                    "sequence_compute_conservation",
                    sequences=library_sequences,
                )
                mutant_linkage = await call(
                    "sequence_compute_linkage",
                    sequences=library_sequences,
                    top_k=5,
                )

        return {
            "data_root": data_root,
            "structure_downloads": download,
            "chain_registration": register_chains,
            "selected_entities": selected_entities,
            "load_details": load_details,
            "sequence_dataset_register": dataset_register,
            "sequence_dataset_load": dataset_load,
            "alignment": alignment,
            "mmseqs": mmseqs,
            "primary_subset": primary_subset,
            "conservation_subset": conservation_subset,
            "linkage_subset": linkage_subset,
            "mutant_results": mutant_results,
            "mutant_conservation": mutant_conservation,
            "mutant_linkage": mutant_linkage,
        }


def main() -> None:
    result = asyncio.run(run_workflow())

    print("Sequence Real Workflow via MCP Tools")
    print("=" * 39)

    for key, value in result.items():
        print(f"\n--- {key} ---")
        print(value)


if __name__ == "__main__":
    main()
