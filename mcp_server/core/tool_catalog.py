"""Tool catalog supporting discovery and guided help for MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolEntry:
    name: str
    group: str
    description: str = ""
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    returns: Dict[str, Any] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    deprecated: bool = False
    tags: List[str] = field(default_factory=list)
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "name": self.name,
            "group": self.group,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
            "aliases": self.aliases,
            "deprecated": self.deprecated,
            "tags": self.tags,
        }
        if self.notes:
            payload["notes"] = self.notes
        return payload


class ToolCatalog:
    """In-memory registry capturing tool metadata for discovery."""

    def __init__(self) -> None:
        self._entries: Dict[str, ToolEntry] = {}
        self._aliases: Dict[str, str] = {}

    def register(
        self,
        *,
        name: str,
        group: str,
        description: str,
        parameters: List[Dict[str, Any]],
        returns: Dict[str, Any],
        aliases: List[str],
        deprecated: bool,
        tags: List[str],
        notes: Optional[str],
    ) -> None:
        entry = ToolEntry(
            name=name,
            group=group,
            description=description,
            parameters=parameters,
            returns=returns,
            aliases=aliases,
            deprecated=deprecated,
            tags=tags,
            notes=notes,
        )
        self._entries[name] = entry
        for alias in aliases:
            self._aliases[alias] = name

    def alias(self, alias_name: str, target: str, *, deprecated: bool = True, note: Optional[str] = None) -> None:
        """Register an alias for an existing tool."""

        if target not in self._entries:
            raise KeyError(f"Cannot create alias '{alias_name}' for unknown tool '{target}'")
        entry = self._entries[target]
        if alias_name not in entry.aliases:
            entry.aliases.append(alias_name)
        self._aliases[alias_name] = target
        if note:
            entry.notes = (entry.notes + "\n" + note) if entry.notes else note
        if deprecated and not entry.deprecated:
            entry.deprecated = False  # target remains active; alias flagged separately

    def resolve(self, name: str) -> Optional[ToolEntry]:
        target = self._aliases.get(name, name)
        return self._entries.get(target)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tools": [entry.to_dict() for entry in sorted(self._entries.values(), key=lambda item: item.name)],
            "groups": self._group_index(),
        }

    def list_groups(self) -> Dict[str, List[str]]:
        return self._group_index()

    def _group_index(self) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        for entry in self._entries.values():
            groups.setdefault(entry.group, []).append(entry.name)
        for names in groups.values():
            names.sort()
        return groups

    def search_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        return [
            entry.to_dict()
            for entry in self._entries.values()
            if tag in entry.tags
        ]


__all__ = ["ToolCatalog", "ToolEntry"]
