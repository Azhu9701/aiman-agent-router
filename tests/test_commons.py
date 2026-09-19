from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiman_agent_router.commons import CommonsStore
from aiman_agent_router.server import _mcp_call


class CommonsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = CommonsStore()
        self.store.register_agent({
            "agent_id": "agent:researcher",
            "display_name": "Researcher",
            "operator": {"type": "organization", "id": "aiman"},
            "capabilities": ["research"],
            "worlds": ["robotics"],
            "provenance": {"source": "test"},
        })

    def test_post_preserves_agent_author_and_world_references(self) -> None:
        post = self.store.create_post({
            "kind": "research",
            "title": "Viabot evidence gap",
            "body": "Need a second source.",
            "author": {"type": "agent", "id": "agent:researcher"},
            "referenced_entities": [{"uri": "https://aiman.world/id/entity:robot:viabot", "world": "robotics"}],
            "evidence": [{"evidence_id": "evidence:test-1", "url": "https://example.com/source"}],
            "agent_mentions": ["agent:reviewer"],
            "requested_capabilities": ["evidence_gathering"],
            "provenance": {"source": "agent:researcher", "method": "mcp"},
        })
        self.assertEqual(post.author["type"], "agent")
        self.assertEqual(self.store.get_thread(post.thread_id)[0]["referenced_entities"][0]["world"], "robotics")

    def test_mcp_minimum_tools(self) -> None:
        response = _mcp_call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.store)
        self.assertEqual([tool["name"] for tool in response["result"]["tools"]], [
            "forum.search", "forum.read_thread", "forum.create_thread", "forum.reply"
        ])

    def test_unknown_agent_cannot_post_as_agent(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown agent author"):
            self.store.create_post({
                "kind": "discussion", "title": "x", "body": "y",
                "author": {"type": "agent", "id": "agent:missing"},
                "provenance": {"source": "test"},
            })


if __name__ == "__main__":
    unittest.main()
