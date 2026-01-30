#!/usr/bin/env python3
"""
LLPS Embedding Workflow - Register sequences and generate embeddings via MCP Tools

This workflow demonstrates:
1. Loading a FASTA file from the input folder
2. Registering sequences as a Protos sequence dataset
3. Generating per-residue and global embeddings using ankh_base model

Usage:
    python workflows/llps_embedding_workflow.py
    python workflows/llps_embedding_workflow.py --file data/input/llps.fasta
    python workflows/llps_embedding_workflow.py --model ankh_base
"""

from __future__ import annotations

import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server


def _convert_payload(value: Any) -> Any:
    """Extract text from MCP message objects."""
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
    """Normalize MCP tool response to a dictionary."""
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


async def run_workflow(
    fasta_path: Optional[str] = None,
    model_name: str = "ankh_base",
    dataset_name: str = "llps",
) -> Dict[str, Any]:
    """Run the LLPS embedding workflow."""

    # Resolve FASTA path - check multiple locations
    if fasta_path:
        fasta_file = Path(fasta_path).resolve()
    else:
        # Check common locations
        possible_paths = [
            REPO_ROOT / "data" / "input" / "llps.fasta",
            REPO_ROOT / "data" / "sequence" / "fasta" / "datasets" / "llps.fasta",
        ]
        fasta_file = None
        for p in possible_paths:
            if p.exists():
                fasta_file = p
                break
        if fasta_file is None:
            raise FileNotFoundError(
                f"FASTA file not found. Checked:\n" +
                "\n".join(f"  - {p}" for p in possible_paths)
            )

    print(f"Input file: {fasta_file}")

    # Initialize MCP server
    data_root_path = (REPO_ROOT / "data").resolve()
    print(f"Initializing Protos MCP server with data root: {data_root_path}")

    server = create_server(
        "Protos LLPS Embedding Workflow",
        config=ServerConfig(data_root=data_root_path),
    )

    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            return _normalize_response(response)

        # Step 1: Initialize data environment
        print("\n1. Initializing Protos data environment...")
        await call("config_initialize_data", reinstall_reference=False, refresh_registry=True)

        # Step 2: Load FASTA file and register as sequence dataset (no entity materialization)
        print(f"\n2. Registering FASTA as dataset: {fasta_file.name}...")
        download_result = await call(
            "sequence_download",
            identifier=str(fasta_file),
            name=dataset_name,
            materialize_entities=False,  # Don't create individual entity files
        )
        download_data = download_result.get("data", download_result)
        registered_name = download_data.get("registered", dataset_name)
        print(f"   Dataset registered: {registered_name}")

        # Step 3: Load the full dataset to get sequence count
        print(f"\n3. Loading dataset contents...")
        dataset_result = await call(
            "dataset_entities",
            name=registered_name,
            processor_type="sequence",
        )
        dataset_data = dataset_result.get("data", dataset_result)
        entities = dataset_data.get("entities", [])
        print(f"   Sequences in dataset: {len(entities)}")

        # Show sequence IDs
        if entities:
            print("   Sequence IDs:")
            for seq_id in entities[:10]:
                print(f"     - {seq_id}")
            if len(entities) > 10:
                print(f"     ... and {len(entities) - 10} more")

        # Step 4: List available embedding models
        print("\n4. Checking available embedding models...")
        models_result = await call("embedding_list_models")
        models_data = models_result.get("data", models_result)
        available_models = models_data.get("models", [])
        if isinstance(available_models, list):
            print(f"   Available models: {', '.join(available_models[:5])}")
            if model_name not in available_models:
                print(f"   WARNING: {model_name} not in available models list")
        else:
            print(f"   Available models: {available_models}")

        # Step 5: Generate both per-residue and global embeddings in one call (batched)
        print(f"\n5. Generating embeddings with {model_name} (batched)...")
        print(f"   Dataset: {registered_name}")
        print(f"   Types: per_residue, mean")
        print("   (Processing all sequences...)")

        embedding_result = await call(
            "embedding_generate",
            model_name=model_name,
            dataset_name=registered_name,
            embedding_types=["per_residue", "mean"],  # Both types in one call
            save_prefix=f"{dataset_name}_ankh",
            register_entities=False,  # Don't materialize individual embedding entities
        )
        embedding_data = embedding_result.get("data", embedding_result)

        # Debug: check for errors
        if "error" in embedding_result or "error" in embedding_data:
            print(f"   ERROR: {embedding_result.get('error', embedding_data.get('error', 'Unknown error'))}")
            print(f"   Suggestion: {embedding_result.get('suggestion', embedding_data.get('suggestion', ''))}")

        generated_embeddings = embedding_data.get("embedding_types", {})

        print(f"   Sequences embedded: {embedding_data.get('sequence_count', 0)}")
        print(f"   Device used: {embedding_data.get('device', 'N/A')}")
        print(f"   Per-residue dataset: {generated_embeddings.get('per_residue', 'N/A')}")
        print(f"   Global (mean) dataset: {generated_embeddings.get('mean', 'N/A')}")

        # Step 6: Summary of generated datasets
        print("\n6. Listing generated embedding datasets...")
        list_result = await call(
            "dataset_list",
            processor_type="embedding",
        )
        list_data = list_result.get("data", list_result)
        embedding_datasets = list_data.get("datasets", [])

        # Handle both dict and string formats
        llps_datasets = []
        for d in embedding_datasets:
            if isinstance(d, dict):
                name = d.get("name", "")
                if dataset_name in name:
                    llps_datasets.append(d)
            elif isinstance(d, str):
                if dataset_name in d:
                    llps_datasets.append({"name": d})

        print(f"   LLPS embedding datasets: {len(llps_datasets)}")
        for ds in llps_datasets:
            name = ds.get("name", ds) if isinstance(ds, dict) else ds
            count = ds.get("entity_count", "N/A") if isinstance(ds, dict) else "N/A"
            print(f"     - {name}: {count} entities")

        # Build result
        result = {
            "input_file": str(fasta_file),
            "dataset_name": registered_name,
            "model": model_name,
            "sequences": {
                "count": len(entities),
                "ids": entities,
            },
            "embeddings": {
                "per_residue": {
                    "dataset": generated_embeddings.get("per_residue"),
                    "status": "error" if "error" in str(generated_embeddings.get("per_residue", "")) else "success",
                },
                "global_mean": {
                    "dataset": generated_embeddings.get("mean"),
                    "status": "error" if "error" in str(generated_embeddings.get("mean", "")) else "success",
                },
            },
            "device": embedding_data.get("device"),
            "all_embedding_datasets": [d.get("name") for d in llps_datasets],
        }

        return result


def summarize(result: Dict[str, Any]) -> None:
    """Print a summary of the workflow results."""
    print("\n" + "=" * 60)
    print("LLPS EMBEDDING WORKFLOW SUMMARY")
    print("=" * 60)

    print(f"\nInput File: {result.get('input_file')}")
    print(f"Dataset Name: {result.get('dataset_name')}")
    print(f"Model: {result.get('model')}")
    print(f"Device: {result.get('device', 'N/A')}")

    sequences = result.get("sequences", {})
    print(f"\nSequences Registered: {sequences.get('count', 0)}")

    embeddings = result.get("embeddings", {})
    per_res = embeddings.get("per_residue", {})
    global_emb = embeddings.get("global_mean", {})

    print(f"\nEmbeddings Generated:")
    print(f"  Per-residue: {per_res.get('dataset', 'N/A')} [{per_res.get('status', 'unknown')}]")
    print(f"  Global mean: {global_emb.get('dataset', 'N/A')} [{global_emb.get('status', 'unknown')}]")

    all_datasets = result.get("all_embedding_datasets", [])
    if all_datasets:
        print(f"\nAll LLPS Embedding Datasets:")
        for ds in all_datasets:
            print(f"  - {ds}")

    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register LLPS sequences and generate embeddings"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Path to FASTA file (default: data/input/llps.fasta)"
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default="ankh_base",
        help="Embedding model to use (default: ankh_base)"
    )
    parser.add_argument(
        "--dataset", "-d",
        type=str,
        default="llps",
        help="Name for the sequence dataset (default: llps)"
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(run_workflow(args.file, args.model, args.dataset))
        summarize(result)
    except Exception as e:
        print(f"\nWorkflow failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
