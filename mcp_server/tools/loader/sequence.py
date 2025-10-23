"""Sequence loader tooling for MCP."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from protos.io.ingest.sequence_loader import SequenceLoader

from ..base import BaseTool


class SequenceLoaderTools(BaseTool):
    """Expose SequenceLoader download and registration operations."""

    def __init__(self, context):
        super().__init__(context)
        self._loader: Optional[SequenceLoader] = None

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

            return self.format_success(payload, message="Sequence data registered")

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

            return self.format_success(result, message="Sequences registered")

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
