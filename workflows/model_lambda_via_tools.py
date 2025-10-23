#!/usr/bin/env python3
"""Recreate the Lambda property-prediction workflow using only MCP tools."""

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


SEQUENCE_DATASET = "lambda_gpcr_sequences"
PROPERTY_TABLE = "lambda_gpcr_predictions"
PROTEIN_FAMILY = "gpcr_a"

TEST_SEQUENCES = {
    "ADRB2_HUMAN": "MGQPGNGSAFLLAPNGSHAPDHDVTQERDEVWVVGMGIVMSLIVLAIVFGNVLVITAIAKFERLQTVTNYFITSLACADLVMGLAVVPFGAAHILMKMWTFGNFWCEFWTSIDVLCVTASIETLCVIAVDRYFAITSPFKYQSLLTKNKARVIILMVWIVSGLTSFLPIQMHWYRATHQEAINCYANETCCDFFTNQAYAIASSIVSFYVPLVIMVFVYSRVFQEAKRQLQKIDKSEGRFHVQNLSQVEQDGRTGHGLRRSSKFCLKEHKALKTLGIIMGTFTLCWLPFFIVNIVHVIQDNLIRKEVYILLNWIGYVNSGFNPLIYCRSPDFRIAFQELLCLRRSSLKAYGNGYSSNGNTGEQSGYHVEQEKENKLLCEDLPGTEDFVGHQGTVPSDNIDSQGRNCSTNDSLL",
    "A2AR_HUMAN": "MPPDSNSTNGEASSSSQNGSAAGPEGQASVGGVLEEAAIAQMVAGPQGSIIISVLVAIIVFGNVLVIAVFTSRALKAPQNLFLVSLASADILVATLVIPFSLANELCGVFFIACLIMCVTSLVLTAVSIGSLLAIAVDRYLAIRIPLEYNITKRTRRVVALVVWVISAVISGLPVIIGWNCIVQVCGICVTEVIAGLCAIGSMNVLFIIKVSLLKVIQKLVKENARRQGNGVQQSKKTEFFTVILAIVLGVFVVCWFPFFFTYTLTAVGCSVPRTLFKFFFWFGYCNSAVNPVIYTIFNHDFRRAFKKILFHKQKRQKKKIDKEPTDFQVSPDDQPLGNSSSSHESKDSK",
    "DRD2_SHORT": "MDPLNLSWYDDDLERQNWSRPFNGSDGKADRPHYNYYATLLTLLIAVIVFGNVLVCMAVSREKALQTTTNYLIVSLAVADLLVATLVMPWVVYLEVVGEWKFSRIHCDIFVTLDVMMCTASILNLCAISIDRYTAVAMPMLYNTRYSSKRRVTVMISIVWVLSFTISCPLLFGLNNADQNECIIANPAFVVYSSIVSFYVPFIVTLLVYIKIYIVLRRRRKRVNTKRSSRAFRAHLRAPLKGNCTHPEDMKLCTVIMKSNGSFPVNRRRVEAARRAQELEMEMLSSTSPPERTRYSPIPPSHHQLTLPDPSHHGLHSTPDSPAKPEKNGHAKDHPKIAKIFEIQTMPNGKTRTSLKTMSRRKLSQQKEKKATQMLAIVLGVFIICWLPFFITHILNIHCDCNIPPVLYSAFTWLGYVNSAVNPIIYTTFNIEFRKAFLKILHC",
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
        "Protos Lambda Workflow via Tools",
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

        save_sequences = await call(
            "sequence_register_records",
            records=[{"name": name, "sequence": seq} for name, seq in TEST_SEQUENCES.items()],
            dataset_name=SEQUENCE_DATASET,
            metadata={"source": "model_lambda_via_tools"},
            overwrite=True,
            materialize_entities=True,
        )

        dataset_entities_resp = await call(
            "dataset_entities",
            name=SEQUENCE_DATASET,
            processor_type="sequence",
        )
        sequence_entities = dataset_entities_resp.get("data", {}).get("entities", []) or []
        if not sequence_entities:
            raise RuntimeError("Sequence dataset has no entities; aborting Lambda workflow")

        resources = await call("model_lambda_prepare_resources")
        run_prediction = await call(
            "model_lambda_run",
            protein_family=PROTEIN_FAMILY,
            sequence_dataset=SEQUENCE_DATASET,
            sequences=[{"name": n, "sequence": s} for n, s in TEST_SEQUENCES.items()],
            dataset_metadata={"source": "model_lambda_via_tools"},
            overwrite_dataset=True,
            property_table=PROPERTY_TABLE,
            collect_attention=False,
            embedding_model="ankh_large",
            embedding_type="per_residue",
        )

        lambda_payload = run_prediction.get("data", run_prediction)
        property_table_name = (
            lambda_payload.get("lambda_run", {}).get("property_table")
            or PROPERTY_TABLE
        )
        property_rows = await call(
            "load_property_rows",
            dataset_name=property_table_name,
            limit=10,
        )

        return {
            "data_root": data_root,
            "sequence_dataset": save_sequences,
            "sequence_entities": sequence_entities,
            "lambda_resources": resources,
            "lambda_run": run_prediction,
            "property_preview": property_rows,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Lambda Workflow via MCP Tools")
    print("=" * 34)

    sequence_data = result.get("sequence_dataset", {}).get("data", {})
    print("Sequences registered:", sequence_data.get("success", True))
    sequence_entities = result.get("sequence_entities") or []
    print("Sequence entities:", sequence_entities)

    resources = result.get("lambda_resources", {}).get("data", {})
    if resources:
        print("Lambda resources prepared:", resources)

    run_data = result.get("lambda_run", {}).get("data", {})
    if run_data:
        print("Lambda dataset context:")
        print("  sequence_dataset:", run_data.get("sequence_dataset"))
        print("  sequence_count:", run_data.get("sequence_count"))
        preview = run_data.get("sequence_preview") or {}
        if preview:
            print("  sequence_preview:")
            for name, seq in preview.items():
                print(f"    {name}: {seq}")
        lambda_info = run_data.get("lambda_run", run_data)
        print("Lambda run metadata:")
        print("  run_id:", lambda_info.get("run_id"))
        print("  property_table:", lambda_info.get("property_table"))
        print("  row_count:", lambda_info.get("prediction_row_count"))
        if lambda_info.get("property_table_path"):
            print("  property_table_path:", lambda_info.get("property_table_path"))

    preview = result.get("property_preview", {}).get("data", {})
    if preview:
        rows = preview.get("data") or []
        print("Prediction preview (first rows):")
        for row in rows:
            print("  ", row)


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
