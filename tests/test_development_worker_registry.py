from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiman_agent_router.development_leases import LeaseDenied, load_trusted_workers


class WorkerAdmissionTests(unittest.TestCase):
    def test_example_only_admits_verified_development_worker(self) -> None:
        registered = load_trusted_workers(ROOT / "examples" / "development-workers.json")
        self.assertEqual(
            registered["mac-worknode"],
            ("aiman-agent-router", "aiman-agent-node", "emibot"),
        )
        self.assertNotIn("new-server-example", registered)
        self.assertNotIn("production", registered)

    def test_duplicate_worker_id_fails_closed(self) -> None:
        data = {
            "schema_version": 1,
            "workers": [
                {"id": "mac-worknode", "role": "development", "enabled": True,
                 "workspaces": ["emibot"]},
                {"id": "mac-worknode", "role": "development", "enabled": False,
                 "workspaces": []},
            ]
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workers.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(LeaseDenied):
                load_trusted_workers(path)

    def test_enabled_unassigned_worker_fails_closed(self) -> None:
        data = {"schema_version": 1, "workers": [
            {"id": "unassigned", "role": "development",
             "enabled": True, "workspaces": []},
        ]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "workers.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(LeaseDenied):
                load_trusted_workers(path)


if __name__ == "__main__":
    unittest.main()
