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
            "structure_download_batch",
            identifiers=STRUCTURE_IDS,
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
            raise RuntimeError("No chain sequences registered from structures")

        sequence_lengths: Dict[str, int] = {}
        alignment_metrics: Dict[str, Dict[str, Any]] = {}
        filtered_sequences: List[str] = []

        for seq_id in registered_sequences:
            seq_resp = await call("load_sequence", sequence_id=seq_id, include_sequence=True)
            seq_data = seq_resp.get("data", {}) if isinstance(seq_resp, dict) else {}
            sequence = seq_data.get("sequence")
            if sequence is None:
                full_seqs = seq_data.get("full_sequences")
                if isinstance(full_seqs, dict) and full_seqs:
                    sequence = next(iter(full_seqs.values()))
            if not sequence:
                continue
            sequence_lengths[seq_id] = len(sequence)

        if REFERENCE_SEQUENCE not in sequence_lengths:
            ref_resp = await call("load_sequence", sequence_id=REFERENCE_SEQUENCE, include_sequence=True)
            ref_data = ref_resp.get("data", {}) if isinstance(ref_resp, dict) else {}
            ref_sequence = ref_data.get("sequence")
            if ref_sequence is None:
                full = ref_data.get("full_sequences")
                if isinstance(full, dict) and full:
                    ref_sequence = next(iter(full.values()))
            if not ref_sequence:
                raise RuntimeError(f"Reference sequence {REFERENCE_SEQUENCE} not available in registry")
            sequence_lengths[REFERENCE_SEQUENCE] = len(ref_sequence)

        for seq_id in registered_sequences:
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
            if seq_id == REFERENCE_SEQUENCE or (normalized is not None and normalized >= ALIGNMENT_THRESHOLD):
                filtered_sequences.append(seq_id)

        filtered_sequences = sorted(set(filtered_sequences))
        excluded_sequences = sorted(set(registered_sequences) - set(filtered_sequences))
        if not filtered_sequences:
            raise RuntimeError("Alignment threshold removed all chain sequences")

        datasets_resp = await call("list_datasets", processor_type="sequence")
        known_datasets = datasets_resp.get("data", {}).get("datasets", []) or []
        metadata_payload = {
            "source": "structure_grn_annotation_via_tools",
            "reference_sequence": REFERENCE_SEQUENCE,
            "threshold": ALIGNMENT_THRESHOLD,
            "entity_count": len(filtered_sequences),
        }
        if FILTERED_DATASET in known_datasets:
            existing_resp = await call("dataset_entities", name=FILTERED_DATASET, processor_type="sequence")
            existing_entities = existing_resp.get("data", {}).get("entities", []) or []
            to_add = sorted(set(filtered_sequences) - set(existing_entities))
            to_remove = sorted(set(existing_entities) - set(filtered_sequences))
            await call(
                "update_dataset",
                name=FILTERED_DATASET,
                processor_type="sequence",
                add_entities=to_add or None,
                remove_entities=to_remove or None,
                metadata=metadata_payload,
            )
        else:
            await call(
                "create_dataset",
                name=FILTERED_DATASET,
                entities=filtered_sequences,
                processor_type="sequence",
                metadata=metadata_payload,
            )

        structure_chain_map: Dict[str, List[str]] = {}
        for seq_id in filtered_sequences:
            if "_chain_" not in seq_id:
                continue
            struct_id, chain_id = seq_id.split("_chain_", 1)
            structure_chain_map.setdefault(struct_id, []).append(chain_id)

        filtered_structure_entities: List[str] = []
        for struct_id, chain_ids in structure_chain_map.items():
            filter_resp = await call(
                "structure_filter_entities",
                structure_ids=[struct_id],
                filters=[
                    {
                        "column": "auth_chain_id",
                        "op": "in",
                        "values": chain_ids,
                    }
                ],
                save_as="{structure_id}_grn_filtered",
                drop_empty=False,
                return_preview=False,
            )
            filter_data = filter_resp.get("data", filter_resp)
            filter_results = filter_data.get("results", [])
            if not filter_results:
                continue
            saved_entity = filter_results[0].get("saved_entity") or struct_id
            filtered_structure_entities.append(saved_entity)

        if not filtered_structure_entities:
            raise RuntimeError("Filtering produced no structure entities; cannot continue")

        structure_dataset_payload: Dict[str, Any]
        datasets_resp = await call("list_datasets", processor_type="structure")
        known_structure_datasets = datasets_resp.get("data", {}).get("datasets", []) or []
        structure_metadata = {
            "source": "structure_grn_annotation_via_tools",
            "reference_sequence": REFERENCE_SEQUENCE,
            "threshold": ALIGNMENT_THRESHOLD,
            "entity_count": len(filtered_structure_entities),
        }
        if FILTERED_STRUCTURE_DATASET in known_structure_datasets:
            existing_structures_resp = await call(
                "dataset_entities",
                name=FILTERED_STRUCTURE_DATASET,
                processor_type="structure",
            )
            existing_structures = existing_structures_resp.get("data", {}).get("entities", []) or []
            to_add = sorted(set(filtered_structure_entities) - set(existing_structures))
            to_remove = sorted(set(existing_structures) - set(filtered_structure_entities))
            await call(
                "update_dataset",
                name=FILTERED_STRUCTURE_DATASET,
                processor_type="structure",
                add_entities=to_add or None,
                remove_entities=to_remove or None,
                metadata=structure_metadata,
            )
            structure_dataset_payload = await call(
                "dataset_info",
                name=FILTERED_STRUCTURE_DATASET,
                processor_type="structure",
            )
        else:
            structure_dataset_payload = await call(
                "create_dataset",
                name=FILTERED_STRUCTURE_DATASET,
                entities=filtered_structure_entities,
                processor_type="structure",
                metadata=structure_metadata,
            )

        grn_annotation = await call(
            "sequence_annotate_with_grn",
            reference_table=REFERENCE_TABLE,
            protein_family=PROTEIN_FAMILY,
            entity_names=filtered_sequences,
            output_table=f"{FILTERED_DATASET}_grn",
            allow_create=True,
            metadata={"source": "structure_grn_annotation_via_tools"},
        )
        grn_data = grn_annotation.get("data", {}) if isinstance(grn_annotation, dict) else {}
        grn_table_name = grn_data.get("output_table") or f"{FILTERED_DATASET}_grn"

        apply_grn = await call(
            "structure_apply_grn_annotations",
            grn_table=grn_table_name,
            structures=filtered_structure_entities,
            column_name="grn",
            save_entities=True,
        )

        dataset_summary = await call(
            "load_sequence_dataset",
            dataset_name=FILTERED_DATASET,
            include_sequences=False,
        )

        return {
            "data_root": data_root,
            "download": download,
            "structures": structure_entities,
            "registered_sequences": registered_sequences,
            "filtered_sequences": filtered_sequences,
            "excluded_sequences": excluded_sequences,
            "alignment_metrics": alignment_metrics,
            "filtered_structures": filtered_structure_entities,
            "grn_annotation": grn_annotation,
            "apply_grn": apply_grn,
            "sequence_dataset": dataset_summary,
            "grn_table": grn_table_name,
            "filtered_structure_dataset": structure_dataset_payload,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Structure GRN Annotation Workflow via MCP Tools")
    print("=" * 51)

    print("Structures:", result.get("structures"))
    print("Registered chains:", result.get("registered_sequences"))
    print("Filtered GPCR-like chains:", result.get("filtered_sequences"))
    excluded = result.get("excluded_sequences") or []
    if excluded:
        print("Excluded chains:", excluded)
    filtered_structs = result.get("filtered_structures") or []
    if filtered_structs:
        print("Filtered structure entities:", filtered_structs)
    metrics = result.get("alignment_metrics") or {}
    if metrics:
        print("Alignment metric (normalized score):")
        for seq_id, payload in metrics.items():
            norm = payload.get("normalized")
            if isinstance(norm, (int, float)):
                print(f"  {seq_id}: {norm:.3f}")
            else:
                print(f"  {seq_id}: n/a")
    grn = result.get("grn_annotation", {}).get("data", {})
    if grn:
        summary = grn.get("summary", {})
        print("GRN summary:", summary.get("global") or summary)
    apply_grn = result.get("apply_grn", {}).get("data", {})
    if apply_grn:
        print("Annotated residues per structure:", apply_grn.get("annotation_counts"))
        if apply_grn.get("skipped"):
            print("Skipped chains:", apply_grn.get("skipped"))
    dataset_info = result.get("sequence_dataset", {}).get("data", {})
    if dataset_info:
        print("Filtered sequence dataset:", dataset_info.get("dataset_name"), "entities=", dataset_info.get("entity_count"))
    structure_dataset_info = result.get("filtered_structure_dataset", {}).get("data", {})
    if structure_dataset_info:
        dataset_name = structure_dataset_info.get("name") or structure_dataset_info.get("dataset_name")
        entity_count = structure_dataset_info.get("entity_count")
        print("Filtered structure dataset:", dataset_name, "entities=", entity_count)
    print("GRN table:", result.get("grn_table"))


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
