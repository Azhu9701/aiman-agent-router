"""Atomic development-task leases for a single trusted AIMAN coordinator.

This is an admission/conflict primitive, not a distributed job runner or an
authorization grant. Only the central scheduler may call it, using a trusted
worker-to-workspace allowlist (never one supplied by a worker).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import time


class LeaseConflict(RuntimeError):
    """A task, branch, or claimed area is already owned."""


class LeaseDenied(ValueError):
    """An invalid or unregistered worker/task request was rejected."""


_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}\Z")
_REPO = re.compile(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+\Z")
_BRANCH = re.compile(r"agent/[a-z0-9][a-z0-9-]{2,80}\Z")
_SHA = re.compile(r"[a-fA-F0-9]{40}\Z")
_AREA = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._/-]{0,180}\Z")


def _check(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise LeaseDenied(f"invalid {label}")
    if ".." in value or "//" in value:
        raise LeaseDenied(f"invalid {label}")
    return value


class DevelopmentLeaseStore:
    """SQLite state held on ONE coordinator host, never on worker-local disks.

    BEGIN IMMEDIATE serializes competing claims. Claim epochs are monotonic
    SQLite AUTOINCREMENT ids; expired workers cannot renew a newer claim.
    External auth, Nexus task validation, and Git permissions are separate.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        allowed_workers: Mapping[str, Iterable[str]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.allowed_workers = {
            _check(node, _NAME, "worker"): frozenset(
                _check(workspace, _NAME, "workspace") for workspace in workspaces
            )
            for node, workspaces in allowed_workers.items()
        }
        self.clock = clock
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS development_leases (
                    epoch INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    worker_id TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    repository TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    base_sha TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS development_locks (
                    lock_key TEXT PRIMARY KEY,
                    epoch INTEGER NOT NULL REFERENCES development_leases(epoch)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_dev_lease_expiry
                    ON development_leases(expires_at);
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=8)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=8000")
        return connection

    def _validate_owner(self, worker_id: str, workspace: str) -> None:
        _check(worker_id, _NAME, "worker")
        _check(workspace, _NAME, "workspace")
        if workspace not in self.allowed_workers.get(worker_id, ()):
            raise LeaseDenied("worker not authorized for workspace")

    @staticmethod
    def _ttl(seconds: int) -> int:
        if type(seconds) is not int or not 30 <= seconds <= 3600:
            raise LeaseDenied("ttl_seconds must be an integer in [30, 3600]")
        return seconds

    def claim(
        self, *, task_id: str, worker_id: str, workspace: str,
        repository: str, branch: str, base_sha: str,
        resources: Iterable[str], ttl_seconds: int = 900,
    ) -> dict:
        self._validate_owner(worker_id, workspace)
        task_id = _check(task_id, _NAME, "task_id")
        repository = _check(repository, _REPO, "repository")
        branch = _check(branch, _BRANCH, "branch")
        base_sha = _check(base_sha, _SHA, "base_sha").lower()
        ttl_seconds = self._ttl(ttl_seconds)
        if isinstance(resources, (str, bytes)):
            raise LeaseDenied("resources must be a collection of scope names")
        areas = sorted({_check(area, _AREA, "resource") for area in resources})
        if not areas:
            raise LeaseDenied("at least one resource is required")
        # All path/module locks are scoped to one canonical Git repository.
        keys = [f"repo:{repository}:area:{area}" for area in areas]
        keys.append(f"repo:{repository}:branch:{branch}")
        now = self.clock()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM development_leases WHERE expires_at <= ?", (now,))
            if conn.execute(
                "SELECT 1 FROM development_leases WHERE task_id = ?", (task_id,)
            ).fetchone():
                raise LeaseConflict("task is already actively claimed")
            for key in keys:
                row = conn.execute(
                    """SELECT l.task_id FROM development_locks k
                       JOIN development_leases l ON l.epoch = k.epoch
                       WHERE k.lock_key = ?""", (key,)
                ).fetchone()
                if row:
                    raise LeaseConflict(f"resource busy: {key}; task={row['task_id']}")
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
            expires = now + ttl_seconds
            cursor = conn.execute(
                """INSERT INTO development_leases
                   (task_id,worker_id,workspace,repository,branch,base_sha,token_hash,expires_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (task_id, worker_id, workspace, repository, branch, base_sha, token_hash, expires),
            )
            epoch = cursor.lastrowid
            conn.executemany(
                "INSERT INTO development_locks(lock_key,epoch) VALUES (?,?)",
                [(key, epoch) for key in keys],
            )
            conn.commit()
            # token MUST only be sent to its assignee over a secure channel;
            # never include it in dashboards, traces, or logs.
            return {
                "task_id": task_id, "worker_id": worker_id, "workspace": workspace,
                "repository": repository, "branch": branch, "base_sha": base_sha,
                "resources": areas, "epoch": epoch, "token": token, "expires_at": expires,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _check_token(self, row: sqlite3.Row | None, token: str, epoch: int, now: float) -> None:
        if not row or row["expires_at"] <= now or row["epoch"] != epoch:
            raise LeaseDenied("lease absent, expired, or superseded")
        if not isinstance(token, str) or not hmac.compare_digest(
            row["token_hash"], hashlib.sha256(token.encode("utf-8")).hexdigest()
        ):
            raise LeaseDenied("invalid lease token")

    def renew(self, *, task_id: str, token: str, epoch: int, ttl_seconds: int = 900) -> float:
        ttl_seconds = self._ttl(ttl_seconds)
        now = self.clock()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM development_leases WHERE task_id=?", (task_id,)
            ).fetchone()
            self._check_token(row, token, epoch, now)
            expires = now + ttl_seconds
            conn.execute(
                "UPDATE development_leases SET expires_at=? WHERE epoch=?", (expires, epoch)
            )
            conn.commit()
            return expires
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release(self, *, task_id: str, token: str, epoch: int) -> None:
        now = self.clock()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM development_leases WHERE task_id=?", (task_id,)
            ).fetchone()
            self._check_token(row, token, epoch, now)
            conn.execute("DELETE FROM development_leases WHERE epoch=?", (epoch,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def active(self) -> list[dict]:
        """Read-only status for a dashboard, intentionally without tokens."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT task_id,worker_id,workspace,repository,branch,base_sha,
                          epoch,expires_at FROM development_leases
                   WHERE expires_at > ? ORDER BY task_id""", (self.clock(),)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

def load_trusted_workers(config_path: str | Path) -> dict[str, tuple[str, ...]]:
    """Read a CENTRAL, administrator-managed registry (not a worker payload).

    Only explicitly enabled development workers with nonempty registered
    workspaces can acquire leases. Production/recovery entries are excluded.
    """
    import json

    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise LeaseDenied("unsupported worker registry schema")
    entries = payload.get("workers")
    if not isinstance(entries, list):
        raise LeaseDenied("worker registry requires workers array")
    allowed: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise LeaseDenied("invalid worker registry record")
        worker_id = _check(entry.get("id"), _NAME, "worker")
        if worker_id in seen:
            raise LeaseDenied("duplicate worker id")
        seen.add(worker_id)
        if type(entry.get("enabled")) is not bool:
            raise LeaseDenied("worker enabled must be explicit boolean")
        role = entry.get("role")
        if role not in {"development", "recovery-admin", "production-operations"}:
            raise LeaseDenied("invalid worker role")
        workspaces = entry.get("workspaces", [])
        if not isinstance(workspaces, list) or any(
            not isinstance(item, str) for item in workspaces
        ):
            raise LeaseDenied("invalid worker workspace list")
        names = tuple(_check(item, _NAME, "workspace") for item in workspaces)
        if entry["enabled"] and role == "development":
            if not names:
                raise LeaseDenied("enabled development worker has no workspace")
            allowed[worker_id] = names
    return allowed
