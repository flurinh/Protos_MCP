"""
Structure analysis tools for analyzing protein structures.

These tools provide analysis capabilities for structural data including
sequence extraction, chain analysis, coordinate extraction, and ligand analysis.
"""

from typing import Dict, List, Optional, Any, Union, Tuple
from functools import reduce
from datetime import datetime
from pathlib import Path
import math
import pandas as pd
import numpy as np

from ..base import BaseTool
from ...core.context_preview import PreviewLimits, build_dataframe_preview
from ...core.exceptions import InvalidInputError, EntityNotFoundError
from protos.analysis.structure_water_networks import summarize_water_networks
from protos.analysis.structure_embedding_similarity import (
    ChainSelection,
    compute_structure_embedding_similarity,
)


STRUCTURE_PREVIEW_LIMITS = PreviewLimits()


class StructureAnalysisTools(BaseTool):
    """Tools for structure analysis and manipulation."""
    
    @staticmethod
    def _normalize_structure_id(structure_id: str) -> str:
        return structure_id.lower().strip()

    def _apply_grn_annotations(
        self,
        *,
        grn_table: str,
        structures: List[str],
        column_name: str = "grn",
        save_entities: bool = True,
    ) -> Dict[str, Any]:
        struct_proc = self.get_processor("structure")
        grn_proc = self.get_processor("grn")
        normalized_structures = [self._normalize_structure_id(s) for s in structures]
        table = grn_proc.load_table(grn_table).fillna("-")

        annotation_counts: Dict[str, Dict[str, int]] = {}
        skipped: Dict[str, str] = {}

        for structure_id in normalized_structures:
            frame = struct_proc.load_entity(structure_id)
            if frame is None:
                skipped[structure_id] = "structure_not_found"
                continue

            reset = frame.reset_index()
            if column_name not in reset.columns:
                reset[column_name] = "-"
            else:
                reset[column_name] = reset[column_name].fillna("-")

            chains = reset.get("auth_chain_id")
            if chains is None:
                skipped[structure_id] = "missing_chain_column"
                continue

            chain_stats: Dict[str, int] = {}
            for chain_id in chains.dropna().unique().tolist():
                seq_name = f"{structure_id}_chain_{chain_id}"
                if seq_name not in table.index:
                    skipped[seq_name] = "sequence_not_in_grn_table"
                    continue

                row = table.loc[seq_name]
                seq_pos_to_grn: Dict[int, str] = {}
                for grn_pos, value in row.items():
                    if not isinstance(value, str) or value.strip() in {"", "-"}:
                        continue
                    digits = "".join(filter(str.isdigit, value))
                    if not digits:
                        continue
                    seq_pos = int(digits)
                    if seq_pos > 0:
                        seq_pos_to_grn[seq_pos] = grn_pos

                chain_df = reset[reset["auth_chain_id"] == chain_id].copy()
                chain_df[column_name] = chain_df[column_name].fillna("-")

                residue_positions = (
                    chain_df.groupby(["auth_seq_id", "insertion"]).first().reset_index()
                )

                assigned = 0
                for _, residue in residue_positions.iterrows():
                    seq_pos = residue["auth_seq_id"]
                    grn_label = seq_pos_to_grn.get(int(seq_pos), "-")
                    mask = (
                        (chain_df["auth_seq_id"] == seq_pos)
                        & (chain_df["insertion"] == residue["insertion"])
                    )
                    chain_df.loc[mask, column_name] = grn_label
                    if grn_label != "-":
                        assigned += 1

                reset.loc[chain_df.index, column_name] = chain_df[column_name]
                chain_stats[chain_id] = assigned

            annotation_counts[structure_id] = chain_stats

            if save_entities:
                struct_proc.save_entity(structure_id, reset)

        return {
            "grn_table": grn_table,
            "structures": normalized_structures,
            "column": column_name,
            "annotation_counts": annotation_counts,
            "skipped": skipped,
            "saved": save_entities,
        }

    def _ensure_structures_loaded(self, processor, structure_ids: Union[str, List[str]]) -> None:
        """Load structures via the processor's load_entity API."""

        if isinstance(structure_ids, str):
            structure_ids = [structure_ids]
        for structure_id in structure_ids:
            processor.load_entity(structure_id)

    def register(self, server):
        """Register structure analysis tools with the server."""

        @server.tool()
        def list_structure_entities(ctx, limit: Optional[int] = None, offset: int = 0) -> Dict:
            """List registered structure entities with optional pagination."""

            try:
                processor = self.get_processor("structure")
                entities = processor.list_entities()
                total = len(entities)
                start = max(offset, 0)
                end = start + limit if limit else total
                sliced = entities[start:end]

                return self.format_success(
                    {
                        "total": total,
                        "offset": start,
                        "count": len(sliced),
                        "entities": sliced,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def load_structure(
            ctx,
            structure_id: str,
            include_atoms: bool = False,
            max_atoms: int = 2000,
        ) -> Dict:
            """Load a structure entity and return summary details."""

            try:
                if error := self.validate_required_params(
                    {"structure_id": structure_id},
                    ["structure_id"],
                ):
                    return error

                processor = self.get_processor("structure")
                df = processor.load_entity(structure_id)
                if df is None:
                    return self.format_error(
                        f"Structure '{structure_id}' not found",
                        "Use download_entity or download_entities first.",
                    )

                reset = df.reset_index()
                atom_count = len(reset)
                chains = (
                    reset["auth_chain_id"].value_counts(dropna=True).to_dict()
                    if "auth_chain_id" in reset
                    else {}
                )

                payload: Dict[str, Any] = {
                    "structure_id": structure_id,
                    "atom_count": atom_count,
                    "columns": list(reset.columns),
                    "chains": chains,
                }

                if include_atoms:
                    safe_limit = max(25, min(max_atoms, STRUCTURE_PREVIEW_LIMITS.max_rows))
                    preview_model = build_dataframe_preview(
                        reset,
                        limits=STRUCTURE_PREVIEW_LIMITS.override(max_rows=safe_limit),
                        label=structure_id,
                    )
                    payload["atom_preview"] = preview_model.export()

                return self.format_success(payload)
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def load_structure_dataset(
            ctx,
            dataset_name: str,
            include_entities: bool = False,
            include_summaries: bool = False,
            max_entities: int = 50,
        ) -> Dict:
            """Load a structure dataset and summarize its members."""

            try:
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name},
                    ["dataset_name"],
                ):
                    return error

                processor = self.get_processor("structure")
                manager = processor.dataset_manager
                if not manager.dataset_exists(dataset_name):
                    return self.format_error(
                        f"Structure dataset '{dataset_name}' not found",
                        "Use dataset.list_datasets or download_entities to populate it.",
                    )

                entities = manager.get_dataset_entities(dataset_name)
                info = manager.get_dataset_info(dataset_name)

                payload: Dict[str, Any] = {
                    "dataset_name": dataset_name,
                    "entity_count": len(entities),
                    "metadata": info.get("metadata", {}),
                }

                if include_entities:
                    payload["entities"] = entities[:max_entities]
                    payload["truncated"] = len(entities) > len(payload["entities"])

                if include_summaries:
                    dataset = processor.load_dataset(dataset_name, return_format="dict")
                    summaries: List[Dict[str, Any]] = []
                    for structure_id, frame in list(dataset.items())[:max_entities]:
                        reset = frame.reset_index()
                        summaries.append(
                            {
                                "structure_id": structure_id,
                                "atom_count": len(reset),
                                "chains": reset["auth_chain_id"].value_counts(dropna=True).to_dict()
                                if "auth_chain_id" in reset
                                else {},
                            }
                        )
                    payload["summaries"] = summaries
                    payload["summaries_truncated"] = len(entities) > len(summaries)

                return self.format_success(payload)
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def structure_filter_entities(
            ctx,
            structure_ids: Union[str, List[str]],
            filters: List[Dict[str, Any]],
            combine: str = "and",
            include_columns: Optional[List[str]] = None,
            save_as: Optional[str] = None,
            create_dataset: Optional[str] = None,
            overwrite_dataset: bool = False,
            drop_empty: bool = True,
            return_preview: bool = True,
            preview_limit: int = 20,
        ) -> Dict:
            """Filter structure entities using column-wise predicates."""

            try:
                if isinstance(structure_ids, str):
                    target_structures = [structure_ids]
                else:
                    target_structures = list(structure_ids)

                if not target_structures:
                    return self.format_error(
                        "No structures provided",
                        "Pass one or more structure identifiers to filter.",
                    )

                if not filters:
                    return self.format_error(
                        "No filters specified",
                        "Provide at least one filter with a column and operator.",
                    )

                combine_mode = (combine or "and").lower()
                if combine_mode not in {"and", "or"}:
                    return self.format_error(
                        "Unsupported combine mode",
                        "Choose 'and' or 'or' for filter combination.",
                    )

                processor = self.get_processor("structure")

                saved_entities: List[str] = []
                dataset_entities: List[str] = []
                results: List[Dict[str, Any]] = []
                errors: Dict[str, str] = {}

                def build_condition(df: pd.DataFrame, predicate: Dict[str, Any]) -> pd.Series:
                    column = predicate.get("column")
                    if not column or column not in df.columns:
                        raise InvalidInputError(
                            "column",
                            f"Column '{column}' not found in structure frame."
                            if column
                            else "Filter predicate missing column",
                        )

                    series = df[column]
                    op = (predicate.get("op") or "eq").lower()
                    value = predicate.get("value")
                    values = predicate.get("values")
                    case_sensitive = predicate.get("case_sensitive", False)

                    if op in {"eq", "=="}:
                        return series == value
                    if op in {"ne", "!="}:
                        return series != value
                    if op in {"lt", "<"}:
                        return series < value
                    if op in {"le", "<="}:
                        return series <= value
                    if op in {"gt", ">"}:
                        return series > value
                    if op in {"ge", ">="}:
                        return series >= value
                    if op in {"in", "isin"}:
                        if values is None:
                            raise InvalidInputError("values", "Provide a 'values' list for 'in' operator")
                        return series.isin(values)
                    if op in {"not_in", "notin", "not in"}:
                        if values is None:
                            raise InvalidInputError("values", "Provide a 'values' list for 'not_in' operator")
                        return ~series.isin(values)
                    if op in {"contains", "icontains"}:
                        if value is None:
                            raise InvalidInputError("value", "'contains' operator requires a value")
                        target = series.astype(str)
                        return target.str.contains(
                            str(value),
                            case=case_sensitive,
                            na=False,
                        )
                    if op == "regex":
                        if value is None:
                            raise InvalidInputError("value", "'regex' operator requires a pattern")
                        target = series.astype(str)
                        return target.str.contains(
                            str(value),
                            regex=True,
                            case=case_sensitive,
                            na=False,
                        )
                    if op == "between":
                        lower = predicate.get("lower")
                        upper = predicate.get("upper")
                        if lower is None or upper is None:
                            raise InvalidInputError(
                                "between",
                                "'between' operator requires 'lower' and 'upper' bounds",
                            )
                        return series.between(lower, upper)

                    raise InvalidInputError("op", f"Unsupported operator '{op}'")

                for structure_id in target_structures:
                    df = processor.load_entity(structure_id)
                    if df is None:
                        errors[structure_id] = "structure_not_found"
                        continue

                    masks: List[pd.Series] = []
                    for predicate in filters:
                        try:
                            condition = build_condition(df, predicate)
                            masks.append(condition)
                        except InvalidInputError as exc:
                            return self.handle_error(exc)

                    if not masks:
                        filtered_df = df
                    else:
                        if combine_mode == "and":
                            combined_mask = reduce(lambda a, b: a & b, masks)
                        else:
                            combined_mask = reduce(lambda a, b: a | b, masks)
                        filtered_df = df[combined_mask]

                    original_rows = len(df)
                    filtered_rows = len(filtered_df)

                    if drop_empty and filtered_rows == 0:
                        results.append(
                            {
                                "structure_id": structure_id,
                                "original_rows": original_rows,
                                "filtered_rows": filtered_rows,
                                "saved_entity": None,
                                "preview": [],
                            }
                        )
                        continue

                    if include_columns:
                        missing_columns = [col for col in include_columns if col not in filtered_df.columns]
                        if missing_columns:
                            return self.format_error(
                                "Columns missing in filtered frame",
                                f"Columns not found: {', '.join(missing_columns)}",
                            )
                        preview_frame = filtered_df[include_columns]
                    else:
                        preview_frame = filtered_df

                    saved_entity = None
                    if save_as:
                        target_id = save_as
                        if "{structure_id}" in save_as:
                            target_id = save_as.format(structure_id=structure_id)
                        metadata = {
                            "source": "structure_filter_entities",
                            "filters": filters,
                            "combine": combine_mode,
                        }
                        processor.save_entity(target_id, filtered_df, metadata=metadata)
                        saved_entity = target_id
                        saved_entities.append(target_id)
                        dataset_entities.append(target_id)
                    else:
                        dataset_entities.append(structure_id)

                    preview_records: List[Dict[str, Any]] = []
                    preview_summary: Optional[Dict[str, Any]] = None
                    if return_preview:
                        safe_limit = max(25, min(preview_limit, STRUCTURE_PREVIEW_LIMITS.max_rows))
                        preview_model = build_dataframe_preview(
                            preview_frame,
                            limits=STRUCTURE_PREVIEW_LIMITS.override(max_rows=safe_limit),
                            label=f"{structure_id}_filter_preview",
                        )
                        preview_summary = preview_model.export()
                        preview_records = preview_summary.get("preview", [])

                    results.append(
                        {
                            "structure_id": structure_id,
                            "original_rows": original_rows,
                            "filtered_rows": filtered_rows,
                            "saved_entity": saved_entity,
                            "preview": preview_records,
                            "preview_summary": preview_summary,
                        }
                    )

                dataset_info: Optional[Dict[str, Any]] = None
                if create_dataset and dataset_entities:
                    manager = processor.dataset_manager
                    if manager.dataset_exists(create_dataset):
                        if overwrite_dataset:
                            manager.delete_dataset(create_dataset)
                            manager.create_dataset(create_dataset, dataset_entities, metadata={
                                "source": "structure_filter_entities",
                                "filters": filters,
                                "combine": combine_mode,
                            })
                        else:
                            existing = manager.get_dataset_entities(create_dataset)
                            to_add = sorted(set(dataset_entities) - set(existing))
                            to_remove = sorted(set(existing) - set(dataset_entities))
                            if to_add:
                                manager.add_to_dataset(create_dataset, to_add)
                            if to_remove:
                                manager.remove_from_dataset(create_dataset, to_remove)
                            metadata_update = {
                                "source": "structure_filter_entities",
                                "filters": filters,
                                "combine": combine_mode,
                            }
                            manager.update_metadata(create_dataset, metadata_update)
                    else:
                        manager.create_dataset(create_dataset, dataset_entities, metadata={
                            "source": "structure_filter_entities",
                            "filters": filters,
                            "combine": combine_mode,
                        })
                    try:
                        dataset_info = manager.get_dataset_info(create_dataset)
                    except Exception:  # pragma: no cover - best effort
                        dataset_info = {
                            "name": create_dataset,
                            "entity_count": len(dataset_entities),
                        }

                payload: Dict[str, Any] = {
                    "results": results,
                    "filters": filters,
                    "combine": combine_mode,
                    "saved_entities": saved_entities,
                    "dataset": dataset_info,
                    "errors": errors,
                }

                return self.format_success(payload)

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def structure_collect_chain_sequences(
            ctx,
            structure_ids: List[str],
            chain_filter: Optional[Union[List[str], Dict[str, List[str]], str]] = None,
            min_length: int = 1,
        ) -> Dict:
            """Collect per-chain sequences for one or more structures."""

            try:
                if error := self.validate_required_params(
                    {"structure_ids": structure_ids},
                    ["structure_ids"],
                ):
                    return error

                processor = self.get_processor("structure")
                collected = processor.collect_chain_sequences(
                    structure_ids,
                    chain_filter=chain_filter,
                    min_length=min_length,
                )

                formatted: Dict[str, Any] = {}
                for struct_id, chains in collected.items():
                    formatted[struct_id] = {
                        chain_id: {
                            "sequence": payload.get("sequence"),
                            "length": payload.get("length"),
                            "residue_span": payload.get("residue_span"),
                            "metadata": payload.get("metadata", {}),
                        }
                        for chain_id, payload in chains.items()
                    }

                return self.format_success(
                    {
                        "structure_ids": structure_ids,
                        "chain_sequences": formatted,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def structure_list_dataset_sequences(ctx, dataset_name: str) -> Dict:
            """List sequences related to each structure in a dataset."""

            try:
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name},
                    ["dataset_name"],
                ):
                    return error

                processor = self.get_processor("structure")
                relations = processor.list_dataset_related_sequences(
                    dataset_name,
                    include_unloaded=True,
                )

                formatted: Dict[str, List[Dict[str, Any]]] = {}
                for struct_id, entries in relations.items():
                    formatted[struct_id] = [
                        {
                            "sequence_name": entry.get("name"),
                            "metadata": entry.get("metadata", {}),
                        }
                        for entry in entries
                    ]

                return self.format_success(
                    {
                        "dataset_name": dataset_name,
                        "structures": formatted,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def structure_annotate_entities(
            ctx,
            structure_id: str,
            chain_annotations: Dict[str, Dict[str, Any]],
            structure_metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict:
            """Apply chain-level and optional structure-level annotations."""

            try:
                if error := self.validate_required_params(
                    {"structure_id": structure_id, "chain_annotations": chain_annotations},
                    ["structure_id", "chain_annotations"],
                ):
                    return error

                processor = self.get_processor("structure")
                annotations: Dict[str, Any] = {
                    "chains": chain_annotations,
                }
                if structure_metadata:
                    annotations["structure"] = structure_metadata

                processor.annotate_structure(structure_id, annotations)

                return self.format_success(
                    {
                        "structure_id": structure_id,
                        "chains": chain_annotations,
                        "structure": structure_metadata or {},
                    },
                    message="Structure annotated",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def structure_export_dataset(
            ctx,
            dataset_name: str,
            output_dir: str,
            format: str = "cif",
            overwrite: bool = True,
        ) -> Dict:
            """Export all structures in a dataset."""

            try:
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name, "output_dir": output_dir},
                    ["dataset_name", "output_dir"],
                ):
                    return error

                processor = self.get_processor("structure")
                exported = processor.export_dataset(
                    dataset_name,
                    Path(output_dir).expanduser(),
                    format=format,
                    overwrite=overwrite,
                )

                mapping = {key: str(path) for key, path in exported.items()}

                return self.format_success(
                    {
                        "dataset_name": dataset_name,
                        "export_directory": str(Path(output_dir).expanduser()),
                        "files": mapping,
                    },
                    message="Dataset exported",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def structure_export_entity(
            ctx,
            structure_id: str,
            output_path: str,
            format: str = "cif",
            overwrite: bool = True,
        ) -> Dict:
            """Export a single structure entity."""

            try:
                if error := self.validate_required_params(
                    {"structure_id": structure_id, "output_path": output_path},
                    ["structure_id", "output_path"],
                ):
                    return error

                processor = self.get_processor("structure")
                exported = processor.export_entity(
                    structure_id,
                    Path(output_path).expanduser(),
                    format=format,
                    overwrite=overwrite,
                )

                return self.format_success(
                    {
                        "structure_id": structure_id,
                        "export_path": str(exported),
                    },
                    message="Structure exported",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def structure_apply_grn_annotations(
            ctx,
            grn_table: str,
            structures: List[str],
            column_name: str = "grn",
            save_entities: bool = True,
        ) -> Dict:
            """Map GRN annotations from a table onto structure residues."""

            try:
                if error := self.validate_required_params(
                    {"grn_table": grn_table, "structures": structures},
                    ["grn_table", "structures"],
                ):
                    return error

                if not structures:
                    return self.format_error(
                        "No structures provided",
                        "Pass one or more structure IDs to annotate",
                    )

                result = self._apply_grn_annotations(
                    grn_table=grn_table,
                    structures=structures,
                    column_name=column_name,
                    save_entities=save_entities,
                )

                return self.format_success(result)

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=structure_apply_grn_annotations,
            name="structure_apply_grn_annotations",
            description="Map a saved GRN table back onto one or more structure entities, writing the results to a column (default 'grn').",
            parameters=[
                {"name": "grn_table", "type": "str"},
                {"name": "structures", "type": "list[str]"},
                {"name": "column_name", "type": "str", "default": "grn"},
                {"name": "save_entities", "type": "bool", "default": True},
            ],
            returns={"fields": ["annotation_counts", "skipped"]},
            tags=["structure", "grn"],
        )

        @server.tool()
        def structure_prepare_grn_annotations(
            ctx,
            structure_ids: List[str],
            reference_table: str,
            protein_family: str,
            reference_sequence_entity: Optional[str] = None,
            reference_sequence: Optional[str] = None,
            alignment_threshold: float = 0.75,
            chain_dataset_prefix: Optional[str] = None,
            filtered_sequence_dataset: Optional[str] = None,
            grn_table_name: Optional[str] = None,
            column_name: str = "grn",
            save_entities: bool = True,
        ) -> Dict:
            """Full GRN annotation pipeline for a set of structures."""

            try:
                if error := self.validate_required_params(
                    {
                        "structure_ids": structure_ids,
                        "reference_table": reference_table,
                        "protein_family": protein_family,
                    },
                    ["structure_ids", "reference_table", "protein_family"],
                ):
                    return error

                if not structure_ids:
                    return self.format_error(
                        "No structures provided",
                        "Pass one or more structure IDs to annotate",
                    )

                struct_proc = self.get_processor("structure")
                seq_proc = self.get_processor("sequence")

                normalized_structures = [self._normalize_structure_id(s) for s in structure_ids]
                missing = [sid for sid in normalized_structures if struct_proc.load_entity(sid) is None]
                if missing:
                    return self.format_error(
                        f"Structures missing: {', '.join(missing)}",
                        "Download the structures before running GRN annotation.",
                    )

                chain_prefix = chain_dataset_prefix or "grn_chain_dataset"
                registration = struct_proc.register_chain_sequences(
                    normalized_structures,
                    dataset_prefix=chain_prefix,
                    create_dataset=True,
                    overwrite=True,
                )

                chain_entities: List[str] = []
                for summary in registration.values():
                    chain_entities.extend(summary.get("registered_entities", []))

                if not chain_entities:
                    return self.format_error(
                        "No chain sequences were registered",
                        "Ensure the structures contain protein chains with resolvable sequences.",
                    )

                sequence_cache: Dict[str, str] = {}
                for entity in chain_entities:
                    data = seq_proc.load_entity(entity)
                    if isinstance(data, dict):
                        data = next((value for value in data.values() if isinstance(value, str)), None)
                    if isinstance(data, str):
                        sequence_cache[entity] = data

                if not sequence_cache:
                    return self.format_error(
                        "Unable to load chain sequences",
                        "Sequence processor returned empty payloads for the registered chains.",
                    )

                ref_sequence_value = reference_sequence
                ref_entity = reference_sequence_entity or next(iter(sequence_cache))
                if ref_sequence_value is None:
                    ref_data = sequence_cache.get(ref_entity) or seq_proc.load_entity(ref_entity)
                    if isinstance(ref_data, dict):
                        ref_data = next((value for value in ref_data.values() if isinstance(value, str)), None)
                    if not isinstance(ref_data, str):
                        return self.format_error(
                            f"Reference sequence '{ref_entity}' unavailable",
                            "Provide reference_sequence or reference_sequence_entity with a registered chain.",
                        )
                    ref_sequence_value = ref_data

                alignment_metrics: Dict[str, Dict[str, Any]] = {}
                filtered_entities: List[str] = []

                for entity, sequence in sequence_cache.items():
                    score, _ = seq_proc.align_sequences(
                        sequence,
                        ref_sequence_value,
                        seq1_id=entity,
                        seq2_id=ref_entity,
                        store_alignment=False,
                    )
                    max_len = max(len(sequence), len(ref_sequence_value)) or 1
                    normalized = float(score) / float(max_len)
                    alignment_metrics[entity] = {
                        "score": float(score),
                        "normalized": round(normalized, 4),
                        "length": len(sequence),
                    }
                    if normalized >= alignment_threshold or entity == ref_entity:
                        filtered_entities.append(entity)

                if not filtered_entities:
                    best = max(
                        alignment_metrics.items(),
                        key=lambda item: item[1]["normalized"],
                    )[0]
                    filtered_entities.append(best)

                filtered_dataset = filtered_sequence_dataset or f"{chain_prefix}_filtered"
                manager = seq_proc.dataset_manager
                if manager.dataset_exists(filtered_dataset):
                    manager.delete_dataset(filtered_dataset)
                seq_proc.create_dataset(
                    filtered_dataset,
                    filtered_entities,
                    metadata={
                        "source": "structure_prepare_grn_annotations",
                        "reference_sequence": ref_entity,
                        "threshold": alignment_threshold,
                        "entity_count": len(filtered_entities),
                    },
                )

                grn_table = grn_table_name or f"{filtered_dataset}_grn"
                annotations, summary = seq_proc.annotate_with_grn(
                    dataset_name=filtered_dataset,
                    reference_table=reference_table,
                    protein_family=protein_family,
                    output_table=grn_table,
                    allow_create=True,
                    metadata={"source": "structure_prepare_grn_annotations"},
                    return_summary=True,
                )

                apply_result = self._apply_grn_annotations(
                    grn_table=grn_table,
                    structures=normalized_structures,
                    column_name=column_name,
                    save_entities=save_entities,
                )

                payload = {
                    "structures": normalized_structures,
                    "chain_entities": sorted(sequence_cache.keys()),
                    "filtered_sequences": filtered_entities,
                    "filtered_dataset": filtered_dataset,
                    "alignment_threshold": alignment_threshold,
                    "alignment_metrics": alignment_metrics,
                    "reference_sequence": ref_entity,
                    "grn_table": grn_table,
                    "sequence_annotation_summary": summary,
                    "structure_annotation_summary": apply_result,
                    "annotation_rows": len(annotations),
                }

                return self.format_success(payload, message="GRN annotations applied")

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=structure_prepare_grn_annotations,
            name="structure_prepare_grn_annotations",
            description="Extract chains, filter/align them, annotate with GRN, and map the GRN labels back onto the provided structures in one call.",
            parameters=[
                {"name": "structure_ids", "type": "list[str]"},
                {"name": "reference_table", "type": "str"},
                {"name": "protein_family", "type": "str"},
                {"name": "reference_sequence_entity", "type": "str", "optional": True},
                {"name": "alignment_threshold", "type": "float", "default": 0.75},
            ],
            returns={"fields": ["filtered_dataset", "grn_table", "structure_annotation_summary"]},
            tags=["structure", "grn", "workflow"],
        )

        @server.tool()
        def extract_sequence_from_structure(ctx, pdb_id: str,
                                          chain_id: str = "A",
                                          save_to_sequence: bool = False) -> Dict:
            """
            Extract amino acid sequence from a protein structure.
            
            Args:
                pdb_id: PDB identifier of the structure
                chain_id: Chain ID to extract sequence from
                save_to_sequence: If True, save to sequence processor
                
            Returns:
                Dictionary with extracted sequence
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                processor = self.get_processor("structure")

                sequence = processor.get_sequence(pdb_id, chain_id)
                if sequence is None:
                    return self.format_error(
                        f"Chain {chain_id} not found in structure {pdb_id}",
                        "Ensure the structure exists and the chain identifier is correct",
                    )

                result = {
                    "pdb_id": pdb_id,
                    "chain_id": chain_id,
                    "sequence": sequence,
                    "length": len(sequence)
                }
                
                # Save to sequence processor if requested
                if save_to_sequence:
                    try:
                        seq_processor = self.get_processor("sequence")
                        seq_processor.save_entity(
                            name=f"{pdb_id}_{chain_id}",
                            data=sequence,
                            metadata={"source": "structure", "pdb_id": pdb_id, "chain": chain_id}
                        )
                        result["saved_to_sequence"] = True
                    except Exception as e:
                        result["save_error"] = str(e)
                        result["saved_to_sequence"] = False
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_all_sequences_from_structure(ctx, pdb_id: str,
                                           save_to_sequence: bool = False) -> Dict:
            """
            Extract sequences from all chains in a structure.
            
            Args:
                pdb_id: PDB identifier
                save_to_sequence: If True, save all to sequence processor
                
            Returns:
                Dictionary with sequences for all chains
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                processor = self.get_processor("structure")
                collected = processor.collect_chain_sequences([pdb_id])
                chains = collected.get(pdb_id, {})

                if not chains:
                    return self.format_error(
                        f"No sequences found for {pdb_id}",
                        "Ensure the structure exists and contains chains",
                    )

                pdb_sequences = {
                    payload.get("entity_name", f"{pdb_id}_chain_{chain_id}"): payload.get("sequence")
                    for chain_id, payload in chains.items()
                    if payload.get("sequence")
                }

                result = {
                    "pdb_id": pdb_id,
                    "chains": len(pdb_sequences),
                    "sequences": pdb_sequences
                }
                
                # Save to sequence processor if requested
                if save_to_sequence:
                    saved = []
                    errors = []
                    try:
                        seq_processor = self.get_processor("sequence")
                        for chain_id, sequence in pdb_sequences.items():
                            try:
                                seq_processor.save_entity(
                                    name=chain_id,
                                    data=sequence,
                                    metadata={"source": "structure", "pdb_id": pdb_id}
                                )
                                saved.append(chain_id)
                            except Exception as e:
                                errors.append({"chain": chain_id, "error": str(e)})
                        
                        result["saved_sequences"] = saved
                        if errors:
                            result["save_errors"] = errors
                    except Exception as e:
                        result["save_error"] = str(e)
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_structure_chains(ctx, pdb_id: str) -> Dict:
            """
            Get list of chains in a structure.
            
            Args:
                pdb_id: PDB identifier
                
            Returns:
                Dictionary with chain information
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                processor = self.get_processor("structure")
                chains = processor.get_chains(pdb_id)

                if not chains:
                    return self.format_error(
                        f"No chains found for {pdb_id}",
                        "Ensure the structure exists",
                    )

                # Get additional info for each chain
                chain_info = []
                for chain in chains:
                    try:
                        seq = processor.get_sequence(pdb_id, chain)
                        chain_info.append({
                            "chain_id": chain,
                            "length": len(seq) if seq else 0
                        })
                    except:
                        chain_info.append({
                            "chain_id": chain,
                            "length": 0
                        })
                
                return self.format_success({
                    "pdb_id": pdb_id,
                    "chain_count": len(chains),
                    "chains": chain_info
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def structure_get_ca_coordinates(ctx, pdb_id: str, chain_id: str = "A") -> Dict:
            """
            Get C-alpha atom coordinates for a chain.
            
            Args:
                pdb_id: PDB identifier
                chain_id: Chain ID
                
            Returns:
                Dictionary with coordinate array
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                processor = self.get_processor("structure")
                try:
                    processor.load_entity(pdb_id)
                    coords = processor.get_ca_coordinates(pdb_id, chain_id)
                except ValueError as e:
                    return self.format_error(
                        str(e),
                        f"Make sure {pdb_id} chain {chain_id} exists"
                    )
                
                return self.format_success({
                    "pdb_id": pdb_id,
                    "chain_id": chain_id,
                    "num_residues": len(coords),
                    "coordinates": coords.tolist(),  # Convert numpy array to list
                    "shape": list(coords.shape)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def extract_ligands_from_structure(ctx, pdb_id: str,
                                         exclude_common: bool = True,
                                         min_atoms: int = 3) -> Dict:
            """
            Extract all ligands from a protein structure.
            
            Args:
                pdb_id: PDB identifier
                exclude_common: Exclude water, ions, common molecules
                min_atoms: Minimum atoms for a ligand
                
            Returns:
                Dictionary with ligand information
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                processor = self.get_processor("structure")
                frame = processor.load_entity(pdb_id)
                if frame is None:
                    return self.format_error(
                        f"Structure '{pdb_id}' not found",
                        "Download or register the structure before extracting ligands",
                    )
                
                # Import analysis function
                try:
                    from protos.analysis.structure_ligand_analysis import extract_all_ligands
                except ImportError:
                    return self.format_error(
                        "Ligand analysis module not available",
                        "Ensure protos.analysis is installed"
                    )
                
                # Extract ligands
                ligands = extract_all_ligands(
                    processor, 
                    pdb_id,
                    exclude_common=exclude_common,
                    min_atoms=min_atoms
                )
                
                # Format results
                ligand_summary = []
                for ligand in ligands:
                    ligand_summary.append({
                        "ligand_id": ligand['ligand_id'],
                        "res_name": ligand['res_name3l'],
                        "chain_id": ligand['chain_id'],
                        "res_id": ligand['res_id'],
                        "num_atoms": ligand['num_atoms'],
                        "centroid": ligand['centroid'].tolist()
                    })
                
                return self.format_success({
                    "pdb_id": pdb_id,
                    "num_ligands": len(ligands),
                    "ligands": ligand_summary,
                    "excluded_common": exclude_common,
                    "min_atoms": min_atoms
                })
                
            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def structure_extract_water_molecules(
            ctx,
            pdb_id: str,
            min_atoms: int = 1,
        ) -> Dict:
            """List water molecules treated as ligand-like records."""

            if error := self.validate_required_params(
                {"pdb_id": pdb_id}, ["pdb_id"],
            ):
                return error

            processor = self.get_processor("structure")
            frame = processor.load_entity(pdb_id)
            if frame is None:
                return self.format_error(
                    f"Structure '{pdb_id}' not found",
                    "Download or register the structure before extracting waters",
                )

            try:
                from protos.analysis.structure_ligand_analysis import extract_water_molecules as _extract_water_molecules
            except ImportError:
                return self.format_error(
                    "Water extraction helpers are unavailable",
                    "Ensure protos.analysis is installed",
                )

            waters = _extract_water_molecules(
                processor,
                pdb_id,
                min_atoms=min_atoms,
            )

            return self.format_success(
                {
                    "pdb_id": pdb_id,
                    "water_count": len(waters),
                    "waters": waters,
                }
            )

        @server.tool()
        def structure_compute_water_networks(
            ctx,
            structure_ids: Union[str, List[str]],
            residue_cutoff: float = 3.4,
            water_water_cutoff: float = 3.4,
            hydrogen_bond_cutoff: float = 3.2,
            property_table_name: Optional[str] = None,
            allow_create_property_table: bool = False,
            include_raw: bool = False,
            include_networks: bool = False,
            include_contacts: bool = False,
            network_table_name: Optional[str] = None,
            contact_table_name: Optional[str] = None,
            allow_create_network_table: bool = False,
            allow_create_contact_table: bool = False,
            max_paths: int = 5,
        ) -> Dict:
            """Analyze water-mediated residue networks for the given structures.

            Returns summary counts by default. Use ``include_networks`` and
            ``include_contacts`` to embed sanitized network/contact payloads in the
            response, and provide ``network_table_name``/``contact_table_name`` when
            you want the detailed rows recorded as property tables.
            """

            def _simplify_residue(residue: Dict[str, Any]) -> Dict[str, Any]:
                return {
                    "label": residue.get("label"),
                    "chain_id": residue.get("chain_id"),
                    "seq_id": residue.get("seq_id"),
                    "res_name": residue.get("res_name"),
                    "grn_labels": residue.get("grn_labels", []),
                }

            def _simplify_water(water: Dict[str, Any]) -> Dict[str, Any]:
                return {
                    "label": water.get("label"),
                    "chain_id": water.get("chain_id"),
                    "seq_id": water.get("seq_id"),
                }

            def _format_paths(network: Dict[str, Any]) -> List[str]:
                sequences: List[str] = []
                raw_paths = network.get("paths") or []
                limit = max_paths if max_paths and max_paths > 0 else None
                for path in raw_paths[:limit]:
                    seq = path.get("sequence_str")
                    if not seq:
                        seq = " -> ".join(path.get("sequence", []))
                    sequences.append(seq)
                return sequences

            def _simplify_network(struct_id: str, network: Dict[str, Any]) -> Dict[str, Any]:
                residues = [_simplify_residue(res) for res in network.get("residues", [])]
                waters = [_simplify_water(w) for w in network.get("waters", [])]
                bridging = [_simplify_water(w) for w in network.get("bridging_waters", [])]
                summary = network.get("summary", {})
                return {
                    "structure_id": struct_id,
                    "network_id": network.get("network_id"),
                    "chains": network.get("chains", []),
                    "summary": summary,
                    "residues": residues,
                    "waters": [w["label"] for w in waters if w.get("label")],
                    "bridging_waters": [w["label"] for w in bridging if w.get("label")],
                    "paths": _format_paths(network),
                    "residue_grn_map": {
                        res["label"]: res.get("grn_labels", []) for res in residues if res.get("label")
                    },
                }

            def _simplify_contacts(struct_id: str, network: Dict[str, Any]) -> List[Dict[str, Any]]:
                simplified: List[Dict[str, Any]] = []
                for edge in network.get("residue_water_edges", []) or []:
                    residue = edge.get("residue", {})
                    water = edge.get("water", {})
                    simplified.append(
                        {
                            "structure_id": struct_id,
                            "network_id": network.get("network_id"),
                            "residue_label": residue.get("label"),
                            "residue_chain": residue.get("chain_id"),
                            "residue_seq_id": residue.get("seq_id"),
                            "residue_name": residue.get("res_name"),
                            "residue_grn_labels": residue.get("grn_labels", []),
                            "water_label": water.get("label"),
                            "water_chain": water.get("chain_id"),
                            "water_seq_id": water.get("seq_id"),
                            "distance": edge.get("distance"),
                            "hydrogen_bond": edge.get("hydrogen_bond"),
                            "backbone_contact": edge.get("backbone_contact"),
                        }
                    )
                return simplified

            try:
                if isinstance(structure_ids, str):
                    requested_ids = [structure_ids]
                else:
                    requested_ids = list(structure_ids)

                if not requested_ids:
                    raise InvalidInputError("structure_ids", "Provide at least one structure identifier")

                processor = self.get_processor("structure")
                analysis = processor.compute_water_networks(
                    requested_ids,
                    residue_cutoff=residue_cutoff,
                    water_water_cutoff=water_water_cutoff,
                    hydrogen_bond_cutoff=hydrogen_bond_cutoff,
                    property_table_name=property_table_name,
                    property_metadata={
                        'tool': 'structure_compute_water_networks',
                        'requested_ids': requested_ids,
                    },
                    allow_create_property_table=allow_create_property_table,
                )

                summary_map = summarize_water_networks(analysis)
                payload: Dict[str, Any] = {
                    'requested_ids': requested_ids,
                    'parameters': {
                        'residue_cutoff': residue_cutoff,
                        'water_water_cutoff': water_water_cutoff,
                        'hydrogen_bond_cutoff': hydrogen_bond_cutoff,
                    },
                    'structures': summary_map,
                    'errors': analysis.get('errors', {}),
                }

                if analysis.get('property_table'):
                    payload['property_table'] = analysis['property_table']

                raw_structures = analysis.get('structures', {}) or {}

                network_details: Dict[str, Any] = {}
                contact_details: Dict[str, List[Dict[str, Any]]] = {}

                needs_networks = include_networks or network_table_name is not None
                needs_contacts = include_contacts or contact_table_name is not None

                if needs_networks or needs_contacts:
                    for struct_id, info in raw_structures.items():
                        networks = info.get('networks', []) or []
                        simplified_networks = [
                            _simplify_network(struct_id, net)
                            for net in networks
                        ]
                        if needs_networks:
                            network_details[struct_id] = {
                                'networks': simplified_networks,
                            }
                        if needs_contacts:
                            all_contacts: List[Dict[str, Any]] = []
                            for net, simplified in zip(networks, simplified_networks):
                                all_contacts.extend(_simplify_contacts(struct_id, net))
                            if all_contacts:
                                contact_details[struct_id] = all_contacts

                if include_networks and network_details:
                    payload['networks'] = network_details

                if include_contacts and contact_details:
                    payload['contacts'] = contact_details

                property_tables: Dict[str, Any] = {}

                if network_table_name and network_details:
                    rows: List[Dict[str, Any]] = []
                    for struct_id, entry in network_details.items():
                        for network in entry.get('networks', []):
                            rows.append(
                                {
                                    "scope": [
                                        {"format": "structure", "name": struct_id},
                                    ],
                                    "entity_name": f"{struct_id}_network_{network.get('network_id')}",
                                    "structure_id": struct_id,
                                    "network_id": network.get('network_id'),
                                    "chains": network.get('chains', []),
                                    "residue_labels": [
                                        res.get('label') for res in network.get('residues', [])
                                        if res.get('label')
                                    ],
                                    "waters": network.get('waters', []),
                                    "bridging_waters": network.get('bridging_waters', []),
                                    "paths": network.get('paths', []),
                                    "residue_grn_map": network.get('residue_grn_map', {}),
                                    "residue_count": network.get('summary', {}).get('residue_count'),
                                    "water_count": network.get('summary', {}).get('water_count'),
                                    "max_residue_path_length": network.get('summary', {}).get('max_residue_path_length'),
                                }
                            )

                    if rows:
                        property_processor = self.get_processor("property")
                        recorded = property_processor.record_properties(
                            network_table_name,
                            rows,
                            metadata={
                                'source': 'structure_compute_water_networks',
                                'kind': 'network',
                            },
                            allow_create=allow_create_network_table,
                        )
                        property_tables['network_table'] = {
                            'name': network_table_name,
                            'row_count': int(len(recorded)),
                            'columns': recorded.columns.tolist(),
                        }

                if contact_table_name and contact_details:
                    contact_rows: List[Dict[str, Any]] = []
                    for struct_id, contacts in contact_details.items():
                        for contact in contacts:
                            contact_rows.append(
                                {
                                    "scope": [
                                        {"format": "structure", "name": struct_id},
                                    ],
                                    "entity_name": f"{struct_id}_{contact.get('residue_label')}_to_{contact.get('water_label')}",
                                    "structure_id": struct_id,
                                    "network_id": contact.get('network_id'),
                                    "residue_label": contact.get('residue_label'),
                                    "residue_chain": contact.get('residue_chain'),
                                    "residue_seq_id": contact.get('residue_seq_id'),
                                    "residue_name": contact.get('residue_name'),
                                    "residue_grn_labels": contact.get('residue_grn_labels', []),
                                    "water_label": contact.get('water_label'),
                                    "water_chain": contact.get('water_chain'),
                                    "water_seq_id": contact.get('water_seq_id'),
                                    "distance": contact.get('distance'),
                                    "hydrogen_bond": contact.get('hydrogen_bond'),
                                    "backbone_contact": contact.get('backbone_contact'),
                                }
                            )

                    if contact_rows:
                        property_processor = self.get_processor("property")
                        recorded_contacts = property_processor.record_properties(
                            contact_table_name,
                            contact_rows,
                            metadata={
                                'source': 'structure_compute_water_networks',
                                'kind': 'contact',
                            },
                            allow_create=allow_create_contact_table,
                        )
                        property_tables['contact_table'] = {
                            'name': contact_table_name,
                            'row_count': int(len(recorded_contacts)),
                            'columns': recorded_contacts.columns.tolist(),
                        }

                if property_tables:
                    payload['property_tables'] = property_tables

                if include_raw:
                    payload['raw_structures'] = raw_structures

                return self.format_success(payload)

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def structure_compute_embedding_similarity(
            ctx,
            reference_structure: str,
            reference_chain: str,
            embedding_dataset: str,
            selection: List[Dict[str, str]],
            window_size: int = 8,
            max_gap: int = 30,
            property_table_name: Optional[str] = None,
            record_property_table: bool = False,
            include_records: bool = False,
            include_plot_points: bool = False,
        ) -> Dict:
            """Compute per-residue embedding similarity relative to a reference chain."""

            try:
                if not selection:
                    return self.format_error(
                        "Selection required",
                        "Provide chain/sequence mappings for each structure.",
                    )

                try:
                    selection_objs = [
                        ChainSelection(
                            structure_id=item["structure_id"],
                            chain_id=item["chain_id"],
                            sequence_id=item["sequence_id"],
                        )
                        for item in selection
                    ]
                except KeyError as exc:
                    return self.format_error(
                        "Invalid selection entry",
                        f"Missing key: {exc.args[0]}. Expected structure_id, chain_id, sequence_id.",
                    )

                struct_proc = self.get_processor("structure")
                embedding_proc = self.get_processor("embedding")

                result = compute_structure_embedding_similarity(
                    struct_proc,
                    embedding_proc,
                    selection_objs,
                    reference_structure=reference_structure,
                    reference_chain=reference_chain,
                    embedding_dataset=embedding_dataset,
                    window_size=window_size,
                    max_gap=max_gap,
                    property_table_name=property_table_name,
                    property_metadata={"tool": "structure_compute_embedding_similarity"},
                    record_property_table=record_property_table,
                )

                response: Dict[str, Any] = {
                    "reference_structure": reference_structure,
                    "reference_chain": reference_chain,
                    "embedding_dataset": embedding_dataset,
                    "rmsd": result["rmsd"],
                    "property_table": result.get("property_table"),
                    "summary": result["summary"].to_dict(orient="records"),
                }

                if include_records:
                    response["records"] = result["records"].to_dict(orient="records")

                if include_plot_points:
                    response["plot_points"] = result["plot_points"]

                return self.format_success(response)

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def structure_get_binding_site_residues(ctx, pdb_id: str,
                                    ligand_name: str,
                                    chain_id: Optional[str] = None,
                                    cutoff: float = 5.0) -> Dict:
            """
            Get residues in the binding site of a ligand.
            
            Args:
                pdb_id: PDB identifier
                ligand_name: Three-letter ligand code
                chain_id: Optional chain specification
                cutoff: Distance cutoff in Angstroms
                
            Returns:
                Dictionary with binding site residues
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id, "ligand_name": ligand_name},
                    ["pdb_id", "ligand_name"]
                ):
                    return error
                
                processor = self.get_processor("structure")
                frame = processor.load_entity(pdb_id)
                if frame is None:
                    return self.format_error(
                        f"Structure '{pdb_id}' not found",
                        "Download or register the structure before computing binding sites",
                    )
                
                # Import analysis functions
                try:
                    from protos.analysis.structure_ligand_analysis import (
                        get_ligand_by_id, get_binding_site
                    )
                except ImportError:
                    return self.format_error(
                        "Ligand analysis module not available",
                        "Ensure protos.analysis is installed"
                    )
                
                # Get ligand atoms
                ligand_atoms = get_ligand_by_id(
                    processor, pdb_id, ligand_name, chain_id
                )
                
                if ligand_atoms is None or ligand_atoms.empty:
                    return self.format_error(
                        f"Ligand {ligand_name} not found in {pdb_id}",
                        "Check ligand name and chain ID"
                    )
                
                # Get binding site
                binding_site = get_binding_site(
                    processor, pdb_id, ligand_atoms, cutoff
                )
                
                # Format results
                residues = binding_site['residues']
                unique_residues = residues[['auth_chain_id', 'res_name3l', 'auth_seq_id']].drop_duplicates()
                
                residue_list = []
                for _, res in unique_residues.iterrows():
                    residue_list.append({
                        "chain": res['auth_chain_id'],
                        "res_name": res['res_name3l'],
                        "res_id": int(res['auth_seq_id'])
                    })
                
                return self.format_success({
                    "pdb_id": pdb_id,
                    "ligand": ligand_name,
                    "chain_id": chain_id,
                    "cutoff": cutoff,
                    "num_residues": len(unique_residues),
                    "binding_site_residues": residue_list,
                    "total_atoms": len(binding_site['atoms'])
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def structure_analyze_ligand_interactions(ctx, pdb_id: str,
                                       ligand_name: str,
                                       chain_id: Optional[str] = None,
                                       detailed: bool = True) -> Dict:
            """
            Analyze detailed protein-ligand interactions including multiple interaction types.
            
            This tool provides comprehensive interaction analysis beyond simple distance cutoffs,
            including hydrogen bonds, hydrophobic contacts, pi-stacking, salt bridges, and
            water-mediated interactions.
            
            Args:
                pdb_id: PDB identifier
                ligand_name: Three-letter ligand code (e.g., 'ATP', 'HEM')
                chain_id: Optional chain specification for the ligand
                detailed: If True, return detailed interaction lists; if False, only summary
                
            Returns:
                Dictionary with comprehensive interaction analysis including:
                - Hydrogen bonds with donor/acceptor information
                - Hydrophobic contacts
                - Water-mediated bridges
                - Pi-stacking interactions
                - Salt bridges
                - Binding site residue summary
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id, "ligand_name": ligand_name},
                    ["pdb_id", "ligand_name"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                frame = processor.load_entity(pdb_id)
                if frame is None:
                    return self.format_error(
                        f"Structure '{pdb_id}' not found",
                        "Download or register the structure before analyzing ligand interactions",
                    )
                
                try:
                    from protos.analysis.structure_ligand_analysis import calculate_ligand_interactions
                except ImportError:
                    return self.format_error(
                        "Advanced ligand analysis module not available",
                        "Ensure protos.analysis is installed"
                    )

                structure_data = frame.reset_index()
                ligand_filter = (structure_data['group'] == 'HETATM') & (structure_data['res_name3l'] == ligand_name)
                if chain_id:
                    ligand_filter &= (structure_data['auth_chain_id'] == chain_id)

                ligand_atoms = structure_data[ligand_filter]
                
                if ligand_atoms.empty:
                    return self.format_error(
                        f"Ligand {ligand_name} not found in {pdb_id}" + 
                        (f" chain {chain_id}" if chain_id else ""),
                        "Check ligand name and chain ID. Use extract_ligands_from_structure to list available ligands"
                    )
                
                # Calculate interactions
                interactions = calculate_ligand_interactions(
                    processor, pdb_id, ligand_atoms, detailed=detailed
                )
                
                # Format the response
                result = {
                    "pdb_id": pdb_id,
                    "ligand": ligand_name,
                    "chain_id": chain_id,
                    "num_ligand_atoms": len(ligand_atoms)
                }
                
                if detailed:
                    # Include full interaction details
                    result.update({
                        "summary": interactions.get('summary', {}),
                        "binding_site": interactions.get('binding_site', {}),
                        "hydrogen_bonds": interactions.get('hydrogen_bonds', []),
                        "hydrophobic_contacts": interactions.get('hydrophobic', []),
                        "water_mediated": interactions.get('water_mediated', []),
                        "pi_stacking": interactions.get('pi_stacking', []),
                        "salt_bridges": interactions.get('salt_bridges', [])
                    })
                else:
                    # Only include summary
                    result["summary"] = interactions
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def structure_analyze_binding_pocket(ctx, pdb_id: str,
                                 ligand_name: str,
                                 chain_id: Optional[str] = None,
                                 cutoff: float = 8.0,
                                 include_volume: bool = True) -> Dict:
            """
            Analyze the binding pocket around a ligand including volume estimation.
            
            This tool provides comprehensive binding pocket analysis including:
            - Binding site residue identification
            - Pocket volume estimation using convex hull
            - Residue conservation potential
            - Pocket properties (hydrophobicity, charge distribution)
            
            Args:
                pdb_id: PDB identifier
                ligand_name: Three-letter ligand code
                chain_id: Optional chain specification for the ligand
                cutoff: Distance cutoff for binding site definition (Angstroms)
                include_volume: Whether to calculate pocket volume
                
            Returns:
                Dictionary with binding pocket analysis
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id, "ligand_name": ligand_name},
                    ["pdb_id", "ligand_name"]
                ):
                    return error
                
                processor = self.get_processor("structure")
                frame = processor.load_entity(pdb_id)
                if frame is None:
                    return self.format_error(
                        f"Structure '{pdb_id}' not found",
                        "Download or register the structure before analyzing binding pockets",
                    )

                try:
                    from protos.analysis.structure_ligand_analysis import (
                        get_binding_site, estimate_binding_site_volume
                    )
                except ImportError:
                    return self.format_error(
                        "Binding pocket analysis module not available",
                        "Ensure protos.analysis is installed"
                    )

                structure_data = frame.reset_index()
                ligand_filter = (structure_data['group'] == 'HETATM') & (structure_data['res_name3l'] == ligand_name)
                if chain_id:
                    ligand_filter &= (structure_data['auth_chain_id'] == chain_id)
                
                ligand_atoms = structure_data[ligand_filter]
                
                if ligand_atoms.empty:
                    return self.format_error(
                        f"Ligand {ligand_name} not found in {pdb_id}",
                        "Use extract_ligands_from_structure to list available ligands"
                    )
                
                # Get binding site
                binding_site = get_binding_site(processor, pdb_id, ligand_atoms, cutoff)
                
                if binding_site['residues'].empty:
                    return self.format_error(
                        "No binding site residues found",
                        f"Try increasing cutoff beyond {cutoff} Angstroms"
                    )
                
                # Analyze pocket composition
                residues_df = binding_site['residues']
                
                # Categorize residues
                hydrophobic = ['ALA', 'VAL', 'LEU', 'ILE', 'MET', 'PHE', 'TRP', 'PRO']
                aromatic = ['PHE', 'TYR', 'TRP']
                charged = ['ARG', 'LYS', 'ASP', 'GLU', 'HIS']
                polar = ['SER', 'THR', 'CYS', 'ASN', 'GLN', 'TYR']
                
                residue_counts = residues_df['res_name'].value_counts().to_dict()
                
                pocket_properties = {
                    "hydrophobic_residues": sum(residues_df['res_name'].isin(hydrophobic)),
                    "aromatic_residues": sum(residues_df['res_name'].isin(aromatic)),
                    "charged_residues": sum(residues_df['res_name'].isin(charged)),
                    "polar_residues": sum(residues_df['res_name'].isin(polar))
                }
                
                # Format residue list
                residue_list = []
                for _, res in residues_df.iterrows():
                    residue_list.append({
                        "residue": f"{res['res_name']}{res['res_id']}",
                        "chain": res['chain_id'],
                        "distance": round(res['min_distance'], 2),
                        "num_atoms": res['num_atoms']
                    })
                
                result = {
                    "pdb_id": pdb_id,
                    "ligand": ligand_name,
                    "chain_id": chain_id,
                    "cutoff": cutoff,
                    "num_residues": len(residues_df),
                    "num_atoms": len(binding_site['atoms']),
                    "residue_composition": residue_counts,
                    "pocket_properties": pocket_properties,
                    "binding_residues": residue_list
                }
                
                # Calculate pocket volume if requested
                if include_volume:
                    try:
                        volume = estimate_binding_site_volume(binding_site['atoms'])
                        result["pocket_volume"] = {
                            "volume_cubic_angstroms": round(volume, 2),
                            "estimated_method": "convex_hull"
                        }
                    except Exception as e:
                        result["pocket_volume"] = {
                            "error": f"Could not calculate volume: {str(e)}"
                        }
                
                # Identify key interaction residues (closest to ligand)
                closest_residues = residues_df.nsmallest(5, 'min_distance')
                result["key_residues"] = [
                    f"{row['res_name']}{row['res_id']}" 
                    for _, row in closest_residues.iterrows()
                ]
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def calculate_structure_properties(ctx, pdb_id: str,
                                         chain_id: Optional[str] = None) -> Dict:
            """
            Calculate basic structural properties.
            
            Args:
                pdb_id: PDB identifier
                chain_id: Optional specific chain
                
            Returns:
                Dictionary with structural properties
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                processor = self.get_processor("structure")
                frame = processor.load_entity(pdb_id)
                if frame is None:
                    return self.format_error(
                        f"Structure '{pdb_id}' not found",
                        "Download or register the structure before computing properties",
                    )

                structure_data = frame.reset_index()
                if chain_id:
                    structure_data = structure_data[structure_data['auth_chain_id'] == chain_id]
                
                if structure_data.empty:
                    return self.format_error(
                        f"No data found for {pdb_id}" + (f" chain {chain_id}" if chain_id else ""),
                        "Check PDB ID and chain specification"
                    )
                
                # Calculate properties
                properties = {
                    "pdb_id": pdb_id,
                    "chain_id": chain_id,
                    "total_atoms": len(structure_data),
                    "protein_atoms": len(structure_data[structure_data['group'] == 'ATOM']),
                    "hetero_atoms": len(structure_data[structure_data['group'] == 'HETATM']),
                    "num_residues": structure_data[structure_data['group'] == 'ATOM']['auth_seq_id'].nunique(),
                    "chains": structure_data['auth_chain_id'].unique().tolist(),
                    "resolution": structure_data['resolution'].iloc[0] if 'resolution' in structure_data.columns else None
                }
                
                # Bounding box
                coords = structure_data[['x', 'y', 'z']].values
                properties["bounding_box"] = {
                    "min": coords.min(axis=0).tolist(),
                    "max": coords.max(axis=0).tolist(),
                    "center": coords.mean(axis=0).tolist()
                }
                
                return self.format_success(properties)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def align_protein_structures(ctx, reference_pdb: str, mobile_pdb: str,
                                   atom_selection: str = "CA",
                                   chain_selection: Optional[str] = None,
                                   window_size: int = 8,
                                   max_gap: int = 30) -> Dict:
            """
            Align two protein structures using CEalign algorithm.
            
            This tool performs structural alignment of two proteins and returns
            the transformation matrix and RMSD. The alignment is performed on
            selected atoms (default: CA atoms).
            
            Args:
                reference_pdb: PDB ID of the reference structure
                mobile_pdb: PDB ID of the structure to align
                atom_selection: Atom type to use for alignment ("CA", "backbone", "all")
                chain_selection: Specific chain to align (e.g., "A"), or None for all
                window_size: Window size for CEalign algorithm
                max_gap: Maximum gap size for CEalign algorithm
                
            Returns:
                Dictionary with alignment results including RMSD and transformation
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"reference_pdb": reference_pdb, "mobile_pdb": mobile_pdb}, 
                    ["reference_pdb", "mobile_pdb"]
                ):
                    return error
                
                processor = self.get_processor("structure")
                self._ensure_structures_loaded(processor, [reference_pdb, mobile_pdb])

                ref_frame = processor.load_entity(reference_pdb)
                mob_frame = processor.load_entity(mobile_pdb)

                if ref_frame is None or mob_frame is None:
                    return self.format_error(
                        "One or both structures not found",
                        "Ensure both structures are registered",
                    )

                ref_data = ref_frame.reset_index()
                mob_data = mob_frame.reset_index()
                
                if ref_data.empty:
                    return self.format_error(
                        f"Reference structure {reference_pdb} not found",
                        "Ensure the structure is loaded"
                    )
                
                if mob_data.empty:
                    return self.format_error(
                        f"Mobile structure {mobile_pdb} not found",
                        "Ensure the structure is loaded"
                    )
                
                # Apply chain selection if specified
                if chain_selection:
                    ref_data = ref_data[ref_data['auth_chain_id'] == chain_selection]
                    mob_data = mob_data[mob_data['auth_chain_id'] == chain_selection]
                    
                    if ref_data.empty or mob_data.empty:
                        return self.format_error(
                            f"Chain {chain_selection} not found in one or both structures",
                            "Check available chains with get_structure_chains"
                        )
                
                # Apply atom selection
                if atom_selection == "CA":
                    ref_coords = ref_data[ref_data['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                    mob_coords = mob_data[mob_data['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                elif atom_selection == "backbone":
                    backbone_atoms = ['N', 'CA', 'C', 'O']
                    ref_coords = ref_data[ref_data['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                    mob_coords = mob_data[mob_data['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                else:  # all atoms
                    ref_coords = ref_data[['x', 'y', 'z']].copy()
                    mob_coords = mob_data[['x', 'y', 'z']].copy()
                
                # Ensure numeric types
                for coord in ['x', 'y', 'z']:
                    ref_coords[coord] = pd.to_numeric(ref_coords[coord], errors='coerce')
                    mob_coords[coord] = pd.to_numeric(mob_coords[coord], errors='coerce')
                
                # Drop NaN values
                ref_coords = ref_coords.dropna()
                mob_coords = mob_coords.dropna()
                
                if ref_coords.empty or mob_coords.empty:
                    return self.format_error(
                        "No valid coordinates found after filtering",
                        "Check atom selection and data quality"
                    )
                
                # Perform alignment using struct_alignment
                from protos.processing.structure.struct_alignment import align_structures
                
                try:
                    aligned_coords, rotation, translation, alignment_path, rmsd = align_structures(
                        ref_coords, mob_coords, 
                        window_size=window_size, 
                        max_gap=max_gap
                    )
                    
                    # Format results
                    return self.format_success({
                        "reference_pdb": reference_pdb,
                        "mobile_pdb": mobile_pdb,
                        "rmsd": round(float(rmsd), 3),
                        "num_aligned_atoms": len(alignment_path[0]) if alignment_path else 0,
                        "atom_selection": atom_selection,
                        "chain_selection": chain_selection,
                        "rotation_matrix": rotation.tolist() if hasattr(rotation, 'tolist') else rotation,
                        "translation_vector": translation.tolist() if hasattr(translation, 'tolist') else translation,
                        "window_size": window_size,
                        "max_gap": max_gap
                    })
                    
                except Exception as e:
                    return self.format_error(
                        f"Alignment failed: {str(e)}",
                        "Check if structures have compatible atom sets"
                    )
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def calculate_structure_rmsd_matrix(ctx, pdb_ids: List[str],
                                          atom_selection: str = "CA",
                                          chain_selection: Optional[str] = None,
                                          mode: str = "all_vs_all") -> Dict:
            """
            Calculate RMSD matrix between multiple structures.
            
            This tool performs pairwise structural alignments between multiple
            proteins and returns an RMSD matrix. Can operate in all-vs-all mode
            or one-vs-all mode.
            
            Args:
                pdb_ids: List of PDB IDs to compare
                atom_selection: Atom type to use for alignment ("CA", "backbone", "all")
                chain_selection: Specific chain to align, or None for all
                mode: Comparison mode ("all_vs_all" or "one_vs_all")
                
            Returns:
                Dictionary with RMSD matrix and statistics
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_ids": pdb_ids}, 
                    ["pdb_ids"]
                ):
                    return error
                
                if len(pdb_ids) < 2:
                    return self.format_error(
                        "Need at least 2 structures",
                        "Provide multiple PDB IDs to compare"
                    )
                
                if mode not in ["all_vs_all", "one_vs_all"]:
                    return self.format_error(
                        f"Invalid mode: {mode}",
                        "Use 'all_vs_all' or 'one_vs_all'"
                    )
                
                processor = self.get_processor("structure")
                self._ensure_structures_loaded(processor, pdb_ids)
                
                # Prepare structure data
                processed_structures = {}
                
                for pdb_id in pdb_ids:
                    frame = processor.load_entity(pdb_id)
                    if frame is None:
                        continue
                    pdb_data = frame.reset_index()
                    
                    if pdb_data.empty:
                        continue
                    
                    # Apply chain selection
                    if chain_selection:
                        pdb_data = pdb_data[pdb_data['auth_chain_id'] == chain_selection]
                    
                    # Apply atom selection
                    if atom_selection == "CA":
                        coords = pdb_data[pdb_data['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                    elif atom_selection == "backbone":
                        backbone_atoms = ['N', 'CA', 'C', 'O']
                        coords = pdb_data[pdb_data['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                    else:
                        coords = pdb_data[['x', 'y', 'z']].copy()
                    
                    # Ensure numeric types
                    for coord in ['x', 'y', 'z']:
                        coords[coord] = pd.to_numeric(coords[coord], errors='coerce')
                    
                    coords = coords.dropna()
                    
                    if not coords.empty:
                        processed_structures[pdb_id] = {'df_norm': coords}
                
                if len(processed_structures) < 2:
                    return self.format_error(
                        "Not enough valid structures after filtering",
                        "Check atom selection and chain availability"
                    )
                
                # Calculate RMSD matrix
                from protos.processing.structure.struct_alignment import (
                    structure_comparison_ava, structure_comparison_1va
                )
                
                if mode == "all_vs_all":
                    rmsd_matrix, structure_ids = structure_comparison_ava(processed_structures)
                    
                    # Convert to dictionary format
                    rmsd_dict = {}
                    for i, id1 in enumerate(structure_ids):
                        rmsd_dict[id1] = {}
                        for j, id2 in enumerate(structure_ids):
                            rmsd_dict[id1][id2] = round(float(rmsd_matrix[i, j]), 3)
                    
                    # Calculate statistics
                    rmsd_values = []
                    for i in range(len(structure_ids)):
                        for j in range(i + 1, len(structure_ids)):
                            rmsd_values.append(rmsd_matrix[i, j])
                    
                    return self.format_success({
                        "mode": "all_vs_all",
                        "num_structures": len(structure_ids),
                        "structure_ids": structure_ids,
                        "rmsd_matrix": rmsd_dict,
                        "min_rmsd": round(float(min(rmsd_values)), 3) if rmsd_values else 0,
                        "max_rmsd": round(float(max(rmsd_values)), 3) if rmsd_values else 0,
                        "mean_rmsd": round(float(sum(rmsd_values) / len(rmsd_values)), 3) if rmsd_values else 0,
                        "atom_selection": atom_selection,
                        "chain_selection": chain_selection
                    })
                    
                else:  # one_vs_all
                    rmsd_list, compared_ids = structure_comparison_1va(processed_structures)
                    reference_id = list(processed_structures.keys())[0]
                    
                    # Create dictionary format
                    rmsd_dict = {reference_id: {}}
                    for i, comp_id in enumerate(compared_ids):
                        rmsd_dict[reference_id][comp_id] = round(float(rmsd_list[i]), 3)
                    
                    return self.format_success({
                        "mode": "one_vs_all",
                        "reference_structure": reference_id,
                        "compared_structures": compared_ids,
                        "rmsd_values": rmsd_dict,
                        "min_rmsd": round(float(min(rmsd_list)), 3) if rmsd_list else 0,
                        "max_rmsd": round(float(max(rmsd_list)), 3) if rmsd_list else 0,
                        "mean_rmsd": round(float(sum(rmsd_list) / len(rmsd_list)), 3) if rmsd_list else 0,
                        "atom_selection": atom_selection,
                        "chain_selection": chain_selection
                    })
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def superimpose_structures(ctx, reference_pdb: str, mobile_pdb: str,
                                 output_name: str,
                                 atom_selection: str = "CA",
                                 chain_selection: Optional[str] = None) -> Dict:
            """
            Superimpose one structure onto another and save the result.
            
            This tool aligns a mobile structure onto a reference structure and
            saves the transformed coordinates as a new entity.
            
            Args:
                reference_pdb: PDB ID of the reference structure
                mobile_pdb: PDB ID of the structure to superimpose
                output_name: Name for the superimposed structure entity
                atom_selection: Atoms to use for alignment ("CA", "backbone", "all")
                chain_selection: Specific chain to align, or None for all
                
            Returns:
                Dictionary with superposition results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"reference_pdb": reference_pdb, "mobile_pdb": mobile_pdb, "output_name": output_name}, 
                    ["reference_pdb", "mobile_pdb", "output_name"]
                ):
                    return error
                
                processor = self.get_processor("structure")
                self._ensure_structures_loaded(processor, [reference_pdb, mobile_pdb])

                ref_frame = processor.load_entity(reference_pdb)
                mob_frame = processor.load_entity(mobile_pdb)
                if ref_frame is None or mob_frame is None:
                    return self.format_error(
                        "One or both structures not found",
                        "Ensure both structures are registered",
                    )

                ref_data = ref_frame.reset_index()
                mob_data = mob_frame.reset_index()
                
                if ref_data.empty or mob_data.empty:
                    return self.format_error(
                        "One or both structures not found",
                        "Ensure both structures are loaded"
                    )
                
                # Get alignment coordinates based on selection
                if chain_selection:
                    ref_align = ref_data[ref_data['auth_chain_id'] == chain_selection].copy()
                    mob_align = mob_data[mob_data['auth_chain_id'] == chain_selection].copy()
                else:
                    ref_align = ref_data.copy()
                    mob_align = mob_data.copy()
                
                if atom_selection == "CA":
                    ref_coords = ref_align[ref_align['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                    mob_coords = mob_align[mob_align['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                elif atom_selection == "backbone":
                    backbone_atoms = ['N', 'CA', 'C', 'O']
                    ref_coords = ref_align[ref_align['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                    mob_coords = mob_align[mob_align['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                else:
                    ref_coords = ref_align[['x', 'y', 'z']].copy()
                    mob_coords = mob_align[['x', 'y', 'z']].copy()
                
                # Ensure numeric types
                for coord in ['x', 'y', 'z']:
                    ref_coords[coord] = pd.to_numeric(ref_coords[coord], errors='coerce')
                    mob_coords[coord] = pd.to_numeric(mob_coords[coord], errors='coerce')
                
                ref_coords = ref_coords.dropna()
                mob_coords = mob_coords.dropna()
                
                # Perform alignment
                from protos.processing.structure.struct_alignment import align_structures
                
                aligned_coords, rotation, translation, alignment_path, rmsd = align_structures(
                    ref_coords, mob_coords
                )
                
                # Apply transformation to ALL atoms of mobile structure
                import numpy as np
                
                # Get all mobile structure coordinates
                all_mob_coords = mob_data[['x', 'y', 'z']].copy()
                for coord in ['x', 'y', 'z']:
                    all_mob_coords[coord] = pd.to_numeric(all_mob_coords[coord], errors='coerce')
                
                # Apply rotation and translation
                coords_array = all_mob_coords.values
                transformed_coords = np.dot(coords_array, rotation) + translation
                
                # Update mobile structure data with transformed coordinates
                transformed_data = mob_data.copy()
                transformed_data[['x', 'y', 'z']] = transformed_coords
                transformed_data['pdb_id'] = output_name  # Update PDB ID
                
                # Save transformed structure
                processor.save_entity(output_name, transformed_data)
                
                return self.format_success({
                    "reference_pdb": reference_pdb,
                    "mobile_pdb": mobile_pdb,
                    "output_name": output_name,
                    "rmsd": round(float(rmsd), 3),
                    "num_aligned_atoms": len(alignment_path[0]) if alignment_path else 0,
                    "total_atoms_transformed": len(transformed_data),
                    "atom_selection": atom_selection,
                    "chain_selection": chain_selection,
                    "saved": True
                })
                
            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def structure_compare_ligand_binding_sites(ctx, structures: List[Dict[str, str]],
                                       cutoff: float = 5.0,
                                       similarity_threshold: float = 0.5) -> Dict:
            """
            Compare binding sites across multiple protein-ligand complexes.
            
            This tool analyzes binding site conservation across structures, useful for:
            - Understanding binding mode conservation
            - Identifying key interaction residues
            - Comparing different ligands in the same pocket
            - Analyzing conformational changes upon ligand binding
            
            Args:
                structures: List of dicts with 'pdb_id', 'ligand_name', and optional 'chain_id'
                cutoff: Distance cutoff for binding site definition (Angstroms)
                similarity_threshold: Jaccard similarity threshold for grouping similar sites
                
            Returns:
                Dictionary with binding site comparison results including:
                - Pairwise binding site similarities
                - Conserved residues across all structures
                - Binding site clustering
                - Key differences between sites
            """
            try:
                # Validate parameters
                if not structures or len(structures) < 2:
                    return self.format_error(
                        "Need at least 2 structures to compare",
                        "Provide multiple structure-ligand pairs"
                    )
                
                for i, struct in enumerate(structures):
                    if 'pdb_id' not in struct or 'ligand_name' not in struct:
                        return self.format_error(
                            f"Structure {i} missing required fields",
                            "Each structure needs 'pdb_id' and 'ligand_name'"
                        )
                
                processor = self.get_processor("structure")
                pdb_ids = [s['pdb_id'] for s in structures]
                self._ensure_structures_loaded(processor, pdb_ids)
                
                # Import analysis functions
                try:
                    from protos.analysis.structure_ligand_analysis import (
                        get_ligand_by_id, get_binding_site, 
                        compare_ligand_binding_sites as compare_sites
                    )
                except ImportError:
                    return self.format_error(
                        "Binding site comparison module not available",
                        "Ensure protos.analysis is installed"
                    )
                
                # Collect binding sites for each structure
                binding_sites = {}
                site_residues = {}
                
                for struct in structures:
                    pdb_id = struct['pdb_id']
                    ligand_name = struct['ligand_name']
                    chain_id = struct.get('chain_id')
                    
                    # Get ligand atoms
                    ligand_atoms = get_ligand_by_id(
                        processor, pdb_id, ligand_name, chain_id
                    )
                    
                    if ligand_atoms is None or ligand_atoms.empty:
                        return self.format_error(
                            f"Ligand {ligand_name} not found in {pdb_id}",
                            "Check ligand names and chain IDs"
                        )
                    
                    # Get binding site
                    binding_site = get_binding_site(
                        processor, pdb_id, ligand_atoms, cutoff
                    )
                    
                    key = f"{pdb_id}_{ligand_name}"
                    if chain_id:
                        key += f"_{chain_id}"
                    
                    binding_sites[key] = binding_site
                    
                    # Extract residue identifiers for comparison
                    if not binding_site['residues'].empty:
                        residues = binding_site['residues']
                        site_residues[key] = set(
                            f"{row['res_name']}{row['res_id']}" 
                            for _, row in residues.iterrows()
                        )
                    else:
                        site_residues[key] = set()
                
                # Perform pairwise comparisons
                comparisons = []
                site_keys = list(site_residues.keys())
                
                for i in range(len(site_keys)):
                    for j in range(i + 1, len(site_keys)):
                        key1, key2 = site_keys[i], site_keys[j]
                        
                        # Calculate Jaccard similarity
                        residues1 = site_residues[key1]
                        residues2 = site_residues[key2]
                        
                        if residues1 or residues2:
                            intersection = residues1 & residues2
                            union = residues1 | residues2
                            similarity = len(intersection) / len(union) if union else 0
                            
                            comparisons.append({
                                "site1": key1,
                                "site2": key2,
                                "similarity": round(similarity, 3),
                                "shared_residues": list(intersection),
                                "unique_to_site1": list(residues1 - residues2),
                                "unique_to_site2": list(residues2 - residues1)
                            })
                
                # Find conserved residues across all sites
                all_residues = list(site_residues.values())
                if all_residues:
                    conserved_residues = set.intersection(*all_residues) if all_residues else set()
                    variable_residues = set.union(*all_residues) - conserved_residues
                else:
                    conserved_residues = set()
                    variable_residues = set()
                
                # Group similar binding sites
                site_groups = []
                grouped = set()
                
                for i, key in enumerate(site_keys):
                    if key in grouped:
                        continue
                    
                    group = [key]
                    grouped.add(key)
                    
                    # Find all sites similar to this one
                    for comp in comparisons:
                        if comp['similarity'] >= similarity_threshold:
                            if comp['site1'] == key and comp['site2'] not in grouped:
                                group.append(comp['site2'])
                                grouped.add(comp['site2'])
                            elif comp['site2'] == key and comp['site1'] not in grouped:
                                group.append(comp['site1'])
                                grouped.add(comp['site1'])
                    
                    if len(group) > 1:
                        site_groups.append(group)
                
                # Calculate binding site statistics
                site_stats = {}
                for key, residues in site_residues.items():
                    site_stats[key] = {
                        "num_residues": len(residues),
                        "residue_list": sorted(list(residues))
                    }
                
                result = {
                    "num_structures": len(structures),
                    "cutoff": cutoff,
                    "site_statistics": site_stats,
                    "conserved_residues": sorted(list(conserved_residues)),
                    "variable_residues": sorted(list(variable_residues)),
                    "conservation_ratio": round(
                        len(conserved_residues) / len(conserved_residues | variable_residues), 3
                    ) if conserved_residues or variable_residues else 0,
                    "pairwise_comparisons": comparisons,
                    "similar_site_groups": site_groups,
                    "similarity_threshold": similarity_threshold
                }
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def structure_align_to_reference(
            ctx,
            reference_id: str,
            structure_ids: List[str],
            method: str = "cealign",
            atom_selection: str = "CA",
            apply_transform: bool = True,
            chain_id: Optional[str] = None,
            cealign_window: int = 8,
            cealign_max_gap: int = 30,
            export_aligned: bool = False,
            export_format: str = "cif",
            export_directory: Optional[str] = None,
            save_dataset_name: Optional[str] = None,
            include_reference_in_dataset: bool = True,
            persist_aligned: bool = False,
            summary_name: Optional[str] = None,
            property_table_name: Optional[str] = None,
        ) -> Dict:
            """Align structures via `StructureProcessor.align_and_record` and surface registry artifacts."""

            if error := self.validate_required_params(
                {"reference_id": reference_id, "structure_ids": structure_ids},
                ["reference_id", "structure_ids"],
            ):
                return error

            ordered_ids = list(dict.fromkeys(structure_ids))
            targets = [sid for sid in ordered_ids if sid != reference_id]

            if not targets:
                return self.format_error(
                    "No alignable structures provided",
                    "Provide at least one structure ID different from the reference.",
                )

            processor = self.get_processor("structure")

            try:
                if processor.load_entity(reference_id) is None:
                    return self.format_error(
                        f"Reference structure '{reference_id}' not available",
                        "Download the reference structure before aligning.",
                    )

                missing = [sid for sid in targets if processor.load_entity(sid) is None]
                if missing:
                    return self.format_error(
                        f"Structures not available: {', '.join(missing)}",
                        "Download structures first with download_entity or download_entities.",
                    )

                summary_metadata = {
                    "requested_by": "structure_align_to_reference",
                    "requested_at": datetime.utcnow().isoformat(),
                }

                summary_payload, _ = processor.align_and_record(
                    structure_ids=targets,
                    reference_id=reference_id,
                    method=method,
                    atom_selection=atom_selection,
                    chain_id=chain_id,
                    cealign_window=cealign_window,
                    cealign_max_gap=cealign_max_gap,
                    apply_transform=apply_transform,
                    save_aligned=persist_aligned or export_aligned or bool(save_dataset_name),
                    summary_name=summary_name,
                    summary_metadata=summary_metadata,
                    aligned_dataset_name=save_dataset_name,
                    aligned_dataset_include_reference=include_reference_in_dataset,
                    property_table_name=property_table_name,
                )

                pairwise = summary_payload.get("rmsd", {}).get("pairwise", [])
                results_map = summary_payload.get("results", {})

                rmsd_map: Dict[str, Dict[str, Optional[float]]] = {}
                alignments: List[Dict[str, Any]] = []

                for row in pairwise:
                    target = row.get("target_id")
                    reference = row.get("reference_id")
                    if not target or not reference:
                        continue
                    rmsd_map.setdefault(target, {})[reference] = row.get("rmsd")
                    result_info = results_map.get(target, {})
                    alignments.append(
                        {
                            "structure_id": target,
                            "reference_id": reference,
                            "aligned_id": result_info.get("aligned_id"),
                            "rmsd": row.get("rmsd"),
                            "algorithm": row.get("algorithm") or result_info.get("algorithm"),
                            "error": result_info.get("error"),
                        }
                    )

                export_paths: Dict[str, str] = {}
                if export_aligned and summary_payload.get("aligned_entities"):
                    export_dir_path = (
                        Path(export_directory)
                        if export_directory
                        else Path(self.paths.get_processor_path("structure")) / "aligned_exports"
                    )
                    export_dir_path.mkdir(parents=True, exist_ok=True)
                    try:
                        exported = processor.export_aligned_structures(
                            structure_ids=summary_payload.get("aligned_entities"),
                            output_dir=export_dir_path,
                            overwrite=True,
                            export_format=export_format,
                        )
                        export_paths = {name: str(path) for name, path in exported.items()}
                    except Exception as exc:  # noqa: BLE001
                        export_paths = {"error": str(exc)}

                payload: Dict[str, Any] = {
                    "reference_id": reference_id,
                    "structure_ids": targets,
                    "summary": summary_payload.get("rmsd", {}).get("global"),
                    "rmsd_map": rmsd_map,
                    "alignments": alignments,
                    "atom_selection": atom_selection,
                    "method": method,
                    "apply_transform": apply_transform,
                }

                if chain_id:
                    payload["chain_id"] = chain_id

                if export_paths:
                    payload["exported_files"] = export_paths

                if summary_payload.get("summary_file"):
                    payload["summary_file"] = summary_payload["summary_file"]

                if summary_payload.get("summary_dataset"):
                    payload["summary_dataset"] = summary_payload["summary_dataset"]

                if summary_payload.get("aligned_dataset") is not None:
                    payload["aligned_dataset"] = summary_payload["aligned_dataset"]
                    if summary_payload.get("aligned_dataset"):
                        aligned_entities = summary_payload.get("aligned_entities", []) or []
                        entity_count = len(aligned_entities)
                        if include_reference_in_dataset and reference_id not in aligned_entities:
                            entity_count += 1
                        payload["dataset"] = {
                            "name": summary_payload["aligned_dataset"],
                            "entity_count": entity_count,
                        }

                if summary_payload.get("property_table"):
                    payload["property_table"] = summary_payload["property_table"]

                if summary_payload.get("aligned_entities"):
                    payload["aligned_entities"] = summary_payload["aligned_entities"]

                if summary_payload.get("summary_name"):
                    payload["summary_name"] = summary_payload["summary_name"]

                if summary_payload.get("metadata"):
                    payload["metadata"] = summary_payload["metadata"]

                if summary_payload.get("errors"):
                    payload["errors"] = summary_payload["errors"]

                return self.format_success(payload)

            except Exception as exc:
                return self.handle_error(exc)

        @server.tool()
        def structure_dataset_stats(
            ctx,
            dataset_name: str,
            include_entities: bool = False,
        ) -> Dict:
            """Summarize a structure dataset (entity counts, metadata)."""

            if error := self.validate_required_params(
                {"dataset_name": dataset_name}, ["dataset_name"],
            ):
                return error

            processor = self.get_processor("structure")
            manager = getattr(processor, "dataset_manager", None)
            if manager is None or not manager.dataset_exists(dataset_name):
                return self.format_error(
                    f"Structure dataset '{dataset_name}' not found",
                    "Use dataset.list_datasets to confirm available structure datasets.",
                )

            info = manager.get_dataset_info(dataset_name)
            entities = manager.get_dataset_entities(dataset_name)

            preview = []
            if include_entities:
                preview = entities[: min(25, len(entities))]

            result = {
                "dataset_name": dataset_name,
                "entity_count": len(entities),
                "metadata": info.get("metadata", {}),
            }
            if include_entities:
                result["entities"] = preview
                result["truncated"] = len(entities) > len(preview)

            return self.format_success(result)
        @server.tool()
        def extract_sequences_from_structure(ctx, pdb_id: str,
                                           chain_ids: Optional[List[str]] = None,
                                           save_as_fasta: Optional[str] = None) -> Dict:
            """
            Extract amino acid sequences from protein chains in a structure.
            
            This tool extracts sequences from specified chains (or all chains) in a 
            protein structure and optionally saves them as a FASTA file using the 
            sequence processor.
            
            Args:
                pdb_id: PDB ID of the structure
                chain_ids: List of chain IDs to extract (None for all chains)
                save_as_fasta: Name to save sequences as FASTA file (without extension)
                
            Returns:
                Dictionary with extracted sequences and metadata
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id}, 
                    ["pdb_id"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                collected = processor.collect_chain_sequences([pdb_id])
                chain_payloads = collected.get(pdb_id, {})

                if not chain_payloads:
                    return self.format_error(
                        f"Structure {pdb_id} not found or contains no chains",
                        "Ensure the structure is registered and chain sequences are available",
                    )

                available_chains = list(chain_payloads.keys())
                if chain_ids:
                    chains_to_extract = [c for c in chain_ids if c in available_chains]
                    if not chains_to_extract:
                        return self.format_error(
                            f"None of the specified chains {chain_ids} found in structure",
                            f"Available chains: {available_chains}",
                        )
                else:
                    chains_to_extract = available_chains

                sequences: Dict[str, str] = {}
                for chain_id in chains_to_extract:
                    payload = chain_payloads.get(chain_id)
                    sequence = payload.get("sequence") if payload else None
                    if not sequence:
                        continue
                    seq_name = payload.get("entity_name") or f"{pdb_id}_chain_{chain_id}"
                    sequences[seq_name] = sequence

                result = {
                    "pdb_id": pdb_id,
                    "chains_extracted": chains_to_extract,
                    "sequences": sequences,
                    "sequence_count": len(sequences),
                }
                
                # Save as FASTA if requested
                if save_as_fasta and sequences:
                    try:
                        seq_processor = self.get_processor("sequence")
                        seq_processor.save_sequences(sequences, save_as_fasta)
                        result["saved_as"] = f"{save_as_fasta}.fasta"
                        result["message"] = f"Sequences saved to {save_as_fasta}.fasta"
                    except Exception as exc:
                        result["save_error"] = str(exc)
                        result["message"] = "Sequences extracted but failed to save as FASTA"
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def structure_extract_all_chains_from_dataset(ctx, dataset_name: str,
                                          save_as_fasta: Optional[str] = None,
                                          chain_filter: Optional[List[str]] = None) -> Dict:
            """
            Extract sequences from all structures in a dataset.
            
            This tool processes an entire structure dataset, extracting sequences
            from all chains (or filtered chains) and optionally saving them as
            a FASTA file.
            
            Args:
                dataset_name: Name of the structure dataset
                save_as_fasta: Name to save all sequences as FASTA file
                chain_filter: List of chain IDs to include (e.g., ['A', 'B'])
                
            Returns:
                Dictionary with extraction results and statistics
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, 
                    ["dataset_name"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                structures = processor.get_dataset_entities(dataset_name)

                if not structures:
                    return self.format_error(
                        f"Dataset '{dataset_name}' has no registered structures",
                        "Use the structure loader to populate the dataset first"
                    )

                collected = processor.collect_chain_sequences(
                    structures,
                    chain_filter=chain_filter,
                )

                all_sequences = {}
                failed_structures: List[Dict[str, Any]] = []
                chain_stats: Dict[str, int] = {}

                for pdb_id in structures:
                    chains = collected.get(pdb_id, {})
                    if not chains:
                        failed_structures.append({
                            "pdb_id": pdb_id,
                            "error": "No extractable chains",
                        })
                        continue

                    for chain_id, payload in chains.items():
                        sequence_id = payload.get("entity_name") or f"{pdb_id}_chain_{chain_id}"
                        sequence = payload.get("sequence")
                        if not sequence:
                            continue

                        all_sequences[sequence_id] = sequence
                        chain_stats[chain_id] = chain_stats.get(chain_id, 0) + 1

                result = {
                    "dataset_name": dataset_name,
                    "total_structures": len(structures),
                    "successful_structures": len(structures) - len(failed_structures),
                    "total_sequences": len(all_sequences),
                    "chain_statistics": chain_stats,
                    "failed_structures": failed_structures
                }
                
                # Save as FASTA if requested
                if save_as_fasta and all_sequences:
                    try:
                        seq_processor = self.get_processor("sequence")
                        metadata = {
                            "source": f"structure_dataset:{dataset_name}",
                            "chain_filter": chain_filter,
                            "extraction_date": datetime.now().isoformat(),
                        }
                        seq_processor.save_sequences(
                            all_sequences,
                            save_as_fasta,
                            dataset_name=save_as_fasta,
                            metadata=metadata,
                            materialize_entities=True,
                        )

                        result["saved_as"] = f"{save_as_fasta}.fasta"
                        result["sequence_dataset"] = save_as_fasta
                        result["message"] = (
                            f"Sequences saved to {save_as_fasta}.fasta and registered as dataset"
                        )
                    except Exception as e:
                        result["save_error"] = str(e)
                        result["message"] = "Sequences extracted but failed to save"
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def structure_graph_generate_from_dataset(
            ctx,
            structure_dataset: str,
            dataset_name: Optional[str] = None,
            level: str = "atom",
            cutoff: float = 5.0,
            include_hydrogens: bool = False,
        ) -> Dict:
            """Generate graphs for each structure in a dataset using GraphProcessor."""

            if error := self.validate_required_params(
                {"structure_dataset": structure_dataset}, ["structure_dataset"]
            ):
                return error

            graph_processor = self.get_processor("graph")

            try:
                dataset_id, entities = graph_processor.generate_graphs_from_dataset(
                    structure_dataset=structure_dataset,
                    dataset_name=dataset_name,
                    level=level,
                    cutoff=cutoff,
                    include_hydrogens=include_hydrogens,
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            return self.format_success(
                {
                    "structure_dataset": structure_dataset,
                    "graph_dataset": dataset_id,
                    "graph_entities": entities,
                    "entity_count": len(entities),
                    "metadata": {
                        "level": level,
                        "cutoff": cutoff,
                        "include_hydrogens": include_hydrogens,
                    },
                },
                message="Graph dataset generated",
            )

        @server.tool()
        def structure_graph_load_entity(
            ctx,
            graph_name: str,
            include_data: bool = False,
            preview_nodes: int = 50,
        ) -> Dict:
            """Load a graph entity and summarize its contents."""

            if error := self.validate_required_params(
                {"graph_name": graph_name}, ["graph_name"]
            ):
                return error

            processor = self.get_processor("graph")

            try:
                graph_payload = processor.load_graph(graph_name)
            except FileNotFoundError:
                return self.format_error(
                    f"Graph '{graph_name}' not found",
                    "Generate graphs first or verify the entity name.",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            metadata = graph_payload.get("graph_metadata", {})
            node_count = metadata.get("node_count")
            edge_count = metadata.get("edge_count")

            response: Dict[str, Any] = {
                "graph_name": graph_name,
                "metadata": metadata,
                "node_count": node_count,
                "edge_count": edge_count,
            }

            if include_data:
                data = graph_payload.get("graph")
                if hasattr(data, "to_dict"):
                    preview = data.to_dict()
                else:
                    preview = data

                if isinstance(preview, dict) and "x" in preview:
                    node_features = preview["x"]
                    if hasattr(node_features, "detach"):
                        node_features = node_features.detach().cpu()
                    if hasattr(node_features, "numpy"):
                        node_features = node_features.numpy()
                    response["node_features_preview"] = node_features[:preview_nodes].tolist()

                response["graph_data"] = preview

            return self.format_success(response)

        @server.tool()
        def structure_filter_dataset(
            ctx,
            dataset_name: str,
            filters: Optional[Dict[str, Any]] = None,
            query: Optional[str] = None,
            new_dataset_name: Optional[str] = None,
            suffix: str = "_filtered",
            register_filtered: bool = True,
            drop_empty: bool = True,
        ) -> Dict:
            """Filter structures in a dataset by column values and optionally register the results."""

            if error := self.validate_required_params(
                {"dataset_name": dataset_name}, ["dataset_name"],
            ):
                return error

            if filters is not None and not isinstance(filters, dict):
                return self.format_error(
                    "Invalid filters payload",
                    "Provide a mapping of column names to single values or lists of values.",
                )

            processor = self.get_processor("structure")
            manager = processor.dataset_manager

            if not manager.dataset_exists(dataset_name):
                return self.format_error(
                    f"Structure dataset '{dataset_name}' not found",
                    "Use the structure loader tools to populate it first.",
                )

            structure_ids = manager.get_dataset_entities(dataset_name)
            if not structure_ids:
                return self.format_error(
                    f"Dataset '{dataset_name}' has no registered structures",
                    "Add structures before applying filters.",
                )

            target_dataset = (
                new_dataset_name or f"{dataset_name}{suffix}"
                if register_filtered
                else dataset_name
            )

            summaries: List[Dict[str, Any]] = []
            filtered_entities: List[str] = []
            failures: List[Dict[str, Any]] = []

            for structure_id in structure_ids:
                target_id = f"{structure_id}{suffix}" if register_filtered else structure_id

                try:
                    filtered_df = processor.filter_structure(
                        structure_id,
                        filters=filters,
                        query=query,
                        new_id=target_id,
                        register=register_filtered,
                        metadata={
                            "source_structure": structure_id,
                            "filters": filters,
                            "query": query,
                        }
                        if register_filtered
                        else None,
                    )
                except ValueError as exc:
                    if drop_empty:
                        failures.append(
                            {
                                "structure_id": structure_id,
                                "error": str(exc),
                            }
                        )
                        continue
                    filtered_df = None
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        {
                            "structure_id": structure_id,
                            "error": str(exc),
                        }
                    )
                    continue

                if filtered_df is None:
                    continue

                filtered_entities.append(target_id)
                summaries.append(
                    {
                        "structure_id": structure_id,
                        "filtered_structure": target_id,
                        "atom_count": int(len(filtered_df)),
                    }
                )

            if register_filtered and filtered_entities:
                metadata = {
                    "source_dataset": dataset_name,
                    "filters": filters,
                    "query": query,
                    "entity_count": len(filtered_entities),
                }
                if manager.dataset_exists(target_dataset):
                    manager.delete_dataset(target_dataset)
                processor.create_dataset(target_dataset, filtered_entities, metadata)

            if not filtered_entities:
                return self.format_error(
                    "No structures passed the filter",
                    "Adjust the filters or disable drop_empty to keep empty results.",
                )

            return self.format_success(
                {
                    "source_dataset": dataset_name,
                    "filtered_dataset": target_dataset if register_filtered else None,
                    "filtered_count": len(filtered_entities),
                    "filtered_entities": filtered_entities,
                    "summaries": summaries,
                    "failures": failures,
                    "filters": filters,
                    "query": query,
                    "registered": register_filtered,
                },
                message="Structure dataset filtered",
            )

        @server.tool()
        def structure_register_chain_sequences_from_dataset(
            ctx,
            dataset_name: str,
            dataset_prefix: Optional[str] = None,
            chain_filter: Optional[Union[List[str], Dict[str, List[str]], str]] = None,
            create_dataset: bool = True,
            overwrite: bool = False,
            min_length: int = 1,
            one_letter: bool = True,
        ) -> Dict:
            """Register per-chain sequences for all structures in a dataset."""

            try:
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name},
                    ["dataset_name"],
                ):
                    return error

                processor = self.get_processor("structure")

                structures = processor.get_dataset_entities(dataset_name)
                if not structures:
                    return self.format_error(
                        f"Dataset '{dataset_name}' has no registered structures",
                        "Use the structure loaders to populate it first",
                    )

                summary = processor.register_chain_sequences(
                    structures,
                    chain_filter=chain_filter,
                    one_letter=one_letter,
                    min_length=min_length,
                    dataset_prefix=dataset_prefix,
                    create_dataset=create_dataset,
                    overwrite=overwrite,
                )

                total_sequences = 0
                registered_entities: List[str] = []
                created_datasets: Dict[str, Optional[str]] = {}

                for struct_id, payload in summary.items():
                    chains = payload.get("chains", {})
                    total_sequences += len(chains)
                    created_datasets[struct_id] = payload.get("dataset")
                    registered_entities.extend(payload.get("registered_entities", []))

                return self.format_success(
                    {
                        "dataset_name": dataset_name,
                        "structures": structures,
                        "total_sequences": total_sequences,
                        "registered_entities": registered_entities,
                        "structure_datasets": created_datasets,
                        "create_dataset": create_dataset,
                        "overwrite": overwrite,
                        "chain_filter": chain_filter,
                        "one_letter": one_letter,
                        "min_length": min_length,
                    }
                )

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)
        @server.tool()
        def structure_get_sequences_and_save_fasta(
            ctx,
            pdb_ids: List[str],
            fasta_name: str,
            use_chain_dict: bool = True,
        ) -> Dict:
            """
            Extract sequences from structures using get_seq_dict/get_chain_dict and save as FASTA.
            
            This helper collects chain sequences for the provided structures and
            saves them as a FASTA file using the sequence processor. The
            `use_chain_dict` flag is kept for backward compatibility but no
            longer changes behaviour (chain extraction always uses the unified
            `collect_chain_sequences`).

            Args:
                pdb_ids: List of PDB IDs to process
                fasta_name: Name for the output FASTA file (without extension)
                use_chain_dict: Deprecated; retained for backwards compatibility
                
            Returns:
                Dictionary with extraction results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_ids": pdb_ids, "fasta_name": fasta_name}, 
                    ["pdb_ids", "fasta_name"]
                ):
                    return error
                
                if not pdb_ids:
                    return self.format_error(
                        "No PDB IDs provided",
                        "Provide at least one PDB ID"
                    )
                
                struct_processor = self.get_processor("structure")
                collected = struct_processor.collect_chain_sequences(pdb_ids)

                sequences: Dict[str, str] = {}
                for pdb_id, chains in collected.items():
                    for chain_id, payload in chains.items():
                        sequence = payload.get("sequence")
                        if not sequence:
                            continue
                        seq_name = payload.get("entity_name") or f"{pdb_id}_chain_{chain_id}"
                        sequences[seq_name] = sequence

                if not sequences:
                    return self.format_error(
                        "No sequences extracted",
                        "Check that the supplied structures contain protein chains",
                    )

                # Get sequence processor and save as FASTA
                seq_processor = self.get_processor("sequence")
                seq_processor.save_sequences(sequences, fasta_name)

                # Create a sequence dataset
                seq_processor.create_dataset(
                    fasta_name,
                    list(sequences.keys()),
                    {
                        "source_structures": pdb_ids,
                        "extraction_method": "collect_chain_sequences",
                        "total_sequences": len(sequences)
                    }
                )
                
                result = {
                    "pdb_ids_processed": pdb_ids,
                    "total_sequences": len(sequences),
                    "fasta_file": f"{fasta_name}.fasta",
                    "sequence_dataset": fasta_name,
                    "method_used": "get_chain_dict" if use_chain_dict else "get_seq_dict",
                    "sequences_extracted": list(sequences.keys())[:10] + (["..."] if len(sequences) > 10 else [])
                }
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
