"""
Standardized response builders for LLM-safe tool returns.

This module provides utilities for building consistent, bounded responses
that prevent context flooding while giving LLMs sufficient information
to understand and work with the data.

Key principles:
1. Return metadata and statistics, not raw data
2. Provide context handles for data access
3. Include small previews only when helpful
4. Always include size/count information
5. Ligands/SMILES are OK to include (they're small)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .context_preview import (
    PreviewLimits,
    estimate_payload_size,
)


class DataType(str, Enum):
    """Supported data types with their LLM-safe handling rules."""

    STRUCTURE = "structure"      # Never return atoms, only chain summaries
    SEQUENCE = "sequence"        # Short preview only (100 chars)
    GRN = "grn"                  # Position names only, no full tables
    PROPERTY = "property"        # Schema + stats, limited row preview
    EMBEDDING = "embedding"      # NEVER return vectors, only metadata
    LIGAND = "ligand"            # OK to include full SMILES
    DATASET = "dataset"          # Entity names only, not contents
    ALIGNMENT = "alignment"      # Score/identity only, no sequences
    GRAPH = "graph"              # Node/edge counts only


@dataclass
class DataSummary:
    """
    LLM-safe summary of loaded data.

    This is what gets returned to the LLM instead of raw data.
    """

    data_type: DataType
    name: str
    count: Optional[int] = None           # Number of items/rows/residues
    size_bytes: Optional[int] = None      # Approximate memory size
    schema: Optional[Dict[str, Any]] = None  # Column names, field types
    preview: Optional[str] = None         # Max 100-200 chars preview
    statistics: Optional[Dict[str, Any]] = None  # Aggregated stats
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "data_type": self.data_type.value,
            "name": self.name,
        }
        if self.count is not None:
            result["count"] = self.count
        if self.size_bytes is not None:
            result["size_bytes"] = self.size_bytes
        if self.schema is not None:
            result["schema"] = self.schema
        if self.preview is not None:
            result["preview"] = self.preview
        if self.statistics:
            result["statistics"] = self.statistics
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class LLMResponse:
    """
    Standardized tool response for LLM consumption.

    All tools should return this format to ensure consistency
    and prevent context flooding.
    """

    success: bool
    context_handle: Optional[str] = None  # Handle to retrieve full data
    summary: Optional[DataSummary] = None
    message: Optional[str] = None
    error: Optional[str] = None
    suggestion: Optional[str] = None

    # For operations that produce multiple results
    summaries: Optional[List[DataSummary]] = None

    # For ligands/small data that's OK to include
    data: Optional[Any] = None  # Only used when data is small (SMILES, scores)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary matching format_success/format_error pattern."""
        if not self.success:
            result: Dict[str, Any] = {
                "success": False,
                "error": self.error or "Unknown error",
            }
            if self.suggestion:
                result["suggestion"] = self.suggestion
            return result

        result = {"success": True, "data": {}}

        if self.context_handle:
            result["data"]["context_handle"] = self.context_handle

        if self.summary:
            result["data"].update(self.summary.to_dict())

        if self.summaries:
            result["data"]["items"] = [s.to_dict() for s in self.summaries]
            result["data"]["item_count"] = len(self.summaries)

        if self.data is not None:
            # Merge small data directly into response
            if isinstance(self.data, dict):
                result["data"].update(self.data)
            else:
                result["data"]["value"] = self.data

        if self.message:
            result["message"] = self.message

        return result


def build_structure_summary(
    name: str,
    atom_count: int,
    chains: Dict[str, int],  # chain_id -> residue_count
    *,
    ligands: Optional[List[str]] = None,
    resolution: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> DataSummary:
    """Build LLM-safe summary for a structure."""
    return DataSummary(
        data_type=DataType.STRUCTURE,
        name=name,
        count=atom_count,
        schema={"chains": list(chains.keys())},
        statistics={
            "chain_residue_counts": chains,
            "total_residues": sum(chains.values()),
            "ligands": ligands or [],
            "resolution": resolution,
        },
        metadata=metadata or {},
    )


def build_sequence_summary(
    name: str,
    length: int,
    sequence: str,
    *,
    preview_length: int = 100,
    metadata: Optional[Dict[str, Any]] = None,
) -> DataSummary:
    """Build LLM-safe summary for a sequence."""
    preview = sequence[:preview_length]
    if len(sequence) > preview_length:
        preview += "..."

    return DataSummary(
        data_type=DataType.SEQUENCE,
        name=name,
        count=length,
        preview=preview,
        metadata=metadata or {},
    )


def build_sequence_dataset_summary(
    name: str,
    sequences: Mapping[str, str],
    *,
    max_ids_shown: int = 20,
    metadata: Optional[Dict[str, Any]] = None,
) -> DataSummary:
    """Build LLM-safe summary for a sequence dataset."""
    lengths = [len(seq) for seq in sequences.values()]
    seq_ids = list(sequences.keys())

    return DataSummary(
        data_type=DataType.DATASET,
        name=name,
        count=len(sequences),
        schema={"sequence_ids": seq_ids[:max_ids_shown]},
        statistics={
            "min_length": min(lengths) if lengths else 0,
            "max_length": max(lengths) if lengths else 0,
            "mean_length": sum(lengths) / len(lengths) if lengths else 0,
            "ids_truncated": len(seq_ids) > max_ids_shown,
        },
        metadata=metadata or {},
    )


def build_grn_table_summary(
    name: str,
    sequence_count: int,
    position_count: int,
    *,
    sample_positions: Optional[List[str]] = None,
    coverage_stats: Optional[Dict[str, float]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> DataSummary:
    """Build LLM-safe summary for a GRN table."""
    return DataSummary(
        data_type=DataType.GRN,
        name=name,
        count=sequence_count,
        schema={
            "position_count": position_count,
            "sample_positions": (sample_positions or [])[:20],
        },
        statistics=coverage_stats or {},
        metadata=metadata or {},
    )


def build_property_table_summary(
    name: str,
    row_count: int,
    columns: List[str],
    *,
    column_types: Optional[Dict[str, str]] = None,
    statistics: Optional[Dict[str, Dict[str, Any]]] = None,
    sample_row: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> DataSummary:
    """Build LLM-safe summary for a property table."""
    return DataSummary(
        data_type=DataType.PROPERTY,
        name=name,
        count=row_count,
        schema={
            "columns": columns[:15],  # Cap at 15 columns shown
            "column_types": column_types or {},
            "columns_truncated": len(columns) > 15,
        },
        statistics=statistics or {},
        preview=str(sample_row)[:200] if sample_row else None,
        metadata=metadata or {},
    )


def build_embedding_summary(
    name: str,
    sequence_count: int,
    dimensions: int,
    model_name: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> DataSummary:
    """Build LLM-safe summary for embeddings (NEVER include vectors)."""
    return DataSummary(
        data_type=DataType.EMBEDDING,
        name=name,
        count=sequence_count,
        schema={
            "dimensions": dimensions,
            "model": model_name,
        },
        # No preview - vectors should never be shown
        metadata=metadata or {},
    )


def build_ligand_response(
    name: str,
    smiles: str,
    properties: Dict[str, Any],
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> LLMResponse:
    """
    Build response for ligand data.

    Ligands are small enough to include in full.
    """
    return LLMResponse(
        success=True,
        summary=DataSummary(
            data_type=DataType.LIGAND,
            name=name,
            metadata=metadata or {},
        ),
        data={
            "smiles": smiles,
            "properties": properties,
        },
    )


def build_alignment_summary(
    seq1_name: str,
    seq2_name: str,
    score: float,
    identity: float,
    *,
    length: Optional[int] = None,
    gaps: Optional[int] = None,
    method: Optional[str] = None,
) -> DataSummary:
    """Build LLM-safe summary for sequence alignment (no aligned sequences)."""
    return DataSummary(
        data_type=DataType.ALIGNMENT,
        name=f"{seq1_name}_vs_{seq2_name}",
        statistics={
            "score": score,
            "identity": round(identity, 4),
            "length": length,
            "gaps": gaps,
            "method": method,
        },
    )


def truncate_list(
    items: Sequence[Any],
    max_items: int = 25,
    *,
    stringify: bool = False,
) -> Dict[str, Any]:
    """
    Truncate a list for LLM-safe return.

    Returns dict with items and truncation info.
    """
    total = len(items)
    truncated = total > max_items
    subset = list(items)[:max_items]

    if stringify:
        subset = [str(item) for item in subset]

    return {
        "items": subset,
        "count": total,
        "truncated": truncated,
        "showing": len(subset),
    }


def check_payload_size(
    payload: Any,
    max_bytes: int = 50_000,
) -> tuple[bool, int]:
    """
    Check if payload exceeds size limit.

    Returns (is_ok, size_bytes).
    """
    size = estimate_payload_size(payload)
    return size <= max_bytes, size


def safe_response(
    data: Dict[str, Any],
    max_bytes: int = 50_000,
) -> Dict[str, Any]:
    """
    Ensure response doesn't exceed size limit.

    If too large, returns truncated version with warning.
    """
    is_ok, size = check_payload_size(data, max_bytes)

    if is_ok:
        return data

    # Response too large - return warning
    return {
        "success": True,
        "data": {
            "warning": "Response truncated due to size",
            "size_bytes": size,
            "max_bytes": max_bytes,
            "note": "Use context_handle to access full data",
        },
        "context_handle": data.get("data", {}).get("context_handle"),
    }


__all__ = [
    "DataType",
    "DataSummary",
    "LLMResponse",
    "build_structure_summary",
    "build_sequence_summary",
    "build_sequence_dataset_summary",
    "build_grn_table_summary",
    "build_property_table_summary",
    "build_embedding_summary",
    "build_ligand_response",
    "build_alignment_summary",
    "truncate_list",
    "check_payload_size",
    "safe_response",
]
