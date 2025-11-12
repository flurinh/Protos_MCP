"""Demonstration workflow exercising context/help tools with live sequence data."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server


def _read_fasta_sequence(path: Path) -> str:
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    return "".join(line for line in lines if not line.startswith(">"))


async def run_low_level_workflow() -> Dict[str, Any]:
    server = create_server("Protos Live Sequence Workflow", config=ServerConfig())
    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            try:
                messages, meta = await server.call_tool(tool, kwargs)
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "error": str(exc), "tool": tool}
            if isinstance(meta, dict) and "result" in meta:
                return meta["result"]
            return meta if isinstance(meta, dict) else {"raw": meta}

        await call("config_initialize_data", reinstall_reference=False, refresh_registry=False)
        await call("context_reset")

        guide_topics = await call("protos_guide")
        initial_status = await call("context_status")

        egfr_sequence_id = "EGFR_HUMAN_live"
        download = await call(
            "sequence_download",
            identifier="uniprot:P00533",
            name=egfr_sequence_id,
            materialize_entities=True,
        )

        sequences_payload: Dict[str, str] = {}

        if not download.get("success"):
            fallback_fasta = Path(__file__).resolve().parent / "test-data" / "egfr_human.fasta"
            fallback_fasta.parent.mkdir(parents=True, exist_ok=True)
            if not fallback_fasta.exists():
                fallback_fasta.write_text(
                    ">EGFR_HUMAN\n"
                    "MHLPSGTALGCLLCLAPLMLLLLGYEGVHNKCVNMEESMVPQKIPSIQLNPAPSRYLA\n"
                    "KWAQARQLVQNNTGAVVPRHLQLVEESGGAVVQLLRACQGPLYATTVQLNQLQDVRFQV\n"
                    "LMPQQLQLSRSEATGMVVHVIDSSGDVRLRHIFSEPTSSQLSSSNITITQLMNGSHCVL\n"
                    "ENLNPTTYQMDVNPGFQNHLFYVANYLEPRNQLYNPTTYQMDVNPGFQNHLFYNPTYTN\n"
                )
            with fallback_fasta.open() as handle:
                lines = [line.strip() for line in handle if line.strip()]
            sequence = "".join(line for line in lines if not line.startswith(">"))
            sequences_payload[egfr_sequence_id] = sequence
            dataset = await call(
                "sequence_register_records",
                records=[{"name": egfr_sequence_id, "sequence": sequence}],
                dataset_name="egfr_demo",
                overwrite=True,
            )
        else:
            export = await call(
                "sequence_export_entity",
                sequence_id=egfr_sequence_id,
                overwrite=True,
                format="fasta",
            )
            export_path = Path(export.get("data", {}).get("file_path", ""))
            if export_path and export_path.exists():
                sequences_payload[egfr_sequence_id] = _read_fasta_sequence(export_path)
            dataset = await call(
                "sequence_save_sequences",
                sequences=sequences_payload or {egfr_sequence_id: ""},
                dataset_name="egfr_demo",
                materialize_entities=False,
            )

        library = await call(
            "sequence_create_mutant_library",
            base_sequence_id=egfr_sequence_id,
            mutation_map={"5": ["S", "T"], "10": ["K"]},
            limit=4,
            include_wildtype=True,
            context_label="egfr_mutants",
        )
        conservation = await call(
            "sequence_compute_conservation",
            dataset_name="egfr_demo",
            sequences=sequences_payload if sequences_payload else None,
            store_in_context=True,
            context_label="egfr_conservation",
        )
        context_snapshot = await call("context_status")
        history = await call("context_history", limit=10)

        toolkit = await call("context_list", kind="dataset")

        return {
            "guide_topics": guide_topics,
            "initial_status": initial_status,
            "download": download,
            "saved_dataset": dataset,
            "mutant_library": library,
            "conservation": conservation,
            "context_snapshot": context_snapshot,
            "recent_history": history,
            "dataset_handles": toolkit,
        }


def summarize(result: Dict[str, Any]) -> None:
    print("Live Sequence Context Workflow")
    print("===============================\n")
    for key, value in result.items():
        print(f"--- {key} ---")
        print(value)
        print()


async def run_workflow() -> Dict[str, Any]:
    return await run_low_level_workflow()


if __name__ == "__main__":
    data = asyncio.run(run_low_level_workflow())
    summarize(data)
