"""ModelManager tooling to expose Protos model orchestration via MCP."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import importlib

import protos.models
from protos.models.model_manager import ModelManager
from protos.models.model_specs import ArtifactSpec, ModelCard
from protos.processing.property import PropertyProcessor
from protos.processing.sequence import SequenceProcessor

from ..base import BaseTool
from ...core.exceptions import (
    DatasetNotFoundError,
    InvalidInputError,
)


class ModelManagerTools(BaseTool):
    """Expose ModelManager metadata and Lambda resource helpers to MCP."""

    _FAMILY_REFERENCE_MAP = {
        "gpcr_a": "vpod1_2",
        "gpcr": "vpod1_2",
        "classa_gpcr": "vpod1_2",
        "mo": "inoue",
        "microbial_opsins": "inoue",
        "microbial_opsin": "inoue",
        "microbial-opsins": "inoue",
        "microbial opsins": "inoue",
    }

    def __init__(self, context) -> None:
        super().__init__(context)
        self._manager: Optional[ModelManager] = None
        self._lambda_runtime = importlib.import_module("protos.models.lambda.runtime_utils")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_manager(self) -> ModelManager:
        data_root = Path(self.paths.data_root)
        manager = self._manager
        if manager is None or Path(manager.paths.data_root) != data_root:
            self._manager = ModelManager(data_root=data_root)
        return self._manager

    @staticmethod
    def _artifact_spec_dict(spec: ArtifactSpec) -> Dict[str, Any]:
        payload = {
            "name": spec.name,
            "kind": spec.kind,
            "provider": spec.provider,
            "optional": spec.optional,
        }
        if spec.format:
            payload["format"] = spec.format
        if spec.params:
            payload["params"] = spec.params
        return payload

    def _card_summary(self, card: ModelCard) -> Dict[str, Any]:
        execution = {
            "mode": card.execution.mode,
            "entrypoint": card.execution.entrypoint,
        }
        if getattr(card.execution, "expected_config", None):
            execution["expected_config"] = card.execution.expected_config
        if getattr(card.execution, "environment", None):
            execution["environment"] = card.execution.environment

        return {
            "name": card.name,
            "version": card.version,
            "description": card.description,
            "execution": execution,
            "input_spec": [self._artifact_spec_dict(spec) for spec in card.input_spec],
            "output_spec": [self._artifact_spec_dict(spec) for spec in card.output_spec],
            "metadata": card.metadata,
        }

    def _lambda_config_dir(self) -> Path:
        return Path(protos.models.__file__).resolve().parent / "lambda" / "lmda" / "configs"

    def _stage_lambda_resources(self) -> Dict[str, Path]:
        data_root = Path(self.paths.data_root)
        lambda_config_dir = self._lambda_config_dir()

        binding_source = lambda_config_dir / "binding_domain2.json"
        positional_source = lambda_config_dir / "final_mapping7.csv"

        if not binding_source.exists() or not positional_source.exists():
            raise FileNotFoundError(
                "Lambda configuration assets are missing; ensure protos.models.lambda is installed."
            )

        binding_target = data_root / "grn" / "configs" / "binding_domain2.json"
        positional_target = data_root / "grn" / "configs" / "final_mapping7.csv"

        copy_if_missing = self._lambda_runtime.copy_if_missing
        normalize_binding_config = self._lambda_runtime.normalize_binding_config

        copy_if_missing(binding_source, binding_target)
        normalize_binding_config(binding_target)
        copy_if_missing(positional_source, positional_target)

        return {
            "binding_config": binding_target,
            "positional_map": positional_target,
        }

    @staticmethod
    def _default_dataset_name(protein_family: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        family_slug = protein_family.replace("/", "_").replace(" ", "_") or "lambda"
        return f"{family_slug}_lambda_{timestamp}"

    @staticmethod
    def _preview_sequences(sequence_map: Dict[str, str], *, limit: int = 5) -> Dict[str, str]:
        preview: Dict[str, str] = {}
        for name in list(sequence_map.keys())[:limit]:
            seq = sequence_map[name]
            if not isinstance(seq, str):
                continue
            preview[name] = seq[:30] + ("…" if len(seq) > 30 else "")
        return preview

    def _normalize_sequences_input(self, sequences: Any) -> Dict[str, str]:
        if sequences is None:
            return {}

        normalized: Dict[str, str] = {}

        if isinstance(sequences, dict):
            items = sequences.items()
        elif isinstance(sequences, list):
            items: Iterable[tuple[str, str]] = []
            temp: List[tuple[str, str]] = []
            for entry in sequences:
                if not isinstance(entry, dict):
                    raise InvalidInputError(
                        "sequences",
                        "Expected list entries to be dictionaries with 'name' and 'sequence' keys",
                        "Provide sequences as [{'name': 'protein', 'sequence': '...'}]",
                    )
                name = entry.get("name") or entry.get("id") or entry.get("entity")
                seq = entry.get("sequence") or entry.get("seq")
                if not name:
                    raise InvalidInputError(
                        "sequences",
                        "A sequence entry is missing the 'name' field",
                        "Include a descriptive identifier for every sequence entry.",
                    )
                if not seq:
                    raise InvalidInputError(
                        "sequences",
                        f"Sequence value missing for entry '{name}'",
                        "Ensure each entry includes a 'sequence' string.",
                    )
                temp.append((str(name), str(seq)))
            items = temp
        else:
            raise InvalidInputError(
                "sequences",
                "Unsupported sequence payload type",
                "Provide sequences as a dict of {name: sequence} or a list of records.",
            )

        for name, seq in items:
            name_str = str(name).strip()
            if not name_str:
                raise InvalidInputError(
                    "sequences",
                    "Encountered an empty sequence name",
                    "Use human-readable identifiers for each sequence.",
                )
            seq_str = str(seq).strip()
            if not seq_str:
                raise InvalidInputError(
                    "sequences",
                    f"Sequence string for '{name_str}' is empty",
                    "Verify the sequence content before calling the tool.",
                )
            if name_str in normalized:
                raise InvalidInputError(
                    "sequences",
                    f"Duplicate sequence name '{name_str}'",
                    "Use unique names or combine identical sequences into one entry.",
                )
            normalized[name_str] = seq_str

        return normalized

    def _resolve_reference_table(
        self,
        protein_family: str,
        override: Optional[str] = None,
    ) -> tuple[str, str]:
        if override:
            return protein_family, override

        family_key = protein_family.strip().lower()
        if not family_key:
            raise InvalidInputError(
                "protein_family",
                "Protein family cannot be empty",
                "Provide a value such as 'gpcr_a' or 'mo'.",
            )

        reference = self._FAMILY_REFERENCE_MAP.get(family_key)
        if reference:
            return family_key, reference

        # Fall back to using the family key directly while signalling the limitation.
        return family_key, family_key

    def _ensure_sequence_dataset(
        self,
        sequence_dataset: Optional[str],
        sequences: Any,
        protein_family: str,
        *,
        dataset_metadata: Optional[Dict[str, Any]] = None,
        materialize_entities: bool = True,
        overwrite_dataset: bool = False,
    ) -> tuple[str, Dict[str, str], bool, Dict[str, Any]]:
        seq_proc: SequenceProcessor = self.get_processor("sequence")  # type: ignore[assignment]

        dataset_created = False
        normalized_sequences = self._normalize_sequences_input(sequences)

        if normalized_sequences:
            dataset_key = sequence_dataset or self._default_dataset_name(protein_family)
            if (
                not overwrite_dataset
                and seq_proc.dataset_manager.dataset_exists(dataset_key)
            ):
                raise InvalidInputError(
                    "sequence_dataset",
                    f"Dataset '{dataset_key}' already exists",
                    "Set overwrite_dataset=True to replace it or omit the name to auto-generate one.",
                )

            metadata = dict(dataset_metadata or {})
            metadata.setdefault("source", "model_lambda_run")
            metadata.setdefault("protein_family", protein_family)
            metadata.setdefault("sequence_count", len(normalized_sequences))

            seq_proc.save_sequences(
                normalized_sequences,
                output_file=dataset_key,
                dataset_name=dataset_key,
                metadata=metadata,
                materialize_entities=materialize_entities,
            )
            dataset_created = True
        else:
            if not sequence_dataset:
                raise InvalidInputError(
                    "sequence_dataset",
                    "Provide an existing dataset name when sequences are omitted",
                    "Either pass inline sequences or reference a registered dataset.",
                )
            dataset_key = sequence_dataset
            if not seq_proc.dataset_manager.dataset_exists(dataset_key):
                raise DatasetNotFoundError(dataset_key, "sequence")
            try:
                normalized_sequences = seq_proc.load_dataset(dataset_key)
            except Exception:
                normalized_sequences = {}

        dataset_info = seq_proc.get_dataset_info(dataset_key)

        return dataset_key, normalized_sequences, dataset_created, dataset_info

    def _prepare_grn_annotations(
        self,
        seq_proc: SequenceProcessor,
        dataset_name: str,
        *,
        reference_table: str,
        protein_family: str,
    ) -> tuple[str, int, Dict[str, Any]]:
        grn_table_name = f"{dataset_name}__grn"
        annotations, summary = seq_proc.annotate_with_grn(
            dataset_name=dataset_name,
            reference_table=reference_table,
            protein_family=protein_family,
            output_table=grn_table_name,
            allow_create=True,
            return_summary=True,
            metadata={
                "source": "model_lambda_run",
                "protein_family": protein_family,
                "reference_table": reference_table,
                "sequence_dataset": dataset_name,
            },
        )

        grn_summary = {
            "global": summary.get("global"),
            "per_sequence": summary.get("per_sequence"),
        }

        return grn_table_name, int(len(annotations)), grn_summary

    def _invoke_lambda_model(
        self,
        dataset_name: str,
        grn_table: str,
        protein_family: str,
        *,
        run_id: Optional[str],
        property_table: Optional[str],
        binding_config: Path,
        positional_map: Path,
        embedding_model: Optional[str],
        embedding_type: Optional[str],
        batch_size: Optional[int],
        collect_attention: bool,
        ingest_embeddings: bool,
        prefer_checkpoint: Optional[bool],
        debug: bool,
        invocation_metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        manager = self._get_manager()
        adapter = manager.adapters.get("lambda")
        if adapter is None:
            raise RuntimeError("Lambda adapter is not registered in ModelManager")

        config: Dict[str, Any] = {
            "run_id": run_id or getattr(adapter, "DEFAULT_RUN_ID", "007061"),
            "property_table": property_table,
            "binding_config": str(binding_config),
            "positional_map": str(positional_map),
            "batch_size": batch_size if batch_size is not None else 1,
            "collect_attention": bool(collect_attention),
            "ingest_embeddings": bool(ingest_embeddings),
            "debug": bool(debug),
        }

        if embedding_model:
            config["embedding_model"] = embedding_model
        if embedding_type:
            config["embedding_type"] = embedding_type
        if prefer_checkpoint is not None:
            config["prefer_checkpoint"] = bool(prefer_checkpoint)

        # Remove entries that remain None to let the adapter apply defaults.
        config = {key: value for key, value in config.items() if value is not None}

        metadata_payload = {"source": "mcp_tool", "tool": "model_lambda_run"}
        if invocation_metadata:
            metadata_payload.update(invocation_metadata)

        invocation = manager.prepare(
            "lambda",
            inputs={
                "sequence_dataset": dataset_name,
                "grn_table": grn_table,
                "protein_family": protein_family,
            },
            config=config,
            metadata=metadata_payload,
        )

        runtime = invocation.runtime
        if runtime is None:
            raise RuntimeError("Lambda invocation did not return runtime results")

        predictions = runtime.outputs.get("predictions") if runtime.outputs else None
        attention = runtime.outputs.get("attention") if runtime.outputs else None
        property_table_name = (
            runtime.metadata.get("property_table")
            if runtime.metadata
            else None
        )

        row_count = 0
        columns: List[str] = []
        preview_rows: List[Dict[str, Any]] = []
        if predictions is not None:
            if hasattr(predictions, "head") and hasattr(predictions, "to_dict"):
                row_count = len(predictions)
                columns = list(predictions.columns)
                preview_rows = predictions.head(10).to_dict(orient="records")
            elif isinstance(predictions, list):
                row_count = len(predictions)
                preview_rows = predictions[:10]

        attention_available = bool(attention)

        prop_proc = PropertyProcessor()
        property_path = None
        if property_table_name:
            property_path = (
                prop_proc.tables_dir / f"{property_table_name}.csv"
            )

        return {
            "run_id": runtime.metadata.get("run_id") if runtime.metadata else None,
            "protein_family": runtime.metadata.get("protein_family") if runtime.metadata else protein_family,
            "prediction_row_count": row_count,
            "prediction_columns": columns,
            "predictions_preview": preview_rows,
            "attention_available": attention_available,
            "property_table": property_table_name,
            "property_table_path": str(property_path) if property_path else None,
            "work_dir": runtime.metadata.get("work_dir") if runtime.metadata else None,
            "outputs_dir": runtime.metadata.get("outputs_dir") if runtime.metadata else None,
            "embedding_dataset": runtime.metadata.get("embedding_dataset") if runtime.metadata else None,
            "embedding_model": runtime.metadata.get("embedding_model") if runtime.metadata else embedding_model,
            "embedding_type": runtime.metadata.get("embedding_type") if runtime.metadata else embedding_type,
        }

    @staticmethod
    def _summarize_sequence_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        sequences = metadata.get("sequences", {}) or {}
        seq_ids = list(sequences.keys())
        preview_ids = seq_ids[:5]
        preview_sequences = {}
        for key in preview_ids:
            sequence = sequences.get(key, "")
            if isinstance(sequence, str) and len(sequence) > 30:
                preview_sequences[key] = f"{sequence[:30]}…"
            else:
                preview_sequences[key] = sequence
        return {
            "dataset": metadata.get("dataset"),
            "sequence_count": len(seq_ids),
            "preview_sequences": preview_sequences,
            "dataset_info": metadata.get("dataset_info"),
        }

    @staticmethod
    def _summarize_grn_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        table = metadata.get("table")
        if table is not None:
            row_count, col_count = table.shape
            columns = list(table.columns[:10])
        else:
            row_count = col_count = 0
            columns = []
        return {
            "table_name": metadata.get("table_name"),
            "row_count": row_count,
            "column_count": col_count,
            "columns_preview": columns,
        }

    @staticmethod
    def _summarize_embedding_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        embeddings = metadata.get("embeddings", {}) or {}
        ids = list(embeddings.keys())
        preview = {}
        for key in ids[:5]:
            tensor = embeddings[key]
            if hasattr(tensor, "shape"):
                preview[key] = list(tensor.shape)
            else:
                preview[key] = None
        return {
            "dataset": metadata.get("dataset"),
            "model_name": metadata.get("model_name"),
            "embedding_type": metadata.get("embedding_type"),
            "entity_count": len(ids),
            "shapes_preview": preview,
        }

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def register(self, server) -> None:  # noqa: D401 - FastMCP tool registration
        @server.tool()
        def list_models(ctx) -> Dict[str, Any]:
            """List registered model cards available through ModelManager."""

            try:
                manager = self._get_manager()
                cards = [self._card_summary(card) for card in manager.cards.values()]
                return self.format_success({
                    "count": len(cards),
                    "models": cards,
                })
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def describe_model(ctx, name: str) -> Dict[str, Any]:
            """Return full model card metadata for a specific model."""

            if not name:
                return self.format_error(
                    "Model name required",
                    "Provide a registered model name such as 'lambda' or 'boltz2'.",
                )

            try:
                manager = self._get_manager()
                card = manager.cards.get(name)
                if card is None:
                    return self.format_error(
                        f"Model '{name}' is not registered",
                        "Call list_models to inspect available model names.",
                    )

                payload = self._card_summary(card)
                payload["adapter_type"] = type(manager.adapters.get(name)).__name__
                return self.format_success(payload)
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def model_lambda_prepare_resources(ctx) -> Dict[str, Any]:
            """Copy and normalize Lambda model resources into the active data root."""

            try:
                staged = self._stage_lambda_resources()
                summary = {
                    "data_root": str(self.paths.data_root),
                    "binding_config": str(staged["binding_config"]),
                    "positional_map": str(staged["positional_map"]),
                    "binding_exists": staged["binding_config"].exists(),
                    "positional_exists": staged["positional_map"].exists(),
                }

                return self.format_success(summary, message="Lambda resources prepared")
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def model_lambda_run(
            ctx,
            protein_family: str,
            sequence_dataset: Optional[str] = None,
            sequences: Optional[Any] = None,
            reference_table: Optional[str] = None,
            dataset_metadata: Optional[Dict[str, Any]] = None,
            overwrite_dataset: bool = False,
            materialize_entities: bool = True,
            run_id: Optional[str] = None,
            property_table: Optional[str] = None,
            embedding_model: Optional[str] = None,
            embedding_type: Optional[str] = None,
            batch_size: Optional[int] = None,
            collect_attention: bool = False,
            ingest_embeddings: bool = False,
            prefer_checkpoint: Optional[bool] = None,
            debug: bool = False,
            invocation_metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Run the full Lambda workflow (dataset → GRN → prediction) in one call."""

            params = {"protein_family": protein_family}
            if error := self.validate_required_params(params, ["protein_family"]):
                return error

            if not sequence_dataset and sequences is None:
                return self.format_error(
                    "Sequences required",
                    "Provide either 'sequence_dataset' or inline 'sequences'.",
                )

            try:
                normalized_family, resolved_reference = self._resolve_reference_table(
                    protein_family,
                    override=reference_table,
                )

                seq_proc: SequenceProcessor = self.get_processor("sequence")  # type: ignore[assignment]
                dataset_name, sequence_map, dataset_created, dataset_info = (
                    self._ensure_sequence_dataset(
                        sequence_dataset,
                        sequences,
                        normalized_family,
                        dataset_metadata=dataset_metadata,
                        materialize_entities=materialize_entities,
                        overwrite_dataset=overwrite_dataset,
                    )
                )

                sequence_count = (
                    dataset_info.get("metadata", {}).get("sequence_count")
                    or dataset_info.get("entity_count")
                    or len(sequence_map)
                )

                grn_table_name, grn_row_count, grn_summary = self._prepare_grn_annotations(
                    seq_proc,
                    dataset_name,
                    reference_table=resolved_reference,
                    protein_family=normalized_family,
                )

                staged_resources = self._stage_lambda_resources()

                lambda_result = self._invoke_lambda_model(
                    dataset_name,
                    grn_table_name,
                    normalized_family,
                    run_id=run_id,
                    property_table=property_table,
                    binding_config=staged_resources["binding_config"],
                    positional_map=staged_resources["positional_map"],
                    embedding_model=embedding_model,
                    embedding_type=embedding_type,
                    batch_size=batch_size,
                    collect_attention=collect_attention,
                    ingest_embeddings=ingest_embeddings,
                    prefer_checkpoint=prefer_checkpoint,
                    debug=debug,
                    invocation_metadata=invocation_metadata,
                )

                sequence_preview = self._preview_sequences(sequence_map)

                response = {
                    "sequence_dataset": dataset_name,
                    "sequence_count": int(sequence_count) if sequence_count is not None else None,
                    "sequence_preview": sequence_preview,
                    "dataset_created": dataset_created,
                    "protein_family": normalized_family,
                    "reference_table": resolved_reference,
                    "grn_table": grn_table_name,
                    "grn_row_count": grn_row_count,
                    "grn_summary": grn_summary,
                    "resources": {
                        "binding_config": str(staged_resources["binding_config"]),
                        "positional_map": str(staged_resources["positional_map"]),
                    },
                    "lambda_run": lambda_result,
                }

                return self.format_success(
                    response,
                    message="Lambda prediction completed",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def model_prepare_job(
            ctx,
            model_name: str,
            inputs: Dict[str, Any],
            config: Optional[Dict[str, Any]] = None,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Prepare a model invocation using ModelManager without executing it."""

            if not model_name:
                return self.format_error(
                    "Model name required",
                    "Provide a registered model name such as 'boltz2' or 'lambda'.",
                )
            if not isinstance(inputs, dict) or not inputs:
                return self.format_error(
                    "Inputs payload empty",
                    "Provide a mapping of model inputs (e.g., sequence_dataset, entity).",
                )

            try:
                manager = self._get_manager()
                invocation = manager.prepare(
                    model_name,
                    inputs=inputs,
                    config=config,
                    metadata=metadata,
                )

                payload: Dict[str, Any] = {
                    "model": model_name,
                    "metadata": invocation.metadata,
                }

                if invocation.job is not None:
                    job = invocation.job
                    artifacts = []
                    for bundle in job.artifacts:
                        artifacts.append(
                            {
                                "name": bundle.spec.name,
                                "kind": bundle.spec.kind,
                                "path": str(bundle.path) if bundle.path else None,
                                "metadata": bundle.metadata,
                            }
                        )
                    payload["job"] = {
                        "command": job.command,
                        "working_dir": str(job.working_dir) if job.working_dir else None,
                        "artifacts": artifacts,
                    }

                if invocation.runtime is not None:
                    runtime = invocation.runtime
                    payload["runtime"] = {
                        "metadata": runtime.metadata,
                        "outputs": {
                            key: (value.shape if hasattr(value, "shape") else None)
                            for key, value in (runtime.outputs or {}).items()
                        },
                    }

                return self.format_success(payload, message="Model job prepared")
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)
