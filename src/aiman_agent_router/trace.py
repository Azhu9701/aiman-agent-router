from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


def canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TraceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, trace: dict[str, Any]) -> Path:
        task_id = str((trace.get("task") or {}).get("task_id") or "unknown")
        now = datetime.now(timezone.utc)
        trace_id = str(trace.get("trace_id") or "")
        if not trace_id:
            trace_id = (
                "trace_"
                + now.strftime("%Y%m%dT%H%M%SZ")
                + "_"
                + task_id.replace("/", "-")[:80]
            )
            trace["trace_id"] = trace_id
        trace["trace_hash"] = canonical_hash(
            {key: value for key, value in trace.items() if key != "trace_hash"}
        )

        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{trace_id}.json"
        payload = json.dumps(trace, ensure_ascii=False, indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(prefix=f".{trace_id}.", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        return path

    def load(self, path: str | Path) -> dict[str, Any]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("trace must be a JSON object")
        expected = data.get("trace_hash")
        if expected:
            actual = canonical_hash(
                {key: value for key, value in data.items() if key != "trace_hash"}
            )
            if actual != expected:
                raise ValueError("trace hash mismatch")
        return data
