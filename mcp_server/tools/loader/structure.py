"""Structure loader tooling for MCP."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from protos.io.ingest.structure_loader import StructureLoader

from ..base import BaseTool


class StructureLoaderTools(BaseTool):
    """Expose StructureLoader download helpers."""

    def __init__(self, context):
        super().__init__(context)
        self._loader: Optional[StructureLoader] = None

    def _get_loader(self) -> StructureLoader:
        processor = self.get_processor("structure")
        loader = self._loader
        if loader is None or loader._processor is not processor:  # type: ignore[attr-defined]
            loader = StructureLoader(processor=processor)
            self._loader = loader
        return loader

    def register(self, server):
        @server.tool()
        def structure_download(
            ctx,
            identifier: str,
            name: Optional[str] = None,
            source: Optional[str] = None,
            overwrite: bool = False,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Download a structure (PDB/AlphaFold/local) and register it."""

            if error := self.validate_required_params(
                {"identifier": identifier}, ["identifier"],
            ):
                return error

            loader = self._get_loader()
            processor = self.get_processor("structure")

            kwargs = {"overwrite": overwrite}
            if source:
                kwargs["source"] = source

            registered = loader.download_and_register(
                identifier,
                name=name,
                metadata=metadata or {},
                **kwargs,
            )

            if not registered:
                return self.format_error(
                    f"Failed to download '{identifier}'",
                    "Verify the identifier (PDB ID, AlphaFold ID, UniProt accession, or path).",
                )

            info = processor.entity_registry.get_entity_metadata(registered, processor.processor_type)
            return self.format_success(
                {
                    "identifier": identifier,
                    "registered": registered,
                    "metadata": info,
                },
                message="Structure registered",
            )

        @server.tool()
        def structure_download_batch(
            ctx,
            identifiers: List[str],
            dataset_name: Optional[str] = None,
            source: Optional[str] = None,
            overwrite: bool = False,
            create_dataset: bool = True,
        ) -> Dict[str, Any]:
            """Download multiple structures and optionally create a dataset."""

            if error := self.validate_required_params(
                {"identifiers": identifiers}, ["identifiers"],
            ):
                return error

            loader = self._get_loader()

            kwargs = {"overwrite": overwrite}
            if source:
                kwargs["source"] = source

            success, failed = loader.download_batch(
                identifiers,
                dataset_name=dataset_name,
                create_dataset=create_dataset,
                **kwargs,
            )

            payload: Dict[str, Any] = {
                "requested": identifiers,
                "downloaded": success,
                "failed": failed,
            }

            if dataset_name and success:
                payload["dataset_name"] = dataset_name

            return self.format_success(payload)

        @server.tool()
        def structure_sources(ctx) -> Dict[str, Any]:
            """List available structure download sources."""

            loader = self._get_loader()
            return self.format_success({"sources": loader.list_sources()})
