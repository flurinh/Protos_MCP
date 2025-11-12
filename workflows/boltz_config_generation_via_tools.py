#!/usr/bin/env python3
"""Demonstrate generating Boltz mutation configs purely via MCP tools."""

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


SEQUENCE_DATASET = "boltz_config_demo"
BOLTZ_MODEL = "boltz2"

TEST_SEQUENCES = {
    "ADRB2_HUMAN": "MGQPGNGSAFLLAPNGSHAPDHDVTQERDEVWVVGMGIVMSLIVLAIVFGNVLVITAIAKFERLQTVTNYFITSLACADLVMGLAVVPFGAAHILMKMWTFGNFWCEFWTSIDVLCVTASIETLCVIAVDRYFAITSPFKYQSLLTKNKARVIILMVWIVSGLTSFLPIQMHWYRATHQEAINCYANETCCDFFTNQAYAIASSIVSFYVPLVIMVFVYSRVFQEAKRQLQKIDKSEGRFHVQNLSQVEQDGRTGHGLRRSSKFCLKEHKALKTLGIIMGTFTLCWLPFFIVNIVHVIQDNLIRKEVYILLNWIGYVNSGFNPLIYCRSPDFRIAFQELLCLRRSSLKAYGNGYSSNGNTGEQSGYHVEQEKENKLLCEDLPGTEDFVGHQGTVPSDNIDSQGRNCSTNDSLL",
    "A2AR_HUMAN": "MPPDSNSTNGEASSSSQNGSAAGPEGQASVGGVLEEAAIAQMVAGPQGSIIISVLVAIIVFGNVLVIAVFTSRALKAPQNLFLVSLASADILVATLVIPFSLANELCGVFFIACLIMCVTSLVLTAVSIGSLLAIAVDRYLAIRIPLEYNITKRTRRVVALVVWVISAVISGLPVIIGWNCIVQVCGICVTEVIAGLCAIGSMNVLFIIKVSLLKVIQKLVKENARRQGNGVQQSKKTEFFTVILAIVLGVFVVCWFPFFFTYTLTAVGCSVPRTLFKFFFWFGYCNSAVNPVIYTIFNHDFRRAFKKILFHKQKRQKKKIDKEPTDFQVSPDDQPLGNSSSSHESKDSK",
}

BASE_CONFIG = {
    "recycling": 4,
    "num_samples": 1,
    "crop_size": 384,
}

MUTATION_BATCH = [
    {
        "entity": "ADRB2_HUMAN",
        "mutations": [
            {"position": 91, "original": "A", "mutant": "V", "name": "A91V"},
            {"position": 101, "original": "F", "mutant": "Y", "name": "F101Y"},
        ],
        "config": {"output_name": "ADRB2_HUMAN_A91V_F101Y"},
    },
    {
        "entity": "A2AR_HUMAN",
        "mutations": [
            {"position": 50, "original": "I", "mutant": "V", "name": "I50V"},
            {"position": 120, "original": "T", "mutant": "A", "name": "T120A"},
        ],
        "config": {"output_name": "A2AR_HUMAN_I50V_T120A"},
    },
]


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
        "Protos Boltz Config Generation via Tools",
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
            "config_initialize_data", reinstall_reference=True, refresh_registry=True
        )

        register_sequences = await call(
            "sequence_register_records",
            records=[
                {"name": name, "sequence": seq} for name, seq in TEST_SEQUENCES.items()
            ],
            dataset_name=SEQUENCE_DATASET,
            metadata={"source": "boltz_config_generation_via_tools"},
            overwrite=True,
            materialize_entities=True,
        )

        mutation_jobs = await call(
            "model_prepare_boltz_mutations",
            dataset_name=SEQUENCE_DATASET,
            mutation_entries=MUTATION_BATCH,
            model_name=BOLTZ_MODEL,
            base_config=BASE_CONFIG,
        )

        payload = mutation_jobs.get("data", mutation_jobs)
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []

        return {
            "data_root": data_root,
            "sequence_dataset": register_sequences,
            "mutation_jobs": jobs,
            "invocations": (
                payload.get("invocations") if isinstance(payload, dict) else None
            ),
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Boltz Config Generation via MCP Tools")
    print("=" * 44)

    jobs = result.get("mutation_jobs", []) or []
    print(f"Prepared {len(jobs)} mutation jobs")
    for idx, job in enumerate(jobs, start=1):
        print(f"\nJob {idx}:")
        print("  Entity:", job.get("entity"))
        print("  Mutations:", job.get("mutations"))
        print("  Config ID:", job.get("config_id"))
        if job.get("config_path"):
            print("  Config YAML:", job.get("config_path"))
        if job.get("fasta_path"):
            print("  FASTA:", job.get("fasta_path"))
        if job.get("command"):
            print("  Command:", " ".join(job.get("command", [])))
        if job.get("working_dir"):
            print("  Working dir:", job.get("working_dir"))


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
