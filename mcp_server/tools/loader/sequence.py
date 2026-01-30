"""Sequence loader tooling for MCP."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from protos.io.ingest.sequence_loader import SequenceLoader

from ..base import BaseTool


class SequenceLoaderTools(BaseTool):
    """Expose SequenceLoader download and registration operations."""

    @property
    def catalog_group(self) -> str:  # noqa: D401 - inherited docs adequate
        return "sequence.loader"

    def __init__(self, context):
        super().__init__(context)
        self._loader: Optional[SequenceLoader] = None

    def _record_artifact(
        self,
        *,
        tool_name: str,
        name: str,
        kind: str,
        summary: Dict[str, Any],
    ) -> str:
        tags = ["sequence", "loader", kind]
        scope = f"sequence.{kind}"
        return self.record_session_artifact(
            tool_name=tool_name,
            name=name,
            kind=kind,
            processor_type="sequence",
            summary=summary,
            tags=tags,
            scope=scope,
        )

    # Helpers -----------------------------------------------------------------

    def _get_loader(self) -> SequenceLoader:
        processor = self.get_processor("sequence")
        loader = self._loader
        if loader is None or loader._processor is not processor:  # type: ignore[attr-defined]
            loader = SequenceLoader(processor=processor)
            self._loader = loader
        return loader

    # Tool registrations ------------------------------------------------------

    def register(self, server):
        @server.tool()
        def sequence_download(
            ctx,
            identifier: str,
            name: Optional[str] = None,
            materialize_entities: bool = True,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Download a FASTA source (local path or UniProt) and register it."""

            if error := self.validate_required_params(
                {"identifier": identifier}, ["identifier"],
            ):
                return error

            loader = self._get_loader()
            processor = self.get_processor("sequence")
            manager = processor.dataset_manager

            saved_name = loader.download_and_register(
                identifier,
                name=name,
                materialize_entities=materialize_entities,
                metadata=metadata or {},
            )

            if not saved_name:
                return self.format_error(
                    f"Failed to download '{identifier}'",
                    "Verify the identifier (local path or UniProt accession).",
                )

            payload: Dict[str, Any] = {
                "identifier": identifier,
                "registered": saved_name,
            }

            if manager.dataset_exists(saved_name):
                payload["entity_type"] = "dataset"
                payload["entities"] = manager.get_dataset_entities(saved_name)
            else:
                payload["entity_type"] = "entity"
                payload["metadata"] = processor.entity_registry.get_entity_metadata(
                    saved_name, processor.processor_type
                )

            summary = {
                "identifier": identifier,
                "registered": saved_name,
                "entity_type": payload["entity_type"],
            }
            if payload["entity_type"] == "dataset":
                summary["entity_count"] = len(payload.get("entities", []))
            handle = self._record_artifact(
                tool_name="sequence_download",
                name=saved_name,
                kind="dataset" if payload["entity_type"] == "dataset" else "entity",
                summary=summary,
            )
            payload["context_handle"] = handle

            return self.format_success(payload, message="Sequence data registered")
        self.register_tool_metadata(
            function=sequence_download,
            name="sequence_download",
            description="Download a FASTA source (local or UniProt) into the sequence processor.",
            parameters=[
                {"name": "identifier", "type": "str"},
                {"name": "name", "type": "str", "optional": True},
                {"name": "materialize_entities", "type": "bool", "default": True},
            ],
            returns={"fields": ["registered", "entity_type", "context_handle"]},
            tags=["sequence", "loader"],
        )

        @server.tool()
        def sequence_register_records(
            ctx,
            records: List[Dict[str, Any]],
            dataset_name: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None,
            overwrite: bool = False,
        ) -> Dict[str, Any]:
            """Register sequences provided inline (e.g., from another tool)."""

            if error := self.validate_required_params(
                {"records": records}, ["records"],
            ):
                return error

            loader = self._get_loader()
            result = loader.register_sequence_records(
                records,
                dataset_name=dataset_name,
                dataset_metadata=metadata,
                overwrite=overwrite,
            )

            context_info: Dict[str, Any] = {}
            dataset_created = result.get("dataset")
            if dataset_created:
                summary = {
                    "dataset": dataset_created,
                    "entity_count": len(result.get("entities", [])),
                    "source": "sequence_register_records",
                }
                dataset_handle = self._record_artifact(
                    tool_name="sequence_register_records",
                    name=dataset_created,
                    kind="dataset",
                    summary=summary,
                )
                context_info["dataset_handle"] = dataset_handle

            entity_handles: List[str] = []
            for entity_name in result.get("entities", []):
                summary = {
                    "entity": entity_name,
                    "source": "sequence_register_records",
                }
                handle = self._record_artifact(
                    tool_name="sequence_register_records",
                    name=entity_name,
                    kind="entity",
                    summary=summary,
                )
                entity_handles.append(handle)

            if entity_handles:
                context_info["entity_handles"] = entity_handles

            if context_info:
                result["context"] = context_info

            return self.format_success(result, message="Sequences registered")
        self.register_tool_metadata(
            function=sequence_register_records,
            name="sequence_register_records",
            description="Register in-memory sequence records (FASTA-style dictionaries).",
            parameters=[
                {"name": "records", "type": "list[dict]"},
                {"name": "dataset_name", "type": "str", "optional": True},
                {"name": "overwrite", "type": "bool", "default": False},
            ],
            returns={"fields": ["entities", "dataset", "context"]},
            tags=["sequence", "loader"],
        )

        @server.tool()
        def sequence_inspect_identifier(ctx, identifier: str) -> Dict[str, Any]:
            """Parse an identifier using SequenceLoader without downloading."""

            if error := self.validate_required_params(
                {"identifier": identifier}, ["identifier"],
            ):
                return error

            loader = self._get_loader()
            try:
                info = loader.parse_identifier(identifier)
            except ValueError as exc:  # noqa: BLE001
                return self.format_error(str(exc))

            return self.format_success(info)
        self.register_tool_metadata(
            function=sequence_inspect_identifier,
            name="sequence_inspect_identifier",
            description="Parse a sequence identifier to understand its source without downloading.",
            parameters=[{"name": "identifier", "type": "str"}],
            returns={"fields": ["source", "name"]},
            tags=["sequence", "loader"],
        )

        @server.tool()
        def sequence_load_dataset(
            ctx,
            dataset_name: str,
            include_sequences: bool = False,
            preview_length: int = 120,
        ) -> Dict[str, Any]:
            """Load a registered sequence dataset with optional sequence content."""

            if error := self.validate_required_params(
                {"dataset_name": dataset_name},
                ["dataset_name"],
            ):
                return error

            processor = self.get_processor("sequence")
            manager = processor.dataset_manager
            if not manager.dataset_exists(dataset_name):
                return self.format_error(
                    f"Sequence dataset '{dataset_name}' not found",
                    "Use dataset_list or sequence_register_records to create it.",
                )

            dataset = processor.load_dataset(dataset_name)
            entities = manager.get_dataset_entities(dataset_name)

            entries: List[Dict[str, Any]] = []
            if isinstance(dataset, dict):
                for key, value in list(dataset.items())[:200]:
                    entry: Dict[str, Any] = {"sequence_id": key}
                    if isinstance(value, str):
                        entry["length"] = len(value)
                        entry["preview"] = value[:preview_length]
                    entries.append(entry)
            else:
                for key in entities:
                    entries.append({"sequence_id": key})

            payload: Dict[str, Any] = {
                "dataset_name": dataset_name,
                "entity_count": len(entities),
                "entities": entries,
            }

            if include_sequences and isinstance(dataset, dict):
                payload["sequences"] = dataset

            return self.format_success(payload)

        self.register_tool_metadata(
            function=sequence_load_dataset,
            name="sequence_load_dataset",
            description="Load a registered sequence dataset for inspection.",
            parameters=[
                {"name": "dataset_name", "type": "str"},
                {"name": "include_sequences", "type": "bool", "default": False},
                {"name": "preview_length", "type": "int", "default": 120},
            ],
            returns={"fields": ["entities", "entity_count"]},
            tags=["sequence", "load"],
        )

        # Legacy aliases removed to avoid duplicate tool registrations.
