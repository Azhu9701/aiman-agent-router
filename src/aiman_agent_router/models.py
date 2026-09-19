from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any


def _string_tuple(value: Any, *, field_name: str, allow_empty: bool = True) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field_name} must be an array of non-empty strings")
    result = tuple(dict.fromkeys(item.strip() for item in value))
    if not allow_empty and not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _stable_task_id(payload: dict[str, Any]) -> str:
    normalized = {key: value for key, value in payload.items() if key != "task_id"}
    raw = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "task_" + hashlib.sha256(raw).hexdigest()[:16]


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    goal: str
    domains: tuple[str, ...]
    intent: str
    required_capabilities: tuple[str, ...] = ()
    constraints: dict[str, Any] = field(default_factory=dict)
    evidence_required: bool = True
    freshness_required: bool = False
    side_effects: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskEnvelope":
        if not isinstance(payload, dict):
            raise ValueError("task envelope must be an object")
        goal = str(payload.get("goal", "")).strip()
        if not goal:
            raise ValueError("goal is required")
        domains = _string_tuple(payload.get("domains"), field_name="domains", allow_empty=False)
        intent = str(payload.get("intent", "research")).strip() or "research"
        required = _string_tuple(payload.get("required_capabilities", []), field_name="required_capabilities")
        constraints = payload.get("constraints", {})
        metadata = payload.get("metadata", {})
        if not isinstance(constraints, dict):
            raise ValueError("constraints must be an object")
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        task_id = str(payload.get("task_id", "")).strip() or _stable_task_id(payload)
        return cls(
            task_id=task_id,
            goal=goal,
            domains=domains,
            intent=intent,
            required_capabilities=required,
            constraints=constraints,
            evidence_required=bool(payload.get("evidence_required", True)),
            freshness_required=bool(payload.get("freshness_required", False)),
            side_effects=bool(payload.get("side_effects", False)),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "domains": list(self.domains),
            "intent": self.intent,
            "required_capabilities": list(self.required_capabilities),
            "constraints": self.constraints,
            "evidence_required": self.evidence_required,
            "freshness_required": self.freshness_required,
            "side_effects": self.side_effects,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class CapabilityDescriptor:
    id: str
    type: str
    name: str
    domains: tuple[str, ...]
    capabilities: tuple[str, ...]
    protocols: tuple[str, ...] = ()
    provenance: str = "unknown"
    freshness: dict[str, Any] = field(default_factory=dict)
    write_policy: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    enabled: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CapabilityDescriptor":
        identifier = str(payload.get("id", "")).strip()
        kind = str(payload.get("type", "")).strip()
        name = str(payload.get("name", "")).strip()
        if not identifier or not kind or not name:
            raise ValueError("capability descriptor requires id, type, and name")
        domains = _string_tuple(payload.get("domains", ["*"]), field_name="domains", allow_empty=False)
        capabilities = _string_tuple(payload.get("capabilities", []), field_name="capabilities", allow_empty=False)
        protocols = _string_tuple(payload.get("protocols", []), field_name="protocols")
        freshness = payload.get("freshness", {})
        write_policy = payload.get("write_policy", {})
        execution = payload.get("execution", {})
        if not isinstance(freshness, dict) or not isinstance(write_policy, dict) or not isinstance(execution, dict):
            raise ValueError("freshness, write_policy, and execution must be objects")
        return cls(
            id=identifier,
            type=kind,
            name=name,
            domains=domains,
            capabilities=capabilities,
            protocols=protocols,
            provenance=str(payload.get("provenance", "unknown")),
            freshness=freshness,
            write_policy=write_policy,
            execution=execution,
            priority=int(payload.get("priority", 0)),
            enabled=bool(payload.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "domains": list(self.domains),
            "capabilities": list(self.capabilities),
            "protocols": list(self.protocols),
            "provenance": self.provenance,
            "freshness": self.freshness,
            "write_policy": self.write_policy,
            "execution": self.execution,
            "priority": self.priority,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class RoutingDecision:
    task_id: str
    status: str
    selected: tuple[str, ...]
    candidate_scores: dict[str, int]
    missing_capabilities: tuple[str, ...]
    human_review_required: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "selected": list(self.selected),
            "candidate_scores": self.candidate_scores,
            "missing_capabilities": list(self.missing_capabilities),
            "human_review_required": self.human_review_required,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class ExecutionStep:
    id: str
    kind: str
    target: str
    capabilities: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "capabilities": list(self.capabilities),
            "depends_on": list(self.depends_on),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ExecutionPlan:
    task_id: str
    status: str
    steps: tuple[ExecutionStep, ...]
    human_review_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "human_review_required": self.human_review_required,
        }


@dataclass(frozen=True)
class ExecutionResult:
    task_id: str
    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[dict[str, Any], ...] = ()
    trace: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "outputs": self.outputs,
            "evidence": list(self.evidence),
            "trace": list(self.trace),
        }
