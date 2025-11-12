"""Session-scoped context state for the Protos MCP server."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, Iterable, List, Optional
from collections import deque
import re
import uuid


_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _slug(value: Optional[str]) -> str:
    if not value:
        return "item"
    text = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    text = text.strip("_") or "item"
    return text.lower()


@dataclass
class SessionArtifact:
    """Entry describing a dataset/entity/model result stored in the session."""

    handle: str
    name: str
    kind: str
    processor_type: Optional[str] = None
    summary: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    source_tool: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "handle": self.handle,
            "name": self.name,
            "kind": self.kind,
            "processor_type": self.processor_type,
            "summary": self.summary,
            "tags": list(self.tags),
            "source_tool": self.source_tool,
            "created_at": self.created_at.strftime(_DATETIME_FORMAT),
        }
        return payload


@dataclass
class SessionEvent:
    """History entry recording recent tool invocations."""

    tool_name: str
    action: str
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())
    details: Dict[str, Any] = field(default_factory=dict)
    handle: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "tool_name": self.tool_name,
            "action": self.action,
            "created_at": self.created_at.strftime(_DATETIME_FORMAT),
            "details": self.details,
        }
        if self.handle:
            payload["handle"] = self.handle
        return payload


class SessionState:
    """Runtime store tracking artifacts and history for a single MCP session."""

    def __init__(self, *, history_limit: int = 200) -> None:
        self._artifacts: Dict[str, SessionArtifact] = {}
        self._active: Dict[str, str] = {}
        self._history: Deque[SessionEvent] = deque(maxlen=history_limit)
        self._history_limit = history_limit

    # Artifact management -------------------------------------------------

    def _make_handle(self, *, kind: str, name: Optional[str] = None, label: Optional[str] = None) -> str:
        slug = _slug(label or name or kind)
        token = uuid.uuid4().hex[:8]
        return f"{kind}.{slug}.{token}"

    def record_artifact(
        self,
        *,
        name: str,
        kind: str,
        processor_type: Optional[str],
        summary: Optional[Dict[str, Any]] = None,
        tags: Optional[Iterable[str]] = None,
        source_tool: Optional[str] = None,
        handle: Optional[str] = None,
        label: Optional[str] = None,
        scope: Optional[str] = None,
        activate: bool = True,
    ) -> SessionArtifact:
        """Store (or update) an artifact description and optionally mark it active."""

        resolved_handle = handle or self._make_handle(kind=kind, name=name, label=label)
        artifact = SessionArtifact(
            handle=resolved_handle,
            name=name,
            kind=kind,
            processor_type=processor_type,
            summary=summary or {},
            tags=list(tags or []),
            source_tool=source_tool,
        )
        self._artifacts[resolved_handle] = artifact

        if activate:
            key = scope or kind
            self._active[key] = resolved_handle

        self.record_event(
            tool_name=source_tool or "unknown",
            action=f"record_{kind}",
            handle=resolved_handle,
            details={"name": name, "processor_type": processor_type},
        )
        return artifact

    def get_artifact(self, handle: str) -> Optional[SessionArtifact]:
        return self._artifacts.get(handle)

    def iter_artifacts(
        self,
        *,
        kind: Optional[str] = None,
        processor_type: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> Iterable[SessionArtifact]:
        tag_set = set(tags or [])
        for artifact in self._artifacts.values():
            if kind and artifact.kind != kind:
                continue
            if processor_type and artifact.processor_type != processor_type:
                continue
            if tag_set and not tag_set.issubset(set(artifact.tags)):
                continue
            yield artifact

    def list_artifacts(self) -> List[Dict[str, Any]]:
        return [artifact.to_dict() for artifact in sorted(self._artifacts.values(), key=lambda a: a.created_at)]

    def clear_artifact(self, handle: str) -> bool:
        if handle in self._artifacts:
            self._artifacts.pop(handle)
            for key, active_handle in list(self._active.items()):
                if active_handle == handle:
                    self._active.pop(key, None)
            self.record_event(
                tool_name="context",
                action="clear_artifact",
                handle=handle,
            )
            return True
        return False

    def clear_all(self) -> None:
        self._artifacts.clear()
        self._active.clear()
        self.record_event(tool_name="context", action="clear_all")

    # Active handles ------------------------------------------------------

    def set_active(self, *, scope: str, handle: str) -> bool:
        if handle not in self._artifacts:
            return False
        self._active[scope] = handle
        self.record_event(
            tool_name="context",
            action="set_active",
            handle=handle,
            details={"scope": scope},
        )
        return True

    def get_active(self, scope: str) -> Optional[str]:
        return self._active.get(scope)

    def active_snapshot(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {}
        for scope, handle in self._active.items():
            artifact = self._artifacts.get(handle)
            snapshot[scope] = artifact.to_dict() if artifact else {"handle": handle}
        return snapshot

    # History -------------------------------------------------------------

    def record_event(
        self,
        *,
        tool_name: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        handle: Optional[str] = None,
    ) -> None:
        event = SessionEvent(
            tool_name=tool_name,
            action=action,
            details=details or {},
            handle=handle,
        )
        self._history.append(event)

    def history(self, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if limit is None or limit >= len(self._history):
            iterable = self._history
        else:
            iterable = list(self._history)[-limit:]
        return [event.to_dict() for event in iterable]

    # Snapshots -----------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        return {
            "artifact_count": len(self._artifacts),
            "artifacts": self.list_artifacts(),
            "active": self.active_snapshot(),
            "history": self.history(limit=20),
        }

    def reset(self) -> None:
        self._artifacts.clear()
        self._active.clear()
        self._history.clear()


__all__ = [
    "SessionArtifact",
    "SessionEvent",
    "SessionState",
]
