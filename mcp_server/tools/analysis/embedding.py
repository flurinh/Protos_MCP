"""Embedding tools leveraging EmbeddingProcessor."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # pragma: no cover - optional dependency
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:  # pragma: no cover - optional dependency
    import torch
except Exception:  # pragma: no cover
    torch = None

from protos.processing.embedding import EmbeddingProcessor

from ..base import BaseTool


def _tensor_to_array(
    value: Any,
    truncate_length: Optional[int] = None,
) -> Any:
    """Convert an embedding tensor/array to a serialisable Python structure."""

    data = value

    if torch is not None and isinstance(value, torch.Tensor):
        if truncate_length is not None and value.ndim >= 1:
            slices = [slice(0, truncate_length)] + [slice(None)] * (value.ndim - 1)
            data = value[tuple(slices)]
        data = data.detach().cpu().numpy()

    if np is not None and isinstance(data, np.ndarray):
        if truncate_length is not None and data.ndim >= 1:
            slices = [slice(0, truncate_length)] + [slice(None)] * (data.ndim - 1)
            data = data[tuple(slices)]
        return data.tolist()

    if truncate_length is not None and hasattr(data, "__getitem__"):
        try:
            data = data[:truncate_length]
        except Exception:  # pragma: no cover - best effort
            pass

    if hasattr(data, "tolist"):
        return data.tolist()

    return data


def _flatten_to_numpy(value: Any) -> Optional["np.ndarray"]:
    """Turn any embedding representation into a 1D numpy array."""

    if torch is not None and isinstance(value, torch.Tensor):
        return value.detach().cpu().numpy().reshape(-1)

    if np is not None and isinstance(value, np.ndarray):
        return value.reshape(-1)

    if np is not None and hasattr(value, "tolist"):
        return np.asarray(value).reshape(-1)

    if np is not None:
        try:
            return np.asarray(value).reshape(-1)
        except Exception:  # pragma: no cover - best effort
            return None

    # Fallback: no numpy available
    return None


class EmbeddingAnalysisTools(BaseTool):
    """Expose embedding workflows over registered sequence datasets."""

    def register(self, server):
        @server.tool()
        def embedding_list_models(ctx) -> Dict[str, Dict[str, object]]:
            """List available embedding models with dimensions/descriptions."""

            return self.format_success({
                "models": EmbeddingProcessor.available_models(),
            })

        @server.tool()
        def embedding_generate(
            ctx,
            model_name: str,
            dataset_name: Optional[str] = None,
            sequences: Optional[Dict[str, str]] = None,
            embedding_types: Optional[List[str]] = None,
            save_prefix: Optional[str] = None,
            register_entities: bool = True,
            device: Optional[str] = None,
        ) -> Dict:
            """Generate embeddings for a dataset or explicit sequence mapping.

            Args:
                model_name: Name of the embedding model to use.
                dataset_name: Name of sequence dataset to embed.
                sequences: Explicit mapping of sequence IDs to sequences.
                embedding_types: Types of embeddings to generate (e.g., ["mean", "cls"]).
                save_prefix: Prefix for saved embedding dataset names.
                register_entities: Whether to register embeddings as entities.
                device: Device to use ('cuda', 'cpu', or None for auto).
                    Use 'cpu' for large models that don't fit in GPU memory.
            """

            if not dataset_name and not sequences:
                return self.format_error(
                    "No sequences provided",
                    "Specify a sequence dataset or pass an explicit mapping.",
                )

            seq_processor = self.get_processor("sequence")

            sequence_map: Dict[str, str] = {}
            if dataset_name:
                try:
                    dataset_sequences = seq_processor.load_dataset(dataset_name)
                except Exception as exc:  # noqa: BLE001
                    return self.format_error(
                        f"Failed to load dataset '{dataset_name}': {exc}",
                        "Verify that the dataset exists in the sequence processor.",
                    )
                sequence_map.update(dataset_sequences)

            if sequences:
                sequence_map.update(sequences)

            if not sequence_map:
                return self.format_error(
                    "Sequence collection is empty",
                    "Provide at least one sequence to embed.",
                )

            try:
                emb_proc = EmbeddingProcessor(model_name=model_name, device=device)
            except Exception as exc:  # noqa: BLE001
                return self.format_error(
                    f"Failed to initialize embedding models '{model_name}': {exc}",
                    "Ensure optional dependencies (torch/transformers) are installed.",
                )

            if not getattr(emb_proc, "dependencies_available", True):
                emb_proc.clear_cache()
                return self.format_error(
                    "Embedding dependencies missing",
                    "Install torch and transformers, or choose a different models.",
                )

            types = embedding_types or ["mean"]
            results: Dict[str, str] = {}
            base_label = save_prefix or dataset_name or "embedding"

            for emb_type in types:
                dataset_tag = f"{base_label}__{model_name}__{emb_type}"
                try:
                    emb_proc.embed_sequences(
                        sequence_map,
                        embedding_type=emb_type,
                        save_dataset=dataset_tag,
                        register_entities=register_entities,
                    )
                    results[emb_type] = dataset_tag
                except Exception as exc:  # noqa: BLE001
                    results[emb_type] = f"error: {exc}"

            used_device = getattr(emb_proc, "device", device or "auto")
            emb_proc.clear_cache()

            return self.format_success(
                {
                    "models": model_name,
                    "embedding_types": results,
                    "sequence_count": len(sequence_map),
                    "device": used_device,
                }
            )

        @server.tool()
        def embedding_load_dataset(
            ctx,
            dataset_name: str,
            include_embeddings: bool = False,
            sequence_ids: Optional[List[str]] = None,
            limit: int = 10,
            truncate_length: Optional[int] = None,
        ) -> Dict:
            """Summarise an embedding dataset and optionally return selected embeddings."""

            if error := self.validate_required_params(
                {"dataset_name": dataset_name}, ["dataset_name"],
            ):
                return error

            processor = self.get_processor("embedding")

            manager = processor.dataset_manager
            if not manager.dataset_exists(dataset_name):
                return self.format_error(
                    f"Embedding dataset '{dataset_name}' not found",
                    "Generate embeddings first with embedding_generate",
                )

            dataset_info = manager.get_dataset_info(dataset_name) or {}
            entities = dataset_info.get("entities", [])

            summary: List[Dict[str, Any]] = []
            for entity in entities[:limit]:
                entry = {
                    "entity_name": entity.get("name"),
                    "metadata": entity.get("metadata", {}),
                }
                summary.append(entry)

            payload: Dict[str, Any] = {
                "dataset_name": dataset_name,
                "entity_count": len(entities),
                "metadata": dataset_info.get("metadata", {}),
                "entities": summary,
                "truncated": len(entities) > len(summary),
            }

            if include_embeddings:
                # In LLM-safe mode, don't return raw embedding vectors
                if self.llm_safe_mode:
                    payload["embeddings_note"] = (
                        "Raw embeddings not returned in LLM-safe mode. "
                        "Use embedding_cosine_similarity for similarity analysis."
                    )
                else:
                    try:
                        embeddings = processor.load_embeddings(dataset_name)
                    except Exception as exc:  # noqa: BLE001
                        return self.format_error(
                            f"Failed to load embeddings for '{dataset_name}': {exc}",
                            "Ensure torch is installed and the dataset is intact.",
                        )

                    if sequence_ids:
                        selected_ids: Iterable[str] = sequence_ids
                    else:
                        selected_ids = []
                        for entity in entities:
                            source = entity.get("metadata", {}).get("source_sequence")
                            candidate = source or entity.get("name")
                            if candidate:
                                selected_ids.append(candidate)
                            if len(selected_ids) >= limit:
                                break

                    embedding_payload: Dict[str, Any] = {}
                    for seq_id in selected_ids:
                        vector = embeddings.get(seq_id)
                        if vector is None:
                            continue
                        embedding_payload[seq_id] = _tensor_to_array(vector, truncate_length)

                    payload["embeddings"] = embedding_payload

            return self.format_success(payload)

        @server.tool()
        def embedding_cosine_similarity(
            ctx,
            dataset_name: str,
            reference_id: str,
            target_ids: Optional[List[str]] = None,
            save_to_table: Optional[str] = None,
        ) -> Dict:
            """Compute cosine similarities between embeddings in a dataset.

            Args:
                dataset_name: Embedding dataset to analyze.
                reference_id: Entity to compare against.
                target_ids: Specific entities to compare (default: all others).
                save_to_table: If provided, save similarity data to this property table.

            Returns:
                Similarity results (or save confirmation if save_to_table specified).
            """

            if np is None:
                return self.format_error(
                    "NumPy not available",
                    "Install numpy to enable embedding similarity comparisons.",
                )

            if error := self.validate_required_params(
                {"dataset_name": dataset_name, "reference_id": reference_id},
                ["dataset_name", "reference_id"],
            ):
                return error

            processor = self.get_processor("embedding")

            try:
                embeddings = processor.load_embeddings(dataset_name)
            except Exception as exc:  # noqa: BLE001
                return self.format_error(
                    f"Failed to load embeddings for '{dataset_name}': {exc}",
                    "Ensure torch is installed and the dataset is intact.",
                )

            if reference_id not in embeddings:
                return self.format_error(
                    f"Reference '{reference_id}' not present in embeddings",
                    "Provide a registered sequence/entity id stored in the dataset.",
                )

            reference_vec = _flatten_to_numpy(embeddings[reference_id])
            if reference_vec is None:
                return self.format_error(
                    "Unsupported embedding format",
                    "Install numpy/torch so embeddings can be processed.",
                )

            targets = target_ids or [key for key in embeddings.keys() if key != reference_id]

            results: List[Dict[str, Any]] = []
            missing: List[str] = []

            ref_norm = np.linalg.norm(reference_vec)
            if ref_norm == 0:
                return self.format_error(
                    "Reference embedding has zero norm",
                    "Cannot compute cosine similarity for zero vectors.",
                )

            for target_id in targets:
                vector = embeddings.get(target_id)
                if vector is None:
                    missing.append(target_id)
                    continue

                target_vec = _flatten_to_numpy(vector)
                if target_vec is None:
                    missing.append(target_id)
                    continue

                target_norm = np.linalg.norm(target_vec)
                if target_norm == 0:
                    cosine = 0.0
                else:
                    cosine = float(np.dot(reference_vec, target_vec) / (ref_norm * target_norm))

                results.append(
                    {
                        "target_id": target_id,
                        "cosine_similarity": cosine,
                    }
                )

            # Save to property table if requested
            if save_to_table:
                rows = []
                for res in results:
                    rows.append({
                        "scope": [{"format": "sequence", "name": reference_id}],
                        "reference_id": reference_id,
                        "target_id": res["target_id"],
                        "cosine_similarity": res["cosine_similarity"],
                        "dataset_name": dataset_name,
                    })
                if rows:
                    prop_proc = self.get_processor("property")
                    prop_proc.record_properties(save_to_table, rows, allow_create=True)
                return self.format_success({
                    "saved": True,
                    "table": save_to_table,
                    "rows": len(rows),
                    "reference_id": reference_id,
                    "missing_ids": missing,
                })

            # In LLM-safe mode, limit results to top 20
            if self.llm_safe_mode:
                # Sort by similarity and take top 20
                sorted_results = sorted(results, key=lambda x: x["cosine_similarity"], reverse=True)
                max_results = 20
                limited_results = sorted_results[:max_results]
                return self.format_success(
                    {
                        "dataset_name": dataset_name,
                        "reference_id": reference_id,
                        "total_comparisons": len(results),
                        "top_results": limited_results,
                        "results_note": f"Showing top {len(limited_results)} of {len(results)} results (LLM-safe mode)",
                        "missing_ids": missing[:10] if missing else [],
                    }
                )

            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "reference_id": reference_id,
                    "results": results,
                    "missing_ids": missing,
                }
            )
