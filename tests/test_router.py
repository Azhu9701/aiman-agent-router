from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiman_agent_router.models import TaskEnvelope
from aiman_agent_router.registry import CapabilityRegistry
from aiman_agent_router.router import AgentRouter


class RouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = CapabilityRegistry.from_directory(ROOT / "registry")
        cls.router = AgentRouter(cls.registry)

    def test_composes_robotics_world_model_and_web_evidence(self) -> None:
        result = self.router.route_and_plan(
            {
                "goal": "Find recent robotics funding events with independent evidence.",
                "domains": ["robotics"],
                "intent": "industry_research",
                "required_capabilities": ["event_query", "evidence_gathering"],
                "evidence_required": True,
                "freshness_required": True,
                "side_effects": False,
            }
        )
        self.assertEqual(result["decision"]["status"], "ready")
        self.assertEqual(
            result["decision"]["selected"],
            ["aiman.robotics", "aiman.public-web-research"],
        )
        targets = [step["target"] for step in result["plan"]["steps"]]
        self.assertIn("aiman.agentdock", targets)
        self.assertEqual(targets[-1], "aiman.router.verifier")

    def test_unknown_capability_fails_closed(self) -> None:
        result = self.router.route_and_plan(
            {
                "goal": "Perform an unsupported action.",
                "domains": ["robotics"],
                "intent": "action",
                "required_capabilities": ["teleport_factory"],
                "side_effects": False,
            }
        )
        self.assertEqual(result["decision"]["status"], "needs_review")
        self.assertEqual(result["decision"]["missing_capabilities"], ["teleport_factory"])
        self.assertTrue(result["decision"]["human_review_required"])

    def test_side_effect_requires_human_gate(self) -> None:
        result = self.router.route_and_plan(
            {
                "goal": "Submit a robotics contribution.",
                "domains": ["robotics"],
                "intent": "contribution",
                "required_capabilities": ["contribution_submit"],
                "side_effects": True,
            }
        )
        self.assertEqual(result["decision"]["status"], "ready")
        self.assertTrue(result["decision"]["human_review_required"])
        self.assertEqual(result["plan"]["steps"][-1]["kind"], "human_gate")

    def test_empty_capability_set_never_auto_executes(self) -> None:
        result = self.router.route_and_plan(
            {
                "goal": "Research robotics.",
                "domains": ["robotics"],
                "intent": "research",
                "required_capabilities": [],
            }
        )
        self.assertEqual(result["decision"]["status"], "needs_review")
        self.assertTrue(result["decision"]["human_review_required"])

    def test_task_id_is_deterministic(self) -> None:
        payload = {
            "goal": "Research robotics.",
            "domains": ["robotics"],
            "intent": "research",
            "required_capabilities": ["event_query"],
        }
        first = TaskEnvelope.from_dict(payload)
        second = TaskEnvelope.from_dict(payload)
        self.assertEqual(first.task_id, second.task_id)

    def test_all_schemas_are_valid_json(self) -> None:
        files = sorted((ROOT / "schemas").glob("*.json"))
        self.assertGreaterEqual(len(files), 5)
        for path in files:
            with self.subTest(path=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data.get("$schema"), "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
