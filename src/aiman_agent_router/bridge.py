from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Sequence


class BridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class BridgeResponse:
    operation: str
    result: dict[str, Any]


class CommandBridge:
    """JSON stdin/stdout bridge to the local execution fabric.

    The command receives one request object:
      {"operation": "...", "arguments": {...}}

    It must return one response object:
      {"ok": true, "operation": "...", "result": {...}}

    Environment-specific SSH, MCP and credential details stay outside Router.
    """

    def __init__(self, command: Sequence[str], *, timeout: int = 180) -> None:
        if not command:
            raise ValueError("bridge command must not be empty")
        self.command = tuple(command)
        self.timeout = timeout

    def call(self, operation: str, arguments: dict[str, Any]) -> BridgeResponse:
        if not operation:
            raise ValueError("operation is required")
        request = {
            "operation": operation,
            "arguments": arguments,
        }
        proc = subprocess.run(
            list(self.command),
            input=json.dumps(request, ensure_ascii=False),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise BridgeError(
                f"bridge exited with {proc.returncode}: {detail[:2000]}"
            )
        try:
            response = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise BridgeError("bridge returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise BridgeError("bridge response must be an object")
        if response.get("ok") is not True:
            raise BridgeError(str(response.get("error") or "bridge call failed"))
        if response.get("operation") != operation:
            raise BridgeError("bridge operation mismatch")
        result = response.get("result")
        if not isinstance(result, dict):
            raise BridgeError("bridge result must be an object")
        return BridgeResponse(operation=operation, result=result)
