#!/usr/bin/env python3
"""Recreate the structure embedding similarity workflow using only MCP tools."""

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
STRUCTURE_DATASET = "embedding_structures"
CHAIN_DATASET_PREFIX = "embedding_chain_dataset"
SEQUENCE_DATASET = "embedding_chain_sequences"
REFERENCE_STRUCTURE = "5d5a"
REFERENCE_CHAIN = "A"
REFERENCE_SEQUENCE = f"{REFERENCE_STRUCTURE}_chain_{REFERENCE_CHAIN}"
ALIGNMENT_THRESHOLD = 0.35
EMBEDDING_MODEL = "esm2_t12_35m"
EMBEDDING_TYPE = "per_residue"
EMBEDDING_DATASET_PREFIX = "embedding_chain_sequences"
PROPERTY_TABLE = "gpcr_structure_embedding_similarity"


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
        "Protos Structure Embedding Similarity via Tools",
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
            raise RuntimeError("No structures available for embedding analysis")

        register = await call(
            "structure_register_chain_sequences_from_dataset",
            dataset_name=STRUCTURE_DATASET,
            dataset_prefix=CHAIN_DATASET_PREFIX,
            create_dataset=True,
            overwrite=True,
            one_letter=True,
            min_length=1,
        )
        register_data = register.get("data", {}) if isinstance(register, dict) else {}
        registered_sequences = sorted(set(register_data.get("registered_entities", [])))
        if not registered_sequences:
            raise RuntimeError("Chain registration produced no sequences")

        sequence_lengths: Dict[str, int] = {}
        for seq_id in registered_sequences:
            seq_resp = await call("load_sequence", sequence_id=seq_id, include_sequence=True)
            seq_data = seq_resp.get("data", {}) if isinstance(seq_resp, dict) else {}
            sequence = seq_data.get("sequence")
            if sequence is None:
                full_sequences = seq_data.get("full_sequences")
                if isinstance(full_sequences, dict) and full_sequences:
                    sequence = next(iter(full_sequences.values()))
            if sequence:
                sequence_lengths[seq_id] = len(sequence)

        if REFERENCE_SEQUENCE not in sequence_lengths:
            ref_resp = await call("load_sequence", sequence_id=REFERENCE_SEQUENCE, include_sequence=True)
            ref_data = ref_resp.get("data", {}) if isinstance(ref_resp, dict) else {}
            ref_sequence = ref_data.get("sequence")
            if ref_sequence is None:
                full_sequences = ref_data.get("full_sequences")
                if isinstance(full_sequences, dict) and full_sequences:
                    ref_sequence = next(iter(full_sequences.values()))
            if not ref_sequence:
                raise RuntimeError(f"Reference sequence {REFERENCE_SEQUENCE} is unavailable")
            sequence_lengths[REFERENCE_SEQUENCE] = len(ref_sequence)

        structure_to_chains: Dict[str, List[str]] = {}
        for seq_id in registered_sequences:
            if "_chain_" not in seq_id:
                continue
            structure_id, _chain = seq_id.split("_chain_", 1)
            structure_to_chains.setdefault(structure_id, []).append(seq_id)

        alignment_metrics: Dict[str, Dict[str, Any]] = {}
        selected_chains: Dict[str, str] = {}
        for structure_id, chain_entities in structure_to_chains.items():
            best_score = -1.0
            best_chain: Optional[str] = None
            for seq_id in chain_entities:
                align_resp = await call(
                    "align_sequences_by_id",
                    entity1=seq_id,
                    entity2=REFERENCE_SEQUENCE,
                    alignment_method="blosum62",
                )
                align_data = align_resp.get("data", align_resp) if isinstance(align_resp, dict) else {}
                score = align_data.get("score")
                length = sequence_lengths.get(seq_id)
                normalized = None
                if score is not None and length:
                    normalized = float(score) / max(float(length), 1.0)
                alignment_metrics[seq_id] = {
                    "score": score,
                    "normalized": normalized,
                    "length": length,
                    "reference": REFERENCE_SEQUENCE,
                }
                if normalized is not None and normalized >= ALIGNMENT_THRESHOLD and normalized > best_score:
                    best_score = normalized
                    best_chain = seq_id
            # Ensure reference structure always keeps its reference chain
            if structure_id == REFERENCE_STRUCTURE:
                best_chain = REFERENCE_SEQUENCE
                best_score = alignment_metrics.get(REFERENCE_SEQUENCE, {}).get("normalized", best_score)
            if best_chain:
                selected_chains[structure_id] = best_chain

        if REFERENCE_STRUCTURE not in selected_chains:
            raise RuntimeError("Reference structure did not pass classification; adjust threshold")
        if len(selected_chains) < 2:
            raise RuntimeError("Insufficient GPCR-like chains identified for embedding comparison")

        filtered_sequences = sorted(selected_chains.values())
        excluded_sequences = sorted(set(registered_sequences) - set(filtered_sequences))

        sequence_metadata = {
            "source": "structure_embedding_similarity_via_tools",
            "reference_sequence": REFERENCE_SEQUENCE,
            "threshold": ALIGNMENT_THRESHOLD,
            "entity_count": len(filtered_sequences),
        }
        datasets_resp = await call("list_datasets", processor_type="sequence")
        known_sequence_datasets = datasets_resp.get("data", {}).get("datasets", []) or []
        if SEQUENCE_DATASET in known_sequence_datasets:
            existing_resp = await call("dataset_entities", name=SEQUENCE_DATASET, processor_type="sequence")
            existing_entities = existing_resp.get("data", {}).get("entities", []) or []
            to_add = sorted(set(filtered_sequences) - set(existing_entities))
            to_remove = sorted(set(existing_entities) - set(filtered_sequences))
            await call(
                "update_dataset",
                name=SEQUENCE_DATASET,
                processor_type="sequence",
                add_entities=to_add or None,
                remove_entities=to_remove or None,
                metadata=sequence_metadata,
            )
            sequence_dataset_summary = await call(
                "dataset_info",
                name=SEQUENCE_DATASET,
                processor_type="sequence",
            )
        else:
            sequence_dataset_summary = await call(
                "create_dataset",
                name=SEQUENCE_DATASET,
                entities=filtered_sequences,
                processor_type="sequence",
                metadata=sequence_metadata,
            )

        embedding_result = await call(
            "embedding_generate",
            model_name=EMBEDDING_MODEL,
            dataset_name=SEQUENCE_DATASET,
            embedding_types=[EMBEDDING_TYPE],
            save_prefix=EMBEDDING_DATASET_PREFIX,
            register_entities=True,
        )
        if not embedding_result.get("success", True):
            raise RuntimeError(f"Embedding generation failed: {embedding_result.get('error')}")
        embedding_data = embedding_result.get("data", embedding_result)
        embedding_dataset_tag = embedding_data.get("embedding_types", {}).get(EMBEDDING_TYPE)
        if not embedding_dataset_tag:
            raise RuntimeError("Embedding dataset tag missing from embedding_generate response")

        selection_payload: List[Dict[str, str]] = []
        for structure_id, seq_id in selected_chains.items():
            if "_chain_" not in seq_id:
                continue
            chain_id = seq_id.split("_chain_", 1)[1]
            selection_payload.append(
                {
                    "structure_id": structure_id,
                    "chain_id": chain_id,
                    "sequence_id": seq_id,
                }
            )

        reference_chain_entry = selected_chains.get(REFERENCE_STRUCTURE, REFERENCE_SEQUENCE)
        reference_chain_id = reference_chain_entry.split("_chain_", 1)[1] if "_chain_" in reference_chain_entry else REFERENCE_CHAIN

        similarity_resp = await call(
            "structure_compute_embedding_similarity",
            reference_structure=REFERENCE_STRUCTURE,
            reference_chain=reference_chain_id,
            embedding_dataset=embedding_dataset_tag,
            selection=selection_payload,
            property_table_name=PROPERTY_TABLE,
            record_property_table=True,
            include_records=False,
            include_plot_points=False,
        )
        similarity_data = similarity_resp.get("data", similarity_resp)
        property_table_name = similarity_data.get("property_table") or PROPERTY_TABLE

        summary_rows = similarity_data.get("summary", [])
        rmsd_map = similarity_data.get("rmsd", {})

        return {
            "data_root": data_root,
            "download": download,
            "structures": structure_entities,
            "registered_sequences": registered_sequences,
            "filtered_sequences": filtered_sequences,
            "excluded_sequences": excluded_sequences,
            "alignment_metrics": alignment_metrics,
            "selected_chains": selected_chains,
            "sequence_dataset": sequence_dataset_summary,
            "embedding_dataset": embedding_dataset_tag,
            "similarity_summary": summary_rows,
            "rmsd": rmsd_map,
            "property_table": property_table_name,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Structure Embedding Similarity via MCP Tools")
    print("=" * 52)

    print("Structures:", result.get("structures"))
    print("Registered chains:", len(result.get("registered_sequences") or []))
    print("Filtered sequences:", result.get("filtered_sequences"))
    excluded = result.get("excluded_sequences") or []
    if excluded:
        print("Excluded sequences:", excluded)
    selection = result.get("selected_chains") or {}
    if selection:
        print("Selected chain per structure:")
        for structure_id, seq_id in selection.items():
            print(f"  {structure_id}: {seq_id}")
    metrics = result.get("alignment_metrics") or {}
    if metrics:
        print("Alignment scores (normalized):")
        for seq_id, payload in metrics.items():
            norm = payload.get("normalized")
            if isinstance(norm, (int, float)):
                print(f"  {seq_id}: {norm:.3f}")
            else:
                print(f"  {seq_id}: n/a")
    seq_dataset = result.get("sequence_dataset", {}).get("data", {})
    if seq_dataset:
        name = seq_dataset.get("name") or seq_dataset.get("dataset_name")
        count = seq_dataset.get("entity_count")
        print("Sequence dataset:", name, "entities=", count)
    print("Embedding dataset:", result.get("embedding_dataset"))
    summary_rows = result.get("similarity_summary") or []
    if summary_rows:
        print("Cosine similarity summary (mean/min/max/count):")
        for row in summary_rows:
            mean = float(row.get('mean_cosine', row.get('mean', 0.0) or 0.0))
            min_val = float(row.get('min_cosine', row.get('min', 0.0) or 0.0))
            max_val = float(row.get('max_cosine', row.get('max', 0.0) or 0.0))
            count = int(row.get('aligned_pairs', row.get('count', 0) or 0))
            print(
                f"  {row.get('target_structure')}: mean={mean:.3f} "
                f"min={min_val:.3f} max={max_val:.3f} count={count}"
            )
    rmsd_map = result.get("rmsd") or {}
    if rmsd_map:
        print("Alignment RMSD (Å):")
        for structure_id, rmsd in rmsd_map.items():
            print(f"  {structure_id}: {rmsd:.3f}")
    print("Property table:", result.get("property_table"))


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
