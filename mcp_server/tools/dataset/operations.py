"""Dataset management tools built on Protos' DatasetManager primitives."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path

import pandas as pd

from ..base import BaseTool
from ...core.exceptions import DatasetNotFoundError


class DatasetOperationTools(BaseTool):
    """Expose dataset CRUD operations backed by BaseProcessor.dataset_manager."""

    def register(self, server):
        @server.tool()
        def create_dataset(
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
            return self.format_success(info, message="Dataset created")

        @server.tool()
        def list_datasets(ctx, processor_type: str) -> Dict[str, Any]:
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
            return self.format_success(info)

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

            entities = manager.get_dataset_entities(name)
            return self.format_success({
                "dataset_name": name,
                "processor_type": processor_type,
                "entities": entities,
            })

        @server.tool()
        def update_dataset(
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
            return self.format_success(info, message="Dataset updated")

        @server.tool()
        def copy_dataset(
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
            return self.format_success(info, message="Dataset copied")

        @server.tool()
        def merge_datasets(
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
            return self.format_success(info, message="Datasets merged")

        @server.tool()
        def refresh_dataset_entities(
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
            return self.format_success(info, message="Dataset entities refreshed")

        @server.tool()
        def refresh_all_datasets(ctx, processor_type: str) -> Dict[str, Any]:
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

        @server.tool()
        def delete_dataset(ctx, name: str, processor_type: str) -> Dict[str, Any]:
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

        @server.tool()
        def load_dataset(
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
