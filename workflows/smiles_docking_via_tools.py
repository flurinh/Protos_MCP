#!/usr/bin/env python3
"""Demonstrate SMILES→docking submissions using MCP tools only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server

SMILES_MAP = {
    "DOPAMINE": "CNCCC1=CC(=C(C=C1)O)O",
    "SEROTONIN": "C1=CC(=C(C=C1CCN)O)OCC2=NOC(=N2)N",
    "HISTAMINE": "NCCC1=CN=CN1",
}

RECEPTOR_ID = "5D5A"
LIGAND_DATASET = "smiles_docking_demo"


def _convert_payload(value: Any) -> Any:
    text_attr = getattr(value, "text", None)
    if isinstance(text_attr, str) and text_attr:
        try:
            return json.loads(text_attr)
        except Exception:
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

    text_messages: list[str] = []
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
        "Protos SMILES Docking via Tools",
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

        ligands = await call(
            "ligand_import_smiles_structures",
            smiles_map=SMILES_MAP,
            dataset_name=LIGAND_DATASET,
            generate_3d=True,
        )
        lig_data = ligands.get("data", {})
        ligand_entities = lig_data.get("structure_entities", []) or []
        if not ligand_entities:
            raise RuntimeError("Failed to register SMILES ligands")

        ligand_entity = ligand_entities[0]
        export_dir = REPO_ROOT / "data" / "docking_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        ligand_export = export_dir / f"{ligand_entity}.sdf"
        ligand_file_resp = await call(
            "structure_export_entity",
            structure_id=ligand_entity,
            output_path=str(ligand_export),
            format="sdf",
            overwrite=True,
        )

        receptor_resp = await call(
            "download_entity",
            entity_id=RECEPTOR_ID,
            processor_type="structure",
            allow_cached=True,
        )
        receptor_name = (
            receptor_resp.get("data", {})
            .get("context", {})
            .get("registered")
            or RECEPTOR_ID
        )
        receptor_path = export_dir / f"{receptor_name}.pdb"
        receptor_file_resp = await call(
            "structure_export_entity",
            structure_id=receptor_name,
            output_path=str(receptor_path),
            format="pdb",
            overwrite=True,
        )

        receptor_path_str = receptor_file_resp.get("data", {}).get("export_path")
        ligand_path_str = ligand_file_resp.get("data", {}).get("export_path")
        if not receptor_path_str or not ligand_path_str:
            raise RuntimeError("Failed to export receptor or ligand for docking")

        docking_job = await call(
            "model_prepare_job",
            model_name="unidock",
            inputs={
                "receptor_pdb": receptor_path_str,
                "ligand_file": ligand_path_str,
            },
            config={
                "search_mode": "fast",
                "num_modes": 5,
                "scoring": "vina",
            },
        )

        job_payload = docking_job.get("data", docking_job)
        job_dict = job_payload.get("job", job_payload)

        return {
            "data_root": data_root,
            "ligand_dataset": lig_data,
            "ligand_entity": ligand_entity,
            "receptor": receptor_name,
            "exports": {
                "ligand": ligand_file_resp,
                "receptor": receptor_file_resp,
            },
            "job": job_dict,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("SMILES Docking via MCP Tools")
    print("=" * 35)
    lig_data = result.get("ligand_dataset", {})
    if lig_data:
        print("Ligand dataset:", lig_data.get("dataset_name"))
        print("Structure entities:", lig_data.get("structure_entities"))
    print("Receptor entity:", result.get("receptor"))
    exports = result.get("exports", {})
    if exports:
        lig = exports.get("ligand", {}).get("data", {})
        rec = exports.get("receptor", {}).get("data", {})
        if lig:
            print("Ligand export:", lig.get("export_path"))
        if rec:
            print("Receptor export:", rec.get("export_path"))

    job_payload = result.get("job", {})
    if job_payload:
        cmd = job_payload.get("command", [])
        print("Job command:", " ".join(cmd))
        print("Working dir:", job_payload.get("working_dir"))
        artifacts = job_payload.get("artifacts", [])
        if artifacts:
            print("Artifacts:")
            for art in artifacts:
                print("  -", art.get("name"), art.get("kind"), art.get("path"))


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
