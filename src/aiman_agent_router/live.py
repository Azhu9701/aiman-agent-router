from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from .bridge import BridgeError, CommandBridge
from .models import TaskEnvelope
from .router import AgentRouter
from .trace import TraceStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _v02_prediction(packet: dict[str, Any], name: str) -> dict[str, Any]:
    row = packet.get(name)
    if not isinstance(row, dict):
        return {}
    predictions = row.get("predictions")
    if not isinstance(predictions, dict):
        return {}
    prediction = predictions.get("aiman_kev_v02c")
    return prediction if isinstance(prediction, dict) else {}


def normalize_kev_result(result: dict[str, Any]) -> dict[str, Any]:
    packet = result.get("decision_packet")
    if not isinstance(packet, dict):
        raise ValueError("Kev result is missing decision_packet")

    decisions: dict[str, Any] = {}
    for name in (
        "content_type",
        "is_event",
        "event_type",
        "timeline_worthy",
        "commercialization_stage",
        "source_quality",
        "needs_second_source",
    ):
        prediction = _v02_prediction(packet, name)
        if not prediction:
            continue
        decisions[name] = {
            "answer": prediction.get("answer"),
            "confidence": prediction.get("raw_probability"),
            "request_id": prediction.get("request_id"),
        }

    hints: list[str] = []
    if decisions.get("is_event", {}).get("answer") is True:
        hints.append("event_query")
    if decisions.get("needs_second_source", {}).get("answer") is True:
        hints.append("evidence_gathering")

    batch = result.get("batch") if isinstance(result.get("batch"), dict) else {}
    return {
        "provider": "aiman-kev-v0.2c",
        "mode": result.get("mode"),
        "production_effect": result.get("production_effect"),
        "decisions": decisions,
        "route_hints": {
            "required_capabilities": hints,
        },
        "provenance": {
            "run_version": batch.get("run_version"),
            "batch_id": batch.get("batch_id"),
            "manifest_sha256": batch.get("aiman_kev_v02_manifest_sha256"),
            "contract_sha256": batch.get("aiman_kev_v02_contract_sha256"),
            "transport": batch.get("transport"),
        },
    }


class LiveRouterRuntime:
    """Read-only v0.2 runtime.

    AgentDock provides the environment bridge. Router keeps task/routing policy,
    trace semantics, and verification logic.
    """

    def __init__(
        self,
        router: AgentRouter,
        bridge: CommandBridge,
        trace_store: TraceStore,
    ) -> None:
        self.router = router
        self.bridge = bridge
        self.trace_store = trace_store

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        working = copy.deepcopy(payload)
        base_task = TaskEnvelope.from_dict(working)
        working["task_id"] = base_task.task_id

        trace: dict[str, Any] = {
            "schema_version": "aiman-router-trace-v0.2",
            "started_at": _utc_now(),
            "input": copy.deepcopy(payload),
            "execution_fabric": {},
            "kev": {},
            "task": {},
            "decision": {},
            "plan": {},
            "execution": [],
            "result": {},
        }

        try:
            health = self.bridge.call("agentdock.health", {})
            trace["execution_fabric"] = health.result
        except BridgeError as exc:
            trace["execution_fabric"] = {
                "ok": False,
                "error": str(exc),
            }

        kev_args = self._kev_arguments(working, base_task.task_id)
        kev_response = self.bridge.call("kev.analyze", kev_args)
        kev = normalize_kev_result(kev_response.result)
        trace["kev"] = kev

        self._apply_route_hints(working, kev)
        routed = self.router.route_and_plan(working)
        trace["task"] = routed["task"]
        trace["decision"] = routed["decision"]
        trace["plan"] = routed["plan"]

        if routed["decision"]["status"] != "ready":
            trace["result"] = {
                "status": "needs_review",
                "verified": False,
                "reason": "router_not_ready",
            }
            return self._finish(trace)

        if routed["task"]["side_effects"]:
            trace["result"] = {
                "status": "needs_review",
                "verified": False,
                "reason": "v0.2_live_runtime_is_read_only",
            }
            return self._finish(trace)

        outputs: dict[str, Any] = {}
        execution_rows: list[dict[str, Any]] = []
        unsupported: list[str] = []

        for identifier in routed["decision"]["selected"]:
            if identifier == "aiman.robotics":
                query = self._iwm_query(routed["task"])
                limit = int(routed["task"]["constraints"].get("limit", 10))
                response = self.bridge.call(
                    "iwm.timeline.search",
                    {"query": query, "limit": max(1, min(limit, 50))},
                )
                outputs[identifier] = response.result
                execution_rows.append(
                    {
                        "target": identifier,
                        "operation": response.operation,
                        "status": "completed",
                    }
                )
                continue

            unsupported.append(identifier)
            execution_rows.append(
                {
                    "target": identifier,
                    "status": "not_executed",
                    "reason": "no_live_adapter_v0.2",
                }
            )

        trace["execution"] = execution_rows

        if unsupported:
            trace["result"] = {
                "status": "needs_review",
                "verified": False,
                "reason": "unsupported_live_target",
                "targets": unsupported,
                "outputs": outputs,
            }
            return self._finish(trace)

        verification = self._verify(routed["task"], outputs)
        trace["result"] = {
            "status": "verified" if verification["ok"] else "failed",
            "verified": verification["ok"],
            "verification": verification,
            "outputs": outputs,
        }
        return self._finish(trace)

    def _kev_arguments(
        self,
        payload: dict[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        source = metadata.get("kev_input")
        source = source if isinstance(source, dict) else {}
        source_types = source.get("source_types")
        source_count = source.get("source_count")
        return {
            "content_id": str(source.get("content_id") or task_id),
            "title": str(source.get("title") or payload.get("goal") or ""),
            "summary": str(source.get("summary") or ""),
            "content": str(source.get("content") or payload.get("goal") or ""),
            "source_types": source_types if isinstance(source_types, list) else None,
            "source_count": source_count if isinstance(source_count, int) else None,
            "mode": "shadow",
        }

    @staticmethod
    def _apply_route_hints(
        payload: dict[str, Any],
        kev: dict[str, Any],
    ) -> None:
        current = payload.get("required_capabilities")
        if not isinstance(current, list):
            current = []
        hints = (
            kev.get("route_hints", {}).get("required_capabilities", [])
            if isinstance(kev.get("route_hints"), dict)
            else []
        )
        merged = list(dict.fromkeys([*current, *hints]))
        payload["required_capabilities"] = merged

        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            payload["metadata"] = metadata
        metadata["kev_snapshot"] = kev

    @staticmethod
    def _iwm_query(task: dict[str, Any]) -> str:
        constraints = task.get("constraints")
        constraints = constraints if isinstance(constraints, dict) else {}
        query = constraints.get("query")
        if isinstance(query, str) and query.strip():
            return query.strip()
        raise ValueError("live IWM execution requires constraints.query")

    @staticmethod
    def _verify(
        task: dict[str, Any],
        outputs: dict[str, Any],
    ) -> dict[str, Any]:
        robotics = outputs.get("aiman.robotics")
        if not isinstance(robotics, dict):
            return {"ok": False, "reason": "missing_robotics_output"}

        events = robotics.get("events")
        if not isinstance(events, list) or not events:
            return {"ok": False, "reason": "no_events"}

        verified = [
            event
            for event in events
            if isinstance(event, dict) and event.get("status") == "verified"
        ]
        if not verified:
            return {"ok": False, "reason": "no_verified_events"}

        if task.get("evidence_required"):
            with_sources = [
                event
                for event in verified
                if isinstance(event.get("sources"), list) and event.get("sources")
            ]
            if not with_sources:
                return {"ok": False, "reason": "verified_events_lack_sources"}

        return {
            "ok": True,
            "event_count": len(events),
            "verified_event_count": len(verified),
            "evidence_required": bool(task.get("evidence_required")),
        }

    def _finish(self, trace: dict[str, Any]) -> dict[str, Any]:
        trace["completed_at"] = _utc_now()
        path = self.trace_store.save(trace)
        trace["trace_path"] = str(path)
        return trace
