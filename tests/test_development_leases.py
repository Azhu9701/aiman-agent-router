from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiman_agent_router.development_leases import (
    DevelopmentLeaseStore, LeaseConflict, LeaseDenied,
)


class DevelopmentLeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "central.sqlite"
        self.clock = [1000.0]
        self.allowed = {"mac-worknode": ["aiman-agent-router"], "grokbot-dev": ["aiman-agent-router"]}
        self.store = DevelopmentLeaseStore(
            self.path, allowed_workers=self.allowed, clock=lambda: self.clock[0]
        )

    def claim(self, task_id="tsk_1", worker_id="mac-worknode",
              branch="agent/tsk-1", resources=("router-core",), **kwargs):
        return self.store.claim(
            task_id=task_id, worker_id=worker_id,
            workspace="aiman-agent-router",
            repository="Azhu9701/aiman-agent-router",
            branch=branch, base_sha="a" * 40,
            resources=resources, **kwargs,
        )

    def test_claim_and_release_unblock_next_agent(self) -> None:
        first = self.claim()
        self.assertEqual(len(self.store.active()), 1)
        with self.assertRaises(LeaseConflict):
            self.claim(task_id="tsk_2", worker_id="grokbot-dev", branch="agent/tsk-2")
        self.store.release(task_id="tsk_1", token=first["token"], epoch=first["epoch"])
        second = self.claim(task_id="tsk_2", worker_id="grokbot-dev", branch="agent/tsk-2")
        self.assertGreater(second["epoch"], first["epoch"])
        self.assertEqual([r["task_id"] for r in self.store.active()], ["tsk_2"])

    def test_same_task_cannot_be_claimed_twice(self) -> None:
        self.claim()
        with self.assertRaises(LeaseConflict):
            self.claim(branch="agent/another", resources=("other-area",))

    def test_same_branch_is_locked_even_when_areas_differ(self) -> None:
        self.claim()
        with self.assertRaises(LeaseConflict):
            self.claim(task_id="tsk_2", branch="agent/tsk-1", resources=("other-area",))

    def test_disjoint_areas_and_branches_can_run_in_parallel(self) -> None:
        self.claim()
        second = self.claim(task_id="tsk_2", worker_id="grokbot-dev",
                            branch="agent/tsk-2", resources=("tests",))
        self.assertEqual(second["task_id"], "tsk_2")
        self.assertEqual(len(self.store.active()), 2)

    def test_expired_lease_recovery_has_fencing_epoch(self) -> None:
        first = self.claim(ttl_seconds=30)
        self.clock[0] += 31
        self.assertEqual(self.store.active(), [])
        next_one = self.claim(task_id="tsk_2", worker_id="grokbot-dev",
                              branch="agent/tsk-2", ttl_seconds=30)
        self.assertGreater(next_one["epoch"], first["epoch"])
        with self.assertRaises(LeaseDenied):
            self.store.renew(task_id="tsk_1", epoch=first["epoch"],
                             token=first["token"], ttl_seconds=30)
        with self.assertRaises(LeaseDenied):
            self.store.release(task_id="tsk_1", epoch=first["epoch"], token=first["token"])

    def test_renew_and_wrong_token(self) -> None:
        first = self.claim(ttl_seconds=30)
        self.clock[0] += 15
        with self.assertRaises(LeaseDenied):
            self.store.renew(task_id="tsk_1", epoch=first["epoch"],
                             token="wrong", ttl_seconds=30)
        expiry = self.store.renew(task_id="tsk_1", epoch=first["epoch"],
                                  token=first["token"], ttl_seconds=30)
        self.assertEqual(expiry, 1045)
        self.clock[0] += 25
        self.assertEqual(len(self.store.active()), 1)

    def test_fail_closed_registration_and_input(self) -> None:
        with self.assertRaises(LeaseDenied):
            self.claim(worker_id="production")
        with self.assertRaises(LeaseDenied):
            self.claim(branch="main")
        with self.assertRaises(LeaseDenied):
            self.claim(resources=())
        with self.assertRaises(LeaseDenied):
            self.claim(resources=("../outside",))
        with self.assertRaises(LeaseDenied):
            self.claim(ttl_seconds=3601)

    def test_lease_token_is_not_exposed_in_status(self) -> None:
        first = self.claim()
        for row in self.store.active():
            self.assertNotIn("token", row)
            self.assertNotIn("token_hash", row)
            self.assertNotIn(first["token"], repr(row))

    def test_concurrent_contenders_claim_one_resource_only_once(self) -> None:
        barrier = threading.Barrier(2)
        def attempt(task_id, worker, branch):
            store = DevelopmentLeaseStore(
                self.path, allowed_workers=self.allowed, clock=lambda: self.clock[0]
            )
            barrier.wait(timeout=5)
            try:
                store.claim(task_id=task_id, worker_id=worker,
                            workspace="aiman-agent-router",
                            repository="Azhu9701/aiman-agent-router",
                            branch=branch, base_sha="a" * 40,
                            resources=["router-core"])
                return "won"
            except LeaseConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(attempt, "tsk_1", "mac-worknode", "agent/tsk-1")
            f2 = pool.submit(attempt, "tsk_2", "grokbot-dev", "agent/tsk-2")
            self.assertEqual(sorted([f1.result(), f2.result()]), ["conflict", "won"])
        self.assertEqual(len(self.store.active()), 1)


if __name__ == "__main__":
    unittest.main()
