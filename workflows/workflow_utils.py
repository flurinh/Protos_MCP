"""
Workflow utilities for memory-efficient MCP tool interactions.

This module provides:
- Response normalization without full payload storage
- Summary extraction from tool responses
- Memory-efficient result formatting
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union


def convert_payload(value: Any) -> Any:
    """Convert MCP response payload to native Python types."""
    text_attr = getattr(value, "text", None)
    if isinstance(text_attr, str) and text_attr:
        try:
            return json.loads(text_attr)
        except Exception:
            return text_attr

    if isinstance(value, list):
        converted = [convert_payload(item) for item in value]
        if len(converted) == 1 and isinstance(converted[0], dict):
            return converted[0]
        return converted

    if isinstance(value, tuple):
        return tuple(convert_payload(item) for item in value)

    if isinstance(value, dict):
        return {key: convert_payload(val) for key, val in value.items()}

    return value


def normalize_response(raw: Any) -> Dict[str, Any]:
    """Normalize MCP tool response to standard format."""
    if isinstance(raw, tuple) and len(raw) == 2:
        messages, meta = raw
    else:
        messages = []
        meta = raw

    text_messages: List[str] = []
    for msg in messages or []:
        text = getattr(msg, "text", None)
        if text:
            text_messages.append(text)

    meta_converted = convert_payload(meta)

    if isinstance(meta_converted, dict):
        candidate = meta_converted.get("result", meta_converted)
        if isinstance(candidate, dict):
            payload = candidate
        else:
            payload = {"result": candidate}
    else:
        payload = {"result": meta_converted}

    if text_messages:
        payload = {**payload, "messages": text_messages}
    return payload


def extract_summary(response: Dict[str, Any], max_items: int = 5) -> Dict[str, Any]:
    """
    Extract a memory-efficient summary from a tool response.

    Args:
        response: Full tool response
        max_items: Maximum number of items to include in lists

    Returns:
        Summarized response with truncated lists and omitted large data
    """
    data = response.get("data", response)
    summary: Dict[str, Any] = {
        "success": response.get("success", True),
    }

    # Extract key metadata without large payloads
    for key in ["message", "error", "suggestion", "count", "total", "num_entities",
                "num_results", "dataset_name", "entity_name", "table_name"]:
        if key in data:
            summary[key] = data[key]
        elif key in response:
            summary[key] = response[key]

    # Handle entity lists - truncate and indicate total
    if "entities" in data:
        entities = data["entities"]
        if isinstance(entities, list):
            summary["entity_count"] = len(entities)
            summary["entities_preview"] = entities[:max_items]
            if len(entities) > max_items:
                summary["entities_truncated"] = True

    # Handle sequences - report IDs only, not content
    if "sequences" in data:
        sequences = data["sequences"]
        if isinstance(sequences, dict):
            summary["sequence_ids"] = list(sequences.keys())[:max_items]
            summary["sequence_count"] = len(sequences)

    # Handle DataFrame-like results
    if "dataframe" in data or "records" in data:
        records = data.get("dataframe") or data.get("records", [])
        if isinstance(records, list):
            summary["record_count"] = len(records)
            summary["records_preview"] = records[:max_items]

    # Handle interaction summaries
    if "summaries" in data:
        summary["summaries"] = data["summaries"]

    # Include artifact paths (lightweight)
    if "artifact_path" in data:
        summary["artifact_path"] = data["artifact_path"]
    if "artifacts" in data:
        summary["artifacts"] = data["artifacts"]

    return summary


def format_workflow_result(
    result: Dict[str, Any],
    verbose: bool = False,
    max_preview_items: int = 3
) -> str:
    """
    Format workflow result for display without memory bloat.

    Args:
        result: Workflow result dictionary
        verbose: Include more detail (but still summarized)
        max_preview_items: Max items to show in previews

    Returns:
        Formatted string representation
    """
    lines: List[str] = []

    for key, value in result.items():
        if value is None:
            continue

        lines.append(f"\n--- {key} ---")

        if isinstance(value, dict):
            # Extract summary info
            success = value.get("success", value.get("data", {}).get("success"))
            if success is not None:
                lines.append(f"  success: {success}")

            # Report counts not contents
            data = value.get("data", value)

            for count_key in ["count", "total", "num_entities", "num_results",
                              "entity_count", "sequence_count", "record_count"]:
                if count_key in data:
                    lines.append(f"  {count_key}: {data[count_key]}")

            # Report artifact paths
            if "artifact_path" in data:
                lines.append(f"  artifact: {data['artifact_path']}")

            # Show error/message
            if "error" in data:
                lines.append(f"  error: {data['error']}")
            if "message" in data:
                lines.append(f"  message: {data['message']}")

            # Preview entity names (not full data)
            if "entities" in data and isinstance(data["entities"], list):
                preview = data["entities"][:max_preview_items]
                lines.append(f"  entities ({len(data['entities'])}): {preview}...")

            if "sequence_ids" in data:
                lines.append(f"  sequences: {data['sequence_ids']}")
            elif "sequences" in data and isinstance(data["sequences"], dict):
                seq_ids = list(data["sequences"].keys())[:max_preview_items]
                lines.append(f"  sequences ({len(data['sequences'])}): {seq_ids}...")

        elif isinstance(value, str):
            # Truncate long strings
            if len(value) > 200:
                lines.append(f"  {value[:200]}...")
            else:
                lines.append(f"  {value}")
        else:
            lines.append(f"  {type(value).__name__}: {str(value)[:100]}")

    return "\n".join(lines)


def get_entity_ids_from_response(response: Dict[str, Any]) -> List[str]:
    """Extract entity IDs from a response without loading full data."""
    data = response.get("data", response)

    # Try various entity list patterns
    if "entities" in data:
        entities = data["entities"]
        if isinstance(entities, list):
            return [
                e.get("entity_id") or e.get("name") or e.get("sequence_id") or str(e)
                for e in entities
                if isinstance(e, dict)
            ] or entities

    if "sequences" in data and isinstance(data["sequences"], dict):
        return list(data["sequences"].keys())

    if "entity_ids" in data:
        return data["entity_ids"]

    return []


def get_dataset_stats(response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract dataset statistics without full content."""
    data = response.get("data", response)
    stats: Dict[str, Any] = {}

    for key in ["count", "total", "num_entities", "num_sequences",
                "entity_count", "sequence_count"]:
        if key in data:
            stats[key] = data[key]

    if "metadata" in data:
        stats["metadata"] = data["metadata"]

    if "dataset_name" in data:
        stats["dataset_name"] = data["dataset_name"]

    return stats
