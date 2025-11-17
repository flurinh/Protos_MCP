"""Utilities for building bounded context previews returned to LLM clients."""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
)

from pydantic import BaseModel, Field, root_validator

from .exceptions import PayloadTooLargeError

try:  # Optional pandas import (used for structure/entity previews)
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - pandas is available in normal runtimes
    pd = None  # type: ignore


DEFAULT_MAX_ROWS = 500
DEFAULT_MAX_COLUMNS = 40
DEFAULT_MAX_ITEMS = 100
DEFAULT_MAX_CHARS = 4000
DEFAULT_MAX_BYTES = 200_000


class PreviewLimits(BaseModel):
    """Size guardrails used for previews returned to the MCP client."""

    max_rows: int = Field(default=DEFAULT_MAX_ROWS, ge=1)
    max_columns: int = Field(default=DEFAULT_MAX_COLUMNS, ge=1)
    max_items: int = Field(default=DEFAULT_MAX_ITEMS, ge=1)
    max_chars: int = Field(default=DEFAULT_MAX_CHARS, ge=200)
    max_bytes: int = Field(default=DEFAULT_MAX_BYTES, ge=1024)

    def override(self, **kwargs: int) -> "PreviewLimits":
        data = self.model_dump()
        data.update({k: v for k, v in kwargs.items() if v is not None})
        return PreviewLimits(**data)


class ContextPreview(BaseModel):
    """Serialized preview payload validated against the configured limits."""

    kind: str
    summary: Dict[str, Any] = Field(default_factory=dict)
    preview: Any = None
    truncated: bool = False
    bytes_estimate: int = 0
    limits: PreviewLimits = Field(default_factory=PreviewLimits)

    @root_validator(skip_on_failure=True)
    def _validate_size(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        limits: PreviewLimits = values.get("limits")
        size: int = values.get("bytes_estimate") or 0
        if size > limits.max_bytes:
            raise PayloadTooLargeError(size=size, limit=limits.max_bytes)
        return values

    def export(self) -> Dict[str, Any]:
        payload = self.model_dump()
        payload.pop("limits", None)
        return payload


def _estimate_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, Mapping):
        return sum(_estimate_size(k) + _estimate_size(v) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return sum(_estimate_size(item) for item in value)
    return len(str(value).encode("utf-8"))


def estimate_payload_size(value: Any) -> int:
    """Public wrapper for estimating the size of a JSON-serializable object."""

    return _estimate_size(value)


def _ensure_pandas_frame(value: Any):
    if pd is None:
        raise PayloadTooLargeError(
            0, DEFAULT_MAX_BYTES, "Pandas is required for structure previews"
        )
    if not isinstance(value, pd.DataFrame):  # type: ignore[attr-defined]
        raise ValueError("Expected a pandas DataFrame for table preview")
    return value


def build_dataframe_preview(
    frame: Any,
    *,
    limits: Optional[PreviewLimits] = None,
    label: Optional[str] = None,
) -> ContextPreview:
    limits = limits or PreviewLimits()
    df = _ensure_pandas_frame(frame)
    row_limit = limits.max_rows
    col_limit = limits.max_columns
    truncated = False

    preview_df = df.head(row_limit)
    if len(df) > len(preview_df):
        truncated = True

    columns = list(preview_df.columns)
    if len(columns) > col_limit:
        preview_df = preview_df[columns[:col_limit]]
        truncated = True
        columns = columns[:col_limit]

    records = preview_df.reset_index(drop=True).to_dict(orient="records")
    size_estimate = _estimate_size(records)

    summary = {
        "rows": int(len(df)),
        "columns": columns,
        "preview_rows": len(preview_df),
        "label": label,
    }

    return ContextPreview(
        kind="table",
        summary=summary,
        preview=records,
        truncated=truncated,
        bytes_estimate=size_estimate,
        limits=limits,
    )


def build_text_preview(
    text: str,
    *,
    limits: Optional[PreviewLimits] = None,
    label: Optional[str] = None,
) -> ContextPreview:
    limits = limits or PreviewLimits()
    max_chars = limits.max_chars
    truncated = len(text) > max_chars
    snippet = text[:max_chars]
    estimate = _estimate_size(snippet)

    return ContextPreview(
        kind="text",
        summary={"length": len(text), "label": label},
        preview=snippet,
        truncated=truncated,
        bytes_estimate=estimate,
        limits=limits,
    )


def build_sequence_preview(
    sequences: Mapping[str, str] | str,
    *,
    limits: Optional[PreviewLimits] = None,
    preview_length: Optional[int] = None,
    label: Optional[str] = None,
) -> ContextPreview:
    limits = limits or PreviewLimits()
    max_chars = preview_length or limits.max_chars

    if isinstance(sequences, str):
        preview = sequences[:max_chars]
        summary = {"length": len(sequences), "label": label}
        truncated = len(sequences) > len(preview)
        estimate = _estimate_size(preview)
        return ContextPreview(
            kind="sequence",
            summary=summary,
            preview=preview,
            truncated=truncated,
            bytes_estimate=estimate,
            limits=limits,
        )

    items = list(sequences.items())
    truncated = len(items) > limits.max_items
    preview_items = []
    for name, seq in items[: limits.max_items]:
        snippet = seq[:max_chars] if isinstance(seq, str) else seq
        preview_items.append(
            {
                "id": name,
                "length": len(seq) if isinstance(seq, str) else None,
                "preview": snippet,
            }
        )
    estimate = _estimate_size(preview_items)
    summary = {
        "sequence_count": len(items),
        "label": label,
    }
    return ContextPreview(
        kind="sequence_dataset",
        summary=summary,
        preview=preview_items,
        truncated=truncated,
        bytes_estimate=estimate,
        limits=limits,
    )


def build_mapping_preview(
    mapping: Mapping[str, Any],
    *,
    limits: Optional[PreviewLimits] = None,
    label: Optional[str] = None,
) -> ContextPreview:
    limits = limits or PreviewLimits()
    items = list(mapping.items())
    truncated = len(items) > limits.max_items

    preview_items: List[Dict[str, Any]] = []
    for key, value in items[: limits.max_items]:
        display_value = value
        if isinstance(value, str) and len(value) > limits.max_chars:
            display_value = value[: limits.max_chars]
            truncated = True
        preview_items.append({"key": key, "value": display_value})

    estimate = _estimate_size(preview_items)
    summary = {"size": len(items), "label": label}

    return ContextPreview(
        kind="mapping",
        summary=summary,
        preview=preview_items,
        truncated=truncated,
        bytes_estimate=estimate,
        limits=limits,
    )


def build_generic_preview(
    data: Any,
    *,
    limits: Optional[PreviewLimits] = None,
    label: Optional[str] = None,
) -> ContextPreview:
    limits = limits or PreviewLimits()
    if pd is not None and isinstance(data, pd.DataFrame):  # type: ignore[attr-defined]
        return build_dataframe_preview(data, limits=limits, label=label)
    if isinstance(data, str):
        return build_text_preview(data, limits=limits, label=label)
    if isinstance(data, Mapping):
        return build_mapping_preview(data, limits=limits, label=label)
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        subset = list(data)[: limits.max_items]
        truncated = len(data) > len(subset)
        preview = [str(item) for item in subset]
        estimate = _estimate_size(preview)
        return ContextPreview(
            kind="sequence",
            summary={"size": len(data), "label": label},
            preview=preview,
            truncated=truncated,
            bytes_estimate=estimate,
            limits=limits,
        )
    snippet = str(data)
    if len(snippet) > limits.max_chars:
        snippet = snippet[: limits.max_chars]
    estimate = _estimate_size(snippet)
    return ContextPreview(
        kind="object",
        summary={"type": type(data).__name__, "label": label},
        preview=snippet,
        truncated=len(snippet) >= limits.max_chars,
        bytes_estimate=estimate,
        limits=limits,
    )


__all__ = [
    "ContextPreview",
    "PreviewLimits",
    "build_dataframe_preview",
    "build_mapping_preview",
    "build_sequence_preview",
    "build_text_preview",
    "build_generic_preview",
    "estimate_payload_size",
]
