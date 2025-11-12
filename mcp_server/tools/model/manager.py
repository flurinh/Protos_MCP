"""ModelManager tooling to expose Protos model orchestration via MCP."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import importlib

import protos.models
from protos.models.model_manager import ModelManager, prepare_mutation_screen
from protos.models.model_specs import (
    ArtifactBundle,
    ArtifactSpec,
    ModelBatch,
    ModelCard,
    ModelInvocation,
    RuntimeResult,
)
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
        self._lambda_runtime = importlib.import_module(
            "protos.models.lambda.runtime_utils"
        )

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
            "output_spec": [
                self._artifact_spec_dict(spec) for spec in card.output_spec
            ],
            "metadata": card.metadata,
        }

    def _serialize_invocation(self, invocation: ModelInvocation) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": invocation.model,
            "metadata": dict(invocation.metadata or {}),
        }

        if invocation.job is not None:
            job = invocation.job
            artifacts: List[Dict[str, Any]] = []
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
                "metadata": dict(runtime.metadata or {}),
                "outputs": {
                    key: (value.shape if hasattr(value, "shape") else None)
                    for key, value in (runtime.outputs or {}).items()
                },
            }

        if invocation.outputs:
            payload["outputs"] = [
                {
                    "name": bundle.spec.name,
                    "kind": bundle.spec.kind,
                    "provider": bundle.spec.provider,
                    "format": bundle.spec.format,
                    "path": str(bundle.path),
                    "metadata": bundle.metadata,
                }
                for bundle in invocation.outputs
            ]

        return payload

    def _invocation_from_payload(self, payload: Dict[str, Any]) -> ModelInvocation:
        if not payload:
            raise InvalidInputError(
                "invocation",
                "Invocation payload is required",
                "Pass the 'data' field returned by a model preparation tool.",
            )

        model_name = payload.get("model")
        if not model_name:
            raise InvalidInputError(
                "invocation",
                "Invocation payload missing model name",
                "Include the 'model' value from the prepare response.",
            )

        manager = self._get_manager()
        card = manager.cards.get(model_name)
        if card is None:
            raise InvalidInputError(
                "invocation",
                f"Model '{model_name}' is not registered",
                "Call list_models to inspect available model names.",
            )

        runtime_payload = payload.get("runtime") or {}
        runtime_metadata = dict(runtime_payload.get("metadata") or {})
        runtime_outputs = dict(runtime_payload.get("outputs") or {})
        runtime_result = None
        if runtime_metadata or runtime_outputs:
            runtime_result = RuntimeResult(
                outputs=runtime_outputs,
                artifacts=[],
                metadata=runtime_metadata,
            )

        bundles: List[ArtifactBundle] = []
        for bundle_payload in payload.get("outputs", []):
            bundle_path = bundle_payload.get("path")
            if not bundle_path:
                continue
            spec = ArtifactSpec(
                name=bundle_payload.get("name", "artifact"),
                kind=bundle_payload.get("kind", "file"),
                provider=bundle_payload.get("provider", "model_manager"),
                format=bundle_payload.get("format"),
            )
            bundles.append(
                ArtifactBundle(
                    spec=spec,
                    path=Path(bundle_path),
                    metadata=bundle_payload.get("metadata", {}),
                )
            )

        return ModelInvocation(
            model=model_name,
            card=card,
            runtime=runtime_result,
            outputs=bundles,
            metadata=dict(payload.get("metadata", {})),
        )

    def _lambda_config_dir(self) -> Path:
        return (
            Path(protos.models.__file__).resolve().parent
            / "lambda"
            / "lmda"
            / "configs"
        )

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
    def _preview_sequences(
        sequence_map: Dict[str, str], *, limit: int = 5
    ) -> Dict[str, str]:
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
            if not overwrite_dataset and seq_proc.dataset_manager.dataset_exists(
                dataset_key
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
            runtime.metadata.get("property_table") if runtime.metadata else None
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
            property_path = prop_proc.tables_dir / f"{property_table_name}.csv"

        return {
            "run_id": runtime.metadata.get("run_id") if runtime.metadata else None,
            "protein_family": (
                runtime.metadata.get("protein_family")
                if runtime.metadata
                else protein_family
            ),
            "prediction_row_count": row_count,
            "prediction_columns": columns,
            "predictions_preview": preview_rows,
            "attention_available": attention_available,
            "property_table": property_table_name,
            "property_table_path": str(property_path) if property_path else None,
            "work_dir": runtime.metadata.get("work_dir") if runtime.metadata else None,
            "outputs_dir": (
                runtime.metadata.get("outputs_dir") if runtime.metadata else None
            ),
            "embedding_dataset": (
                runtime.metadata.get("embedding_dataset") if runtime.metadata else None
            ),
            "embedding_model": (
                runtime.metadata.get("embedding_model")
                if runtime.metadata
                else embedding_model
            ),
            "embedding_type": (
                runtime.metadata.get("embedding_type")
                if runtime.metadata
                else embedding_type
            ),
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
                return self.format_success(
                    {
                        "count": len(cards),
                        "models": cards,
                    }
                )
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

                grn_table_name, grn_row_count, grn_summary = (
                    self._prepare_grn_annotations(
                        seq_proc,
                        dataset_name,
                        reference_table=resolved_reference,
                        protein_family=normalized_family,
                    )
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
                    "sequence_count": (
                        int(sequence_count) if sequence_count is not None else None
                    ),
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
                payload = self._serialize_invocation(invocation)
                return self.format_success(payload, message="Model job prepared")
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=model_prepare_job,
            name="model_prepare_job",
            description="Low-level wrapper around ModelManager.prepare for arbitrary adapters.",
            parameters=[
                {"name": "model_name", "type": "str"},
                {"name": "inputs", "type": "dict[str,Any]"},
            ],
            returns={"fields": ["job", "runtime", "metadata"]},
            tags=["model", "prepare"],
        )

        @server.tool()
        def model_prepare_input(
            ctx,
            model_name: str,
            entity: str,
            dataset_name: Optional[str] = None,
            entity_format: str = "sequence",
            dataset_input_key: Optional[str] = None,
            inputs: Optional[Dict[str, Any]] = None,
            config: Optional[Dict[str, Any]] = None,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Prepare a single-entity invocation via ModelManager.prepare_input."""

            if not model_name:
                return self.format_error(
                    "Model name required",
                    "Provide a registered model such as 'boltz2' or 'lambda'.",
                )
            if not entity:
                return self.format_error(
                    "Entity name required",
                    "Provide the entity identifier inside the referenced dataset.",
                )

            try:
                invocation = self._get_manager().prepare_input(
                    model_name,
                    entity_name=entity,
                    entity_format=entity_format,
                    dataset_name=dataset_name,
                    dataset_input_key=dataset_input_key,
                    inputs=inputs,
                    config=config,
                    metadata=metadata,
                )
                payload = self._serialize_invocation(invocation)
                return self.format_success(payload, message="Model input prepared")
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=model_prepare_input,
            name="model_prepare_input",
            description="Prepare an invocation for a single entity/dataset pair.",
            parameters=[
                {"name": "model_name", "type": "str"},
                {"name": "entity", "type": "str"},
                {"name": "dataset_name", "type": "str", "optional": True},
                {"name": "entity_format", "type": "str", "default": "sequence"},
            ],
            tags=["model", "prepare"],
        )

        @server.tool()
        def model_prepare_batch(
            ctx,
            model_name: str,
            entity_configs: List[Dict[str, Any]],
            batch_name: Optional[str] = None,
            default_entity_format: str = "sequence",
            base_config: Optional[Dict[str, Any]] = None,
            batch_metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Normalize a batch of entity configs for later execution."""

            if not model_name:
                return self.format_error(
                    "Model name required", "Specify the model to batch."
                )
            if not entity_configs:
                return self.format_error(
                    "No entity configs provided",
                    "Pass a non-empty list of entity configuration dictionaries.",
                )

            try:
                batch = self._get_manager().prepare_batch(
                    model_name,
                    entity_configs,
                    batch_name=batch_name,
                    default_entity_format=default_entity_format,
                    base_config=base_config,
                    batch_metadata=batch_metadata,
                )
                return self.format_success(batch.to_dict(), message="Batch prepared")
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=model_prepare_batch,
            name="model_prepare_batch",
            description="Record a batch of entity configs (without executing them).",
            parameters=[
                {"name": "model_name", "type": "str"},
                {"name": "entity_configs", "type": "list[dict]"},
            ],
            returns={"fields": ["name", "inputs"]},
            tags=["model", "batch"],
        )

        @server.tool()
        def model_ingest_outputs(
            ctx,
            invocation: Optional[Dict[str, Any]] = None,
            runtime_metadata: Optional[Dict[str, Any]] = None,
            outputs: Optional[List[Dict[str, Any]]] = None,
        ) -> Dict[str, Any]:
            """Register model outputs (property tables, ligands, etc.) with Protos."""

            if invocation is None and runtime_metadata is None and outputs is None:
                return self.format_error(
                    "No ingestion payload provided",
                    "Pass the invocation dictionary and/or explicit outputs to ingest.",
                )

            try:
                payload = dict(invocation or {})
                if runtime_metadata:
                    runtime = dict(payload.get("runtime") or {})
                    runtime["metadata"] = runtime_metadata
                    payload["runtime"] = runtime
                if outputs is not None:
                    payload["outputs"] = outputs

                summary = self._get_manager().ingest_outputs(
                    self._invocation_from_payload(payload)
                )
                return self.format_success(summary, message="Outputs ingested")
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=model_ingest_outputs,
            name="model_ingest_outputs",
            description="Ingest property tables or other artifacts referenced by an invocation payload.",
            parameters=[
                {"name": "invocation", "type": "dict", "optional": True},
                {"name": "runtime_metadata", "type": "dict", "optional": True},
                {"name": "outputs", "type": "list[dict]", "optional": True},
            ],
            tags=["model", "ingest"],
        )

        @server.tool()
        def model_prepare_mutation_screen(
            ctx,
            dataset_name: str,
            grn_positions: List[str],
            mutations: List[str],
            model_name: str = "boltz2",
            grn_table_name: Optional[str] = None,
            protein_family: str = "gpcr_a",
            reference_table: str = "gpcrdb_ref",
            base_config: Optional[Dict[str, Any]] = None,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Prepare Boltz mutation predictions across GRN labels via ModelManager."""

            if not dataset_name:
                return self.format_error(
                    "dataset_name required", "Provide a sequence dataset name."
                )
            if not grn_positions:
                return self.format_error(
                    "grn_positions empty", "Provide at least one GRN label to mutate."
                )
            if not mutations:
                return self.format_error(
                    "mutations empty",
                    "Provide the amino acids to scan at each GRN label.",
                )

            try:
                seq_proc: SequenceProcessor = self.get_processor("sequence")  # type: ignore[assignment]
                invocations = prepare_mutation_screen(
                    seq_proc=seq_proc,
                    dataset_name=dataset_name,
                    grn_positions=grn_positions,
                    mutations=mutations,
                    grn_table_name=grn_table_name,
                    protein_family=protein_family,
                    reference_table=reference_table,
                    manager=self._get_manager(),
                    model_name=model_name,
                    base_config=base_config,
                    metadata=metadata,
                )
                serialized = [self._serialize_invocation(inv) for inv in invocations]
                return self.format_success(
                    {"count": len(serialized), "invocations": serialized},
                    message="Mutation screen prepared",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=model_prepare_mutation_screen,
            name="model_prepare_mutation_screen",
            description="Prepare Boltz-style mutation configs across GRN positions.",
            parameters=[
                {"name": "dataset_name", "type": "str"},
                {"name": "grn_positions", "type": "list[str]"},
                {"name": "mutations", "type": "list[str]"},
                {"name": "model_name", "type": "str", "default": "boltz2"},
            ],
            tags=["model", "mutations"],
        )

        @server.tool()
        def model_prepare_boltz_mutations(
            ctx,
            dataset_name: str,
            mutation_entries: List[Dict[str, Any]],
            model_name: str = "boltz2",
            base_config: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Prepare Boltz configuration jobs for explicit mutation payloads."""

            if not dataset_name:
                return self.format_error(
                    "dataset_name required",
                    "Provide the sequence dataset containing the source entities.",
                )
            if not mutation_entries:
                return self.format_error(
                    "mutation_entries required",
                    "Provide at least one entry with an entity and mutations list.",
                )

            try:
                manager = self._get_manager()
                invocations = manager.prepare_boltz_mutations(
                    dataset_name,
                    mutation_entries,
                    base_config=base_config,
                    model_name=model_name,
                )
                serialized = [self._serialize_invocation(inv) for inv in invocations]

                jobs_summary: List[Dict[str, Any]] = []
                for invocation in invocations:
                    metadata = dict(invocation.metadata or {})
                    entry = dict(metadata.get("mutation_entry") or {})
                    job_info: Dict[str, Any] = {
                        "entity": metadata.get("entity") or entry.get("entity"),
                        "mutations": entry.get("mutations"),
                        "config_id": metadata.get("config_id"),
                    }
                    if invocation.job:
                        config_path = None
                        fasta_path = None
                        for bundle in invocation.job.artifacts:
                            if bundle.spec.name == "boltz_config" and bundle.path:
                                config_path = str(bundle.path)
                            if bundle.spec.name == "boltz_sequences" and bundle.path:
                                fasta_path = str(bundle.path)
                        if config_path:
                            job_info["config_path"] = config_path
                        if fasta_path:
                            job_info["fasta_path"] = fasta_path
                        job_info["command"] = invocation.job.command
                        job_info["working_dir"] = (
                            str(invocation.job.working_dir)
                            if invocation.job.working_dir
                            else None
                        )
                    jobs_summary.append(job_info)

                return self.format_success(
                    {
                        "count": len(serialized),
                        "invocations": serialized,
                        "jobs": jobs_summary,
                    },
                    message="Boltz mutation jobs prepared",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=model_prepare_boltz_mutations,
            name="model_prepare_boltz_mutations",
            description="Prepare Boltz configuration YAML/FASTA bundles for explicit mutation payloads.",
            parameters=[
                {"name": "dataset_name", "type": "str"},
                {"name": "mutation_entries", "type": "list[dict]"},
                {"name": "model_name", "type": "str", "default": "boltz2"},
                {"name": "base_config", "type": "dict", "optional": True},
            ],
            tags=["model", "boltz", "mutations"],
        )
