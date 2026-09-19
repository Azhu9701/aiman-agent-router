from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiman_agent_router.bridge import BridgeResponse
from aiman_agent_router.live import LiveRouterRuntime, normalize_kev_result
from aiman_agent_router.registry import CapabilityRegistry
from aiman_agent_router.router import AgentRouter
from aiman_agent_router.trace import TraceStore


def kev_result(*, needs_second_source: bool = False) -> dict:
    def row(answer, probability=0.99):
        return {
            "predictions": {
                "aiman_kev_v02c": {
                    "answer": answer,
                    "raw_probability": probability,
                    "request_id": "kev-test-request",
                }
            }
        }

    return {
        "mode": "shadow",
        "production_effect": "none",
        "decision_packet": {
            "content_type": row("event"),
            "is_event": row(True),
            "event_type": row("funding", 0.93),
            "timeline_worthy": row(True),
            "commercialization_stage": row("not_applicable"),
            "source_quality": row("direct_primary"),
            "needs_second_source": row(needs_second_source),
        },
        "batch": {
            "run_version": "shadow-v0.2-four-line",
            "batch_id": "batch-test",
            "aiman_kev_v02_manifest_sha256": "manifest",
            "aiman_kev_v02_contract_sha256": "contract",
            "transport": "mcp-stdio",
        },
    }


class FakeBridge:
    def __init__(self, *, empty_events: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.empty_events = empty_events

    def call(self, operation: str, arguments: dict) -> BridgeResponse:
        self.calls.append((operation, arguments))
        if operation == "agentdock.health":
            return BridgeResponse(
                operation=operation,
                result={"ok": True, "executor": "agentdock-test"},
            )
        if operation == "kev.analyze":
            return BridgeResponse(operation=operation, result=kev_result())
        if operation == "iwm.timeline.search":
            events = [] if self.empty_events else [
                {
                    "id": 203,
                    "eventKey": "2026-09-17-viabot-series-a-24m",
                    "eventType": "funding",
                    "status": "verified",
                    "sources": [
                        {"sourceType": "official", "url": "https://example.com/official"},
                        {"sourceType": "media", "url": "https://example.com/media"},
                    ],
                }
            ]
            return BridgeResponse(
                operation=operation,
                result={"count": len(events), "events": events},
            )
        raise AssertionError(f"unexpected operation: {operation}")


class LiveRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = CapabilityRegistry.from_directory(ROOT / "registry")
        cls.router = AgentRouter(registry)

    def test_kev_normalization_emits_event_query_hint(self) -> None:
        normalized = normalize_kev_result(kev_result())
        self.assertEqual(normalized["provider"], "aiman-kev-v0.2c")
        self.assertEqual(
            normalized["route_hints"]["required_capabilities"],
            ["event_query"],
        )
        self.assertEqual(
            normalized["decisions"]["event_type"]["answer"],
            "funding",
        )

    def test_live_runtime_routes_executes_verifies_and_persists_trace(self) -> None:
        bridge = FakeBridge()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveRouterRuntime(
                self.router,
                bridge,
                TraceStore(tmp),
            )
            trace = runtime.run(
                {
                    "goal": "Find the canonical Viabot funding event.",
                    "domains": ["robotics"],
                    "intent": "industry_research",
                    "required_capabilities": [],
                    "constraints": {
                        "query": "Viabot",
                        "limit": 10,
                    },
                    "evidence_required": True,
                    "freshness_required": True,
                    "side_effects": False,
                    "metadata": {
                        "kev_input": {
                            "title": "Viabot announced a Series A financing round",
                            "summary": "A robotics-company financing event.",
                            "content": "Viabot announced a funding round.",
                            "source_types": ["official", "industry_media"],
                            "source_count": 2,
                        }
                    },
                }
            )
            self.assertEqual(trace["decision"]["status"], "ready")
            self.assertEqual(trace["decision"]["selected"], ["aiman.robotics"])
            self.assertEqual(trace["result"]["status"], "verified")
            self.assertTrue(trace["result"]["verified"])
            self.assertTrue(Path(trace["trace_path"]).is_file())

            saved = TraceStore(tmp).load(trace["trace_path"])
            self.assertEqual(saved["result"]["status"], "verified")
            self.assertTrue(saved["trace_hash"])
            self.assertEqual(
                [name for name, _ in bridge.calls],
                ["agentdock.health", "kev.analyze", "iwm.timeline.search"],
            )

    def test_live_runtime_fails_verification_when_iwm_returns_no_events(self) -> None:
        bridge = FakeBridge(empty_events=True)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveRouterRuntime(self.router, bridge, TraceStore(tmp))
            trace = runtime.run(
                {
                    "goal": "Find an event.",
                    "domains": ["robotics"],
                    "intent": "industry_research",
                    "required_capabilities": [],
                    "constraints": {"query": "missing"},
                    "evidence_required": True,
                    "freshness_required": True,
                    "side_effects": False,
                }
            )
            self.assertEqual(trace["result"]["status"], "failed")
            self.assertEqual(
                trace["result"]["verification"]["reason"],
                "no_events",
            )


if __name__ == "__main__":
    unittest.main()
