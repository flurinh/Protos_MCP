#!/usr/bin/env python3
"""Recreate the water-network GRN workflow using only MCP tools."""

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


STRUCTURE_IDS = ["3sn6", "5d5a"]
DATASET_NAME = "water_network_structures"
CHAIN_PREFIX = "water_network_chain"
GRN_TABLE = "gpcr_structure_water_networks_grn"
PROPERTY_TABLE = "gpcr_structure_water_networks"
NETWORK_TABLE = "gpcr_structure_water_network_details"
REFERENCE_TABLE = "gpcrdb_ref"
PROTEIN_FAMILY = "gpcr_a"
REFERENCE_SEQUENCE = "5d5a_chain_A"
GPCR_THRESHOLD = 1


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
        "Protos Structure Water Network Workflow via Tools",
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
            dataset_name=DATASET_NAME,
            create_dataset=True,
            overwrite=True,
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

        candidate_ids = downloaded or dataset_list
        candidate_ids = list(dict.fromkeys(candidate_ids))

        available: List[str] = []
        for struct_id in candidate_ids:
            load_resp = await call("load_structure", structure_id=struct_id, include_atoms=False)
            if load_resp.get("success", True):
                available.append(struct_id)

        if not available:
            raise RuntimeError("No structures available for water-network analysis")

        register = await call(
            "structure_register_chain_sequences_from_dataset",
            dataset_name=DATASET_NAME,
            dataset_prefix=CHAIN_PREFIX,
            create_dataset=True,
            overwrite=True,
            one_letter=True,
            min_length=1,
        )

        register_data = register.get("data", {}) if isinstance(register, dict) else {}
        registered_entities = sorted(set(register_data.get("registered_entities", [])))
        if not registered_entities:
            raise RuntimeError("No chain sequences were registered; cannot proceed with GRN annotation")

        sequence_payloads: Dict[str, str] = {}
        sequence_lengths: Dict[str, int] = {}
        for seq_id in registered_entities:
            seq_resp = await call("load_sequence", sequence_id=seq_id, include_sequence=True)
            seq_data = seq_resp.get("data", {}) if isinstance(seq_resp, dict) else {}
            sequence = seq_data.get("sequence")
            if sequence is None and isinstance(seq_data.get("full_sequences"), dict):
                sequence = next(iter(seq_data["full_sequences"].values()), None)
            if sequence:
                sequence_payloads[seq_id] = sequence
                sequence_lengths[seq_id] = len(sequence)

        reference_sequence_id = REFERENCE_SEQUENCE if REFERENCE_SEQUENCE in registered_entities else registered_entities[0]
        if reference_sequence_id not in sequence_payloads:
            ref_resp = await call("load_sequence", sequence_id=reference_sequence_id, include_sequence=True)
            ref_data = ref_resp.get("data", {}) if isinstance(ref_resp, dict) else {}
            ref_sequence = ref_data.get("sequence")
            if ref_sequence is None and isinstance(ref_data.get("full_sequences"), dict):
                ref_sequence = next(iter(ref_data["full_sequences"].values()), None)
            if ref_sequence:
                sequence_payloads[reference_sequence_id] = ref_sequence
                sequence_lengths[reference_sequence_id] = len(ref_sequence)

        alignment_metrics: Dict[str, Dict[str, Any]] = {}
        filtered_sequences: List[str] = []
        for seq_id in registered_entities:
            align_resp = await call("align_sequences_by_id", entity1=seq_id, entity2=reference_sequence_id, alignment_method="blosum62")
            align_data = align_resp.get("data", align_resp) if isinstance(align_resp, dict) else {}
            score = align_data.get("score")
            length = sequence_lengths.get(seq_id, len(sequence_payloads.get(seq_id, "")))
            normalized = None
            if score is not None and length:
                normalized = float(score) / max(float(length), 1.0)
            alignment_metrics[seq_id] = {
                "score": score,
                "normalized": normalized,
                "length": length,
                "reference": reference_sequence_id,
            }
            if seq_id == reference_sequence_id or (normalized is not None and normalized >= GPCR_THRESHOLD):
                filtered_sequences.append(seq_id)

        filtered_sequences = sorted(set(filtered_sequences))
        non_gpcr_sequences = sorted(set(registered_entities) - set(filtered_sequences))
        if not filtered_sequences:
            raise RuntimeError("Sequence alignment failed to identify GPCR-like chains; adjust threshold or inputs.")

        filtered_dataset_name = f"{CHAIN_PREFIX}_gpcr_sequences"
        datasets_resp = await call("list_datasets", processor_type="sequence")
        datasets_list = datasets_resp.get("data", {}).get("datasets", []) or []
        metadata_payload = {
            "source": "structure_water_network_via_tools",
            "reference_sequence": reference_sequence_id,
            "threshold": GPCR_THRESHOLD,
            "entity_count": len(filtered_sequences),
        }
        if filtered_dataset_name in datasets_list:
            existing_resp = await call("dataset_entities", name=filtered_dataset_name, processor_type="sequence")
            existing_entities = existing_resp.get("data", {}).get("entities", []) or []
            to_add = sorted(set(filtered_sequences) - set(existing_entities))
            to_remove = sorted(set(existing_entities) - set(filtered_sequences))
            await call(
                "update_dataset",
                name=filtered_dataset_name,
                processor_type="sequence",
                add_entities=to_add or None,
                remove_entities=to_remove or None,
                metadata=metadata_payload,
            )
        else:
            await call("create_dataset", name=filtered_dataset_name, entities=filtered_sequences, processor_type="sequence", metadata=metadata_payload)

        grn_annotation = await call(
            "sequence_annotate_with_grn",
            reference_table=REFERENCE_TABLE,
            protein_family=PROTEIN_FAMILY,
            entity_names=filtered_sequences,
            output_table=GRN_TABLE,
            allow_create=True,
            metadata={"source": "structure_water_network_via_tools"},
        )

        grn_data = grn_annotation.get("data", {}) if isinstance(grn_annotation, dict) else {}
        grn_table_name = grn_data.get("output_table") or GRN_TABLE

        apply_grn = await call(
            "structure_apply_grn_annotations",
            grn_table=grn_table_name,
            structures=available,
            column_name="grn",
            save_entities=True,
        )

        water_networks = await call(
            "structure_compute_water_networks",
            structure_ids=available,
            residue_cutoff=3.4,
            water_water_cutoff=3.4,
            hydrogen_bond_cutoff=3.2,
            property_table_name=PROPERTY_TABLE,
            allow_create_property_table=True,
            include_networks=True,
            network_table_name=NETWORK_TABLE,
            allow_create_network_table=True,
            max_paths=5,
        )

        water_data = water_networks.get("data", {}) if isinstance(water_networks, dict) else {}
        property_rows = None
        if water_data.get("property_table"):
            property_rows = await call(
                "load_property_rows",
                dataset_name=PROPERTY_TABLE,
                limit=20,
            )

        return {
            "data_root": data_root,
            "download": download,
            "available_structures": available,
            "registered_sequences": registered_entities,
            "registered_metadata": register_data,
            "reference_sequence": reference_sequence_id,
            "alignment_metrics": alignment_metrics,
            "filtered_sequences": filtered_sequences,
            "non_gpcr_sequences": non_gpcr_sequences,
            "grn_annotation": grn_annotation,
            "apply_grn": apply_grn,
            "water_networks": water_networks,
            "property_rows": property_rows,
            "network_table_name": NETWORK_TABLE,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Structure Water Network Workflow via MCP Tools")
    print("=" * 48)

    print("Structures:", result.get("available_structures"))
    print("Registered chains:", result.get("registered_sequences"))
    print("Reference sequence:", result.get("reference_sequence"))
    if result.get("network_table_name"):
        print("Network table:", result.get("network_table_name"))
    filtered = result.get("filtered_sequences") or []
    non_gpcr = result.get("non_gpcr_sequences") or []
    print("Filtered GPCR chains:", filtered)
    if non_gpcr:
        print("Excluded chains:", non_gpcr)
    metrics = result.get("alignment_metrics") or {}
    if metrics:
        print("Alignment scores (normalized):")
        for seq_id, payload in metrics.items():
            norm = payload.get("normalized")
            if isinstance(norm, (int, float)):
                print(f"  {seq_id}: {norm:.3f}")
            else:
                print(f"  {seq_id}: n/a")
    grn = result.get("grn_annotation", {})
    grn_data = grn.get("data") if isinstance(grn, dict) else {}
    if grn_data:
        summary = grn_data.get("summary", {})
        global_stats = summary.get("global") or summary
        print("GRN summary:", global_stats)
    apply_grn = result.get("apply_grn", {})
    apply_data = apply_grn.get("data") if isinstance(apply_grn, dict) else {}
    if apply_data:
        print("Annotated residues per structure:", apply_data.get("annotation_counts"))
    water = result.get("water_networks", {})
    water_data = water.get("data") if isinstance(water, dict) else {}
    if water_data:
        summary = water_data.get("structures") or {}
        for struct_id, payload in summary.items():
            stats = (payload or {}).get("summary") or {}
            print(f"Water networks for {struct_id}: count={stats.get('network_count')} waters={stats.get('water_count')} max_path={stats.get('max_residue_path_length')}")
        property_tables = water_data.get("property_tables", {})
        if property_tables:
            print("Recorded property tables:")
            for label, info in property_tables.items():
                name = (info or {}).get("name")
                row_count = (info or {}).get("row_count")
                columns = (info or {}).get("columns") or []
                print(f"  {label}: {name} rows={row_count} cols={len(columns)}")
    property_rows = result.get("property_rows", {})
    if property_rows:
        data = property_rows.get("data") or {}
        row_count = data.get("row_count")
        if row_count is None:
            row_count = len(data.get("data", []))
        print("Property rows returned:", row_count)


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
