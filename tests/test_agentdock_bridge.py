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
