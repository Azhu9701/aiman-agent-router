from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiman_agent_router.decision import (
    build_laya_request,
    normalize_laya_result,
)


class DecisionLayerTests(unittest.TestCase):
    def test_build_request_combines_router_and_kev_profiles(self) -> None:
        request = build_laya_request(
            {
                "goal": "Check a robotics funding announcement",
                "domains": ["robotics"],
                "intent": "industry_research",
                "required_capabilities": [],
                "constraints": {},
                "evidence_required": True,
                "freshness_required": True,
                "side_effects": False,
                "metadata": {
                    "kev_input": {
                        "title": "Viabot raises a Series A",
                        "content": "Viabot announced a funding round.",
                        "source_types": ["official", "industry_media"],
                        "source_count": 2,
                    }
                },
            },
            "task_test",
            include_kev=True,
        )
        self.assertIn("worker", request["questions"])
        self.assertIn("is_event", request["questions"])
        self.assertEqual(
            request["state"]["robotics_content"]["source_count"],
            2,
        )

    def test_laya_normalization_emits_legacy_route_hints(self) -> None:
        normalized = normalize_laya_result(
            {
                "answers": {
                    "worker": {
                        "type": "choice",
                        "choice": "vps",
                        "confidence": 0.81,
                        "probabilities": {"vps": 0.81, "none": 0.19},
                    },
                    "is_event": {
                        "type": "noul",
                        "noul": 0.94,
                        "confidence": 0.88,
                    },
                    "needs_second_source": {
                        "type": "noul",
                        "noul": 0.77,
                        "confidence": 0.54,
                    },
                },
                "routing": {"model": "multilingual"},
                "usage": {"input_tokens": 42, "output_tokens": 0},
            },
            include_kev=True,
        )
        self.assertEqual(normalized["provider"], "laya")
        self.assertEqual(
            normalized["route_hints"]["required_capabilities"],
            ["event_query", "evidence_gathering"],
        )
        self.assertEqual(
            normalized["router_shadow"]["worker"]["answer"],
            "vps",
        )

    def test_router_shadow_does_not_emit_kev_hints_without_profile(self) -> None:
        normalized = normalize_laya_result(
            {
                "answers": {
                    "worker": {
                        "type": "choice",
                        "choice": "mac-worknode",
                        "confidence": 0.9,
                    }
                },
                "routing": {"model": "english"},
            },
            include_kev=False,
        )
        self.assertEqual(
            normalized["route_hints"]["required_capabilities"],
            [],
        )
        self.assertEqual(normalized["kev_compat"], {})


if __name__ == "__main__":
    unittest.main()
