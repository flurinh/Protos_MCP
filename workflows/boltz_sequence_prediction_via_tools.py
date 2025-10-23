#!/usr/bin/env python3
"""Prepare Boltz structure prediction jobs using MCP tools only."""

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


SEQUENCE_DATASET = "boltz_gpcr_sequences"
BOLTZ_MODEL = "boltz2"

TEST_SEQUENCES = {
    "ADRB2_HUMAN": "MGQPGNGSAFLLAPNGSHAPDHDVTQERDEVWVVGMGIVMSLIVLAIVFGNVLVITAIAKFERLQTVTNYFITSLACADLVMGLAVVPFGAAHILMKMWTFGNFWCEFWTSIDVLCVTASIETLCVIAVDRYFAITSPFKYQSLLTKNKARVIILMVWIVSGLTSFLPIQMHWYRATHQEAINCYANETCCDFFTNQAYAIASSIVSFYVPLVIMVFVYSRVFQEAKRQLQKIDKSEGRFHVQNLSQVEQDGRTGHGLRRSSKFCLKEHKALKTLGIIMGTFTLCWLPFFIVNIVHVIQDNLIRKEVYILLNWIGYVNSGFNPLIYCRSPDFRIAFQELLCLRRSSLKAYGNGYSSNGNTGEQSGYHVEQEKENKLLCEDLPGTEDFVGHQGTVPSDNIDSQGRNCSTNDSLL",
    "A2AR_HUMAN": "MPPDSNSTNGEASSSSQNGSAAGPEGQASVGGVLEEAAIAQMVAGPQGSIIISVLVAIIVFGNVLVIAVFTSRALKAPQNLFLVSLASADILVATLVIPFSLANELCGVFFIACLIMCVTSLVLTAVSIGSLLAIAVDRYLAIRIPLEYNITKRTRRVVALVVWVISAVISGLPVIIGWNCIVQVCGICVTEVIAGLCAIGSMNVLFIIKVSLLKVIQKLVKENARRQGNGVQQSKKTEFFTVILAIVLGVFVVCWFPFFFTYTLTAVGCSVPRTLFKFFFWFGYCNSAVNPVIYTIFNHDFRRAFKKILFHKQKRQKKKIDKEPTDFQVSPDDQPLGNSSSSHESKDSK",
    "DRD2_SHORT": "MDPLNLSWYDDDLERQNWSRPFNGSDGKADRPHYNYYATLLTLLIAVIVFGNVLVCMAVSREKALQTTTNYLIVSLAVADLLVATLVMPWVVYLEVVGEWKFSRIHCDIFVTLDVMMCTASILNLCAISIDRYTAVAMPMLYNTRYSSKRRVTVMISIVWVLSFTISCPLLFGLNNADQNECIIANPAFVVYSSIVSFYVPFIVTLLVYIKIYIVLRRRRKRVNTKRSSRAFRAHLRAPLKGNCTHPEDMKLCTVIMKSNGSFPVNRRRVEAARRAQELEMEMLSSTSPPERTRYSPIPPSHHQLTLPDPSHHGLHSTPDSPAKPEKNGHAKDHPKIAKIFEIQTMPNGKTRTSLKTMSRRKLSQQKEKKATQMLAIVLGVFIICWLPFFITHILNIHCDCNIPPVLYSAFTWLGYVNSAVNPIIYTTFNIEFRKAFLKILHC",
}

STANDARD_CONFIG = {
    "recycling": 3,
    "num_samples": 1,
    "crop_size": 384,
}

HIGH_CONF_CONFIG = {
    "recycling": 10,
    "num_samples": 5,
    "crop_size": 512,
    "output_name": "ADRB2_HUMAN_high_confidence",
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
        "Protos Boltz Sequence Prediction via Tools",
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

        register_sequences = await call(
            "sequence_register_records",
            records=[{"name": name, "sequence": seq} for name, seq in TEST_SEQUENCES.items()],
            dataset_name=SEQUENCE_DATASET,
            metadata={"source": "boltz_sequence_prediction_via_tools"},
            overwrite=True,
            materialize_entities=True,
        )

        dataset_entities = await call(
            "dataset_entities",
            name=SEQUENCE_DATASET,
            processor_type="sequence",
        )
        sequence_entities = dataset_entities.get("data", {}).get("entities", []) or []
        if not sequence_entities:
            raise RuntimeError("Sequence dataset is empty; cannot prepare Boltz jobs")

        jobs: List[Dict[str, Any]] = []
        for name in sequence_entities:
            config = dict(STANDARD_CONFIG)
            config.setdefault("output_name", f"{name}_predicted")
            job_resp = await call(
                "model_prepare_job",
                model_name=BOLTZ_MODEL,
                inputs={"sequence_dataset": SEQUENCE_DATASET, "entity": name},
                config=config,
            )
            jobs.append(job_resp.get("data", job_resp))

        high_conf_job = await call(
            "model_prepare_job",
            model_name=BOLTZ_MODEL,
            inputs={"sequence_dataset": SEQUENCE_DATASET, "entity": "ADRB2_HUMAN"},
            config=HIGH_CONF_CONFIG,
        )

        jobs.append(high_conf_job.get("data", high_conf_job))

        return {
            "data_root": data_root,
            "sequence_dataset": register_sequences,
            "sequence_entities": sequence_entities,
            "jobs": jobs,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Boltz Sequence Prediction via MCP Tools")
    print("=" * 46)

    sequence_entities = result.get("sequence_entities", [])
    print("Sequence dataset entities:", sequence_entities)

    jobs = result.get("jobs", [])
    for idx, job in enumerate(jobs, start=1):
        job_data = job.get("job", {})
        metadata = job.get("metadata", {})
        print(f"\nJob {idx}:")
        print("  Entity:", metadata.get("entity"))
        print("  Config ID:", metadata.get("config_id"))
        if job_data:
            print("  Command:", " ".join(job_data.get("command", [])))
            print("  Working dir:", job_data.get("working_dir"))
            artifacts = job_data.get("artifacts", [])
            if artifacts:
                print("  Artifacts:")
                for art in artifacts:
                    print(
                        "    -",
                        art.get("name"),
                        art.get("kind"),
                        art.get("path"),
                    )
        else:
            print("  No external job produced (model may run inline)")


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
