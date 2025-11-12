"""Dataset management tools built on Protos' DatasetManager primitives."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path

import pandas as pd

from ..base import BaseTool
from ...core.exceptions import DatasetNotFoundError


class DatasetOperationTools(BaseTool):
    """Expose dataset CRUD operations backed by BaseProcessor.dataset_manager."""

    _METADATA_ENTITY_KEYS = (
        "sequence_ids",
        "entity_ids",
        "structure_ids",
        "molecule_ids",
        "graph_ids",
        "embedding_ids",
        "ids",
        "names",
    )

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if isinstance(value, bool):  # bool subclasses int; explicitly ignore
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else None
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _iter_candidates(value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, pd.DataFrame):
            return list(value.index)
        if isinstance(value, pd.Series):  # type: ignore[attr-defined]
            return list(value.tolist())
        if isinstance(value, (list, tuple, set)):
            return list(value)
        if isinstance(value, str):
            return [value]
        try:
            return list(value)
        except TypeError:
            return [value]

    @classmethod
    def _normalize_names(cls, value: Any, *, seen: Optional[set[str]] = None) -> List[str]:
        names: List[str] = []
        if seen is None:
            seen = set()

        for item in cls._iter_candidates(value):
            candidate: Optional[str] = None
            if isinstance(item, str):
                candidate = item
            elif isinstance(item, dict):
                for key in ("name", "id", "sequence_id", "entity_id"):
                    raw = item.get(key)
                    if isinstance(raw, str):
                        candidate = raw
                        break
            if not candidate:
                continue
            normalized = candidate.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            names.append(normalized)
        return names

    def _harvest_entity_names(self, info: Dict[str, Any], *, default: Any = None) -> List[str]:
        seen: set[str] = set()
        names: List[str] = []

        if default is not None:
            names.extend(self._normalize_names(default, seen=seen))

        for key in ("entities", "entity_ids"):
            if isinstance(info, dict) and key in info:
                names.extend(self._normalize_names(info.get(key), seen=seen))

        metadata = info.get("metadata") if isinstance(info, dict) else None
        if isinstance(metadata, dict):
            for key in self._METADATA_ENTITY_KEYS:
                if key in metadata:
                    names.extend(self._normalize_names(metadata.get(key), seen=seen))

        return names

    @property
    def catalog_group(self) -> str:  # noqa: D401 - inherited docs adequate
        return "dataset"

    def _record_dataset(
        self,
        *,
        tool_name: str,
        processor_type: str,
        dataset_name: str,
        info: Dict[str, Any],
    ) -> str:
        existing_handle = self._find_dataset_handle(dataset_name, processor_type)
        metadata: Dict[str, Any] = {}
        if isinstance(info, dict):
            raw_metadata = info.get("metadata")
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata

        metadata_keys = sorted(metadata.keys()) if metadata else []

        entity_names = self._harvest_entity_names(info)

        size_value = self._coerce_int(info.get("size") if isinstance(info, dict) else None)
        count_candidates = [
            self._coerce_int(info.get("entity_count") if isinstance(info, dict) else None),
            size_value,
            self._coerce_int(metadata.get("entity_count")),
            self._coerce_int(metadata.get("sequence_count")),
            self._coerce_int(metadata.get("structure_count")),
            self._coerce_int(metadata.get("molecule_count")),
            self._coerce_int(metadata.get("graph_count")),
            self._coerce_int(metadata.get("embedding_count")),
            self._coerce_int(metadata.get("variant_count")),
        ]

        entity_count: Optional[int] = None
        zero_candidate: Optional[int] = None
        for candidate in count_candidates:
            if candidate is None:
                continue
            if candidate > 0:
                entity_count = candidate
                break
            if zero_candidate is None:
                zero_candidate = candidate

        if entity_count is None:
            entity_count = zero_candidate

        if entity_count is None and entity_names:
            entity_count = len(entity_names)
        elif entity_count == 0 and entity_names:
            positive_count = len(entity_names)
            if positive_count:
                entity_count = positive_count

        summary = {
            "dataset": dataset_name,
            "processor_type": processor_type,
            "metadata_keys": metadata_keys,
        }

        if size_value is not None:
            summary["size"] = size_value

        if entity_count is not None:
            summary["entity_count"] = entity_count
            summary["entityCount"] = entity_count
            plural = "entity" if entity_count == 1 else "entities"
            summary["notes"] = f"{entity_count} {plural}"

        if entity_names:
            preview = entity_names[:10]
            summary["entity_preview"] = preview
            summary["entityPreview"] = preview

        materialized = metadata.get("materialized")
        if isinstance(materialized, bool):
            summary["materialized"] = materialized

        description = metadata.get("description")
        if (
            summary.get("notes") is None
            and isinstance(description, str)
            and description.strip()
        ):
            summary["notes"] = description.strip()

        tags = [processor_type, "dataset", "manager"]
        scope = f"{processor_type}.dataset"
        return self.record_session_artifact(
            tool_name=tool_name,
            name=dataset_name,
            kind="dataset",
            processor_type=processor_type,
            summary=summary,
            tags=tags,
            scope=scope,
            handle=existing_handle,
        )

    def _find_dataset_handle(self, dataset_name: str, processor_type: str) -> Optional[str]:
        for artifact in self.session.iter_artifacts(kind="dataset", processor_type=processor_type):
            if artifact.name == dataset_name:
                return artifact.handle
        return None

    def register(self, server):
        @server.tool()
        def dataset_create(
            ctx,
            name: str,
            entities: List[str],
            processor_type: str,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Create a dataset from registered entity names."""

            if error := self.validate_required_params(
                {"name": name, "entities": entities, "processor_type": processor_type},
                ["name", "entities", "processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support (structure, sequence, grn, ...).",
                )

            missing = [entity for entity in entities if not processor.entity_exists(entity)]
            if missing:
                return self.format_error(
                    "Some entities are not registered",
                    f"Register entities first: {', '.join(missing)}",
                )

            manager.create_dataset(name, entities, metadata or {})
            info = manager.get_dataset_info(name)
            handle = self._record_dataset(
                tool_name="dataset_create",
                processor_type=processor_type,
                dataset_name=name,
                info=info,
            )
            payload = dict(info)
            payload["context_handle"] = handle
            return self.format_success(payload, message="Dataset created")
        self.register_tool_metadata(
            function=dataset_create,
            name="dataset_create",
            description="Create a dataset from registered entity names.",
            parameters=[
                {"name": "name", "type": "str"},
                {"name": "entities", "type": "list[str]"},
                {"name": "processor_type", "type": "str"},
            ],
            returns={"fields": ["context_handle", "metadata"]},
            tags=["dataset", "create"],
        )

        @server.tool()
        def create_dataset(
            ctx,
            name: str,
            entities: List[str],
            processor_type: str,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Deprecated alias for dataset_create."""

            return dataset_create(
                ctx,
                name=name,
                entities=entities,
                processor_type=processor_type,
                metadata=metadata,
            )

        self.tool_catalog.alias(
            "create_dataset",
            "dataset_create",
            note="Legacy alias; prefer dataset_create",
        )

        @server.tool()
        def dataset_list(ctx, processor_type: str) -> Dict[str, Any]:
            """List datasets known to a processor."""

            if error := self.validate_required_params(
                {"processor_type": processor_type}, ["processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            datasets = manager.list_datasets()
            return self.format_success({
                "processor_type": processor_type,
                "count": len(datasets),
                "datasets": datasets,
            })

        self.register_tool_metadata(
            function=dataset_list,
            name="dataset_list",
            description="List datasets known to a processor.",
            parameters=[{"name": "processor_type", "type": "str"}],
            returns={"fields": ["datasets"]},
            tags=["dataset", "list"],
        )

        @server.tool()
        def list_datasets(ctx, processor_type: str) -> Dict[str, Any]:
            """Deprecated alias for dataset_list."""

            return dataset_list(ctx, processor_type)

        self.tool_catalog.alias(
            "list_datasets",
            "dataset_list",
            note="Legacy alias; prefer dataset_list",
        )

        @server.tool()
        def dataset_info(ctx, name: str, processor_type: str) -> Dict[str, Any]:
            """Return metadata and current entity coverage for a dataset."""

            if error := self.validate_required_params(
                {"name": name, "processor_type": processor_type}, ["name", "processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            if not manager.dataset_exists(name):
                raise DatasetNotFoundError(name, processor_type)

            info = manager.get_dataset_info(name)
            handle = self._record_dataset(
                tool_name="dataset_info",
                processor_type=processor_type,
                dataset_name=name,
                info=info,
            )
            payload = dict(info)
            payload["context_handle"] = handle
            return self.format_success(payload)
        self.register_tool_metadata(
            function=dataset_info,
            name="dataset_info",
            description="Return metadata and current entity coverage for a dataset.",
            parameters=[
                {"name": "name", "type": "str"},
                {"name": "processor_type", "type": "str"},
            ],
            returns={"fields": ["metadata", "context_handle"]},
            tags=["dataset", "inspect"],
        )

        @server.tool()
        def dataset_entities(ctx, name: str, processor_type: str) -> Dict[str, Any]:
            """Return the entity names associated with a dataset."""

            if error := self.validate_required_params(
                {"name": name, "processor_type": processor_type}, ["name", "processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            if not manager.dataset_exists(name):
                raise DatasetNotFoundError(name, processor_type)

            raw_entities = manager.get_dataset_entities(name)

            entity_list: List[str]
            if isinstance(raw_entities, pd.DataFrame):
                entity_list = [str(index) for index in raw_entities.index]
            else:
                entity_list = [str(value) for value in self._iter_candidates(raw_entities)]

            info = manager.get_dataset_info(name)
            if isinstance(info, dict):
                info = dict(info)
                info["entities"] = entity_list

            if not entity_list and isinstance(info, dict):
                entity_list = self._harvest_entity_names(info)
                info["entities"] = entity_list

            handle = self._record_dataset(
                tool_name="dataset_entities",
                processor_type=processor_type,
                dataset_name=name,
                info=info if isinstance(info, dict) else {"entities": entity_list},
            )

            entity_count = len(entity_list)

            return self.format_success({
                "dataset_name": name,
                "processor_type": processor_type,
                "entities": entity_list,
                "entity_count": entity_count,
                "context_handle": handle,
            })

        self.register_tool_metadata(
            function=dataset_entities,
            name="dataset_entities",
            description="Return the entity names associated with a dataset.",
            parameters=[
                {"name": "name", "type": "str"},
                {"name": "processor_type", "type": "str"},
            ],
            returns={"fields": ["entities"]},
            tags=["dataset", "inspect"],
        )

        @server.tool()
        def dataset_update(
            ctx,
            name: str,
            processor_type: str,
            add_entities: Optional[List[str]] = None,
            remove_entities: Optional[List[str]] = None,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Add/remove entities and/or merge metadata into an existing dataset."""

            if error := self.validate_required_params(
                {"name": name, "processor_type": processor_type}, ["name", "processor_type"],
            ):
                return error

            if not any([add_entities, remove_entities, metadata]):
                return self.format_error(
                    "No updates specified",
                    "Provide entities to add/remove or metadata to merge.",
                )

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            if not manager.dataset_exists(name):
                raise DatasetNotFoundError(name, processor_type)

            if add_entities:
                missing = [entity for entity in add_entities if not processor.entity_exists(entity)]
                if missing:
                    return self.format_error(
                        "Some entities are not registered",
                        f"Register entities first: {', '.join(missing)}",
                    )
                manager.add_to_dataset(name, add_entities)

            if remove_entities:
                manager.remove_from_dataset(name, remove_entities)

            if metadata:
                manager.update_metadata(name, metadata)

            info = manager.get_dataset_info(name)
            handle = self._record_dataset(
                tool_name="dataset_update",
                processor_type=processor_type,
                dataset_name=name,
                info=info,
            )
            payload = dict(info)
            payload["context_handle"] = handle
            return self.format_success(payload, message="Dataset updated")
        self.register_tool_metadata(
            function=dataset_update,
            name="dataset_update",
            description="Add/remove entities or metadata for an existing dataset.",
            parameters=[
                {"name": "name", "type": "str"},
                {"name": "processor_type", "type": "str"},
                {"name": "add_entities", "type": "list[str]", "optional": True},
                {"name": "remove_entities", "type": "list[str]", "optional": True},
            ],
            returns={"fields": ["context_handle"]},
            tags=["dataset", "update"],
        )

        @server.tool()
        def update_dataset(
            ctx,
            name: str,
            processor_type: str,
            add_entities: Optional[List[str]] = None,
            remove_entities: Optional[List[str]] = None,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Deprecated alias for dataset_update."""

            return dataset_update(
                ctx,
                name=name,
                processor_type=processor_type,
                add_entities=add_entities,
                remove_entities=remove_entities,
                metadata=metadata,
            )

        self.tool_catalog.alias(
            "update_dataset",
            "dataset_update",
            note="Legacy alias; prefer dataset_update",
        )

        @server.tool()
        def dataset_copy(
            ctx,
            source_name: str,
            target_name: str,
            processor_type: str,
            overwrite: bool = False,
        ) -> Dict[str, Any]:
            """Copy a dataset to a new name using `DatasetManager.copy_dataset`."""

            if error := self.validate_required_params(
                {"source_name": source_name, "target_name": target_name, "processor_type": processor_type},
                ["source_name", "target_name", "processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            if not manager.dataset_exists(source_name):
                return self.format_error(
                    f"Source dataset '{source_name}' does not exist",
                    "Use list_datasets to view available datasets.",
                )

            if manager.dataset_exists(target_name):
                if not overwrite:
                    return self.format_error(
                        f"Dataset '{target_name}' already exists",
                        "Set overwrite=true to replace the existing dataset.",
                    )
                manager.delete_dataset(target_name)

            manager.copy_dataset(source_name, target_name)
            info = manager.get_dataset_info(target_name)
            handle = self._record_dataset(
                tool_name="dataset_copy",
                processor_type=processor_type,
                dataset_name=target_name,
                info=info,
            )
            payload = dict(info)
            payload["context_handle"] = handle
            return self.format_success(payload, message="Dataset copied")
        self.register_tool_metadata(
            function=dataset_copy,
            name="dataset_copy",
            description="Copy a dataset to a new name using DatasetManager.copy_dataset.",
            parameters=[
                {"name": "source_name", "type": "str"},
                {"name": "target_name", "type": "str"},
                {"name": "processor_type", "type": "str"},
                {"name": "overwrite", "type": "bool", "default": False},
            ],
            returns={"fields": ["context_handle"]},
            tags=["dataset", "copy"],
        )

        @server.tool()
        def copy_dataset(
            ctx,
            source_name: str,
            target_name: str,
            processor_type: str,
            overwrite: bool = False,
        ) -> Dict[str, Any]:
            """Deprecated alias for dataset_copy."""

            return dataset_copy(
                ctx,
                source_name=source_name,
                target_name=target_name,
                processor_type=processor_type,
                overwrite=overwrite,
            )

        self.tool_catalog.alias(
            "copy_dataset",
            "dataset_copy",
            note="Legacy alias; prefer dataset_copy",
        )

        @server.tool()
        def dataset_merge(
            ctx,
            dataset_names: List[str],
            target_name: str,
            processor_type: str,
            overwrite: bool = False,
        ) -> Dict[str, Any]:
            """Merge multiple datasets into a single dataset using `DatasetManager.merge_datasets`."""

            if error := self.validate_required_params(
                {"dataset_names": dataset_names, "target_name": target_name, "processor_type": processor_type},
                ["dataset_names", "target_name", "processor_type"],
            ):
                return error

            if not dataset_names:
                return self.format_error(
                    "No source datasets provided",
                    "Provide one or more dataset names to merge.",
                )

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            missing = [name for name in dataset_names if not manager.dataset_exists(name)]
            if missing:
                return self.format_error(
                    "Some source datasets are missing",
                    f"Missing datasets: {', '.join(missing)}",
                )

            if manager.dataset_exists(target_name):
                if not overwrite:
                    return self.format_error(
                        f"Dataset '{target_name}' already exists",
                        "Set overwrite=true to replace the existing dataset.",
                    )
                manager.delete_dataset(target_name)

            manager.merge_datasets(dataset_names, target_name)
            info = manager.get_dataset_info(target_name)
            handle = self._record_dataset(
                tool_name="dataset_merge",
                processor_type=processor_type,
                dataset_name=target_name,
                info=info,
            )
            payload = dict(info)
            payload["context_handle"] = handle
            return self.format_success(payload, message="Datasets merged")
        self.register_tool_metadata(
            function=dataset_merge,
            name="dataset_merge",
            description="Merge multiple datasets into a single dataset.",
            parameters=[
                {"name": "dataset_names", "type": "list[str]"},
                {"name": "target_name", "type": "str"},
                {"name": "processor_type", "type": "str"},
            ],
            returns={"fields": ["context_handle"]},
            tags=["dataset", "merge"],
        )

        @server.tool()
        def merge_datasets(
            ctx,
            dataset_names: List[str],
            target_name: str,
            processor_type: str,
            overwrite: bool = False,
        ) -> Dict[str, Any]:
            """Deprecated alias for dataset_merge."""

            return dataset_merge(
                ctx,
                dataset_names=dataset_names,
                target_name=target_name,
                processor_type=processor_type,
                overwrite=overwrite,
            )

        self.tool_catalog.alias(
            "merge_datasets",
            "dataset_merge",
            note="Legacy alias; prefer dataset_merge",
        )

        @server.tool()
        def dataset_refresh_entities(
            ctx,
            name: str,
            processor_type: str,
        ) -> Dict[str, Any]:
            """Refresh entity names in a dataset using `DatasetManager.refresh_dataset_entities`."""

            if error := self.validate_required_params(
                {"name": name, "processor_type": processor_type},
                ["name", "processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            if not manager.dataset_exists(name):
                return self.format_error(
                    f"Dataset '{name}' does not exist",
                    "Use list_datasets to view available datasets.",
                )

            manager.refresh_dataset_entities(name)
            info = manager.get_dataset_info(name)
            handle = self._record_dataset(
                tool_name="dataset_refresh_entities",
                processor_type=processor_type,
                dataset_name=name,
                info=info,
            )
            payload = dict(info)
            payload["context_handle"] = handle
            return self.format_success(payload, message="Dataset entities refreshed")
        self.register_tool_metadata(
            function=dataset_refresh_entities,
            name="dataset_refresh_entities",
            description="Refresh entity names in a dataset via DatasetManager.refresh_dataset_entities.",
            parameters=[
                {"name": "name", "type": "str"},
                {"name": "processor_type", "type": "str"},
            ],
            returns={"fields": ["context_handle"]},
            tags=["dataset", "refresh"],
        )

        @server.tool()
        def refresh_dataset_entities(
            ctx,
            name: str,
            processor_type: str,
        ) -> Dict[str, Any]:
            """Deprecated alias for dataset_refresh_entities."""

            return dataset_refresh_entities(ctx, name, processor_type)

        self.tool_catalog.alias(
            "refresh_dataset_entities",
            "dataset_refresh_entities",
            note="Legacy alias; prefer dataset_refresh_entities",
        )

        @server.tool()
        def dataset_refresh_all(ctx, processor_type: str) -> Dict[str, Any]:
            """Refresh entity names for all datasets of a processor."""

            if error := self.validate_required_params(
                {"processor_type": processor_type}, ["processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            manager.refresh_all_datasets()
            datasets = manager.list_datasets()
            return self.format_success(
                {
                    "processor_type": processor_type,
                    "dataset_count": len(datasets),
                    "datasets": datasets,
                },
                message="All datasets refreshed",
            )

        self.register_tool_metadata(
            function=dataset_refresh_all,
            name="dataset_refresh_all",
            description="Refresh entity names for all datasets of a processor.",
            parameters=[{"name": "processor_type", "type": "str"}],
            returns={"fields": ["dataset_count", "datasets"]},
            tags=["dataset", "refresh"],
        )

        @server.tool()
        def refresh_all_datasets(ctx, processor_type: str) -> Dict[str, Any]:
            """Deprecated alias for dataset_refresh_all."""

            return dataset_refresh_all(ctx, processor_type)

        self.tool_catalog.alias(
            "refresh_all_datasets",
            "dataset_refresh_all",
            note="Legacy alias; prefer dataset_refresh_all",
        )

        @server.tool()
        def dataset_export(
            ctx,
            dataset_name: str,
            processor_type: str,
            output_dir: Optional[str] = None,
            format: Optional[str] = None,
            overwrite: bool = False,
            name_pattern: Optional[str] = None,
            extra_options: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Export a dataset using the processor's `export_dataset` helper."""

            if error := self.validate_required_params(
                {"dataset_name": dataset_name, "processor_type": processor_type},
                ["dataset_name", "processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            export_func = getattr(processor, "export_dataset", None)
            if export_func is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not provide export_dataset",
                    "Export is only available for processors with dataset exporters.",
                )

            manager = getattr(processor, "dataset_manager", None)
            if manager is None or not manager.dataset_exists(dataset_name):
                return self.format_error(
                    f"Dataset '{dataset_name}' does not exist",
                    "Use list_datasets to confirm the dataset name before exporting.",
                )

            if output_dir:
                export_dir = Path(output_dir)
                export_dir.mkdir(parents=True, exist_ok=True)
            else:
                default_export_dir = Path(self.paths.get_processor_path(processor_type)) / "exports"
                default_export_dir.mkdir(parents=True, exist_ok=True)
                export_dir = default_export_dir

            call_kwargs: Dict[str, Any] = {
                "output_dir": export_dir,
                "overwrite": overwrite,
            }
            if format is not None:
                call_kwargs["format"] = format
            if name_pattern is not None:
                call_kwargs["name_pattern"] = name_pattern
            if extra_options:
                call_kwargs.update(extra_options)

            try:
                exported = export_func(dataset_name, **call_kwargs)
            except TypeError as exc:
                return self.format_error(
                    f"Exporter rejected arguments: {exc}",
                    "Adjust export parameters or provide them via extra_options.",
                )

            if isinstance(exported, dict):
                exported_map = {key: str(value) for key, value in exported.items()}
            else:
                exported_map = str(exported)

            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "processor_type": processor_type,
                    "output_dir": str(export_dir),
                    "exported": exported_map,
                },
                message="Dataset exported",
            )

        self.register_tool_metadata(
            function=dataset_export,
            name="dataset_export",
            description="Export a dataset using the processor's export_dataset helper.",
            parameters=[
                {"name": "dataset_name", "type": "str"},
                {"name": "processor_type", "type": "str"},
                {"name": "output_dir", "type": "str", "optional": True},
                {"name": "format", "type": "str", "optional": True},
            ],
            tags=["dataset", "export"],
        )

        @server.tool()
        def export_dataset(
            ctx,
            dataset_name: str,
            processor_type: str,
            output_dir: Optional[str] = None,
            format: Optional[str] = None,
            overwrite: bool = False,
            name_pattern: Optional[str] = None,
            extra_options: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Deprecated alias for dataset_export."""

            return dataset_export(
                ctx,
                dataset_name=dataset_name,
                processor_type=processor_type,
                output_dir=output_dir,
                format=format,
                overwrite=overwrite,
                name_pattern=name_pattern,
                extra_options=extra_options,
            )

        self.tool_catalog.alias(
            "export_dataset",
            "dataset_export",
            note="Legacy alias; prefer dataset_export",
        )

        @server.tool()
        def dataset_delete(ctx, name: str, processor_type: str) -> Dict[str, Any]:
            """Delete a dataset definition."""

            if error := self.validate_required_params(
                {"name": name, "processor_type": processor_type}, ["name", "processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            if not manager.dataset_exists(name):
                raise DatasetNotFoundError(name, processor_type)

            manager.delete_dataset(name)
            return self.format_success({
                "dataset_name": name,
                "processor_type": processor_type,
            }, message="Dataset deleted")

        self.register_tool_metadata(
            function=dataset_delete,
            name="dataset_delete",
            description="Delete a dataset definition from the registry.",
            parameters=[
                {"name": "name", "type": "str"},
                {"name": "processor_type", "type": "str"},
            ],
            tags=["dataset", "delete"],
        )

        @server.tool()
        def delete_dataset(ctx, name: str, processor_type: str) -> Dict[str, Any]:
            """Deprecated alias for dataset_delete."""

            return dataset_delete(ctx, name, processor_type)

        self.tool_catalog.alias(
            "delete_dataset",
            "dataset_delete",
            note="Legacy alias; prefer dataset_delete",
        )

        @server.tool()
        def dataset_load(
            ctx,
            name: str,
            processor_type: str,
            summary_only: bool = True,
        ) -> Dict[str, Any]:
            """Load dataset members via the processor for quick inspection."""

            if error := self.validate_required_params(
                {"name": name, "processor_type": processor_type}, ["name", "processor_type"],
            ):
                return error

            if error := self.validate_processor_type(processor_type):
                return error

            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return self.format_error(
                    f"Processor '{processor_type}' does not support datasets",
                    "Choose a processor with dataset support.",
                )

            if not manager.dataset_exists(name):
                raise DatasetNotFoundError(name, processor_type)

            try:
                data = processor.load_dataset(name)
            except FileNotFoundError:
                raise DatasetNotFoundError(name, processor_type)
            except Exception as exc:  # noqa: BLE001
                return self.format_error(
                    f"Failed to load dataset '{name}': {exc}",
                    "Ensure all referenced entities are downloaded and registered.",
                )

            if summary_only:
                entity_names = manager.get_dataset_entities(name)
                count = len(entity_names)
                summary: Dict[str, Any] = {
                    "dataset_name": name,
                    "processor_type": processor_type,
                    "entity_count": count,
                }
                if isinstance(data, pd.DataFrame):
                    summary.update({
                        "rows": int(data.shape[0]),
                        "columns": list(map(str, data.columns[:10])),
                    })
                elif isinstance(data, dict):
                    summary.update({"preview_keys": list(list(data.keys())[:10])})
                return self.format_success(summary)

            serializable: Any
            if isinstance(data, pd.DataFrame):
                serializable = data.to_dict(orient="records")
            elif isinstance(data, dict):
                serializable = data
            else:
                serializable = str(data)

            return self.format_success({
                "dataset_name": name,
                "processor_type": processor_type,
                "data": serializable,
            })

        self.register_tool_metadata(
            function=dataset_load,
            name="dataset_load",
            description="Load dataset members via the processor for quick inspection.",
            parameters=[
                {"name": "name", "type": "str"},
                {"name": "processor_type", "type": "str"},
                {"name": "summary_only", "type": "bool", "default": True},
            ],
            tags=["dataset", "load"],
        )

        @server.tool()
        def load_dataset(
            ctx,
            name: str,
            processor_type: str,
            summary_only: bool = True,
        ) -> Dict[str, Any]:
            """Deprecated alias for dataset_load."""

            return dataset_load(ctx, name, processor_type, summary_only)

        self.tool_catalog.alias(
            "load_dataset",
            "dataset_load",
            note="Legacy alias; prefer dataset_load",
        )

        @server.tool()
        def register_gpcr_sequence_dataset(ctx) -> Dict[str, Any]:
            """Install the packaged GPCR agonist/antagonist sequence dataset."""

            dataset_name = _register_gpcr_sequence_dataset()
            processor = self.get_processor("sequence")
            manager = processor.dataset_manager
            info = manager.get_dataset_info(dataset_name) or {}
            entities = manager.get_dataset_entities(dataset_name)

            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "processor_type": "sequence",
                    "entity_count": len(entities),
                    "metadata": info.get("metadata", {}),
                },
                message="GPCR sequence dataset registered",
            )

        @server.tool()
        def register_rhodopsin_structure_dataset(ctx) -> Dict[str, Any]:
            """Install the packaged rhodopsin state structure dataset."""

            dataset_name = _register_rhodopsin_structure_dataset()
            processor = self.get_processor("structure")
            manager = processor.dataset_manager
            info = manager.get_dataset_info(dataset_name) or {}
            entities = manager.get_dataset_entities(dataset_name)

            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "processor_type": "structure",
                    "entity_count": len(entities),
                    "metadata": info.get("metadata", {}),
                },
                message="Rhodopsin structure dataset registered",
            )

        @server.tool()
        def register_chembl_ligand_dataset(ctx) -> Dict[str, Any]:
            """Install the packaged ChEMBL ligand reference dataset."""

            dataset_name = _register_chembl_ligand_dataset()
            processor = self.get_processor("molecule")
            manager = processor.dataset_manager

            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "processor_type": "molecule",
                    "available_datasets": manager.list_datasets(),
                },
                message="ChEMBL ligand dataset registered",
            )

        @server.tool()
        def register_gpcr_property_dataset(ctx) -> Dict[str, Any]:
            """Install the packaged GPCR ligand-binding property dataset."""

            dataset_name = _register_gpcr_property_dataset()
            processor = self.get_processor("property")
            manager = processor.dataset_manager
            info = manager.get_dataset_info(dataset_name) or {}
            entities = manager.get_dataset_entities(dataset_name)

            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "processor_type": "property",
                    "entity_count": len(entities),
                    "metadata": info.get("metadata", {}),
                },
                message="GPCR property dataset registered",
            )

        @server.tool()
        def register_rhodopsin_graph_dataset(ctx) -> Dict[str, Any]:
            """Install the packaged rhodopsin residue graph dataset."""

            dataset_name = _register_rhodopsin_graph_dataset()
            processor = self.get_processor("graph")
            manager = processor.dataset_manager
            info = manager.get_dataset_info(dataset_name) or {}
            entities = manager.get_dataset_entities(dataset_name)

            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "processor_type": "graph",
                    "entity_count": len(entities),
                    "metadata": info.get("metadata", {}),
                },
                message="Rhodopsin graph dataset registered",
            )
