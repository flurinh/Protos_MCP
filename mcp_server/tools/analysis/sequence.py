"""
Sequence analysis tools leveraging Protos' SequenceProcessor.

These tools provide sequence analysis capabilities including alignment,
identity calculation, conservation analysis, and mutation detection.
"""

from typing import Dict, List, Optional, Any, Tuple, Union
from datetime import datetime
import json
import logging

from ..base import BaseTool
from ...core.context_preview import PreviewLimits, build_sequence_preview
from ...core.exceptions import InvalidInputError, EntityNotFoundError
from protos.analysis.sequence.alignment_engine import SequenceAlignmentEngine
from protos.analysis.sequence.mmseqs_interface import MMseqsUnavailableError

logger = logging.getLogger(__name__)


SEQUENCE_PREVIEW_LIMITS = PreviewLimits()


class SequenceAnalysisTools(BaseTool):
    """Tools for sequence analysis and processing."""

    def register(self, server):
        """Register sequence analysis tools with the server."""

        @server.tool()
        def list_sequence_entities(
            ctx, limit: Optional[int] = None, offset: int = 0
        ) -> Dict:
            """List registered sequence entities with optional pagination."""

            try:
                processor = self.get_processor("sequence")
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
        def load_sequence(
            ctx,
            sequence_id: str,
            include_sequence: bool = False,
            preview_length: int = 120,
        ) -> Dict:
            """Load a sequence entity and return summary details."""

            try:
                if error := self.validate_required_params(
                    {"sequence_id": sequence_id},
                    ["sequence_id"],
                ):
                    return error

                processor = self.get_processor("sequence")
                entity = processor.load_entity(sequence_id)
                if entity is None:
                    return self.format_error(
                        f"Sequence '{sequence_id}' not found",
                        "Use sequence_download or sequence_register_records first.",
                    )

                limits = SEQUENCE_PREVIEW_LIMITS.override(
                    max_chars=min(preview_length, SEQUENCE_PREVIEW_LIMITS.max_chars),
                    max_items=min(50, SEQUENCE_PREVIEW_LIMITS.max_items),
                )

                payload: Dict[str, Any] = {
                    "sequence_id": sequence_id,
                    "entity_type": (
                        "multi"
                        if isinstance(entity, dict) and len(entity) > 1
                        else "single"
                    ),
                }

                preview = build_sequence_preview(
                    entity if isinstance(entity, (str, dict)) else str(entity),
                    limits=limits,
                    preview_length=preview_length,
                    label=sequence_id,
                ).export()

                payload["preview_summary"] = preview

                if isinstance(entity, str):
                    payload["length"] = preview["summary"].get("length")
                    payload["preview"] = preview.get("preview")
                    # Explicit include_sequence=True request is honored
                    if include_sequence:
                        payload["sequence"] = entity
                elif isinstance(entity, dict):
                    payload["sequence_count"] = preview["summary"].get("sequence_count")
                    payload["sequences"] = preview.get("preview")
                    # Explicit include_sequence=True request is honored
                    if include_sequence:
                        payload["full_sequences"] = entity
                else:
                    payload["data"] = preview.get("preview")

                return self.format_success(payload)
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def load_sequence_dataset(
            ctx,
            dataset_name: str,
            include_sequences: bool = False,
            max_sequences: int = 50,
            preview_length: int = 120,
        ) -> Dict:
            """Load a sequence dataset and summarize its members."""

            try:
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
                        "Use dataset.list_datasets or create the dataset first.",
                    )

                dataset = processor.load_dataset(dataset_name)
                if not isinstance(dataset, dict):
                    dataset = dict(dataset)

                info = manager.get_dataset_info(dataset_name)

                summary = []
                for key, value in list(dataset.items())[:max_sequences]:
                    length = len(value) if isinstance(value, str) else None
                    preview = value[:preview_length] if isinstance(value, str) else None
                    summary.append(
                        {
                            "sequence_id": key,
                            "length": length,
                            "preview": preview,
                        }
                    )

                limits = SEQUENCE_PREVIEW_LIMITS.override(
                    max_chars=max(200, min(preview_length, SEQUENCE_PREVIEW_LIMITS.max_chars)),
                    max_items=min(max_sequences, SEQUENCE_PREVIEW_LIMITS.max_items),
                )

                preview = build_sequence_preview(
                    dataset,
                    limits=limits,
                    preview_length=preview_length,
                    label=dataset_name,
                ).export()

                # Return metadata and entity IDs
                payload: Dict[str, Any] = {
                    "dataset_name": dataset_name,
                    "sequence_count": len(dataset),
                    "metadata": info.get("metadata", {}),
                    "entity_ids": list(dataset.keys())[:max_sequences],
                    "truncated": len(dataset) > max_sequences,
                }

                # Include basic stats
                if dataset:
                    lengths = [len(v) for v in dataset.values() if isinstance(v, str)]
                    if lengths:
                        payload["length_stats"] = {
                            "min": min(lengths),
                            "max": max(lengths),
                            "avg": round(sum(lengths) / len(lengths), 1),
                        }

                # If include_sequences explicitly requested, honor it
                # Explicit request = user/workflow needs the data
                if include_sequences:
                    payload["sequences"] = {
                        k: v for k, v in list(dataset.items())[:max_sequences]
                        if isinstance(v, str)
                    }
                else:
                    payload["note"] = "Sequences available in Protos context. Use include_sequences=True to retrieve."

                return self.format_success(payload)
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def sequence_save_sequences(
            ctx,
            sequences: Dict[str, str],
            output_file: Optional[str] = None,
            dataset_name: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None,
            materialize_entities: bool = False,
        ) -> Dict:
            """Persist multiple sequences via SequenceProcessor.save_sequences."""

            try:
                if error := self.validate_required_params(
                    {"sequences": sequences},
                    ["sequences"],
                ):
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

                return self.format_success(
                    {
                        "dataset_name": dataset_key,
                        "artifact_path": str(path),
                        "sequence_count": len(sequences),
                        "materialized": materialize_entities,
                        "metadata": dataset_info.get("metadata", {}),
                    },
                    message="Sequences saved",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def sequence_export_dataset(
            ctx,
            dataset_name: str,
            export_name: Optional[str] = None,
            sequence_ids: Optional[List[str]] = None,
            materialize_entities: bool = False,
            overwrite: bool = True,
            format: str = "fasta",
        ) -> Dict:
            """Export a sequence dataset to a managed FASTA artifact."""

            try:
                processor = self.get_processor("sequence")
                exported = processor.export_dataset(
                    dataset_name,
                    export_name=export_name,
                    format=format,
                    overwrite=overwrite,
                    sequence_ids=sequence_ids,
                    materialize_entities=materialize_entities,
                )

                return self.format_success(
                    exported,
                    message="Dataset exported",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def sequence_export_entity(
            ctx,
            sequence_id: str,
            export_name: Optional[str] = None,
            sequence_ids: Optional[List[str]] = None,
            overwrite: bool = True,
            format: str = "fasta",
        ) -> Dict:
            """Export a single sequence entity to FASTA."""

            try:
                processor = self.get_processor("sequence")
                exported = processor.export_entity(
                    sequence_id,
                    export_name=export_name,
                    format=format,
                    overwrite=overwrite,
                    sequence_ids=sequence_ids,
                )

                return self.format_success(
                    exported,
                    message="Sequence exported",
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def align_sequences(
            ctx,
            sequence1: str,
            sequence2: str,
            alignment_method: str = "blosum62",
            gap_open: int = -10,
            gap_extend: int = -1,
        ) -> Dict:
            """
            Perform pairwise sequence alignment using raw sequences.

            Note: For entity-based alignment, use align_sequences_by_id instead.

            Args:
                sequence1: First sequence (raw string)
                sequence2: Second sequence (raw string)
                alignment_method: Alignment method ("blosum62", "pam250", etc.)
                gap_open: Gap opening penalty
                gap_extend: Gap extension penalty

            Returns:
                Dictionary with alignment results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"sequence1": sequence1, "sequence2": sequence2},
                    ["sequence1", "sequence2"],
                ):
                    return error

                # Get sequence processor
                processor = self.get_processor("sequence")

                # Perform alignment
                from protos.processing.sequence.seq_alignment import (
                    init_aligner,
                    align_blosum62,
                    format_alignment,
                )

                aligner = init_aligner()

                if alignment_method == "blosum62":
                    # Note: align_blosum62 doesn't accept gap penalty parameters
                    alignment = align_blosum62(
                        sequence1,
                        sequence2,
                        aligner,
                    )
                else:
                    # Use generic alignment
                    alignment = aligner.align(sequence1, sequence2)[0][0]

                # Format alignment - returns [target, midline, query]
                formatted = format_alignment(alignment)
                aligned_seq1, midline, aligned_seq2 = formatted

                # Calculate statistics
                matches = sum(
                    1 for a, b in zip(aligned_seq1, aligned_seq2) if a == b and a != "-"
                )
                length = len(
                    [
                        a
                        for a, b in zip(aligned_seq1, aligned_seq2)
                        if a != "-" or b != "-"
                    ]
                )
                identity = matches / length if length > 0 else 0

                # Count gaps
                gaps_seq1 = aligned_seq1.count("-")
                gaps_seq2 = aligned_seq2.count("-")

                # In LLM-safe mode, don't return full alignment strings
                alignment_response: Dict[str, Any] = {
                    "score": float(alignment.score),
                    "identity": round(identity, 3),
                    "matches": matches,
                    "length": length,
                    "gaps_seq1": gaps_seq1,
                    "gaps_seq2": gaps_seq2,
                    "method": alignment_method,
                }

                # Only include alignment text if not in LLM-safe mode
                if not self.llm_safe_mode:
                    alignment_response["alignment"] = formatted

                return self.format_success(alignment_response)

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def align_sequences_by_id(
            ctx,
            entity1: str,
            entity2: str,
            alignment_method: str = "blosum62",
            store_alignment: bool = True,
            include_alignment: bool = False,
        ) -> Dict:
            """
            Perform pairwise sequence alignment using entity identifiers.

            This tool loads sequences from Protos storage rather than requiring
            the full sequence strings as input.

            Args:
                entity1: Entity identifier for first sequence.
                entity2: Entity identifier for second sequence.
                alignment_method: Currently only ``"blosum62"`` is supported.
                store_alignment: If True, persist the alignment via SequenceProcessor.
                include_alignment: If True, include full aligned sequences in response.
                    Defaults to False to minimize context usage.

            Returns:
                Dictionary with alignment results (score, identity, gaps, etc.).
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"entity1": entity1, "entity2": entity2}, ["entity1", "entity2"]
                ):
                    return error

                # Get sequence processor
                processor = self.get_processor("sequence")

                # Load sequences from storage
                try:
                    seq1_data = processor.load_entity(entity1)
                    seq2_data = processor.load_entity(entity2)
                except Exception as e:
                    return self.format_error(
                        f"Failed to load sequences: {str(e)}",
                        "Ensure both entities exist in sequence processor",
                    )

                # Extract sequence strings
                if isinstance(seq1_data, dict):
                    # Handle multi-sequence files
                    seq1 = list(seq1_data.values())[0] if seq1_data else ""
                else:
                    seq1 = str(seq1_data)

                if isinstance(seq2_data, dict):
                    seq2 = list(seq2_data.values())[0] if seq2_data else ""
                else:
                    seq2 = str(seq2_data)

                if not seq1 or not seq2:
                    return self.format_error(
                        "Empty sequences found",
                        "Check that entities contain valid sequence data",
                    )

                # Perform alignment
                if alignment_method.lower() != "blosum62":
                    return self.format_error(
                        f"Unsupported alignment method '{alignment_method}'",
                        "Currently only 'blosum62' alignment is exposed through this tool.",
                    )

                score, formatted = processor.align_sequences(
                    seq1,
                    seq2,
                    seq1_id=entity1,
                    seq2_id=entity2,
                    store_alignment=store_alignment,
                )

                aligned_seq1, aligned_midline, aligned_seq2 = formatted
                matches = sum(
                    1 for a, b in zip(aligned_seq1, aligned_seq2) if a == b and a != "-"
                )
                length = len(
                    [
                        1
                        for a, b in zip(aligned_seq1, aligned_seq2)
                        if a != "-" or b != "-"
                    ]
                )
                identity = matches / length if length else 0.0

                result = {
                    "entity1": entity1,
                    "entity2": entity2,
                    "score": float(score),
                    "identity": round(identity, 3),
                    "matches": matches,
                    "length": length,
                    "gaps_seq1": aligned_seq1.count("-"),
                    "gaps_seq2": aligned_seq2.count("-"),
                    "method": "blosum62",
                    "stored": store_alignment,
                }
                # Only include full alignment if explicitly requested
                if include_alignment:
                    result["alignment"] = formatted
                else:
                    result["note"] = "Alignment stored in Protos context. Use include_alignment=True for full data."

                return self.format_success(result)

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def sequence_align_to_reference(
            ctx,
            reference_id: str,
            sequence_ids: List[str],
            save_alignments: bool = False,
            aligned_dataset_name: Optional[str] = None,
            include_reference_in_dataset: bool = True,
            summary_name: Optional[str] = None,
            property_table_name: Optional[str] = None,
        ) -> Dict:
            """Align multiple sequences against a reference using SequenceProcessor helpers."""

            if error := self.validate_required_params(
                {"reference_id": reference_id, "sequence_ids": sequence_ids},
                ["reference_id", "sequence_ids"],
            ):
                return error

            if not sequence_ids:
                return self.format_error(
                    "No sequences provided",
                    "Provide one or more sequence IDs to align against the reference.",
                )

            processor = self.get_processor("sequence")

            try:
                reference_sequence = processor.get_sequence(reference_id)
                if reference_sequence is None:
                    return self.format_error(
                        f"Reference sequence '{reference_id}' not available",
                        "Ensure the reference sequence is registered via the sequence loader or processor.",
                    )

                missing = [
                    sid
                    for sid in sequence_ids
                    if sid != reference_id and processor.get_sequence(sid) is None
                ]
                if missing:
                    return self.format_error(
                        f"Sequences not available: {', '.join(missing)}",
                        "Load sequences first with sequence_download or register_sequence.",
                    )

                summary_metadata = {
                    "requested_by": "sequence_align_to_reference",
                    "requested_at": datetime.utcnow().isoformat(),
                }

                summary_payload, _ = processor.align_and_record(
                    sequence_ids=sequence_ids,
                    reference_id=reference_id,
                    save_alignments=save_alignments,
                    summary_name=summary_name,
                    summary_metadata=summary_metadata,
                    aligned_dataset_name=aligned_dataset_name,
                    aligned_dataset_include_reference=include_reference_in_dataset,
                    property_table_name=property_table_name,
                )

                payload: Dict[str, Any] = {
                    "reference_id": reference_id,
                    "sequence_ids": sequence_ids,
                    "summary": summary_payload.get("alignment", {}).get("global"),
                    "alignments": summary_payload.get("alignment", {}).get("pairwise"),
                }

                if summary_payload.get("summary_file"):
                    payload["summary_file"] = summary_payload["summary_file"]
                if summary_payload.get("summary_dataset"):
                    payload["summary_dataset"] = summary_payload["summary_dataset"]
                if summary_payload.get("aligned_dataset") is not None:
                    payload["aligned_dataset"] = summary_payload["aligned_dataset"]
                if summary_payload.get("aligned_sequences"):
                    payload["aligned_sequences"] = summary_payload["aligned_sequences"]
                if summary_payload.get("property_table"):
                    payload["property_table"] = summary_payload["property_table"]
                if summary_payload.get("metadata"):
                    payload["metadata"] = summary_payload["metadata"]
                if summary_payload.get("errors"):
                    payload["errors"] = summary_payload["errors"]

                return self.format_success(payload)

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def sequence_align_mmseqs(
            ctx,
            sequences: Optional[Dict[str, str]] = None,
            sequence_ids: Optional[List[str]] = None,
            dataset_name: Optional[str] = None,
            store_in_context: bool = False,
            context_label: Optional[str] = None,
        ) -> Dict:
            """Run MMseqs pairwise alignment over a collection of sequences."""

            try:
                sequence_map: Dict[str, str] = {}
                processor = self.get_processor("sequence")

                if sequences:
                    sequence_map = sequences
                elif dataset_name:
                    dataset = processor.load_dataset(dataset_name)
                    if isinstance(dataset, dict):
                        sequence_map = {
                            key: value
                            for key, value in dataset.items()
                            if isinstance(value, str)
                        }
                elif sequence_ids:
                    for seq_id in sequence_ids:
                        entity = processor.load_entity(seq_id)
                        if isinstance(entity, str):
                            sequence_map[seq_id] = entity
                        elif isinstance(entity, dict):
                            sequence_map.update(entity)
                        else:
                            return self.format_error(
                                f"Sequence '{seq_id}' is empty or unsupported",
                                "Ensure the sequence entity contains FASTA content",
                            )
                else:
                    return self.format_error(
                        "No sequences specified",
                        "Provide a dataset name, a mapping of sequences, or sequence IDs",
                    )

                if not sequence_map:
                    return self.format_error(
                        "No sequences available for MMseqs alignment",
                        "Check that supplied identifiers reference valid sequence data",
                    )

                engine = SequenceAlignmentEngine()
                try:
                    mmseqs_output = engine.align_pairwise_mmseqs(sequence_map)
                except MMseqsUnavailableError as exc:
                    return self.format_error(
                        "MMseqs2 is not available",
                        str(exc),
                    )

                if mmseqs_output is None:
                    return self.format_error(
                        "MMseqs alignment returned no data",
                        "Check that MMseqs is installed and produced valid results.",
                    )

                payload: Dict[str, Any] = {
                    "sequence_count": len(sequence_map),
                    "source": dataset_name or sequence_ids or list(sequence_map.keys()),
                }

                # Convert DataFrame-like outputs to JSON-serialisable records
                if hasattr(mmseqs_output, "to_dict") and hasattr(
                    mmseqs_output, "columns"
                ):
                    records = mmseqs_output.to_dict(orient="records")  # type: ignore[assignment]
                    # In LLM-safe mode, limit the number of rows returned
                    if self.llm_safe_mode:
                        max_rows = 20
                        payload.update(
                            {
                                "result_type": "table",
                                "columns": list(getattr(mmseqs_output, "columns", [])),
                                "rows": records[:max_rows],
                                "row_count": len(records),
                                "rows_shown": min(max_rows, len(records)),
                                "truncated": len(records) > max_rows,
                            }
                        )
                    else:
                        payload.update(
                            {
                                "result_type": "table",
                                "columns": list(getattr(mmseqs_output, "columns", [])),
                                "rows": records,
                                "row_count": len(records),
                            }
                        )
                else:
                    lines = list(mmseqs_output)
                    payload.update(
                        {
                            "result_type": "lines",
                            "lines": lines,
                            "line_count": len(lines),
                        }
                    )

                if store_in_context:
                    artifact_name = (
                        context_label
                        or (dataset_name if isinstance(dataset_name, str) else None)
                        or "sequence_mmseqs_alignment"
                    )
                    summary = {
                        "sequence_count": payload.get("sequence_count"),
                        "result_type": payload.get("result_type"),
                        "source": "sequence_align_mmseqs",
                    }
                    context_handle = self.record_session_artifact(
                        tool_name="sequence_align_mmseqs",
                        name=artifact_name,
                        kind="result",
                        processor_type="sequence",
                        summary=summary,
                        tags=["sequence", "analysis", "alignment"],
                        label=context_label,
                        scope="sequence.result",
                    )
                    payload["context_handle"] = context_handle

                return self.format_success(payload)

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def sequence_find_best_match(
            ctx,
            *,
            query_sequence: Optional[str] = None,
            query_entity: Optional[str] = None,
            reference_sequences: Optional[Dict[str, str]] = None,
            reference_ids: Optional[List[str]] = None,
            reference_dataset: Optional[str] = None,
            use_mmseqs: bool = True,
        ) -> Dict:
            """Find the best-matching reference sequence for a query."""

            try:
                processor = self.get_processor("sequence")

                if query_sequence is None and query_entity is None:
                    return self.format_error(
                        "Missing query sequence",
                        "Provide either `query_sequence` or `query_entity`.",
                    )

                if query_sequence is None and query_entity is not None:
                    entity_data = processor.load_entity(query_entity)
                    if isinstance(entity_data, str):
                        query_sequence = entity_data
                    elif isinstance(entity_data, dict):
                        if entity_data:
                            query_sequence = next(iter(entity_data.values()))
                    if not query_sequence:
                        return self.format_error(
                            f"Sequence entity '{query_entity}' has no data",
                            "Ensure the entity exists and contains FASTA content.",
                        )

                references: Dict[str, str] = {}
                if reference_sequences:
                    references.update(reference_sequences)

                if reference_ids:
                    for ref_id in reference_ids:
                        data = processor.load_entity(ref_id)
                        if isinstance(data, str):
                            references[ref_id] = data
                        elif isinstance(data, dict):
                            references.update(
                                {f"{ref_id}:{k}": v for k, v in data.items()}
                            )

                if reference_dataset:
                    dataset = processor.load_dataset(reference_dataset)
                    for ref_id, record in dataset.items():
                        if isinstance(record, str):
                            references.setdefault(ref_id, record)
                        elif isinstance(record, dict):
                            for sub_id, seq in record.items():
                                references.setdefault(f"{ref_id}:{sub_id}", seq)

                if not references:
                    return self.format_error(
                        "No reference sequences provided",
                        "Supply `reference_ids`, `reference_dataset`, or `reference_sequences`.",
                    )

                best_id, score, alignment = processor.find_best_match(
                    query_sequence,
                    references,
                    use_mmseqs=use_mmseqs,
                )

                response = {
                    "query_entity": query_entity,
                    "query_sequence_length": (
                        len(query_sequence) if query_sequence else 0
                    ),
                    "best_match": best_id,
                    "score": score,
                    "alignment": alignment,
                    "reference_count": len(references),
                }

                if best_id is None:
                    return self.format_success(
                        response, message="No reference produced a valid alignment"
                    )

                return self.format_success(response)

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def sequence_dataset_stats(
            ctx,
            dataset_name: str,
            include_entities: bool = False,
        ) -> Dict:
            """Summarize a sequence dataset (entity counts, length stats)."""

            if error := self.validate_required_params(
                {"dataset_name": dataset_name},
                ["dataset_name"],
            ):
                return error

            processor = self.get_processor("sequence")

            manager = getattr(processor, "dataset_manager", None)
            if manager is None or not manager.dataset_exists(dataset_name):
                return self.format_error(
                    f"Sequence dataset '{dataset_name}' not found",
                    "Use dataset.list_datasets to confirm available sequence datasets.",
                )

            dataset = processor.load_dataset(dataset_name)
            if isinstance(dataset, dict):
                sequences = dataset
            else:
                sequences = {}
                for key, value in dataset.items():
                    if isinstance(value, str):
                        sequences[key] = value

            lengths = [len(seq) for seq in sequences.values() if isinstance(seq, str)]
            stats = {
                "dataset_name": dataset_name,
                "entity_count": len(sequences),
                "length_min": min(lengths) if lengths else None,
                "length_max": max(lengths) if lengths else None,
                "length_mean": sum(lengths) / len(lengths) if lengths else None,
            }

            if include_entities:
                stats["entities"] = list(sequences.keys())[: min(25, len(sequences))]
                stats["truncated"] = len(sequences) > min(25, len(sequences))

            return self.format_success(stats)

        @server.tool()
        def sequence_annotate_with_grn(
            ctx,
            reference_table: str,
            protein_family: str,
            dataset_name: Optional[str] = None,
            sequences: Optional[Dict[str, str]] = None,
            entity_names: Optional[List[str]] = None,
            output_table: Optional[str] = None,
            allow_create: bool = False,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict:
            """Annotate sequences with GRN positions using bundled references."""

            try:
                if error := self.validate_required_params(
                    {
                        "reference_table": reference_table,
                        "protein_family": protein_family,
                    },
                    ["reference_table", "protein_family"],
                ):
                    return error

                processor = self.get_processor("sequence")
                annotations, summary = processor.annotate_with_grn(
                    dataset_name=dataset_name,
                    sequences=sequences,
                    entity_names=entity_names,
                    reference_table=reference_table,
                    protein_family=protein_family,
                    output_table=output_table,
                    allow_create=allow_create,
                    metadata=metadata,
                    return_summary=True,
                )

                # Build statistics for LLM-safe response
                grn_columns = [c for c in annotations.columns if c not in ["sequence", "entity_name"]]
                sequence_count = len(annotations)

                # Count non-empty values per GRN position
                grn_coverage: Dict[str, int] = {}
                for col in grn_columns:
                    if col in annotations.columns:
                        non_empty = annotations[col].notna() & (annotations[col] != "-") & (annotations[col] != "")
                        grn_coverage[col] = int(non_empty.sum())

                # Get AA distribution summary (top 3 AAs per position for first 10 positions)
                aa_distribution_preview: Dict[str, Dict[str, int]] = {}
                for col in grn_columns[:10]:  # Preview first 10 GRN positions
                    if col in annotations.columns:
                        counts = annotations[col].value_counts()
                        # Filter out gaps/empty
                        counts = counts[~counts.index.isin(["-", "", None])]
                        aa_distribution_preview[col] = counts.head(3).to_dict()

                payload: Dict[str, Any] = {
                    "reference_table": reference_table,
                    "protein_family": protein_family,
                    "sequence_count": sequence_count,
                    "grn_position_count": len(grn_columns),
                    "grn_positions": grn_columns[:50] if len(grn_columns) > 50 else grn_columns,
                    "grn_positions_truncated": len(grn_columns) > 50,
                    "grn_coverage": grn_coverage,
                    "aa_distribution_preview": aa_distribution_preview,
                    "summary": summary,
                }

                if dataset_name:
                    payload["dataset_name"] = dataset_name
                if entity_names:
                    payload["entity_names"] = entity_names
                if output_table:
                    payload["output_table"] = output_table
                    payload["note"] = (
                        "Full GRN annotations saved to table. Use grn_query_entity or "
                        "grn_query_position to inspect specific data."
                    )
                else:
                    payload["note"] = (
                        "GRN annotations computed but not saved. Use grn_query_entity or "
                        "grn_query_position to inspect, or provide output_table to persist."
                    )

                return self.format_success(payload)

            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def calculate_sequence_identity(
            ctx, sequences: Dict[str, str], reference_sequence: Optional[str] = None
        ) -> Dict:
            """
            Calculate pairwise sequence identities using raw sequences.

            Note: For entity-based identity calculation, use sequence_calculate_identity_from_dataset instead.

            Args:
                sequences: Dictionary mapping sequence IDs to sequences (raw strings)
                reference_sequence: Optional reference sequence to compare all against

            Returns:
                Dictionary with identity matrix
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"sequences": sequences}, ["sequences"]
                ):
                    return error

                if len(sequences) < 2 and not reference_sequence:
                    return self.format_error(
                        "Need at least 2 sequences",
                        "Provide multiple sequences or a reference sequence",
                    )

                # Calculate identities
                identities = {}

                if reference_sequence:
                    # Compare all to reference
                    for seq_id, seq in sequences.items():
                        # Simple identity calculation
                        min_len = min(len(seq), len(reference_sequence))
                        matches = sum(
                            1 for i in range(min_len) if seq[i] == reference_sequence[i]
                        )
                        identity = matches / max(len(seq), len(reference_sequence))
                        identities[seq_id] = round(identity, 3)
                else:
                    # All vs all comparison
                    seq_ids = list(sequences.keys())
                    for i, id1 in enumerate(seq_ids):
                        identities[id1] = {}
                        for j, id2 in enumerate(seq_ids):
                            if i == j:
                                identities[id1][id2] = 1.0
                            else:
                                seq1 = sequences[id1]
                                seq2 = sequences[id2]
                                min_len = min(len(seq1), len(seq2))
                                matches = sum(
                                    1 for k in range(min_len) if seq1[k] == seq2[k]
                                )
                                identity = matches / max(len(seq1), len(seq2))
                                identities[id1][id2] = round(identity, 3)

                # Calculate statistics
                if reference_sequence:
                    avg_identity = sum(identities.values()) / len(identities)
                    min_identity = min(identities.values())
                    max_identity = max(identities.values())
                else:
                    all_values = []
                    for id1 in identities:
                        for id2 in identities[id1]:
                            if id1 != id2:
                                all_values.append(identities[id1][id2])
                    avg_identity = (
                        sum(all_values) / len(all_values) if all_values else 0
                    )
                    min_identity = min(all_values) if all_values else 0
                    max_identity = max(all_values) if all_values else 0

                return self.format_success(
                    {
                        "num_sequences": len(sequences),
                        "reference_used": bool(reference_sequence),
                        "identities": identities,
                        "avg_identity": round(avg_identity, 3),
                        "min_identity": round(min_identity, 3),
                        "max_identity": round(max_identity, 3),
                    }
                )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def sequence_calculate_identity_from_dataset(
            ctx, dataset_name: str, reference_entity: Optional[str] = None
        ) -> Dict:
            """
            Calculate pairwise sequence identities for all sequences in a dataset.

            Args:
                dataset_name: Name of the sequence dataset
                reference_entity: Optional reference entity for one-vs-all comparison

            Returns:
                Dictionary with identity matrix or list
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, ["dataset_name"]
                ):
                    return error

                # Get sequence processor
                processor = self.get_processor("sequence")

                # Load dataset
                try:
                    dataset = processor.load_dataset(dataset_name)
                except Exception as e:
                    return self.format_error(
                        f"Failed to load dataset: {str(e)}",
                        "Check dataset exists in sequence processor",
                    )

                # Get entity list from dataset
                if hasattr(dataset, "content"):
                    entities = dataset.content
                elif hasattr(dataset, "entities"):
                    entities = dataset.entities
                else:
                    return self.format_error(
                        "Cannot determine dataset entities",
                        "Dataset structure not recognized",
                    )

                # Load all sequences
                sequences = {}
                for entity in entities:
                    try:
                        seq_data = processor.load_entity(entity)
                        if isinstance(seq_data, dict):
                            sequences[entity] = list(seq_data.values())[0]
                        else:
                            sequences[entity] = str(seq_data)
                    except Exception as e:
                        logger.warning(f"Failed to load {entity}: {e}")

                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences for identity calculation",
                        "Ensure dataset contains multiple valid sequences",
                    )

                # Calculate identities
                from protos.processing.sequence.seq_alignment import calculate_identity

                if reference_entity:
                    # One-vs-all mode
                    if reference_entity not in sequences:
                        return self.format_error(
                            f"Reference entity '{reference_entity}' not in dataset",
                            "Choose a reference from the dataset entities",
                        )

                    ref_seq = sequences[reference_entity]
                    identities = {}

                    for entity, seq in sequences.items():
                        if entity != reference_entity:
                            identity = calculate_identity(ref_seq, seq)
                            identities[entity] = round(identity, 3)

                    return self.format_success(
                        {
                            "mode": "one_vs_all",
                            "reference": reference_entity,
                            "dataset": dataset_name,
                            "num_comparisons": len(identities),
                            "identities": identities,
                            "avg_identity": round(
                                sum(identities.values()) / len(identities), 3
                            ),
                            "min_identity": round(min(identities.values()), 3),
                            "max_identity": round(max(identities.values()), 3),
                        }
                    )
                else:
                    # All-vs-all mode
                    identity_matrix = {}

                    for entity1 in sequences:
                        identity_matrix[entity1] = {}
                        for entity2 in sequences:
                            if entity1 == entity2:
                                identity_matrix[entity1][entity2] = 1.0
                            else:
                                identity = calculate_identity(
                                    sequences[entity1], sequences[entity2]
                                )
                                identity_matrix[entity1][entity2] = round(identity, 3)

                    # Calculate statistics
                    all_identities = []
                    for e1 in sequences:
                        for e2 in sequences:
                            if e1 != e2:
                                all_identities.append(identity_matrix[e1][e2])

                    return self.format_success(
                        {
                            "mode": "all_vs_all",
                            "dataset": dataset_name,
                            "num_sequences": len(sequences),
                            "identity_matrix": identity_matrix,
                            "avg_identity": (
                                round(sum(all_identities) / len(all_identities), 3)
                                if all_identities
                                else 0
                            ),
                            "min_identity": (
                                round(min(all_identities), 3) if all_identities else 0
                            ),
                            "max_identity": (
                                round(max(all_identities), 3) if all_identities else 0
                            ),
                        }
                    )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def sequence_find_conserved_regions(
            ctx,
            sequences: Dict[str, str],
            min_conservation: float = 0.8,
            min_length: int = 5,
        ) -> Dict:
            """
            Find conserved regions across multiple sequences using raw sequences.

            Note: For dataset-based conservation analysis, use sequence_find_conserved_regions_in_dataset instead.

            Args:
                sequences: Dictionary mapping sequence IDs to sequences (raw strings)
                min_conservation: Minimum conservation threshold (0-1)
                min_length: Minimum length of conserved region

            Returns:
                Dictionary with conserved regions
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"sequences": sequences}, ["sequences"]
                ):
                    return error

                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences",
                        "Provide multiple sequences to find conservation",
                    )

                # Get sequence processor
                processor = self.get_processor("sequence")

                # Find the shortest sequence length
                min_seq_length = min(len(seq) for seq in sequences.values())

                # Calculate conservation at each position
                conservation_scores = []
                for pos in range(min_seq_length):
                    residues = [
                        seq[pos] for seq in sequences.values() if pos < len(seq)
                    ]
                    # Calculate frequency of most common residue
                    if residues:
                        most_common = max(set(residues), key=residues.count)
                        conservation = residues.count(most_common) / len(residues)
                        conservation_scores.append(
                            {
                                "position": pos,
                                "conservation": conservation,
                                "consensus": most_common,
                                "residues": "".join(sorted(set(residues))),
                            }
                        )

                # Find conserved regions
                conserved_regions = []
                current_region = None

                for score in conservation_scores:
                    if score["conservation"] >= min_conservation:
                        if current_region is None:
                            current_region = {
                                "start": score["position"],
                                "end": score["position"],
                                "conservation": [score["conservation"]],
                                "consensus": score["consensus"],
                            }
                        else:
                            current_region["end"] = score["position"]
                            current_region["conservation"].append(score["conservation"])
                            current_region["consensus"] += score["consensus"]
                    else:
                        if (
                            current_region
                            and (current_region["end"] - current_region["start"] + 1)
                            >= min_length
                        ):
                            current_region["avg_conservation"] = sum(
                                current_region["conservation"]
                            ) / len(current_region["conservation"])
                            conserved_regions.append(current_region)
                        current_region = None

                # Check last region
                if (
                    current_region
                    and (current_region["end"] - current_region["start"] + 1)
                    >= min_length
                ):
                    current_region["avg_conservation"] = sum(
                        current_region["conservation"]
                    ) / len(current_region["conservation"])
                    conserved_regions.append(current_region)

                # Clean up regions
                for region in conserved_regions:
                    region.pop("conservation", None)
                    region["length"] = region["end"] - region["start"] + 1

                return self.format_success(
                    {
                        "num_sequences": len(sequences),
                        "sequence_length": min_seq_length,
                        "min_conservation": min_conservation,
                        "min_length": min_length,
                        "num_conserved_regions": len(conserved_regions),
                        "conserved_regions": conserved_regions[:20],  # First 20
                        "total_conserved_positions": sum(
                            r["length"] for r in conserved_regions
                        ),
                    }
                )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def sequence_find_conserved_regions_in_dataset(
            ctx, dataset_name: str, min_conservation: float = 0.8, min_length: int = 5
        ) -> Dict:
            """
            Find conserved regions across all sequences in a dataset.

            Args:
                dataset_name: Name of the sequence dataset
                min_conservation: Minimum conservation threshold (0-1)
                min_length: Minimum length for conserved regions

            Returns:
                Dictionary with conserved regions
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, ["dataset_name"]
                ):
                    return error

                if not 0 <= min_conservation <= 1:
                    return self.format_error(
                        "min_conservation must be between 0 and 1",
                        "Use 0.8 for 80% conservation",
                    )

                # Get sequence processor
                processor = self.get_processor("sequence")

                # Load dataset and sequences
                try:
                    dataset = processor.load_dataset(dataset_name)
                    entities = (
                        dataset.content
                        if hasattr(dataset, "content")
                        else dataset.entities
                    )

                    sequences = {}
                    for entity in entities:
                        seq_data = processor.load_entity(entity)
                        if isinstance(seq_data, dict):
                            sequences[entity] = list(seq_data.values())[0]
                        else:
                            sequences[entity] = str(seq_data)

                except Exception as e:
                    return self.format_error(
                        f"Failed to load dataset sequences: {str(e)}",
                        "Ensure dataset exists and contains valid sequences",
                    )

                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences for conservation analysis",
                        "Add more sequences to the dataset",
                    )

                # Find conserved regions
                from protos.processing.sequence.seq_conservation import (
                    find_conserved_regions,
                )

                conserved_regions = find_conserved_regions(
                    list(sequences.values()),
                    threshold=min_conservation,
                    min_length=min_length,
                )

                # Format results
                formatted_regions = []
                for region in conserved_regions:
                    formatted_regions.append(
                        {
                            "start": region["start"],
                            "end": region["end"],
                            "length": region["end"] - region["start"] + 1,
                            "consensus": region["consensus"],
                            "avg_conservation": round(region["conservation"], 3),
                        }
                    )

                # Sort by position
                formatted_regions.sort(key=lambda x: x["start"])

                total_conserved = sum(r["length"] for r in formatted_regions)
                avg_seq_length = sum(len(s) for s in sequences.values()) / len(
                    sequences
                )

                return self.format_success(
                    {
                        "dataset": dataset_name,
                        "num_sequences": len(sequences),
                        "conservation_threshold": min_conservation,
                        "num_conserved_regions": len(formatted_regions),
                        "conserved_regions": formatted_regions,
                        "total_conserved_positions": total_conserved,
                        "conservation_coverage": (
                            round(total_conserved / avg_seq_length, 3)
                            if avg_seq_length > 0
                            else 0
                        ),
                    }
                )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def sequence_detect_mutations(
            ctx, wild_type: str, variant: str, numbering_start: int = 1
        ) -> Dict:
            """
            Detect mutations between wild-type and variant sequences using raw sequences.

            Note: For entity-based mutation detection, use sequence_detect_mutations_between_entities instead.

            Args:
                wild_type: Wild-type sequence (raw string)
                variant: Variant sequence (raw string)
                numbering_start: Position numbering start (default 1)

            Returns:
                Dictionary with detected mutations
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"wild_type": wild_type, "variant": variant},
                    ["wild_type", "variant"],
                ):
                    return error

                # Detect mutations
                mutations = []
                insertions = []
                deletions = []

                # Simple mutation detection (without alignment)
                if len(wild_type) == len(variant):
                    # Same length - check substitutions
                    for i, (wt_res, var_res) in enumerate(zip(wild_type, variant)):
                        if wt_res != var_res:
                            mutations.append(
                                {
                                    "position": i + numbering_start,
                                    "wild_type": wt_res,
                                    "variant": var_res,
                                    "type": "substitution",
                                    "notation": f"{wt_res}{i + numbering_start}{var_res}",
                                }
                            )
                else:
                    # Different lengths - need alignment
                    from protos.processing.sequence.seq_alignment import (
                        init_aligner,
                        align_blosum62,
                    )

                    aligner = init_aligner()
                    alignment = align_blosum62(wild_type, variant, aligner)

                    wt_aligned = str(alignment.seqA)
                    var_aligned = str(alignment.seqB)

                    wt_pos = numbering_start - 1
                    var_pos = 0

                    for wt_res, var_res in zip(wt_aligned, var_aligned):
                        if wt_res != "-":
                            wt_pos += 1

                        if wt_res == "-" and var_res != "-":
                            # Insertion
                            insertions.append(
                                {
                                    "position": wt_pos,
                                    "inserted": var_res,
                                    "type": "insertion",
                                    "notation": f"ins{wt_pos}{var_res}",
                                }
                            )
                        elif wt_res != "-" and var_res == "-":
                            # Deletion
                            deletions.append(
                                {
                                    "position": wt_pos,
                                    "deleted": wt_res,
                                    "type": "deletion",
                                    "notation": f"del{wt_pos}{wt_res}",
                                }
                            )
                        elif wt_res != "-" and var_res != "-" and wt_res != var_res:
                            # Substitution
                            mutations.append(
                                {
                                    "position": wt_pos,
                                    "wild_type": wt_res,
                                    "variant": var_res,
                                    "type": "substitution",
                                    "notation": f"{wt_res}{wt_pos}{var_res}",
                                }
                            )

                # Combine all mutations
                all_mutations = mutations + insertions + deletions
                all_mutations.sort(key=lambda x: x["position"])

                # Calculate statistics
                num_substitutions = len(mutations)
                num_insertions = len(insertions)
                num_deletions = len(deletions)
                total_mutations = len(all_mutations)

                # Calculate similarity
                matches = sum(1 for wt, var in zip(wild_type, variant) if wt == var)
                similarity = (
                    matches / max(len(wild_type), len(variant))
                    if max(len(wild_type), len(variant)) > 0
                    else 0
                )

                return self.format_success(
                    {
                        "wild_type_length": len(wild_type),
                        "variant_length": len(variant),
                        "total_mutations": total_mutations,
                        "substitutions": num_substitutions,
                        "insertions": num_insertions,
                        "deletions": num_deletions,
                        "similarity": round(similarity, 3),
                        "mutations": all_mutations[:50],  # First 50
                        "mutation_rate": (
                            round(total_mutations / len(wild_type), 3)
                            if len(wild_type) > 0
                            else 0
                        ),
                    }
                )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def sequence_detect_mutations_between_entities(
            ctx,
            reference_entity: str,
            variant_entity: str,
            include_positions: bool = True,
        ) -> Dict:
            """
            Detect mutations between two sequence entities.

            Args:
                reference_entity: Reference sequence entity ID
                variant_entity: Variant sequence entity ID
                include_positions: Include detailed position information

            Returns:
                Dictionary with detected mutations
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {
                        "reference_entity": reference_entity,
                        "variant_entity": variant_entity,
                    },
                    ["reference_entity", "variant_entity"],
                ):
                    return error

                # Get sequence processor
                processor = self.get_processor("sequence")

                # Load sequences
                try:
                    ref_data = processor.load_entity(reference_entity)
                    var_data = processor.load_entity(variant_entity)

                    # Extract sequences
                    ref_seq = (
                        list(ref_data.values())[0]
                        if isinstance(ref_data, dict)
                        else str(ref_data)
                    )
                    var_seq = (
                        list(var_data.values())[0]
                        if isinstance(var_data, dict)
                        else str(var_data)
                    )

                except Exception as e:
                    return self.format_error(
                        f"Failed to load sequences: {str(e)}",
                        "Ensure both entities exist in sequence processor",
                    )

                # Align sequences first
                from protos.processing.sequence.seq_alignment import (
                    init_aligner,
                    align_blosum62,
                )

                aligner = init_aligner()
                alignment = align_blosum62(ref_seq, var_seq, aligner)

                aligned_ref = str(alignment.seqA)
                aligned_var = str(alignment.seqB)

                # Detect mutations
                mutations = []
                ref_pos = 0
                var_pos = 0

                for i, (ref_aa, var_aa) in enumerate(zip(aligned_ref, aligned_var)):
                    if ref_aa != "-":
                        ref_pos += 1
                    if var_aa != "-":
                        var_pos += 1

                    if ref_aa != var_aa:
                        if ref_aa == "-":
                            # Insertion
                            mutations.append(
                                {
                                    "type": "insertion",
                                    "position": ref_pos,
                                    "reference": "-",
                                    "variant": var_aa,
                                    "notation": f"ins{ref_pos}{var_aa}",
                                }
                            )
                        elif var_aa == "-":
                            # Deletion
                            mutations.append(
                                {
                                    "type": "deletion",
                                    "position": ref_pos,
                                    "reference": ref_aa,
                                    "variant": "-",
                                    "notation": f"{ref_aa}{ref_pos}del",
                                }
                            )
                        else:
                            # Substitution
                            mutations.append(
                                {
                                    "type": "substitution",
                                    "position": ref_pos,
                                    "reference": ref_aa,
                                    "variant": var_aa,
                                    "notation": f"{ref_aa}{ref_pos}{var_aa}",
                                }
                            )

                # Summary statistics
                mut_types = {"substitution": 0, "insertion": 0, "deletion": 0}
                for mut in mutations:
                    mut_types[mut["type"]] += 1

                result = {
                    "reference_entity": reference_entity,
                    "variant_entity": variant_entity,
                    "total_mutations": len(mutations),
                    "mutation_types": mut_types,
                    "alignment_score": float(alignment.score),
                    "sequence_identity": round(
                        sum(
                            1
                            for a, b in zip(aligned_ref, aligned_var)
                            if a == b and a != "-"
                        )
                        / len([a for a in aligned_ref if a != "-"]),
                        3,
                    ),
                }

                if include_positions:
                    result["mutations"] = mutations

                return self.format_success(result)

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def translate_sequence(
            ctx, dna_sequence: str, genetic_code: int = 1, to_stop: bool = True
        ) -> Dict:
            """
            Translate DNA/RNA sequence to protein.

            Args:
                dna_sequence: DNA or RNA sequence
                genetic_code: NCBI genetic code table (1=standard)
                to_stop: Stop translation at first stop codon

            Returns:
                Dictionary with translation results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dna_sequence": dna_sequence}, ["dna_sequence"]
                ):
                    return error

                # Clean sequence
                dna_sequence = dna_sequence.upper().replace("U", "T")

                # Standard genetic code
                codon_table = {
                    "TTT": "F",
                    "TTC": "F",
                    "TTA": "L",
                    "TTG": "L",
                    "TCT": "S",
                    "TCC": "S",
                    "TCA": "S",
                    "TCG": "S",
                    "TAT": "Y",
                    "TAC": "Y",
                    "TAA": "*",
                    "TAG": "*",
                    "TGT": "C",
                    "TGC": "C",
                    "TGA": "*",
                    "TGG": "W",
                    "CTT": "L",
                    "CTC": "L",
                    "CTA": "L",
                    "CTG": "L",
                    "CCT": "P",
                    "CCC": "P",
                    "CCA": "P",
                    "CCG": "P",
                    "CAT": "H",
                    "CAC": "H",
                    "CAA": "Q",
                    "CAG": "Q",
                    "CGT": "R",
                    "CGC": "R",
                    "CGA": "R",
                    "CGG": "R",
                    "ATT": "I",
                    "ATC": "I",
                    "ATA": "I",
                    "ATG": "M",
                    "ACT": "T",
                    "ACC": "T",
                    "ACA": "T",
                    "ACG": "T",
                    "AAT": "N",
                    "AAC": "N",
                    "AAA": "K",
                    "AAG": "K",
                    "AGT": "S",
                    "AGC": "S",
                    "AGA": "R",
                    "AGG": "R",
                    "GTT": "V",
                    "GTC": "V",
                    "GTA": "V",
                    "GTG": "V",
                    "GCT": "A",
                    "GCC": "A",
                    "GCA": "A",
                    "GCG": "A",
                    "GAT": "D",
                    "GAC": "D",
                    "GAA": "E",
                    "GAG": "E",
                    "GGT": "G",
                    "GGC": "G",
                    "GGA": "G",
                    "GGG": "G",
                }

                # Translate in all three frames
                translations = {}

                for frame in range(3):
                    protein = []
                    for i in range(frame, len(dna_sequence) - 2, 3):
                        codon = dna_sequence[i : i + 3]
                        if len(codon) == 3:
                            aa = codon_table.get(codon, "X")
                            if to_stop and aa == "*":
                                break
                            protein.append(aa)
                    translations[f"frame_{frame+1}"] = "".join(protein)

                # Find ORFs (Open Reading Frames)
                orfs = []
                for frame_name, protein in translations.items():
                    # Find sequences between M and *
                    import re

                    for match in re.finditer(r"M[^*]*\*", protein):
                        if len(match.group()) >= 10:  # At least 10 amino acids
                            orfs.append(
                                {
                                    "frame": frame_name,
                                    "start": match.start(),
                                    "end": match.end(),
                                    "length": len(match.group()) - 1,  # Exclude stop
                                    "sequence": match.group()[:-1],  # Remove stop
                                }
                            )

                # Sort ORFs by length
                orfs.sort(key=lambda x: x["length"], reverse=True)

                return self.format_success(
                    {
                        "dna_length": len(dna_sequence),
                        "translations": translations,
                        "num_orfs": len(orfs),
                        "longest_orf": orfs[0] if orfs else None,
                        "orfs": orfs[:10],  # Top 10 ORFs
                    }
                )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def cluster_sequences(
            ctx,
            sequences: Dict[str, str],
            identity_threshold: float = 0.9,
            method: str = "single",
        ) -> Dict:
            """
            Cluster sequences by similarity using raw sequences.

            Note: For dataset-based clustering, use cluster_dataset_sequences instead.

            Args:
                sequences: Dictionary mapping sequence IDs to sequences (raw strings)
                identity_threshold: Identity threshold for clustering (0-1)
                method: Clustering method ("single", "complete", "average")

            Returns:
                Dictionary with cluster assignments
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"sequences": sequences}, ["sequences"]
                ):
                    return error

                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences",
                        "Provide multiple sequences to cluster",
                    )

                # Calculate pairwise identities
                seq_ids = list(sequences.keys())
                n = len(seq_ids)
                identity_matrix = [[1.0] * n for _ in range(n)]

                for i in range(n):
                    for j in range(i + 1, n):
                        seq1 = sequences[seq_ids[i]]
                        seq2 = sequences[seq_ids[j]]

                        # Simple identity calculation
                        min_len = min(len(seq1), len(seq2))
                        matches = sum(1 for k in range(min_len) if seq1[k] == seq2[k])
                        identity = matches / max(len(seq1), len(seq2))

                        identity_matrix[i][j] = identity
                        identity_matrix[j][i] = identity

                # Simple clustering based on threshold
                clusters = {}
                assigned = set()
                cluster_id = 0

                for i, seq_id in enumerate(seq_ids):
                    if seq_id in assigned:
                        continue

                    # Start new cluster
                    cluster_id += 1
                    cluster_members = [seq_id]
                    assigned.add(seq_id)

                    # Find similar sequences
                    for j, other_id in enumerate(seq_ids):
                        if (
                            other_id not in assigned
                            and identity_matrix[i][j] >= identity_threshold
                        ):
                            cluster_members.append(other_id)
                            assigned.add(other_id)

                    clusters[f"cluster_{cluster_id}"] = {
                        "members": cluster_members,
                        "size": len(cluster_members),
                        "representative": seq_id,
                    }

                # Calculate cluster statistics
                cluster_sizes = [c["size"] for c in clusters.values()]

                return self.format_success(
                    {
                        "num_sequences": len(sequences),
                        "num_clusters": len(clusters),
                        "identity_threshold": identity_threshold,
                        "clustering_method": method,
                        "clusters": clusters,
                        "largest_cluster": max(cluster_sizes) if cluster_sizes else 0,
                        "singleton_clusters": sum(1 for s in cluster_sizes if s == 1),
                    }
                )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def cluster_dataset_sequences(
            ctx,
            dataset_name: str,
            similarity_threshold: float = 0.8,
            method: str = "single",
        ) -> Dict:
            """
            Cluster sequences in a dataset by similarity.

            Args:
                dataset_name: Name of the sequence dataset
                similarity_threshold: Similarity threshold for clustering (0-1)
                method: Clustering method (single, complete, average)

            Returns:
                Dictionary with cluster assignments
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, ["dataset_name"]
                ):
                    return error

                if not 0 <= similarity_threshold <= 1:
                    return self.format_error(
                        "similarity_threshold must be between 0 and 1",
                        "Use 0.8 for 80% similarity clustering",
                    )

                # Get sequence processor
                processor = self.get_processor("sequence")

                # Load dataset
                try:
                    dataset = processor.load_dataset(dataset_name)
                    entities = (
                        dataset.content
                        if hasattr(dataset, "content")
                        else dataset.entities
                    )

                    sequences = {}
                    for entity in entities:
                        seq_data = processor.load_entity(entity)
                        if isinstance(seq_data, dict):
                            sequences[entity] = list(seq_data.values())[0]
                        else:
                            sequences[entity] = str(seq_data)

                except Exception as e:
                    return self.format_error(
                        f"Failed to load dataset: {str(e)}",
                        "Ensure dataset exists in sequence processor",
                    )

                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences for clustering",
                        "Add more sequences to the dataset",
                    )

                # Calculate pairwise distances
                from protos.processing.sequence.seq_alignment import calculate_identity
                import numpy as np

                entities_list = list(sequences.keys())
                n = len(entities_list)
                distance_matrix = np.zeros((n, n))

                for i in range(n):
                    for j in range(i + 1, n):
                        identity = calculate_identity(
                            sequences[entities_list[i]], sequences[entities_list[j]]
                        )
                        distance = 1 - identity  # Convert identity to distance
                        distance_matrix[i, j] = distance
                        distance_matrix[j, i] = distance

                # Perform hierarchical clustering
                from scipy.cluster.hierarchy import linkage, fcluster

                # Convert to condensed distance matrix
                condensed_dist = []
                for i in range(n):
                    for j in range(i + 1, n):
                        condensed_dist.append(distance_matrix[i, j])

                # Cluster
                linkage_matrix = linkage(condensed_dist, method=method)
                clusters = fcluster(
                    linkage_matrix, 1 - similarity_threshold, criterion="distance"
                )

                # Format results
                cluster_dict = {}
                for entity, cluster_id in zip(entities_list, clusters):
                    cluster_key = f"cluster_{cluster_id}"
                    if cluster_key not in cluster_dict:
                        cluster_dict[cluster_key] = []
                    cluster_dict[cluster_key].append(entity)

                # Calculate cluster statistics
                cluster_stats = {}
                for cluster_key, members in cluster_dict.items():
                    if len(members) > 1:
                        # Calculate average within-cluster identity
                        identities = []
                        for i, e1 in enumerate(members):
                            for e2 in members[i + 1 :]:
                                identity = calculate_identity(
                                    sequences[e1], sequences[e2]
                                )
                                identities.append(identity)
                        avg_identity = (
                            sum(identities) / len(identities) if identities else 1.0
                        )
                    else:
                        avg_identity = 1.0

                    cluster_stats[cluster_key] = {
                        "size": len(members),
                        "avg_identity": round(avg_identity, 3),
                    }

                return self.format_success(
                    {
                        "dataset": dataset_name,
                        "num_sequences": len(sequences),
                        "similarity_threshold": similarity_threshold,
                        "clustering_method": method,
                        "num_clusters": len(cluster_dict),
                        "clusters": cluster_dict,
                        "cluster_statistics": cluster_stats,
                        "singletons": sum(
                            1 for c in cluster_dict.values() if len(c) == 1
                        ),
                    }
                )

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def extract_sequence_from_structure_batch(
            ctx,
            dataset_name: str,
            chain_selection: Optional[str] = None,
            save_as_dataset: Optional[str] = None,
        ) -> Dict:
            """
            Extract sequences from all structures in a dataset.

            This is a batch operation that processes multiple structures and
            extracts their sequences, optionally saving them as a new sequence dataset.

            Args:
                dataset_name: Name of the structure dataset
                chain_selection: Chain to extract (e.g., "A"), or None for all chains
                save_as_dataset: Optional name for saving extracted sequences

            Returns:
                Dictionary with extracted sequences
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, ["dataset_name"]
                ):
                    return error

                # Get processors
                struct_processor = self.get_processor("structure")
                seq_processor = self.get_processor("sequence")

                entities = struct_processor.get_dataset_entities(dataset_name)

                if not entities:
                    return self.format_error(
                        f"Dataset '{dataset_name}' has no registered structures",
                        "Use structure tools to populate the dataset first",
                    )

                chain_filter: Optional[Union[str, List[str], Dict[str, List[str]]]]
                if chain_selection:
                    chain_filter = chain_selection
                else:
                    chain_filter = None

                collected = struct_processor.collect_chain_sequences(
                    entities,
                    chain_filter=chain_filter,
                )

                extracted_sequences: Dict[str, str] = {}
                failed_extractions: List[Dict[str, Any]] = []

                for entity in entities:
                    chains = collected.get(entity, {})
                    if not chains:
                        failed_extractions.append(
                            {
                                "entity": entity,
                                "error": "No chains matched selection",
                            }
                        )
                        continue

                    for payload in chains.values():
                        seq_id = payload.get("entity_name")
                        sequence = payload.get("sequence")
                        if not seq_id or not sequence:
                            continue
                        extracted_sequences[seq_id] = sequence

                if not extracted_sequences:
                    return self.format_error(
                        "No sequences could be extracted",
                        "Check structure dataset and chain selection",
                    )
                # Save as dataset if requested
                saved_entities: List[str] = []
                if save_as_dataset:
                    try:
                        metadata = {
                            "source_dataset": dataset_name,
                            "chain_selection": chain_selection,
                        }

                        seq_processor.save_sequences(
                            extracted_sequences,
                            save_as_dataset,
                            dataset_name=save_as_dataset,
                            metadata=metadata,
                            materialize_entities=True,
                        )

                        saved_entities = list(extracted_sequences.keys())

                    except Exception as e:
                        logger.warning(f"Failed to save sequences: {e}")

                result = {
                    "source_dataset": dataset_name,
                    "num_structures": len(entities),
                    "num_sequences_extracted": len(extracted_sequences),
                    "chain_selection": chain_selection or "all",
                    "sequence_ids": list(extracted_sequences.keys()),
                }

                if save_as_dataset:
                    result["saved_as_dataset"] = save_as_dataset
                    result["saved_entities"] = saved_entities

                if failed_extractions:
                    result["failed_extractions"] = failed_extractions

                return self.format_success(result)

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def sequence_create_mutant_library(
            ctx,
            base_sequence_id: str,
            mutation_map: Dict[str, List[str]],
            base_name: Optional[str] = None,
            include_wildtype: bool = True,
            limit: Optional[int] = None,
            zero_indexed: bool = False,
            register_mutations: bool = False,
            register: Optional[bool] = None,
            field_register: Optional[bool] = None,
            dataset_name: Optional[str] = None,
            materialize_entities: bool = False,
            metadata: Optional[Dict[str, Any]] = None,
            return_metadata: bool = False,
        ) -> Dict:
            """Generate a mutant library and optionally persist it."""

            if error := self.validate_required_params(
                {"base_sequence_id": base_sequence_id, "mutation_map": mutation_map},
                ["base_sequence_id", "mutation_map"],
            ):
                return error

            processor = self.get_processor("sequence")

            try:
                normalized_map: Dict[int, List[str]] = {}
                for key, values in mutation_map.items():
                    try:
                        pos = int(key)
                    except ValueError as exc:
                        raise ValueError(
                            f"Mutation map key '{key}' is not an integer"
                        ) from exc
                    normalized_map[pos] = values

                register_flag = register if register is not None else register_mutations
                if field_register is not None:
                    register_flag = field_register

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

                variants: Dict[str, str]
                dataset_path: Optional[str] = None
                metadata_records: Optional[List[Dict[str, Any]]] = None

                if return_metadata:
                    if register_flag:
                        variants, metadata_df, dataset_path = result  # type: ignore[misc]
                        metadata_records = metadata_df.to_dict(orient="records")
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

                return self.format_success(payload, message="Mutant library generated")

            except Exception as exc:
                return self.handle_error(exc)

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
        ) -> Dict:
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

                # Return summary stats only - full data stays in Protos context
                summary = {
                    "positions": int(len(df)),
                    "top_conserved": df.nsmallest(5, "entropy").to_dict(
                        orient="records"
                    ),
                    "most_variable": df.nlargest(5, "entropy").to_dict(
                        orient="records"
                    ),
                    "avg_entropy": round(float(df["entropy"].mean()), 4) if "entropy" in df else None,
                    "stored": store_result,
                    "note": "Full table available in Protos context via processor." if not store_result else None,
                }

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

            except Exception as exc:
                return self.handle_error(exc)

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
        ) -> Dict:
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

                # Return summary + top pairs only - full data stays in Protos context
                top_pairs = df.nlargest(10, df.columns[-1]).to_dict(orient="records") if len(df) > 0 else []
                payload = {
                    "pair_count": int(len(df)),
                    "top_pairs": top_pairs,
                    "stored": store_result,
                    "note": "Full linkage data available in Protos context via processor.",
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

            except Exception as exc:
                return self.handle_error(exc)
