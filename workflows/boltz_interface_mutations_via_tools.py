#!/usr/bin/env python3
"""Prepare Boltz interface mutation jobs using MCP tools only."""

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


STRUCTURE_ID = "3sn6"
STRUCTURE_DATASET = "boltz_interface_structures"
CHAIN_DATASET_PREFIX = "boltz_interface_chain_dataset"
SEQUENCE_DATASET = "boltz_interface_sequences"
BOLTZ_MODEL = "boltz2"
MAX_JOBS = 10

INTERFACE_POSITIONS = {
    "R": [131, 135, 139],
    "A": [380, 384, 387],
}

MUTATION_CHOICES = ["W", "Y", "F", "R", "K"]

STANDARD_CONFIG = {
    "recycling": 3,
    "num_samples": 1,
    "crop_size": 384,
}


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
        "Protos Boltz Interface Mutations via Tools",
        config=ServerConfig(data_root=data_root_path),
    )
    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            return _normalize_response(response)

        data_root = await call("config_get_data_root")
        await call("config_initialize_data", reinstall_reference=True, refresh_registry=True)

        download = await call(
            "download_entities",
            identifiers=[STRUCTURE_ID],
            processor_type="structure",
            dataset_name=STRUCTURE_DATASET,
            create_dataset=True,
            overwrite=False,
        )

        chain_sequences_resp = await call(
            "structure_collect_chain_sequences",
            structure_ids=[STRUCTURE_ID],
            min_length=30,
        )
        chain_sequences = chain_sequences_resp.get("data", {}).get(STRUCTURE_ID, {})
        if not chain_sequences:
            raise RuntimeError("Unable to collect chain sequences for structure")

        sequence_records: List[Dict[str, Any]] = []
        for chain_id, payload in chain_sequences.items():
            sequence = payload.get("sequence")
            entity_name = payload.get("entity_name")
            if not sequence or not entity_name:
                continue
            sequence_records.append({"name": entity_name, "sequence": sequence})

        sequence_dataset = await call(
            "sequence_register_records",
            records=sequence_records,
            dataset_name=SEQUENCE_DATASET,
            metadata={"source": "boltz_interface_mutations_via_tools"},
            overwrite=True,
            materialize_entities=True,
        )

        targeted_sequences: Dict[str, Dict[str, Any]] = {}
        for chain_id, positions in INTERFACE_POSITIONS.items():
            payload = chain_sequences.get(chain_id)
            if not payload:
                continue
            entity_name = payload.get("entity_name")
            sequence = payload.get("sequence")
            targeted_sequences[chain_id] = {
                "entity": entity_name,
                "sequence": sequence,
                "positions": positions,
            }

        mutation_jobs: List[Dict[str, Any]] = []
        for chain_id, payload in targeted_sequences.items():
            entity = payload["entity"]
            sequence = payload["sequence"] or ""
            for position in payload["positions"]:
                if position > len(sequence):
                    continue
                original = sequence[position - 1]
                for mutant in MUTATION_CHOICES:
                    if mutant == original:
                        continue
                    mutation_label = f"{original}{position}{mutant}"
                    config = dict(STANDARD_CONFIG)
                    config.update(
                        {
                            "output_name": f"{entity}_{mutation_label}_interface",
                            "mutations": [
                                {
                                    "position": position,
                                    "original": original,
                                    "mutant": mutant,
                                    "name": mutation_label,
                                }
                            ],
                        }
                    )
                    job_resp = await call(
                        "model_prepare_job",
                        model_name=BOLTZ_MODEL,
                        inputs={"sequence_dataset": SEQUENCE_DATASET, "entity": entity},
                        config=config,
                    )
                    mutation_jobs.append(job_resp.get("data", job_resp))
                    if len(mutation_jobs) >= MAX_JOBS:
                        break
                if len(mutation_jobs) >= MAX_JOBS:
                    break
            if len(mutation_jobs) >= MAX_JOBS:
                break

        return {
            "data_root": data_root,
            "structure_downloads": download,
            "sequence_dataset": sequence_dataset,
            "targeted_sequences": targeted_sequences,
            "mutation_jobs": mutation_jobs,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Boltz Interface Mutations via MCP Tools")
    print("=" * 46)

    targeted = result.get("targeted_sequences", {})
    for chain_id, payload in targeted.items():
        print(f"Chain {chain_id}: entity={payload['entity']} positions={payload['positions']}")

    jobs = result.get("mutation_jobs", [])
    print(f"Prepared {len(jobs)} jobs")
    for idx, job in enumerate(jobs, start=1):
        job_data = job.get("job", {})
        metadata = job.get("metadata", {})
        print(f"\nJob {idx}:")
        print("  Entity:", metadata.get("entity"))
        print("  Mutations:", metadata.get("mutations"))
        if job_data:
            print("  Command:", " ".join(job_data.get("command", [])))
            print("  Working dir:", job_data.get("working_dir"))
        artifacts = job_data.get("artifacts", []) if job_data else []
        if artifacts:
            print("  Artifacts:")
            for art in artifacts:
                print(
                    "    -",
                    art.get("name"),
                    art.get("kind"),
                    art.get("path"),
                )


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
