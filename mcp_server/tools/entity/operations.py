"""
Entity operation tools for CRUD operations on Protos entities.

These tools handle downloading, saving, loading, and deleting entities
with automatic path management and registration.
"""

from typing import Dict, List, Optional, Any
import json
import base64
from pathlib import Path

from protos.io.ingest.sequence_loader import SequenceLoader
from protos.io.ingest.structure_loader import StructureLoader

from ..base import BaseTool
from ...core.context_preview import (
    PreviewLimits,
    build_generic_preview,
    estimate_payload_size,
)
from ...core.exceptions import PayloadTooLargeError


class EntityOperationTools(BaseTool):
    """Tools for entity CRUD operations."""

    def __init__(self, context):
        super().__init__(context)
        self._sequence_loader: Optional[SequenceLoader] = None
        self._structure_loader: Optional[StructureLoader] = None
        self._preview_limits = PreviewLimits()

    # Loader helpers -----------------------------------------------------

    def _get_sequence_loader(self) -> SequenceLoader:
        processor = self.get_processor("sequence")
        loader = self._sequence_loader
        if loader is None or getattr(loader, "_processor", None) is not processor:
            loader = SequenceLoader(processor=processor)
            self._sequence_loader = loader
        return loader

    def _get_structure_loader(self) -> StructureLoader:
        processor = self.get_processor("structure")
        loader = self._structure_loader
        if loader is None or getattr(loader, "_processor", None) is not processor:
            loader = StructureLoader(processor=processor)
            self._structure_loader = loader
        return loader

    @staticmethod
    def _normalize_structure_id(structure_id: str) -> str:
        return structure_id.lower().strip()

    def _delete_entity(self, processor, name: str) -> None:
        if hasattr(processor, "delete_entity") and processor.entity_exists(name):
            try:
                processor.delete_entity(name)
            except Exception:
                pass

    def _record_download_artifact(
        self,
        *,
        tool_name: str,
        processor_type: str,
        name: str,
        kind: str,
        summary: Dict[str, Any],
    ) -> str:
        tags = [processor_type, "download", kind]
        scope = f"{processor_type}.{kind}"
        return self.record_session_artifact(
            tool_name=tool_name,
            name=name,
            kind=kind,
            processor_type=processor_type,
            summary=summary,
            tags=tags,
            scope=scope,
        )

    def _build_download_context(
        self,
        *,
        tool_name: str,
        processor_type: str,
        downloaded: List[str],
        dataset_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {}

        handles = [
            self._record_download_artifact(
                tool_name=tool_name,
                processor_type=processor_type,
                name=name,
                kind="entity",
                summary={"identifier": name, "source": tool_name},
            )
            for name in downloaded
        ]
        if handles:
            context["entity_handles"] = handles

        if dataset_name:
            dataset_handle = self._record_download_artifact(
                tool_name=tool_name,
                processor_type=processor_type,
                name=dataset_name,
                kind="dataset",
                summary={
                    "dataset": dataset_name,
                    "entity_count": len(downloaded),
                    "source": tool_name,
                },
            )
            context["dataset_handle"] = dataset_handle

        return context

    def _download_structure_entity(
        self,
        *,
        identifier: str,
        source: Optional[str],
        overwrite: bool,
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        processor = self.get_processor("structure")
        normalized_id = self._normalize_structure_id(identifier)

        if not overwrite and processor.entity_exists(normalized_id):
            return self.format_error(
                f"Structure '{identifier}' already exists",
                "Set overwrite=true to refresh it or use download_entities for batch operations",
            )

        if overwrite and processor.entity_exists(normalized_id):
            self._delete_entity(processor, normalized_id)

        loader = self._get_structure_loader()
        registered = loader.download_and_register(
            identifier,
            name=normalized_id,
            metadata=metadata,
            source=source,
        )

        if not registered:
            return self.format_error(
                f"Failed to download '{identifier}'",
                "Verify the identifier (PDB ID, AlphaFold ID, UniProt accession, or local path).",
            )

        info = (
            processor.entity_registry.get_entity_metadata(
                registered, processor.processor_type
            )
            or {}
        )
        payload = {
            "identifier": identifier,
            "registered": registered,
            "metadata": info,
        }

        handle = self._record_download_artifact(
            tool_name="download_entity",
            processor_type="structure",
            name=registered,
            kind="entity",
            summary={
                "identifier": identifier,
                "registered": registered,
                "metadata_keys": sorted(info.keys()),
            },
        )
        payload["context_handle"] = handle

        return self.format_success(payload, message="Structure registered")

    def _download_sequence_entity(
        self,
        *,
        identifier: str,
        overwrite: bool,
        metadata: Optional[Dict[str, Any]],
        materialize_entities: bool,
    ) -> Dict[str, Any]:
        processor = self.get_processor("sequence")
        target_name = identifier

        if not overwrite and processor.entity_exists(target_name):
            return self.format_error(
                f"Sequence '{identifier}' already exists",
                "Use overwrite=true or pick a different entity name",
            )

        if overwrite and processor.entity_exists(target_name):
            self._delete_entity(processor, target_name)

        loader = self._get_sequence_loader()
        saved_name = loader.download_and_register(
            identifier,
            name=target_name,
            materialize_entities=materialize_entities,
            metadata=metadata,
        )

        if not saved_name:
            return self.format_error(
                f"Failed to download '{identifier}'",
                "Provide a local FASTA path or UniProt accession (optionally prefixed with 'uniprot:').",
            )

        manager = processor.dataset_manager
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
                saved_name,
                processor.processor_type,
            )

        summary = {
            "identifier": identifier,
            "registered": saved_name,
            "entity_type": payload["entity_type"],
        }
        if payload["entity_type"] == "dataset":
            summary["entity_count"] = len(payload.get("entities", []))

        handle = self._record_download_artifact(
            tool_name="download_entity",
            processor_type="sequence",
            name=saved_name,
            kind="dataset" if payload["entity_type"] == "dataset" else "entity",
            summary=summary,
        )
        payload["context_handle"] = handle

        return self.format_success(payload, message="Sequence data registered")

    def register(self, server):
        """Register entity operation tools with the server."""

        @server.tool()
        def download_entity(
            ctx,
            entity_id: str,
            processor_type: str = "structure",
            source: Optional[str] = None,
            overwrite: bool = False,
            metadata: Optional[Dict[str, Any]] = None,
            materialize_entities: bool = True,
        ) -> Dict:
            """Download a single entity (structure or sequence) via the canonical loaders."""

            try:
                if error := self.validate_required_params(
                    {"entity_id": entity_id}, ["entity_id"]
                ):
                    return error

                if error := self.validate_processor_type(processor_type):
                    return error

                normalized_type = processor_type.lower()

                if normalized_type == "structure":
                    return self._download_structure_entity(
                        identifier=entity_id,
                        source=source,
                        overwrite=overwrite,
                        metadata=metadata,
                    )

                if normalized_type == "sequence":
                    return self._download_sequence_entity(
                        identifier=entity_id,
                        overwrite=overwrite,
                        metadata=metadata,
                        materialize_entities=materialize_entities,
                    )

                return self.format_error(
                    f"Download not implemented for processor '{processor_type}'",
                    "Currently supported processor types: structure, sequence.",
                )

            except Exception as exc:
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=download_entity,
            name="download_entity",
            description="Download a single entity (structure or sequence) and register it with the appropriate processor.",
            parameters=[
                {"name": "entity_id", "type": "str"},
                {"name": "processor_type", "type": "str", "default": "structure"},
                {"name": "source", "type": "str", "optional": True},
                {"name": "overwrite", "type": "bool", "default": False},
                {"name": "materialize_entities", "type": "bool", "default": True},
            ],
            returns={"fields": ["registered", "context_handle"]},
            tags=["entity", "download"],
        )

        @server.tool()
        def download_entities(
            ctx,
            identifiers: List[str],
            processor_type: str = "structure",
            dataset_name: Optional[str] = None,
            create_dataset: bool = True,
            source: Optional[str] = None,
            overwrite: bool = False,
            metadata: Optional[Dict[str, Any]] = None,
            materialize_entities: bool = True,
        ) -> Dict:
            """Download multiple entities and optionally create/register a dataset."""

            try:
                if error := self.validate_required_params(
                    {"identifiers": identifiers}, ["identifiers"]
                ):
                    return error

                if not identifiers:
                    return self.format_error(
                        "No identifiers provided", "Pass one or more IDs to download."
                    )

                if error := self.validate_processor_type(processor_type):
                    return error

                normalized_type = processor_type.lower()
                processor = self.get_processor(normalized_type)
                skipped_existing: List[str] = []
                download_targets: List[str] = []

                for identifier in identifiers:
                    target_name = (
                        self._normalize_structure_id(identifier)
                        if normalized_type == "structure"
                        else identifier
                    )
                    if (
                        not overwrite
                        and hasattr(processor, "entity_exists")
                        and processor.entity_exists(target_name)
                    ):
                        skipped_existing.append(identifier)
                        continue
                    if (
                        overwrite
                        and hasattr(processor, "entity_exists")
                        and processor.entity_exists(target_name)
                    ):
                        self._delete_entity(processor, target_name)
                    download_targets.append(identifier)

                downloaded: List[str] = []
                failed: List[str] = []

                if download_targets:
                    if normalized_type == "structure":
                        loader = self._get_structure_loader()
                        downloaded, failed = loader.download_batch(
                            download_targets,
                            dataset_name=dataset_name,
                            create_dataset=create_dataset,
                            source=source,
                            metadata=metadata,
                        )
                    elif normalized_type == "sequence":
                        loader = self._get_sequence_loader()
                        downloaded, failed = loader.download_batch(
                            download_targets,
                            dataset_name=dataset_name,
                            create_dataset=create_dataset,
                            metadata=metadata,
                            materialize_entities=materialize_entities,
                        )
                    else:
                        return self.format_error(
                            f"Download not implemented for processor '{processor_type}'",
                            "Currently supported processor types: structure, sequence.",
                        )

                payload: Dict[str, Any] = {
                    "processor_type": normalized_type,
                    "requested": identifiers,
                    "downloaded": downloaded,
                    "failed": failed,
                }

                if skipped_existing:
                    payload["skipped_existing"] = skipped_existing

                if dataset_name and downloaded and create_dataset:
                    payload["dataset_name"] = dataset_name

                context_handles = self._build_download_context(
                    tool_name="download_entities",
                    processor_type=normalized_type,
                    downloaded=downloaded,
                    dataset_name=(
                        dataset_name
                        if dataset_name and downloaded and create_dataset
                        else None
                    ),
                )
                if context_handles:
                    payload["context"] = context_handles

                message = "Download completed"
                if failed:
                    message = f"Downloaded {len(downloaded)} of {len(identifiers)} identifiers"

                return self.format_success(payload, message=message)

            except Exception as exc:
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=download_entities,
            name="download_entities",
            description="Download a list of entities for a processor, optionally materializing them as a dataset.",
            parameters=[
                {"name": "identifiers", "type": "list[str]"},
                {"name": "processor_type", "type": "str", "default": "structure"},
                {"name": "dataset_name", "type": "str", "optional": True},
                {"name": "create_dataset", "type": "bool", "default": True},
                {"name": "overwrite", "type": "bool", "default": False},
                {"name": "materialize_entities", "type": "bool", "default": True},
            ],
            returns={"fields": ["downloaded", "failed", "context"]},
            tags=["entity", "download", "batch"],
        )

        @server.tool()
        def download_sources(ctx, processor_type: str = "structure") -> Dict:
            """List available download sources for the requested processor."""

            try:
                if error := self.validate_processor_type(processor_type):
                    return error

                normalized_type = processor_type.lower()
                if normalized_type == "structure":
                    loader = self._get_structure_loader()
                    sources = loader.list_sources()
                    canonical = ["rcsb", "alphafold", "local"]
                    hint = (
                        "Use 'rcsb' for experimental PDB IDs, 'alphafold' for predictions, and 'local' to"
                        " import CIF/PDB files. Aliases like 'pdb' and 'mmcif' map to the canonical names."
                    )
                elif normalized_type == "sequence":
                    loader = self._get_sequence_loader()
                    sources = sorted(set(loader.list_sources() + ["local", "uniprot"]))
                    canonical = ["local", "uniprot"]
                    hint = "Provide local FASTA paths or UniProt accessions (with or without the 'uniprot:' prefix)."
                else:
                    return self.format_error(
                        f"Download sources not implemented for processor '{processor_type}'",
                        "Currently supported processor types: structure, sequence.",
                    )

                return self.format_success(
                    {
                        "processor_type": normalized_type,
                        "sources": sources,
                        "canonical": canonical,
                        "hint": hint,
                    }
                )

            except Exception as exc:
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=download_sources,
            name="download_sources",
            description="List valid download sources/aliases for a processor.",
            parameters=[
                {"name": "processor_type", "type": "str", "default": "structure"}
            ],
            returns={"fields": ["sources", "canonical", "hint"]},
            tags=["entity", "download", "guide"],
        )

        @server.tool()
        def load_entity(
            ctx,
            name: str,
            format: str,
            output_format: str = "summary",
            max_preview_rows: int = 250,
            max_preview_items: int = 120,
            max_preview_chars: int = 800,
        ) -> Dict:
            """
            Load an entity's data.

            Args:
                name: Entity name
                format: Processor type (structure, sequence, etc.)
                output_format: How to return data (json, base64, summary)

            Returns:
                Dictionary with entity data
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "format": format}, ["name", "format"]
                ):
                    return error

                # Validate processor type (format parameter is processor type)
                if error := self.validate_processor_type(format):
                    return error

                # Get processor
                processor = self.get_processor(format)
                resolved_name = (
                    self._normalize_structure_id(name)
                    if format == "structure"
                    else name
                )

                # Load entity based on processor type
                try:
                    if format == "structure":
                        frame = processor.load_entity(resolved_name)
                        if frame is None:
                            return self.format_error(
                                f"Failed to load structure {name}",
                                "Structure may not exist. Try downloading it first.",
                            )
                        data = frame.reset_index()
                    elif format == "property":
                        # For properties, get all properties for the entity
                        if hasattr(processor, "get_entity_properties"):
                            data = processor.get_entity_properties(name)
                        else:
                            return self.format_error(
                                "Property loading not available",
                                "PropertyProcessor doesn't have get_entity_properties method",
                            )
                    elif hasattr(processor, "load_entity"):
                        data = processor.load_entity(resolved_name)
                    elif hasattr(processor, "load_sequence") and format == "sequence":
                        data = processor.load_sequence(resolved_name)
                    elif hasattr(processor, "load") and format == "grn":
                        data = processor.load(resolved_name)
                    else:
                        return self.format_error(
                            f"Load not implemented for {format} processor",
                            "This processor may not support entity loading",
                        )
                except FileNotFoundError:
                    return self.format_error(
                        f"Entity '{name}' not found",
                        f"Use download_entity to fetch it first",
                    )

                limits = self._preview_limits.override(
                    max_rows=min(max_preview_rows, self._preview_limits.max_rows),
                    max_items=min(max_preview_items, self._preview_limits.max_items),
                    max_chars=min(max_preview_chars, self._preview_limits.max_chars),
                )

                normalized_format = (output_format or "summary").lower()

                if normalized_format == "summary":
                    preview = build_generic_preview(
                        data, limits=limits, label=resolved_name
                    )
                    return self.format_success(
                        {
                            "name": resolved_name,
                            "format": format,
                            "preview": preview.export(),
                        }
                    )

                if normalized_format == "base64":
                    if hasattr(data, "to_json"):
                        json_str = data.to_json()
                    elif hasattr(data, "to_dict"):
                        json_str = json.dumps(data.to_dict())
                    else:
                        json_str = json.dumps(data)
                    size = estimate_payload_size(json_str)
                    if size > limits.max_bytes:
                        raise PayloadTooLargeError(size=size, limit=limits.max_bytes)
                    encoded = base64.b64encode(json_str.encode()).decode()
                    return self.format_success(
                        {
                            "name": resolved_name,
                            "format": format,
                            "encoding": "base64",
                            "data": encoded,
                        }
                    )

                # Default to JSON output with guardrails
                if hasattr(data, "reset_index") and hasattr(data, "to_dict"):
                    json_data = data.reset_index(drop=True).to_dict(orient="records")
                elif hasattr(data, "to_dict"):
                    json_data = data.to_dict()
                elif hasattr(data, "to_json"):
                    json_data = json.loads(data.to_json())
                elif isinstance(data, str):
                    json_data = {"sequence": data}
                else:
                    json_data = data

                size = estimate_payload_size(json_data)
                if size > limits.max_bytes:
                    raise PayloadTooLargeError(size=size, limit=limits.max_bytes)

                return self.format_success(
                    {
                        "name": resolved_name,
                        "format": format,
                        "data": json_data,
                    }
                )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def save_entity(
            ctx,
            name: str,
            data: Any,
            format: str,
            metadata: Optional[Dict] = None,
            data_encoding: str = "json",
        ) -> Dict:
            """
            Save a new entity or update existing one.

            Args:
                name: Entity name
                data: Entity data (JSON object, JSON string, or base64 encoded string)
                format: Processor type
                metadata: Optional metadata to store
                data_encoding: How data is encoded (json or base64)

            Returns:
                Dictionary with save status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "data": data, "format": format},
                    ["name", "data", "format"],
                ):
                    return error

                # Validate processor type
                if error := self.validate_processor_type(format):
                    return error

                # Get processor
                processor = self.get_processor(format)

                # Decode data
                if data_encoding == "base64":
                    try:
                        decoded = base64.b64decode(data).decode()
                        data = decoded
                    except Exception as e:
                        return self.format_error(
                            f"Failed to decode base64 data: {e}",
                            "Ensure data is properly base64 encoded",
                        )

                # Parse data based on format
                if format == "sequence":
                    # For sequences, data might be string, dict, or JSON string
                    if isinstance(data, str):
                        # Check if it's a JSON string
                        if data.startswith("{"):
                            parsed = json.loads(data)
                            sequence_data = parsed.get("sequence", parsed)
                        else:
                            # It's a plain sequence string
                            sequence_data = data
                    elif isinstance(data, dict):
                        # Direct dictionary input
                        sequence_data = data.get("sequence", data)
                    else:
                        sequence_data = data

                    # Use the processor's save_entity method - it handles ALL path management
                    if hasattr(processor, "save_entity"):
                        processor.save_entity(name, sequence_data, metadata)
                    elif hasattr(processor, "save_sequence"):
                        # Fallback to save_sequence if available
                        processor.save_sequence(name, sequence_data)
                        # Note: The processor internally handles entity registration
                    else:
                        return self.format_error(
                            "Save not implemented for sequence processor",
                            "The processor must implement save_entity or save_sequence",
                        )

                elif format == "structure":
                    # For structures, parse the data and use processor's save methods
                    try:
                        import pandas as pd

                        # Parse structure data
                        parsed_data = json.loads(data)

                        # Convert to DataFrame if it's a dict/list
                        if isinstance(parsed_data, dict):
                            if "data" in parsed_data:
                                df = pd.DataFrame(parsed_data["data"])
                            else:
                                df = pd.DataFrame([parsed_data])
                        elif isinstance(parsed_data, list):
                            df = pd.DataFrame(parsed_data)
                        else:
                            return self.format_error(
                                "Invalid structure data format",
                                "Provide structure data as JSON object or array",
                            )

                        # Use processor's save_structure method - it handles ALL path management
                        if hasattr(processor, "save_structure"):
                            processor.save_structure(name, df, format="pkl")
                        elif hasattr(processor, "save_entity"):
                            processor.save_entity(name, df, metadata)
                        else:
                            return self.format_error(
                                "Save not implemented for structure processor",
                                "The processor must implement save_structure or save_entity",
                            )
                    except json.JSONDecodeError as e:
                        return self.format_error(
                            f"Invalid JSON data: {e}",
                            "Ensure data is valid JSON format",
                        )
                    except Exception as e:
                        return self.format_error(
                            f"Failed to save structure: {e}",
                            "Check data format and try again",
                        )

                elif format == "grn":
                    # For GRN, save as a table
                    try:
                        parsed_data = (
                            json.loads(data) if isinstance(data, str) else data
                        )

                        # GRN processor expects a DataFrame or Series
                        if isinstance(parsed_data, dict):
                            # Convert dict to Series for single entity
                            import pandas as pd

                            grn_series = pd.Series(parsed_data)
                            processor.save_entity(name, grn_series)
                        else:
                            processor.save_entity(name, parsed_data)
                    except Exception as e:
                        return self.format_error(
                            f"Failed to save GRN data: {e}",
                            "Ensure data is a valid GRN mapping (dict of position -> residue)",
                        )

                elif format == "property":
                    # For properties, use assign_property instead of save_entity
                    try:
                        parsed_data = (
                            json.loads(data) if isinstance(data, str) else data
                        )

                        if isinstance(parsed_data, dict):
                            # Assign each property
                            for prop_name, prop_value in parsed_data.items():
                                processor.assign_property(name, prop_name, prop_value)
                        else:
                            return self.format_error(
                                "Property data must be a dictionary",
                                "Provide properties as {property_name: value}",
                            )
                    except Exception as e:
                        return self.format_error(
                            f"Failed to save properties: {e}",
                            "Check property format and try again",
                        )

                elif format == "molecule":
                    # For ligands, expect ligand-specific data
                    try:
                        parsed_data = (
                            json.loads(data) if isinstance(data, str) else data
                        )
                        processor.save_entity(name, parsed_data, metadata)
                    except Exception as e:
                        return self.format_error(
                            f"Failed to save ligand data: {e}",
                            "Ensure data is valid ligand information",
                        )

                else:
                    # Generic save for other formats
                    if hasattr(processor, "save_entity"):
                        processor.save_entity(name, data, metadata)
                    else:
                        return self.format_error(
                            f"Save not implemented for {format} processor"
                        )

                return self.format_success(
                    {"name": name, "format": format, "status": "saved"},
                    metadata=metadata,
                )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def delete_entity(ctx, name: str, formats: List[str]) -> Dict:
            """
            Delete an entity from specified formats.

            Args:
                name: Entity name
                formats: List of formats to delete from

            Returns:
                Dictionary with deletion status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "formats": formats}, ["name", "formats"]
                ):
                    return error

                if not formats:
                    return self.format_error(
                        "No formats specified",
                        "Provide a list of formats to delete from",
                    )

                # Track results
                results = {}

                for format in formats:
                    try:
                        # Validate processor type
                        if error := self.validate_processor_type(format):
                            results[format] = f"invalid_processor_type"
                            continue

                        processor = self.get_processor(format)

                        if hasattr(processor, "delete_entity"):
                            processor.delete_entity(name)
                            results[format] = "deleted"
                        else:
                            results[format] = "not_implemented"

                    except Exception as e:
                        results[format] = f"error: {str(e)}"

                # Determine overall success
                deleted = [f for f, r in results.items() if r == "deleted"]
                failed = [f for f, r in results.items() if r.startswith("error")]

                if deleted and not failed:
                    return self.format_success(
                        {"name": name, "deleted_from": deleted, "results": results}
                    )
                else:
                    return self.format_error(
                        f"Deletion partially failed",
                        f"Check results for details",
                        error_type="PartialFailure",
                    )

            except Exception as e:
                return self.handle_error(e)
