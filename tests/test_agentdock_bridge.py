from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiman_agent_router import agentdock_bridge


class AgentDockBridgeTests(unittest.TestCase):
    def test_health_operation_is_allowlisted(self) -> None:
        with patch.object(
            agentdock_bridge,
            "_health",
            return_value={"ok": True, "executor": "agentdock-test"},
        ):
            result = agentdock_bridge.dispatch(
                {"operation": "agentdock.health", "arguments": {}}
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["operation"], "agentdock.health")
        self.assertEqual(result["result"]["executor"], "agentdock-test")

    def test_deepseek_harness_operation_is_allowlisted(self) -> None:
        with patch.object(
            agentdock_bridge,
            "_deepseek_harness_propose",
            return_value={"ok": True, "worker": "deepseek-harness.headless"},
        ) as mocked:
            result = agentdock_bridge.dispatch(
                {
                    "operation": "deepseek.harness.propose",
                    "arguments": {
                        "workspace": "aiman-agent-router",
                        "task": "inspect the router",
                        "timeout": 60,
                    },
                }
            )
        mocked.assert_called_once_with(
            {
                "workspace": "aiman-agent-router",
                "task": "inspect the router",
                "timeout": 60,
            }
        )
        self.assertTrue(result["result"]["ok"])


    def test_lineage_operation_is_allowlisted(self) -> None:
        with patch.object(
            agentdock_bridge,
            "_kev_lineage_analyze",
            return_value={"safe_relation": "same_platform", "production_effect": "none"},
        ) as mocked:
            result = agentdock_bridge.dispatch(
                {
                    "operation": "kev.lineage.analyze",
                    "arguments": {
                        "left": {"id": "a", "name": "A"},
                        "right": {"id": "b", "name": "B"},
                    },
                }
            )
        mocked.assert_called_once()
        self.assertEqual(result["result"]["safe_relation"], "same_platform")

    def test_robot_lineage_admission_shortlists_and_fails_closed(self) -> None:
        search_payloads = {
            "40DOF": {
                "robots": [
                    {
                        "id": "candidate-a2",
                        "name": "A2 Ultra",
                        "company": "AGIBOT",
                        "formCategory": "人形",
                        "heatScore": 80,
                    }
                ]
            },
            "169": {
                "robots": [
                    {
                        "id": "candidate-a2",
                        "name": "A2 Ultra",
                        "company": "AGIBOT",
                        "formCategory": "人形",
                        "heatScore": 80,
                    },
                    {
                        "id": "candidate-other",
                        "name": "Other Humanoid",
                        "company": "Other",
                        "formCategory": "人形",
                        "heatScore": 60,
                    },
                ]
            },
        }

        def fake_api(path: str, *, timeout: int = 60):
            if path.startswith("/api/robots?search="):
                from urllib.parse import parse_qs, urlsplit

                query = parse_qs(urlsplit(path).query)["search"][0]
                return search_payloads.get(query, {"robots": []})
            if path == "/api/robots/candidate-a2":
                return {
                    "robot": {
                        "id": "candidate-a2",
                        "name": "A2 Ultra",
                        "company": "AGIBOT",
                        "formCategory": "人形",
                    },
                    "provenance": {
                        "specEvidence": [
                            {"key": "height", "value": 169},
                            {"key": "weight", "value": 69},
                            {"key": "dof", "value": 40},
                        ]
                    },
                }
            if path == "/api/robots/candidate-other":
                return {
                    "robot": {
                        "id": "candidate-other",
                        "name": "Other Humanoid",
                        "company": "Other",
                        "formCategory": "人形",
                    },
                    "provenance": {
                        "specEvidence": [
                            {"key": "height", "value": 175},
                            {"key": "weight", "value": 80},
                            {"key": "dof", "value": 30},
                        ]
                    },
                }
            raise AssertionError(path)

        with patch.object(agentdock_bridge, "_production_api", side_effect=fake_api), patch.object(
            agentdock_bridge,
            "_kev_lineage_analyze",
            return_value={
                "safe_relation": "probable_oem_derivative",
                "needs_human_review": True,
                "fingerprint": {"score": 1.0},
                "provider_agreement": False,
                "canonical_write_allowed": False,
                "production_effect": "none",
            },
        ) as lineage:
            result = agentdock_bridge._robot_lineage_admission(
                {
                    "robot": {
                        "id": "new-ff",
                        "name": "FF Futurist",
                        "company": "Faraday Future",
                        "formCategory": "人形",
                        "specs": {
                            "height": 169,
                            "weight": 69,
                            "dof": 40,
                        },
                        "search_anchors": ["40DOF", "169"],
                    },
                    "shortlist_limit": 1,
                }
            )

        self.assertFalse(result["canonical_write_allowed"])
        self.assertEqual(result["production_effect"], "none")
        self.assertEqual(result["candidate_pool_count"], 2)
        self.assertEqual(result["results"][0]["candidate"]["id"], "candidate-a2")
        self.assertEqual(
            result["results"][0]["safe_relation"],
            "probable_oem_derivative",
        )
        lineage.assert_called_once()

    def test_unknown_operation_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            agentdock_bridge.dispatch(
                {"operation": "shell.exec", "arguments": {"cmd": "anything"}}
            )

    def test_iwm_operation_passes_only_structured_arguments(self) -> None:
        with patch.object(
            agentdock_bridge,
            "_iwm_search",
            return_value={"count": 0, "events": []},
        ) as mocked:
            result = agentdock_bridge.dispatch(
                {
                    "operation": "iwm.timeline.search",
                    "arguments": {"query": "Viabot", "limit": 10},
                }
            )
        mocked.assert_called_once_with({"query": "Viabot", "limit": 10})
        self.assertEqual(result["result"]["events"], [])


if __name__ == "__main__":
    unittest.main()
