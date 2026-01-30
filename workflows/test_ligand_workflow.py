#!/usr/bin/env python3
"""
Recreate the ligand workflow test using MCP tools only.

This workflow demonstrates memory-efficient patterns:
- Uses processor context for large data (structures)
- Returns summaries not full payloads
- References entities by ID not by content
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "protos" / "src"
for path in (REPO_ROOT, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import protos
from protos.analysis.structure_ligand_analysis import ligand_to_smiles

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server

# Use shared workflow utilities for memory-efficient operations
from workflow_utils import normalize_response as _normalize_response, extract_summary


TARGET_STRUCTURE = "5d5a"
STRUCTURE_DATASET = "ligand_workflow_structures"
CHAIN_DATASET_PREFIX = "ligand_workflow_chains"
FILTERED_DATASET = "ligand_workflow_filtered"
GRN_TABLE_NAME = "ligand_workflow_grn"
GRN_COLUMN = "grn"
REFERENCE_TABLE = "gpcrdb_ref"
PROTEIN_FAMILY = "gpcr_a"
ALIGNMENT_THRESHOLD = 0.8
PREFERRED_LIGAND = "CAU"
EXCLUDED_LIGANDS = {"HOH", "WAT", "SO4", "PO4", "GOL", "PEG"}
LIGAND_SMILES_OVERRIDES = {
    "CAU": "CC(C)NC1=NC(=O)N(C=C1)C2=CN=C(N)N=C2N",
    "CLR": "C[C@H](CCC[C@]1(C)CC=C2C[C@H]3CC[C@]4(C)C(=CC[C@H]4O)C3CC[C@]12C)C",
}
BINDING_CUTOFF = 4.0
PROPERTY_TABLE_NAME = f"{TARGET_STRUCTURE.lower()}_ligand_contacts"


def _choose_ligand(entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    best: Optional[Dict[str, Any]] = None
    best_atoms = -1
    for entry in entries:
        comp = (entry.get("res_name") or entry.get("ligand") or "").upper()
        if comp in EXCLUDED_LIGANDS:
            continue
        record = {
            "res_name": comp,
            "chain_id": entry.get("chain_id"),
            "res_id": entry.get("res_id"),
            "num_atoms": entry.get("num_atoms", 0),
        }
        if comp == PREFERRED_LIGAND:
            return record
        if record["num_atoms"] > best_atoms:
            best = record
            best_atoms = record["num_atoms"]
    if best is None:
        raise RuntimeError("No ligand satisfied the selection criteria")
    return best


def _parse_chain_id(entity_name: str) -> Optional[str]:
    token = entity_name.split("_chain_", 1)
    if len(token) == 2 and token[1]:
        return token[1]
    return None


def _attach_grn_labels(structure_df: pd.DataFrame, binding_df: pd.DataFrame) -> pd.Series:
    if "grn" not in structure_df.columns:
        return pd.Series([None] * len(binding_df))

    mapping: Dict[Tuple[str, int], Optional[str]] = {}
    for row in structure_df.itertuples():
        seq_id = getattr(row, "auth_seq_id", None)
        chain = getattr(row, "auth_chain_id", None)
        if chain is None or seq_id != seq_id:
            continue
        try:
            key = (str(chain), int(seq_id))
        except (TypeError, ValueError):
            continue
        value = getattr(row, "grn", None)
        if isinstance(value, str):
            label = value.strip()
        else:
            label = None
        if not label or label == "-":
            continue
        mapping[key] = label

    labels: List[Optional[str]] = []
    for record in binding_df.itertuples():
        key = (record.chain_id, int(record.res_id))
        labels.append(mapping.get(key))
    return pd.Series(labels)


async def run_workflow() -> Dict[str, Any]:
    data_root_path = (REPO_ROOT / "data").resolve()
    protos.set_data_path(str(data_root_path))

    server = create_server(
        "Protos Ligand Workflow via Tools",
        config=ServerConfig(data_root=data_root_path),
    )
    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, *, raise_on_error: bool = False, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            payload = _normalize_response(response)
            success = payload.get("success", True)
            if raise_on_error and not success:
                raise RuntimeError(f"{tool} failed: {payload.get('error', 'unknown error')}")
            return payload

        await call("config_get_data_root", raise_on_error=True)
        await call(
            "config_initialize_data",
            reinstall_reference=True,
            refresh_registry=True,
            raise_on_error=True,
        )

        await call(
            "download_entities",
            identifiers=[TARGET_STRUCTURE],
            processor_type="structure",
            dataset_name=STRUCTURE_DATASET,
            create_dataset=True,
            overwrite=False,
            raise_on_error=True,
        )

        grn_resp = await call(
            "structure_prepare_grn_annotations",
            structure_ids=[TARGET_STRUCTURE],
            reference_table=REFERENCE_TABLE,
            protein_family=PROTEIN_FAMILY,
            chain_dataset_prefix=CHAIN_DATASET_PREFIX,
            filtered_sequence_dataset=FILTERED_DATASET,
            grn_table_name=GRN_TABLE_NAME,
            column_name=GRN_COLUMN,
            alignment_threshold=ALIGNMENT_THRESHOLD,
            raise_on_error=True,
        )
        grn_data = grn_resp.get("data", {})
        sequence_dataset = grn_data.get("filtered_dataset", FILTERED_DATASET)
        filtered_sequences = grn_data.get("filtered_sequences", []) or []
        if not filtered_sequences:
            raise RuntimeError("GRN annotation did not return any filtered sequences")
        sequence_entity = filtered_sequences[0]
        grn_table = grn_data.get("grn_table", GRN_TABLE_NAME)
        chain_id = _parse_chain_id(sequence_entity) or "A"

        # Load structure directly from Protos (bypasses MCP payload limits for large DataFrames)
        # Note: protos.set_data_path() was called earlier, so StructureProcessor will use that path
        from protos.processing.structure import StructureProcessor
        structure_processor = StructureProcessor(name="workflow_structure_processor")
        structure_df = structure_processor.load_entity(TARGET_STRUCTURE)
        if structure_df is None or structure_df.empty:
            raise RuntimeError("Structure load returned no coordinate rows")
        structure_df = structure_df.reset_index()

        ligand_resp = await call(
            "extract_ligands_from_structure",
            pdb_id=TARGET_STRUCTURE,
            exclude_common=True,
            min_atoms=4,
            raise_on_error=True,
        )
        ligands = ligand_resp.get("data", {}).get("ligands", [])
        if not ligands:
            raise RuntimeError("Unable to locate ligands in the target structure")
        chosen_ligand = _choose_ligand(ligands)
        ligand_comp = chosen_ligand["res_name"]
        ligand_chain = chosen_ligand.get("chain_id") or chain_id
        ligand_res_id = int(chosen_ligand.get("res_id"))

        group_series = structure_df["group"].astype(str).str.upper()
        seq_ids = pd.to_numeric(structure_df["auth_seq_id"], errors="coerce")
        ligand_atoms = structure_df[
            (group_series == "HETATM")
            & (structure_df["auth_chain_id"] == ligand_chain)
            & (seq_ids == ligand_res_id)
        ].copy()
        if ligand_atoms.empty:
            raise RuntimeError(f"No atoms found for ligand {ligand_comp} {ligand_chain}{ligand_res_id}")

        interaction_resp = await call(
            "ligand_compute_interactions",
            structure_id=TARGET_STRUCTURE,
            ligand_names=[ligand_comp],
            distance_cutoff=BINDING_CUTOFF,
            raise_on_error=True,
        )
        interaction_data = interaction_resp.get("data", interaction_resp)
        raw_binding_rows = interaction_data.get("dataframe") or interaction_data.get("interactions") or []
        binding_df = pd.DataFrame(raw_binding_rows)
        if not binding_df.empty:
            ligand_series = binding_df.get("ligand")
            if ligand_series is not None:
                binding_df = binding_df[ligand_series.str.upper() == ligand_comp]
        property_result = None
        if not binding_df.empty:
            binding_df["grn"] = _attach_grn_labels(structure_df, binding_df)
            rows: List[Dict[str, Any]] = []
            for record in binding_df.to_dict("records"):
                rows.append(
                    {
                        "scope": [
                            {"format": "structure", "name": TARGET_STRUCTURE},
                            {"format": "sequence", "name": sequence_entity},
                        ],
                        "entity_name": f"{TARGET_STRUCTURE}_{record['chain_id']}_{record['res_id']}",
                        "chain_id": record["chain_id"],
                        "res_id": record["res_id"],
                        "res_name": record["res_name"],
                        "grn": record.get("grn"),
                        "min_distance": record["min_distance"],
                        "num_contacts": record["num_contacts"],
                    }
                )

            property_result = await call(
                "record_property_rows",
                dataset_name=PROPERTY_TABLE_NAME,
                rows=rows,
                allow_create=True,
                metadata={
                    "structure_id": TARGET_STRUCTURE,
                    "ligand": ligand_comp,
                    "sequence_entity": sequence_entity,
                    "workflow": "ligand_workflow",
                },
                raise_on_error=True,
            )

        ligand_smiles = None
        try:
            ligand_smiles = ligand_to_smiles(ligand_atoms, ligand_comp)
        except Exception:  # noqa: BLE001
            ligand_smiles = None
        if not ligand_smiles:
            ligand_smiles = LIGAND_SMILES_OVERRIDES.get(ligand_comp)
        if not ligand_smiles:
            raise RuntimeError(f"Unable to recover a SMILES string for {ligand_comp}")

        ligand_entity_name = f"{TARGET_STRUCTURE}_{ligand_comp}_{ligand_chain}"
        await call(
            "save_entity",
            name=ligand_entity_name,
            format="molecule",
            data={"smiles": ligand_smiles, "kind": "smiles_record"},
            metadata={"source_structure": TARGET_STRUCTURE},
            raise_on_error=True,
        )

        boltz_config = {
            "output_name": f"{TARGET_STRUCTURE}_{ligand_chain}_{ligand_comp}_dock",
            "ligand": {"id": ligand_comp, "smiles": ligand_smiles},
            "default_sequence_type": "protein",
        }
        job_resp = await call(
            "model_prepare_job",
            model_name="boltz2",
            inputs={"sequence_dataset": sequence_dataset, "entity": sequence_entity},
            config=boltz_config,
            raise_on_error=True,
        )
        job_payload = job_resp.get("data", {}).get("job", {})

        # Test Tanimoto similarity search
        similarity_resp = await call(
            "search_similar_ligands",
            query_smiles=ligand_smiles,
            similarity_threshold=0.5,
            max_results=10,
        )
        similarity_data = similarity_resp.get("data", {})

        return {
            "structure": TARGET_STRUCTURE,
            "sequence_dataset": sequence_dataset,
            "sequence_entity": sequence_entity,
            "grn_table": grn_table,
            "ligand": {
                "name": ligand_comp,
                "chain": ligand_chain,
                "res_id": ligand_res_id,
                "smiles": ligand_smiles,
                "entity": ligand_entity_name,
            },
            # Store only top contacts in workflow result; full data is in property table
            "binding_contacts_count": len(binding_df),
            "binding_contacts_preview": binding_df.head(10).to_dict("records"),
            "interaction_summary": interaction_data.get("summaries", {}),
            "property_table": PROPERTY_TABLE_NAME if property_result else None,
            "boltz_job": job_payload,
            "similarity_search": extract_summary(similarity_resp),
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Ligand Workflow via MCP Tools")
    print("=" * 35)
    print(f"Structure: {result['structure']}")
    print(f"Sequence dataset: {result['sequence_dataset']}")
    print(f"Sequence entity: {result['sequence_entity']}")
    ligand = result.get("ligand", {})
    if ligand:
        print(
            "Ligand: {name} chain {chain} res {res_id} (entity {entity})".format(
                name=ligand.get("name"),
                chain=ligand.get("chain"),
                res_id=ligand.get("res_id"),
                entity=ligand.get("entity"),
            )
        )
        print("SMILES:", ligand.get("smiles"))

    binding_count = result.get("binding_contacts_count", 0)
    binding_preview = result.get("binding_contacts_preview", [])
    print(f"Binding contacts: {binding_count} total")
    if binding_preview:
        df = pd.DataFrame(binding_preview)
        if not df.empty:
            cols = [c for c in ["chain_id", "res_id", "res_name", "min_distance", "grn"] if c in df.columns]
            print(f"Top {len(df)} contacts:")
            print(df[cols].to_string(index=False))

    prop_table = result.get("property_table")
    if prop_table:
        print("Property table:", prop_table)

    summaries = result.get("interaction_summary", {}) or {}
    if summaries:
        print("Interaction summaries:")
        for descriptor, summary in summaries.items():
            if not isinstance(summary, dict):
                continue
            print(f"  - {descriptor}:")
            print(f"      Binding residues: {summary.get('num_binding_residues', 0)}")
            print(f"      Hydrogen bonds: {summary.get('num_hydrogen_bonds', 0)}")
            print(f"      Hydrophobic contacts: {summary.get('num_hydrophobic', 0)}")
            print(f"      Pi-stacking: {summary.get('num_pi_stacking', 0)}")
            print(f"      Salt bridges: {summary.get('num_salt_bridges', 0)}")
            print(f"      Water bridges: {summary.get('num_water_bridges', 0)}")
            pi_types = summary.get('pi_stacking_types', [])
            if pi_types:
                print(f"      Pi-stacking types: {', '.join(pi_types)}")

    job = result.get("boltz_job", {})
    if job:
        command = " ".join(job.get("command", []))
        print("Boltz job command:", command)
        print("Working dir:", job.get("working_dir"))
        artifacts = job.get("artifacts", [])
        if artifacts:
            print("Job artifacts:")
            for art in artifacts:
                print("  -", art.get("name"), art.get("kind"), art.get("path"))

    sim_data = result.get("similarity_search", {})
    if sim_data:
        print("\nTanimoto Similarity Search:")
        print(f"  Results: {sim_data.get('num_results', sim_data.get('count', 0))}")
        if sim_data.get('success') is False:
            print(f"  Error: {sim_data.get('error', 'Unknown')}")


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
