from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiman_agent_router.bridge import BridgeError, BridgeResponse
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
    def __init__(
        self,
        *,
        empty_events: bool = False,
        scout_fail: bool = False,
        scout_bridge_error: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.empty_events = empty_events
        self.scout_fail = scout_fail
        self.scout_bridge_error = scout_bridge_error

    def call(self, operation: str, arguments: dict) -> BridgeResponse:
        self.calls.append((operation, arguments))
        if operation == "agentdock.health":
            return BridgeResponse(
                operation=operation,
                result={"ok": True, "executor": "agentdock-test"},
            )
        if operation == "kev.analyze":
            return BridgeResponse(operation=operation, result=kev_result())
        if operation == "context.scout":
            if self.scout_bridge_error:
                raise BridgeError("simulated scout transport failure")
            if self.scout_fail:
                return BridgeResponse(
                    operation=operation,
                    result={
                        "ok": False,
                        "code": "SCOUT_MODEL_UNAVAILABLE",
                        "fallback": "normal_repository_inspection",
                        "read_only": True,
                        "production_effect": "none",
                        "elapsed_ms": 1,
                    },
                )
            return BridgeResponse(
                operation=operation,
                result={
                    "ok": True,
                    "workspace": arguments["workspace"],
                    "source_head": "abc123",
                    "read_only": True,
                    "production_effect": "none",
                    "isolation": "committed_head_snapshot_no_remote",
                    "elapsed_ms": 7,
                    "citations": [
                        {
                            "path": "src/aiman_agent_router/router.py",
                            "source_ref": "src/aiman_agent_router/router.py:1-20",
                            "verified": True,
                        }
                    ],
                },
            )
        if operation == "deepseek.harness.propose":
            return BridgeResponse(
                operation=operation,
                result={
                    "ok": True,
                    "worker": "deepseek-harness.headless",
                    "harnessVersion": "test",
                    "workspace": arguments["workspace"],
                    "sourceHead": "abc123",
                    "isolation": "ephemeral_git_snapshot_no_remote",
                    "final": "proposal ready",
                    "reasoning": "",
                    "proposalPatch": "diff --git a/a b/a",
                    "proposalPatchTruncated": False,
                    "changedFiles": ["a"],
                    "harnessHeadChanged": False,
                    "rc": 0,
                    "elapsedMs": 1,
                },
            )
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

    def test_live_runtime_routes_code_task_to_deepseek_without_kev(self) -> None:
        bridge = FakeBridge()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveRouterRuntime(
                self.router,
                bridge,
                TraceStore(tmp),
            )
            trace = runtime.run(
                {
                    "goal": "Inspect the router and propose a safe patch.",
                    "domains": ["software"],
                    "intent": "development",
                    "required_capabilities": ["code_analysis", "patch_proposal"],
                    "constraints": {
                        "workspace": "aiman-agent-router",
                        "timeout": 60,
                    },
                    "evidence_required": False,
                    "freshness_required": False,
                    "side_effects": False,
                }
            )
            self.assertEqual(
                trace["decision"]["selected"],
                ["aiman.deepseek-harness-headless"],
            )
            self.assertTrue(trace["kev"]["skipped"])
            self.assertEqual(trace["result"]["status"], "verified")
            self.assertTrue(trace["result"]["verified"])
            self.assertEqual(
                [name for name, _ in bridge.calls],
                ["agentdock.health", "deepseek.harness.propose"],
            )

    def test_live_runtime_executes_and_verifies_context_scout(self) -> None:
        bridge = FakeBridge()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveRouterRuntime(self.router, bridge, TraceStore(tmp))
            trace = runtime.run(
                {
                    "goal": "Locate the routing implementation.",
                    "domains": ["software"],
                    "intent": "development",
                    "required_capabilities": ["repository_context"],
                    "constraints": {
                        "workspace": "aiman-agent-router",
                        "scout_query": "locate the router",
                        "scout_max_turns": 4,
                        "scout_timeout": 60,
                    },
                    "evidence_required": False,
                    "freshness_required": False,
                    "side_effects": False,
                }
            )
            self.assertEqual(trace["decision"]["selected"], ["aiman.context-scout"])
            self.assertEqual(trace["result"]["status"], "verified")
            self.assertTrue(trace["result"]["verified"])
            self.assertEqual(
                trace["result"]["verification"]["context_scout"]["citation_count"],
                1,
            )
            self.assertEqual(
                [name for name, _ in bridge.calls],
                ["agentdock.health", "context.scout"],
            )

    def test_context_scout_can_precede_deepseek_and_pass_citations_forward(self) -> None:
        bridge = FakeBridge()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveRouterRuntime(self.router, bridge, TraceStore(tmp))
            trace = runtime.run(
                {
                    "goal": "Locate the code and propose a safe patch.",
                    "domains": ["software"],
                    "intent": "development",
                    "required_capabilities": ["repository_context", "patch_proposal"],
                    "constraints": {
                        "workspace": "aiman-agent-router",
                        "scout_query": "locate the router",
                        "timeout": 60,
                    },
                    "evidence_required": False,
                    "freshness_required": False,
                    "side_effects": False,
                }
            )
            self.assertEqual(
                trace["decision"]["selected"],
                ["aiman.context-scout", "aiman.deepseek-harness-headless"],
            )
            self.assertEqual(trace["result"]["status"], "verified")
            deepseek_calls = [
                arguments
                for operation, arguments in bridge.calls
                if operation == "deepseek.harness.propose"
            ]
            self.assertEqual(len(deepseek_calls), 1)
            self.assertEqual(
                deepseek_calls[0]["context_citations"],
                ["src/aiman_agent_router/router.py:1-20"],
            )
            self.assertEqual(
                [name for name, _ in bridge.calls],
                ["agentdock.health", "context.scout", "deepseek.harness.propose"],
            )

    def test_context_scout_unavailable_returns_non_blocking_fallback(self) -> None:
        bridge = FakeBridge(scout_fail=True)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveRouterRuntime(self.router, bridge, TraceStore(tmp))
            trace = runtime.run(
                {
                    "goal": "Locate the routing implementation.",
                    "domains": ["software"],
                    "intent": "development",
                    "required_capabilities": ["repository_context"],
                    "constraints": {"workspace": "aiman-agent-router"},
                    "evidence_required": False,
                    "freshness_required": False,
                    "side_effects": False,
                }
            )
            self.assertEqual(trace["result"]["status"], "fallback")
            self.assertFalse(trace["result"]["verified"])
            self.assertEqual(
                trace["result"]["verification"]["fallback"],
                "normal_repository_inspection",
            )

    def test_context_scout_bridge_error_is_bounded_fallback(self) -> None:
        bridge = FakeBridge(scout_bridge_error=True)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveRouterRuntime(self.router, bridge, TraceStore(tmp))
            trace = runtime.run(
                {
                    "goal": "Locate the routing implementation.",
                    "domains": ["software"],
                    "intent": "development",
                    "required_capabilities": ["repository_context"],
                    "constraints": {"workspace": "aiman-agent-router"},
                    "evidence_required": False,
                    "freshness_required": False,
                    "side_effects": False,
                }
            )
            self.assertEqual(trace["result"]["status"], "fallback")
            self.assertEqual(
                trace["result"]["verification"]["context_scout"]["code"],
                "SCOUT_BRIDGE_UNAVAILABLE",
            )
            self.assertEqual(
                trace["result"]["verification"]["fallback"],
                "normal_repository_inspection",
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
