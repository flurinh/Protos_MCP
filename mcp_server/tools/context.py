"""Context/session management tools for MCP."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseTool


class ContextTools(BaseTool):
    """Expose session-scoped context operations to MCP clients."""

    def register(self, server) -> None:
        @server.tool()
        def context_status(ctx) -> Dict[str, Any]:
            """Return a summary snapshot of the current session context."""

            snapshot = self.session.snapshot()
            return self.format_success(snapshot)
        self.register_tool_metadata(
            function=context_status,
            name="context_status",
            group="context",
            tags=["context", "status"],
            returns={"type": "session_snapshot"},
        )

        @server.tool()
        def context_list(
            ctx,
            kind: Optional[str] = None,
            processor_type: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """List stored context artifacts filtered by kind/processor/tags."""

            artifacts = [
                artifact.to_dict()
                for artifact in self.session.iter_artifacts(
                    kind=kind,
                    processor_type=processor_type,
                    tags=tags,
                )
            ]
            payload = {
                "count": len(artifacts),
                "artifacts": artifacts,
            }
            if kind:
                payload["kind"] = kind
            if processor_type:
                payload["processor_type"] = processor_type
            if tags:
                payload["tags"] = tags
            return self.format_success(payload)
        self.register_tool_metadata(
            function=context_list,
            name="context_list",
            group="context",
            tags=["context", "list"],
            parameters=[
                {"name": "kind", "type": "str", "optional": True},
                {"name": "processor_type", "type": "str", "optional": True},
                {"name": "tags", "type": "list[str]", "optional": True},
            ],
            returns={"fields": ["count", "artifacts"]},
        )

        @server.tool()
        def context_get(
            ctx,
            handle: str,
            resolve: bool = False,
            preview_length: int = 120,
            max_items: int = 25,
        ) -> Dict[str, Any]:
            """Fetch a stored artifact and optionally resolve underlying data."""

            artifact = self.session.get_artifact(handle)
            if not artifact:
                return self.format_error(
                    f"No artifact found for handle '{handle}'",
                    "Use context_list to view available handles.",
                )

            payload: Dict[str, Any] = artifact.to_dict()

            if resolve:
                resolution = self._resolve_artifact(
                    artifact,
                    preview_length=preview_length,
                    max_items=max_items,
                )
                payload["resolved"] = resolution

            return self.format_success(payload)
        self.register_tool_metadata(
            function=context_get,
            name="context_get",
            group="context",
            tags=["context", "inspect"],
            parameters=[
                {"name": "handle", "type": "str"},
                {"name": "resolve", "type": "bool", "default": False},
            ],
            returns={"fields": ["artifact", "resolved"]},
        )

        @server.tool()
        def context_set_active(ctx, handle: str, scope: Optional[str] = None) -> Dict[str, Any]:
            """Mark an artifact handle as active for a given scope."""

            key = scope or "default"
            if not self.session.set_active(scope=key, handle=handle):
                return self.format_error(
                    f"Cannot activate unknown handle '{handle}'",
                    "Use context_list to locate a valid handle.",
                )
            artifact = self.session.get_artifact(handle)
            return self.format_success(
                {
                    "scope": key,
                    "handle": handle,
                    "artifact": artifact.to_dict() if artifact else None,
                },
                message="Handle activated",
            )
        self.register_tool_metadata(
            function=context_set_active,
            name="context_set_active",
            group="context",
            tags=["context", "active"],
            parameters=[
                {"name": "handle", "type": "str"},
                {"name": "scope", "type": "str", "optional": True},
            ],
            returns={"fields": ["scope", "handle"]},
        )

        @server.tool()
        def context_clear(
            ctx,
            handle: Optional[str] = None,
            kind: Optional[str] = None,
            processor_type: Optional[str] = None,
            clear_all: bool = False,
        ) -> Dict[str, Any]:
            """Remove stored artifacts matching the provided filters."""

            removed: List[str] = []
            if clear_all:
                removed = [artifact.handle for artifact in self.session.iter_artifacts()]
                self.session.clear_all()
            elif handle:
                if self.session.clear_artifact(handle):
                    removed.append(handle)
            else:
                for artifact in list(
                    self.session.iter_artifacts(
                        kind=kind,
                        processor_type=processor_type,
                    )
                ):
                    if self.session.clear_artifact(artifact.handle):
                        removed.append(artifact.handle)

            return self.format_success(
                {
                    "removed": removed,
                    "cleared_all": clear_all,
                },
                message="Context cleared" if removed else "No matching artifacts",
            )
        self.register_tool_metadata(
            function=context_clear,
            name="context_clear",
            group="context",
            tags=["context", "clear"],
            parameters=[
                {"name": "handle", "type": "str", "optional": True},
                {"name": "kind", "type": "str", "optional": True},
                {"name": "processor_type", "type": "str", "optional": True},
                {"name": "clear_all", "type": "bool", "default": False},
            ],
        )

        @server.tool()
        def context_history(ctx, limit: int = 25) -> Dict[str, Any]:
            """Return the recent context history events."""

            history = self.session.history(limit=limit)
            return self.format_success({"count": len(history), "events": history})
        self.register_tool_metadata(
            function=context_history,
            name="context_history",
            group="context",
            tags=["context", "history"],
            parameters=[{"name": "limit", "type": "int", "default": 25}],
            returns={"fields": ["events"]},
        )

        @server.tool()
        def context_reset(ctx) -> Dict[str, Any]:
            """Clear all recorded artifacts and history for the session."""

            self.session.reset()
            return self.format_success(
                {
                    "artifact_count": 0,
                    "active": {},
                },
                message="Session context reset",
            )
        self.register_tool_metadata(
            function=context_reset,
            name="context_reset",
            group="context",
            tags=["context", "reset"],
        )

    # ------------------------------------------------------------------

    def _resolve_artifact(
        self,
        artifact,
        *,
        preview_length: int,
        max_items: int,
    ) -> Dict[str, Any]:
        """Attempt to resolve the underlying data for an artifact."""

        payload: Dict[str, Any] = {"kind": artifact.kind}
        processor_type = artifact.processor_type

        if artifact.kind == "dataset" and processor_type:
            processor = self.get_processor(processor_type)
            manager = getattr(processor, "dataset_manager", None)
            if manager and manager.dataset_exists(artifact.name):
                info = manager.get_dataset_info(artifact.name)
                entities = manager.get_dataset_entities(artifact.name)
                payload.update(
                    {
                        "dataset_info": info,
                        "entities": entities[:max_items],
                        "entity_count": len(entities),
                        "truncated": len(entities) > max_items,
                    }
                )
        elif artifact.kind == "entity" and processor_type:
            processor = self.get_processor(processor_type)
            if hasattr(processor, "load_entity"):
                entity = processor.load_entity(artifact.name)
                payload.update(self._summarize_entity(entity, preview_length=preview_length))
        elif artifact.kind == "result":
            payload.update({"summary": artifact.summary})

        return payload

    def _summarize_entity(self, entity, *, preview_length: int) -> Dict[str, Any]:
        """Create a lightweight summary for an entity payload."""

        if entity is None:
            return {"entity": None}

        if isinstance(entity, str):
            return {
                "entity_type": "sequence",
                "length": len(entity),
                "preview": entity[:preview_length],
            }
        if isinstance(entity, dict):
            sample = list(entity.items())[:10]
            preview = [
                {
                    "key": key,
                    "length": len(value) if isinstance(value, str) else None,
                    "preview": value[:preview_length] if isinstance(value, str) else None,
                }
                for key, value in sample
            ]
            return {
                "entity_type": "mapping",
                "size": len(entity),
                "preview": preview,
                "truncated": len(entity) > len(sample),
            }
        if hasattr(entity, "shape"):
            rows = getattr(entity, "shape", [None])[0]
            cols = getattr(entity, "columns", None)
            return {
                "entity_type": "table",
                "rows": rows,
                "columns": list(cols)[:20] if cols is not None else None,
            }
        return {"entity": str(entity)}


__all__ = ["ContextTools"]
