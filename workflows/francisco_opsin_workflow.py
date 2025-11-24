#!/usr/bin/env python3
"""Opsin binding-site workflow that addresses Francisco's questions with real data."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from statistics import quantiles
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
PROTOS_SRC = REPO_ROOT / "protos" / "src"
if PROTOS_SRC.exists() and str(PROTOS_SRC) not in sys.path:
    sys.path.insert(0, str(PROTOS_SRC))

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server

try:  # Optional direct processor access for B-factor analysis
    from protos.processing.structure import StructureProcessor
except Exception:  # pragma: no cover - optional dependency
    StructureProcessor = None  # type: ignore

OPSIN_DATASET = "rhodopsin_states"
OPSIN_REFERENCE_TABLE = "gpcrdb_ref"
OPSIN_PROTEIN_FAMILY = "gpcr_a"
OPSIN_LIGAND = "RET"
BOUNDARY_CHAIN_DATASET = "opsin_chain_dataset"
BOUNDARY_CHAIN_FILTERED = "opsin_chain_filtered"
BOUNDARY_GRN_TABLE = "opsin_chain_grn"

HYDROPHOBIC_RESIDUES = {"ALA", "VAL", "LEU", "ILE", "MET", "PHE", "TRP", "PRO"}
AROMATIC_RESIDUES = {"PHE", "TYR", "TRP"}
CHARGED_RESIDUES = {"ARG", "LYS", "ASP", "GLU", "HIS"}
POLAR_RESIDUES = {"SER", "THR", "CYS", "ASN", "GLN", "TYR"}


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
        payload = meta_converted.get("result", meta_converted)
        if not isinstance(payload, dict):
            payload = {"result": payload}
    else:
        payload = {"result": meta_converted}

    if text_messages:
        payload = {**payload, "messages": text_messages}
    return payload


def _instantiate_structure_processor() -> Optional[StructureProcessor]:
    if StructureProcessor is None:
        return None
    try:
        return StructureProcessor()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Unable to instantiate StructureProcessor: {exc}", file=sys.stderr)
        return None


def _summarize_flexibility(
    struct_proc: Optional[StructureProcessor],
    structure_id: str,
    residues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if struct_proc is None or not residues:
        return {"available": False, "reason": "structure_processor_unavailable"}

    try:
        frame = struct_proc.load_entity(structure_id.lower())
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"load_failed:{exc}"}

    if frame is None:
        return {"available": False, "reason": "structure_missing"}

    reset = frame.reset_index()
    if "b_factor" not in reset.columns:
        return {"available": False, "reason": "b_factor_missing"}

    residue_stats: List[Dict[str, Any]] = []
    grn_counter: Counter[str] = Counter()

    for residue in residues:
        chain = residue.get("chain")
        seq_id = residue.get("res_id")
        if chain is None or seq_id is None:
            continue

        mask = (reset["auth_chain_id"] == chain) & (reset["auth_seq_id"] == seq_id)
        atoms = reset[mask]
        if atoms.empty:
            continue

        mean_b = float(atoms["b_factor"].mean())
        min_b = float(atoms["b_factor"].min())
        max_b = float(atoms["b_factor"].max())

        grn_labels: List[str] = []
        if "grn" in atoms.columns:
            grn_labels = [
                label
                for label in atoms["grn"].dropna().unique().tolist()
                if isinstance(label, str) and label.strip() and label != "-"
            ]
            for label in grn_labels:
                grn_counter[label] += 1

        residue_stats.append(
            {
                "residue": f"{residue.get('res_name', '')}{seq_id}",
                "chain": chain,
                "mean_b_factor": round(mean_b, 2),
                "min_b_factor": round(min_b, 2),
                "max_b_factor": round(max_b, 2),
                "atom_count": int(len(atoms)),
                "grn_labels": sorted(grn_labels),
            }
        )

    if not residue_stats:
        return {"available": False, "reason": "no_matching_residues"}

    overall_mean = round(sum(item["mean_b_factor"] for item in residue_stats) / len(residue_stats), 2)
    return {
        "available": True,
        "residue_stats": residue_stats,
        "average_b_factor": overall_mean,
        "grn_counts": dict(grn_counter),
    }


def _cluster_volumes(volumes: List[Dict[str, Any]]) -> Dict[str, Any]:
    usable = [entry for entry in volumes if isinstance(entry.get("volume"), (int, float))]
    if not usable:
        return {"clusters": {}, "thresholds": {}, "source": []}

    scalar_volumes = [float(entry["volume"]) for entry in usable]
    if len(scalar_volumes) >= 3:
        q1, q2 = quantiles(scalar_volumes, n=3)
    else:
        mean_val = sum(scalar_volumes) / len(scalar_volumes)
        q1 = q2 = mean_val

    clusters: Dict[str, str] = {}
    for entry in volumes:
        key = f"{entry.get('structure')}:{entry.get('chain')}"
        vol = entry.get("volume")
        if not isinstance(vol, (int, float)):
            clusters[key] = "missing"
            continue
        if vol <= q1:
            clusters[key] = "compact"
        elif vol <= q2:
            clusters[key] = "intermediate"
        else:
            clusters[key] = "expanded"

    return {
        "clusters": clusters,
        "thresholds": {"lower": round(q1, 2), "upper": round(q2, 2)},
        "source": volumes,
    }


def _collect_retinal_targets(
    struct_proc: Optional[StructureProcessor],
    structure_ids: List[str],
) -> List[Dict[str, Any]]:
    if struct_proc is None:
        return []

    targets: List[Dict[str, Any]] = []
    for struct_id in structure_ids:
        try:
            frame = struct_proc.load_entity(struct_id.lower())
        except Exception:  # noqa: BLE001
            frame = None
        if frame is None:
            continue
        reset = frame.reset_index()
        required_cols = {"group", "res_name3l", "auth_chain_id", "auth_seq_id"}
        if required_cols - set(reset.columns):
            continue
        ligand_atoms = reset[
            (reset["group"] == "HETATM") & (reset["res_name3l"] == OPSIN_LIGAND)
        ]
        if ligand_atoms.empty:
            continue
        chains = ligand_atoms["auth_chain_id"].dropna().unique().tolist()
        for chain_id in chains:
            chain_atoms = ligand_atoms[ligand_atoms["auth_chain_id"] == chain_id]
            if chain_atoms.empty:
                continue
            residue_ids = sorted(
                {
                    int(res)
                    for res in chain_atoms["auth_seq_id"].dropna().unique().tolist()
                    if isinstance(res, (int, float))
                }
            )
            targets.append(
                {
                    "structure": struct_id,
                    "chain": chain_id,
                    "res_ids": residue_ids,
                }
            )
    return targets


def _estimate_pocket_volume(atoms: Optional[np.ndarray]) -> Optional[float]:
    if atoms is None or atoms.size == 0:
        return None
    spans = atoms.max(axis=0) - atoms.min(axis=0)
    if np.any(spans <= 0):
        return None
    return float(np.prod(spans) * 0.5)


def _analyze_binding_site(frame, chain_id: Optional[str], cutoff: float = 6.0) -> Optional[Dict[str, Any]]:
    required_cols = {"group", "auth_chain_id", "auth_seq_id", "res_name3l", "x", "y", "z"}
    if required_cols - set(frame.columns):
        return None

    retinal_atoms = frame[(frame["group"] == "HETATM") & (frame["res_name3l"] == OPSIN_LIGAND)].copy()
    if chain_id:
        retinal_atoms = retinal_atoms[retinal_atoms["auth_chain_id"] == chain_id]
    if retinal_atoms.empty:
        return None

    protein_atoms = frame[frame["group"] == "ATOM"].copy()
    if protein_atoms.empty:
        return None

    ret_coords = retinal_atoms[["x", "y", "z"]].to_numpy(dtype=float)
    prot_coords = protein_atoms[["x", "y", "z"]].to_numpy(dtype=float)
    if not ret_coords.size or not prot_coords.size:
        return None

    diff = prot_coords[:, None, :] - ret_coords[None, :, :]
    distances = np.linalg.norm(diff, axis=2)
    min_dist = distances.min(axis=1)
    protein_atoms.loc[:, "min_distance"] = min_dist
    binding_atoms = protein_atoms[protein_atoms["min_distance"] <= cutoff].copy()
    if binding_atoms.empty:
        return None

    residue_records: List[Dict[str, Any]] = []
    grn_counts: Counter[str] = Counter()
    for (chain, seq_id, res_name), atoms in binding_atoms.groupby(
        ["auth_chain_id", "auth_seq_id", "res_name3l"]
    ):
        labels = []
        if "grn" in atoms.columns:
            labels = [
                label
                for label in atoms["grn"].dropna().unique().tolist()
                if isinstance(label, str) and label.strip() and label != "-"
            ]
            for label in labels:
                grn_counts[label] += 1
        residue_records.append(
            {
                "chain": chain,
                "res_name": res_name,
                "res_id": int(seq_id) if not pd.isna(seq_id) else None,
                "min_distance": round(float(atoms["min_distance"].min()), 2),
                "atom_count": int(len(atoms)),
                "grn_labels": sorted(labels),
            }
        )

    res_names = [res.get("res_name") for res in residue_records if res.get("res_name")]
    residue_composition = dict(Counter(res_names))
    pocket_properties = {
        "hydrophobic_residues": sum(name in HYDROPHOBIC_RESIDUES for name in res_names),
        "aromatic_residues": sum(name in AROMATIC_RESIDUES for name in res_names),
        "charged_residues": sum(name in CHARGED_RESIDUES for name in res_names),
        "polar_residues": sum(name in POLAR_RESIDUES for name in res_names),
    }

    key_residues = sorted(residue_records, key=lambda item: item.get("min_distance", 999))[:5]
    binding_volume = _estimate_pocket_volume(binding_atoms[["x", "y", "z"]].to_numpy(dtype=float))
    contact_summary = {
        "atom_contacts": int(len(binding_atoms)),
        "residue_contacts": int(len(residue_records)),
        "close_contacts": int((binding_atoms["min_distance"] <= 3.5).sum()),
        "vdw_contacts": int((binding_atoms["min_distance"] <= 4.5).sum()),
        "mean_distance": round(float(binding_atoms["min_distance"].mean()), 2),
        "min_distance": round(float(binding_atoms["min_distance"].min()), 2),
    }

    return {
        "binding_residues": residue_records,
        "residue_composition": residue_composition,
        "pocket_properties": pocket_properties,
        "key_residues": key_residues,
        "volume": binding_volume,
        "contact_summary": contact_summary,
        "grn_counts": dict(grn_counts),
    }


def _register_rhodopsin_dataset_locally(data_root: Path) -> Dict[str, Any]:
    """Fallback registration using local mmCIF assets bundled with the repo."""

    try:
        from protos.processing.structure import StructureProcessor  # type: ignore
        from protos.io.ingest.structure_loader import StructureLoader  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"StructureProcessor unavailable: {exc}") from exc

    pdb_ids = ["1U19", "1F88", "3PQR", "3PXO", "2I37", "6CMO", "4ZWJ"]
    processor = StructureProcessor()
    manager = processor.dataset_manager
    if manager.dataset_exists(OPSIN_DATASET):
        entities = manager.get_dataset_entities(OPSIN_DATASET)
        return {"dataset_name": OPSIN_DATASET, "mode": "existing", "entities": entities}

    loader = StructureLoader(processor=processor)
    source_root = REPO_ROOT / "protos" / "data" / "structure" / "mmcif"
    temp_dir = Path(processor.path_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    def _entity_exists(name: str) -> bool:
        try:
            return processor.entity_registry.find_entity(name, processor.processor_type) is not None
        except Exception:  # noqa: BLE001
            return False

    registered: List[str] = []
    for pdb_id in pdb_ids:
        if _entity_exists(pdb_id):
            registered.append(pdb_id)
            continue
        source_path = source_root / f"{pdb_id.lower()}.cif"
        if not source_path.exists():
            continue
        temp_target = temp_dir / source_path.name
        shutil.copyfile(source_path, temp_target)
        try:
            loader.download_and_register(
                str(temp_target),
                name=pdb_id,
                source="local",
                metadata={
                    "source": "repo_protos_data",
                    "resource": source_path.name,
                },
            )
            registered.append(pdb_id)
        finally:
            temp_target.unlink(missing_ok=True)

    available = [pdb for pdb in pdb_ids if _entity_exists(pdb)]
    if not available:
        raise RuntimeError("No rhodopsin structures could be registered from local assets")

    processor.create_dataset(
        OPSIN_DATASET,
        available,
        {
            "source": "manual_repo_registration",
            "description": "Rhodopsin state structures from local protos/data assets",
        },
    )
    return {"dataset_name": OPSIN_DATASET, "mode": "manual", "entities": available}


async def run_workflow() -> Dict[str, Any]:
    data_root = (REPO_ROOT / "data").resolve()
    server = create_server(
        "Francisco Opsin Workflow",
        config=ServerConfig(data_root=data_root),
    )

    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            return _normalize_response(response)

        workflow_log: Dict[str, Any] = {"data_root": str(data_root)}

        # Ensure reference data and dataset are ready
        await call(
            "config_initialize_data",
            reinstall_reference=False,
            refresh_registry=False,
        )

        try:
            dataset_resp = await call("register_rhodopsin_structure_dataset")
            dataset_name = dataset_resp.get("data", {}).get("dataset_name", OPSIN_DATASET)
        except ToolError as exc:
            fallback = _register_rhodopsin_dataset_locally(data_root)
            dataset_name = fallback.get("dataset_name", OPSIN_DATASET)
            dataset_resp = {
                "data": {"dataset_name": dataset_name},
                "messages": [
                    f"register_rhodopsin_structure_dataset tool failed ({exc}); used packaged helper instead"
                ],
                "fallback": fallback,
            }
        workflow_log["dataset"] = dataset_resp

        dataset_entities = await call(
            "dataset_entities",
            name=dataset_name,
            processor_type="structure",
        )
        structures = dataset_entities.get("data", {}).get("entities", [])
        workflow_log["structures"] = structures

        if not structures:
            raise RuntimeError("No rhodopsin structures are available for analysis")

        grn_result = await call(
            "structure_prepare_grn_annotations",
            structure_ids=structures,
            reference_table=OPSIN_REFERENCE_TABLE,
            protein_family=OPSIN_PROTEIN_FAMILY,
            alignment_threshold=0.6,
            chain_dataset_prefix=BOUNDARY_CHAIN_DATASET,
            filtered_sequence_dataset=BOUNDARY_CHAIN_FILTERED,
            grn_table_name=BOUNDARY_GRN_TABLE,
            column_name="grn",
            save_entities=True,
        )
        workflow_log["grn_annotation"] = grn_result

        struct_proc = _instantiate_structure_processor()

        analysis_targets = _collect_retinal_targets(struct_proc, structures)
        workflow_log["target_detection"] = {
            "method": "structure_scan",
            "count": len(analysis_targets),
        }

        if not analysis_targets:
            raise RuntimeError(
                "No RET ligands were detected in the registered rhodopsin structures"
            )

        pocket_records: List[Dict[str, Any]] = []
        volume_records: List[Dict[str, Any]] = []
        grn_counter: Counter[str] = Counter()

        for target in analysis_targets:
            struct_id = target["structure"]
            chain_id = target.get("chain")
            frame = None
            try:
                frame = struct_proc.load_entity(struct_id.lower()) if struct_proc else None
            except Exception:  # noqa: BLE001
                frame = None
            if frame is None:
                continue
            reset = frame.reset_index()
            site_summary = _analyze_binding_site(reset, chain_id, cutoff=6.0)
            if site_summary is None:
                continue

            binding_residues = site_summary.get("binding_residues", [])
            flex_summary = _summarize_flexibility(struct_proc, struct_id, binding_residues)
            if flex_summary.get("available"):
                for stat in flex_summary.get("residue_stats", []):
                    for label in stat.get("grn_labels", []):
                        grn_counter[label] += 1
            for label, count in site_summary.get("grn_counts", {}).items():
                grn_counter[label] += count

            volume_value = site_summary.get("volume")
            volume_records.append(
                {
                    "structure": struct_id,
                    "chain": chain_id,
                    "volume": volume_value,
                }
            )

            pocket_records.append(
                {
                    "structure": struct_id,
                    "chain": chain_id,
                    "pocket": {
                        "volume": site_summary.get("volume"),
                        "properties": site_summary.get("pocket_properties"),
                        "residue_composition": site_summary.get("residue_composition"),
                        "binding_residue_count": len(binding_residues),
                        "key_residues": site_summary.get("key_residues"),
                    },
                    "binding_site_residues": binding_residues,
                    "flexibility": flex_summary,
                    "interactions": {
                        "summary": site_summary.get("contact_summary"),
                    },
                }
            )

        cluster_summary = _cluster_volumes(volume_records)
        workflow_log["analysis_targets"] = analysis_targets

        return {
            "dataset": dataset_name,
            "structures": structures,
            "targets": analysis_targets,
            "pocket_records": pocket_records,
            "volume_clusters": cluster_summary,
            "grn_contact_counts": dict(grn_counter),
            "log": workflow_log,
        }


def main() -> None:
    result = asyncio.run(run_workflow())
    print("=== Opsin Binding Workflow Summary ===")
    print(json.dumps(
        {
            "dataset": result.get("dataset"),
            "structure_count": len(result.get("structures", [])),
            "target_count": len(result.get("targets", [])),
            "volume_clusters": result.get("volume_clusters", {}),
            "grn_contact_counts": result.get("grn_contact_counts", {}),
        },
        indent=2,
    ))
    print("\n--- Detailed Records ---")
    for record in result.get("pocket_records", []):
        header = f"{record['structure']} chain {record.get('chain') or '?'}"
        print(f"\n[{header}] Pocket / Flexibility Snapshot")
        print(json.dumps({k: v for k, v in record.items() if k != "structure" and k != "chain"}, indent=2))


if __name__ == "__main__":
    main()
