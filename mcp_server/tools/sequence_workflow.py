"""Lightweight sequence workflow helpers for MCP tests."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .base import BaseTool


class SequenceWorkflowTools(BaseTool):
    """Expose a minimal set of sequence utilities required by workflows."""

    @property
    def catalog_group(self) -> str:  # noqa: D401 - inherited docs adequate
        return "sequence.workflow"

    def register(self, server) -> None:  # noqa: D401 - FastMCP registration
        @server.tool()
        def sequence_save_sequences(
            ctx,
            sequences: Dict[str, str],
            output_file: Optional[str] = None,
            dataset_name: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None,
            materialize_entities: bool = False,
        ) -> Dict[str, Any]:
            """Persist multiple sequences via SequenceProcessor.save_sequences."""

            if error := self.validate_required_params({"sequences": sequences}, ["sequences"]):
                return error

            if not sequences:
                return self.format_error(
                    "No sequences provided",
                    "Pass a non-empty mapping of sequence_id -> sequence",
                )

            processor = self.get_processor("sequence")
            base_name = output_file or dataset_name or "saved_sequences"
            dataset_key = dataset_name or base_name

            path = processor.save_sequences(
                sequences,
                output_file=base_name,
                dataset_name=dataset_key,
                metadata=metadata,
                materialize_entities=materialize_entities,
            )

            manager = processor.dataset_manager
            dataset_info = manager.get_dataset_info(dataset_key)
            handle = self.record_session_artifact(
                tool_name="sequence_save_sequences",
                name=dataset_key,
                kind="dataset",
                processor_type="sequence",
                summary={
                    "dataset": dataset_key,
                    "entity_count": len(dataset_info.get("entities", []))
                    if isinstance(dataset_info.get("entities"), list)
                    else dataset_info.get("size"),
                },
                tags=["sequence", "dataset", "export"],
                scope="sequence.dataset",
            )

            payload = {
                "dataset_name": dataset_key,
                "output_file": str(path),
                "context_handle": handle,
            }
            payload.update(dataset_info)
            return self.format_success(payload, message="Sequences saved")

        self.register_tool_metadata(
            function=sequence_save_sequences,
            name="sequence_save_sequences",
            description="Persist multiple sequences and return the dataset handle.",
            parameters=[{"name": "sequences", "type": "dict[str,str]"}],
            returns={"fields": ["dataset_name", "context_handle"]},
            tags=["sequence", "export"],
        )

        @server.tool()
        def sequence_create_mutant_library(
            ctx,
            base_sequence_id: str,
            mutation_map: Dict[str, Iterable[str]],
            base_name: Optional[str] = None,
            include_wildtype: bool = True,
            limit: Optional[int] = None,
            zero_indexed: bool = False,
            register_mutations: bool = False,
            register: Optional[bool] = None,
            dataset_name: Optional[str] = None,
            materialize_entities: bool = False,
            metadata: Optional[Dict[str, Any]] = None,
            return_metadata: bool = False,
            context_label: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Generate a mutant library and optionally persist it."""

            if error := self.validate_required_params(
                {"base_sequence_id": base_sequence_id, "mutation_map": mutation_map},
                ["base_sequence_id", "mutation_map"],
            ):
                return error

            processor = self.get_processor("sequence")

            normalized_map: Dict[int, Iterable[str]] = {}
            try:
                for key, values in mutation_map.items():
                    normalized_map[int(key)] = values
            except ValueError as exc:
                return self.format_error(
                    f"Mutation map key is not an integer: {exc}",
                    "Ensure mutation_map keys are residue positions.",
                )

            register_flag = register if register is not None else register_mutations

            try:
                result = processor.create_mutant_library(
                    base_sequence_id=base_sequence_id,
                    mutation_map=normalized_map,
                    base_name=base_name,
                    include_wildtype=include_wildtype,
                    limit=limit,
                    zero_indexed=zero_indexed,
                    register=register_flag,
                    dataset_name=dataset_name,
                    materialize_entities=materialize_entities,
                    metadata=metadata,
                    return_metadata=return_metadata,
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            variants: Dict[str, str]
            dataset_path: Optional[str] = None
            metadata_records: Optional[List[Dict[str, Any]]] = None

            if return_metadata:
                if register_flag:
                    variants, metadata_df, dataset_path = result  # type: ignore[misc]
                else:
                    variants, metadata_df = result  # type: ignore[misc]
                metadata_records = metadata_df.to_dict(orient="records")
            else:
                if register_flag:
                    variants, dataset_path = result  # type: ignore[misc]
                else:
                    variants = result  # type: ignore[assignment]

            payload: Dict[str, Any] = {
                "variant_count": len(variants),
                "variants": list(variants.keys()),
                "library": dict(variants),
            }
            if dataset_path:
                payload["dataset_path"] = dataset_path
            if metadata_records is not None:
                payload["metadata"] = metadata_records

            self.record_session_artifact(
                tool_name="sequence_create_mutant_library",
                name=dataset_name or (base_name or base_sequence_id) + "_library",
                kind="result",
                processor_type="sequence",
                summary={
                    "variant_count": len(variants),
                    "source": "sequence_create_mutant_library",
                },
                tags=["sequence", "mutants"],
                label=context_label,
                scope="sequence.result",
            )

            return self.format_success(payload, message="Mutant library generated")

        self.register_tool_metadata(
            function=sequence_create_mutant_library,
            name="sequence_create_mutant_library",
            description="Generate a combinatorial mutant library for a registered sequence.",
            parameters=[
                {"name": "base_sequence_id", "type": "str"},
                {"name": "mutation_map", "type": "dict[int,list[str]]"},
            ],
            tags=["sequence", "mutants"],
        )

        @server.tool()
        def sequence_compute_conservation(
            ctx,
            dataset_name: Optional[str] = None,
            sequences: Optional[Dict[str, str]] = None,
            ignore_gaps: bool = True,
            pseudocount: float = 0.0,
            normalize_entropy: bool = True,
            store_result: bool = False,
            result_name: Optional[str] = None,
            store_in_context: bool = False,
            context_label: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Compute per-position conservation across aligned sequences."""

            if not dataset_name and not sequences:
                return self.format_error(
                    "No sequences provided",
                    "Specify a dataset_name or pass an explicit sequence mapping.",
                )

            processor = self.get_processor("sequence")
            try:
                df = processor.compute_conservation(
                    sequences=sequences,
                    dataset_name=dataset_name,
                    ignore_gaps=ignore_gaps,
                    pseudocount=pseudocount,
                    normalize_entropy=normalize_entropy,
                    store_result=store_result,
                    result_name=result_name,
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            summary = {
                "positions": int(len(df)),
                "top_conserved": df.nsmallest(5, "entropy").to_dict(orient="records"),
                "most_variable": df.nlargest(5, "entropy").to_dict(orient="records"),
            }
            if not store_result:
                summary["full_table"] = df.to_dict(orient="records")

            if store_in_context:
                artifact_name = (
                    context_label
                    or result_name
                    or dataset_name
                    or "sequence_conservation"
                )
                context_handle = self.record_session_artifact(
                    tool_name="sequence_compute_conservation",
                    name=artifact_name,
                    kind="result",
                    processor_type="sequence",
                    summary={
                        "positions": summary.get("positions"),
                        "dataset": dataset_name,
                        "source": "sequence_compute_conservation",
                    },
                    tags=["sequence", "analysis", "conservation"],
                    label=context_label,
                    scope="sequence.result",
                )
                summary["context_handle"] = context_handle

            return self.format_success(summary)

        self.register_tool_metadata(
            function=sequence_compute_conservation,
            name="sequence_compute_conservation",
            description="Compute per-position conservation across aligned sequences.",
            tags=["sequence", "analysis"],
        )

        @server.tool()
        def sequence_compute_linkage(
            ctx,
            dataset_name: Optional[str] = None,
            sequences: Optional[Dict[str, str]] = None,
            ignore_gaps: bool = True,
            min_observations: int = 5,
            normalize: bool = True,
            top_k: Optional[int] = 20,
            store_result: bool = False,
            result_name: Optional[str] = None,
            store_in_context: bool = False,
            context_label: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Compute residue linkage using mutual information."""

            if not dataset_name and not sequences:
                return self.format_error(
                    "No sequences provided",
                    "Specify a dataset_name or pass an explicit sequence mapping.",
                )

            processor = self.get_processor("sequence")
            try:
                df = processor.compute_linkage(
                    sequences=sequences,
                    dataset_name=dataset_name,
                    ignore_gaps=ignore_gaps,
                    min_observations=min_observations,
                    normalize=normalize,
                    top_k=top_k,
                    store_result=store_result,
                    result_name=result_name,
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            payload = {
                "pair_count": int(len(df)),
                "pairs": df.to_dict(orient="records"),
            }

            if store_in_context:
                artifact_name = (
                    context_label
                    or result_name
                    or dataset_name
                    or "sequence_linkage"
                )
                context_handle = self.record_session_artifact(
                    tool_name="sequence_compute_linkage",
                    name=artifact_name,
                    kind="result",
                    processor_type="sequence",
                    summary={
                        "pair_count": payload["pair_count"],
                        "dataset": dataset_name,
                        "source": "sequence_compute_linkage",
                    },
                    tags=["sequence", "analysis", "linkage"],
                    label=context_label,
                    scope="sequence.result",
                )
                payload["context_handle"] = context_handle

            return self.format_success(payload)

        self.register_tool_metadata(
            function=sequence_compute_linkage,
            name="sequence_compute_linkage",
            description="Compute residue linkage (mutual information) across sequences.",
            tags=["sequence", "analysis"],
        )


__all__ = ["SequenceWorkflowTools"]
