#!/usr/bin/env python3
"""GRN workflow demo reconstructed with MCP tools only."""

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


GPCR_SEQUENCES = {
    "ADRB2_HUMAN": "MGQPGNGSAFLLAPNGSHAPDHDVTQERDEVWVVGMGIVMSLIVLAIVFGNVLVITAIAKFERLQTVTNYFITSLACADLVMGLAVVPFGAAHILMKMWTFGNFWCEFWTSIDVLCVTASIETLCVIAVDRYFAITSPFKYQSLLTKNKARVIILMVWIVSGLTSFLPIQMHWYRATHQEAINCYANETCCDFFTNQAYAIASSIVSFYVPLVIMVFVYSRVFQEAKRQLQKIDKSEGRFHVQNLSQVEQDGRTGHGLRRSSKFCLKEHKALKTLGIIMGTFTLCWLPFFIVNIVHVIQDNLIRKEVYILLNWIGYVNSGFNPLIYCRSPDFRIAFQELLCLRRSSLKAYGNGYSSNGNTGEQSGYHVEQEKENKLLCEDLPGTEDFVGHQGTVPSDNIDSQGRNCSTNDSLL",
    "AA2AR_HUMAN": "MPIMGSSVYITVELAIAVLAILGNVLVCWAVWLNSNLQNVTNYFVVSLAAADIAVGVLAIPFAITISTGFCAACHGCLFIACFVLVLTQSSIFSLLAIAIDRYIAIRIPLRYNGLVTGTRAKGIIAICWVLSFAIGLTPMLGWNNCGQPKEGKNHSQGCGEGQVACLFEDVVPMNYMVYFNFFACVLVPLLLMLGVYLRIFLAARRQLKQMESQPLPGERARSTLQKEVHAAKSLAIIVGLFALCWLPLHIINCFTFFCPDCSHAPLWLMYLAIVLSHTNSVVNPFIYAYRIREFRQTFRKIIRSHVLRQQEPFKAAGTSARVLAAHGSDGEQVSLRLNGHPPGVWANGSAPHPERRPNGYALGLVSGGSAQESQGNTGLPDVELLSHELKGVCPEPPGLDDPLAQDGAGVS",
    "OPRM_HUMAN": "MDSSAAPTNASNCTDALAYSSCSPAPSPGSWVNLSHLDGNLSDPCGPNRTDLGGRDSLCPPTGSPSMITAITIMALYSIVCVVGLFGNFLVMYVIVRYTKMKTATNIYIFNLALADALATSTLPFQSVNYLMGTWPFGTILCKIVISIDYYNMFTSIFTLCTMSVDRYIAVCHPVKALDFRTPRNAKIINVCNWILSSAIGLPVMFMATTKYRQGSIDCTLTFSHPTWYWENLLKICVFIFAFIMPVLIITVCYGLMILRLKSVRMLSGSKEKDRNLRRITRMVLVVVAVFIVCWTPIHIYVIIKALVTIPETTFQTVSWHFCIALGYTNSCLNPVLYAFLDENFKRCFRDFCFPLKMRMERQSTSRVRNTVQDPAYLRDIDGMNKPV",
}

REFERENCE_TABLE = "gpcrdb_ref"
PROTEIN_FAMILY = "gpcr_a"
TARGET_REFERENCE = "ADRB2_HUMAN"


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
        "Protos GRN Workflow via Tools",
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

        register_resp = await call(
            "sequence_register_records",
            records=[
                {"name": name, "sequence": seq}
                for name, seq in GPCR_SEQUENCES.items()
            ],
            dataset_name="gpcr_seqs",
            overwrite=True,
            materialize_entities=True,
            metadata={"source": "tools_grn_workflow"},
        )

        dataset_load = await call(
            "load_sequence_dataset",
            dataset_name="gpcr_seqs",
            include_sequences=True,
        )

        sequences = dataset_load.get("data", {}).get("sequences", {})
        if TARGET_REFERENCE not in sequences:
            raise RuntimeError(f"Reference sequence {TARGET_REFERENCE} not present")

        reference_sequence = sequences[TARGET_REFERENCE]

        classifications: Dict[str, Dict[str, Any]] = {}
        for seq_id, sequence in sequences.items():
            match_resp = await call(
                "sequence_find_best_match",
                query_entity=seq_id,
                reference_sequences={TARGET_REFERENCE: reference_sequence},
                use_mmseqs=True,
            )

            match_data = match_resp.get("data", match_resp)
            score = match_data.get("score")
            best_match = match_data.get("best_match")

            if score is None or score == float("-inf"):
                fallback = await call(
                    "sequence_find_best_match",
                    query_entity=seq_id,
                    reference_sequences={TARGET_REFERENCE: reference_sequence},
                    use_mmseqs=False,
                )
                match_data = fallback.get("data", fallback)
                score = match_data.get("score")
                best_match = match_data.get("best_match")

            if score is None:
                continue

            normalized = score / max(len(sequence), 1)
            classifications[seq_id] = {
                "reference": best_match or TARGET_REFERENCE,
                "raw_score": score,
                "normalized_score": normalized,
            }

        grn_annotation = await call(
            "sequence_annotate_with_grn",
            dataset_name="gpcr_seqs",
            reference_table=REFERENCE_TABLE,
            protein_family=PROTEIN_FAMILY,
            output_table="gpcr_grn_demo",
            allow_create=True,
        )

        grn_table_summary = await call(
            "load_grn_table",
            table_name="gpcr_grn_demo",
        )

        reference_info = await call(
            "load_grn_reference_table",
            reference_name=REFERENCE_TABLE,
        )

        entity_annotations = await call(
            "load_entity",
            name=TARGET_REFERENCE,
            format="grn",
            output_format="json",
        )

        return {
            "data_root": data_root,
            "sequence_register": register_resp,
            "sequence_dataset": dataset_load,
            "similarity_scores": classifications,
            "grn_annotation": grn_annotation,
            "grn_table": grn_table_summary,
            "reference_info": reference_info,
            "target_entity_annotations": entity_annotations,
        }


def main() -> None:
    result = asyncio.run(run_workflow())

    print("GRN Workflow via MCP Tools")
    print("=" * 31)

    for key, value in result.items():
        print(f"\n--- {key} ---")
        print(value)


if __name__ == "__main__":
    main()

