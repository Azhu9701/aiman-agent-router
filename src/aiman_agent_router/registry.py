from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import CapabilityDescriptor


class CapabilityRegistry:
    def __init__(self, descriptors: Iterable[CapabilityDescriptor]):
        items = list(descriptors)
        ids = [item.id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate capability descriptor id")
        self._items = {item.id: item for item in items}

    @classmethod
    def from_directory(cls, root: str | Path) -> "CapabilityRegistry":
        base = Path(root)
        if not base.is_dir():
            raise ValueError(f"registry directory not found: {base}")
        descriptors: list[CapabilityDescriptor] = []
        for path in sorted(base.rglob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            descriptors.append(CapabilityDescriptor.from_dict(payload))
        return cls(descriptors)

    def all(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(self._items[key] for key in sorted(self._items))

    def get(self, identifier: str) -> CapabilityDescriptor:
        try:
            return self._items[identifier]
        except KeyError as exc:
            raise KeyError(f"unknown capability descriptor: {identifier}") from exc

    def by_type(self, kind: str) -> tuple[CapabilityDescriptor, ...]:
        return tuple(item for item in self.all() if item.type == kind and item.enabled)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_default_registry() -> CapabilityRegistry:
    return CapabilityRegistry.from_directory(repository_root() / "registry")
