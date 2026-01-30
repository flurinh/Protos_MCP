#!/usr/bin/env python3
"""Workflow to download melanopsin (Q9UHM6), register it, and generate ESM2 3B embeddings.

This workflow demonstrates:
1. Downloading a sequence from UniProt using sequence_download tool
2. Verifying registration with sequence_load_dataset
3. Generating embeddings using ESM2 3B (esm2_t36_3b) model
4. Loading and inspecting the generated embeddings
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server


def _convert_payload(value: Any) -> Any:
    """Convert MCP response payload to native Python types."""
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
    """Normalize MCP tool response into a clean dictionary."""
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
    """Execute the melanopsin embedding workflow."""

    # Configuration
    UNIPROT_ID = "Q9UHM6"  # Human melanopsin (OPN4)
    DATASET_NAME = "melanopsin"
    MODEL_NAME = "esm2_t36_3b"  # ESM2 3B model
    # Device: None = auto (GPU if available), 'cpu' = force CPU, 'cuda' = force GPU
    # Use 'cpu' for large models that don't fit in GPU memory
    DEVICE = "cpu"  # Force CPU for the 3B model on limited VRAM

    server = create_server(
        "Melanopsin Embedding Workflow",
        config=ServerConfig(data_root=Path("data").resolve())
    )

    results: Dict[str, Any] = {
        "config": {
            "uniprot_id": UNIPROT_ID,
            "dataset_name": DATASET_NAME,
            "model_name": MODEL_NAME,
            "device": DEVICE,
        }
    }

    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            return _normalize_response(response)

        # Step 0: Initialize Protos data root
        print("Step 0: Initializing Protos data root...")
        data_root_info = await call("config_get_data_root")
        results["data_root"] = data_root_info
        print(f"  Data root: {data_root_info.get('data', {}).get('data_root', 'N/A')}")

        # Step 1: List available embedding models
        print("\nStep 1: Listing available embedding models...")
        models_info = await call("embedding_list_models")
        results["available_models"] = models_info

        if models_info.get("success"):
            models = models_info.get("data", {}).get("models", {})
            print(f"  Available models: {list(models.keys())}")
            if MODEL_NAME in models:
                model_info = models[MODEL_NAME]
                print(f"  Selected model ({MODEL_NAME}):")
                print(f"    - Embedding dim: {model_info.get('embedding_dim')}")
                print(f"    - Description: {model_info.get('description')}")

        # Step 2: Download melanopsin from UniProt
        print(f"\nStep 2: Downloading melanopsin ({UNIPROT_ID}) from UniProt...")
        try:
            download_result = await call(
                "sequence_download",
                identifier=f"uniprot:{UNIPROT_ID}",
                name=DATASET_NAME,
                materialize_entities=True,
            )
            results["download"] = download_result

            if download_result.get("success"):
                registered_name = download_result.get("data", {}).get("registered")
                print(f"  Registered as: {registered_name}")
                entity_type = download_result.get("data", {}).get("entity_type")
                print(f"  Entity type: {entity_type}")
            else:
                print(f"  Error: {download_result.get('error', 'Unknown error')}")
                return results

        except Exception as exc:
            results["download"] = {"success": False, "error": str(exc)}
            print(f"  Download failed: {exc}")
            return results

        # Step 2.5: Create a dataset from the entity
        # sequence_download with a single UniProt ID creates an entity, not a dataset.
        # We need to create a dataset explicitly for embedding_generate to work.
        print(f"\nStep 2.5: Creating dataset from entity '{DATASET_NAME}'...")
        try:
            create_result = await call(
                "dataset_create",
                name=DATASET_NAME,
                entities=[DATASET_NAME],  # The entity name matches the dataset name
                processor_type="sequence",
                metadata={"source": "uniprot", "uniprot_id": UNIPROT_ID},
            )
            results["dataset_create"] = create_result

            if create_result.get("success"):
                print(f"  Dataset '{DATASET_NAME}' created successfully")
            else:
                print(f"  Error creating dataset: {create_result.get('error')}")
                # Try to continue anyway in case the dataset already exists
        except Exception as exc:
            results["dataset_create"] = {"success": False, "error": str(exc)}
            print(f"  Dataset creation failed: {exc}")
            # Don't return, try to continue

        # Step 3: Load and verify the sequence dataset
        print("\nStep 3: Verifying registered sequence...")
        try:
            dataset_info = await call(
                "sequence_load_dataset",
                dataset_name=DATASET_NAME,
                include_sequences=True,
                preview_length=80,
            )
            results["sequence_info"] = dataset_info

            if dataset_info.get("success"):
                data = dataset_info.get("data", {})
                entity_count = data.get("entity_count", 0)
                entities = data.get("entities", [])
                print(f"  Entity count: {entity_count}")

                for entity in entities[:3]:
                    seq_id = entity.get("sequence_id", "N/A")
                    length = entity.get("length", "N/A")
                    preview = entity.get("preview", "")[:60]
                    print(f"  - {seq_id}: {length} residues")
                    print(f"    Preview: {preview}...")
            else:
                print(f"  Error loading dataset: {dataset_info.get('error')}")

        except Exception as exc:
            results["sequence_info"] = {"success": False, "error": str(exc)}
            print(f"  Verification failed: {exc}")

        # Step 4: Generate embeddings using ESM2 3B
        print(f"\nStep 4: Generating embeddings with {MODEL_NAME}...")
        print("  (This may take a while for the 3B model - downloading ~11GB if not cached)")

        try:
            embedding_result = await call(
                "embedding_generate",
                model_name=MODEL_NAME,
                dataset_name=DATASET_NAME,
                embedding_types=["mean", "cls"],  # Generate both mean and CLS embeddings
                save_prefix=DATASET_NAME,
                register_entities=True,
                device=DEVICE,  # Use CPU for large models that don't fit in GPU memory
            )
            results["embedding_generation"] = embedding_result

            if embedding_result.get("success"):
                data = embedding_result.get("data", {})
                print(f"  Model: {data.get('models')}")
                print(f"  Sequences embedded: {data.get('sequence_count')}")
                print(f"  Embedding types generated:")
                for emb_type, dataset_tag in data.get("embedding_types", {}).items():
                    print(f"    - {emb_type}: {dataset_tag}")
            else:
                print(f"  Error: {embedding_result.get('error')}")
                suggestion = embedding_result.get("suggestion", "")
                if suggestion:
                    print(f"  Suggestion: {suggestion}")

        except Exception as exc:
            results["embedding_generation"] = {"success": False, "error": str(exc)}
            print(f"  Embedding generation failed: {exc}")
            return results

        # Step 5: Load and inspect the generated embeddings
        print("\nStep 5: Loading generated embeddings...")

        embedding_datasets = results.get("embedding_generation", {}).get("data", {}).get("embedding_types", {})

        for emb_type, dataset_tag in embedding_datasets.items():
            if dataset_tag.startswith("error:"):
                print(f"  Skipping {emb_type} (failed to generate)")
                continue

            try:
                load_result = await call(
                    "embedding_load_dataset",
                    dataset_name=dataset_tag,
                    include_embeddings=True,
                    limit=5,
                    truncate_length=10,  # Only show first 10 dimensions
                )
                results[f"embedding_{emb_type}"] = load_result

                if load_result.get("success"):
                    data = load_result.get("data", {})
                    print(f"\n  Dataset: {dataset_tag}")
                    print(f"    Entity count: {data.get('entity_count')}")

                    embeddings = data.get("embeddings", {})
                    for seq_id, emb_preview in embeddings.items():
                        if isinstance(emb_preview, list):
                            print(f"    {seq_id}: dim={len(emb_preview)} (truncated), first 5 values: {emb_preview[:5]}")
                else:
                    print(f"  Error loading {emb_type}: {load_result.get('error')}")

            except Exception as exc:
                results[f"embedding_{emb_type}"] = {"success": False, "error": str(exc)}
                print(f"  Failed to load {emb_type} embeddings: {exc}")

    return results


def summarize(result: Dict[str, Any]) -> None:
    """Print a summary of the workflow results."""
    print("\n" + "=" * 60)
    print("MELANOPSIN EMBEDDING WORKFLOW SUMMARY")
    print("=" * 60)

    config = result.get("config", {})
    print(f"\nConfiguration:")
    print(f"  UniProt ID: {config.get('uniprot_id')}")
    print(f"  Dataset name: {config.get('dataset_name')}")
    print(f"  Model: {config.get('model_name')}")
    print(f"  Device: {config.get('device', 'auto')}")

    download = result.get("download", {})
    print(f"\nDownload: {'SUCCESS' if download.get('success') else 'FAILED'}")
    if download.get("success"):
        print(f"  Registered as: {download.get('data', {}).get('registered')}")

    dataset_create = result.get("dataset_create", {})
    print(f"\nDataset Creation: {'SUCCESS' if dataset_create.get('success') else 'FAILED'}")

    embedding = result.get("embedding_generation", {})
    print(f"\nEmbedding Generation: {'SUCCESS' if embedding.get('success') else 'FAILED'}")
    if embedding.get("success"):
        data = embedding.get("data", {})
        print(f"  Sequences: {data.get('sequence_count')}")
        for emb_type, tag in data.get("embedding_types", {}).items():
            status = "OK" if not tag.startswith("error:") else "FAILED"
            print(f"  {emb_type}: {status} -> {tag}")

    print("\n" + "=" * 60)


def main() -> None:
    """Run the melanopsin embedding workflow."""
    print("Melanopsin Embedding Workflow")
    print("=" * 60)
    print("This workflow will:")
    print("  1. Download melanopsin (Q9UHM6) from UniProt")
    print("  2. Register the sequence in Protos")
    print("  3. Generate ESM2 3B embeddings (mean and CLS)")
    print("  4. Load and verify the embeddings")
    print("=" * 60 + "\n")

    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
