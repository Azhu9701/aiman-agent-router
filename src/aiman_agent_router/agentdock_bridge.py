from __future__ import annotations

import json
import os
import select
import shlex
import subprocess
import sys
import time
from typing import Any

DECISION_MCP = os.environ.get(
    "AIMAN_DECISION_MCP",
    "/srv/agentdock/.local/bin/aiman-decision-mcp",
)
SSH = os.environ.get("AIMAN_SSH_BIN", "/usr/bin/ssh")
SSH_CONFIG = os.environ.get(
    "AIMAN_SSH_CONFIG",
    "/srv/agentdock/.ssh/config",
)
MAC_WORKNODE = os.environ.get("AIMAN_MAC_WORKNODE", "mac-worknode")
PRODUCTION = os.environ.get("AIMAN_PRODUCTION_HOST", "production")
EMIBOT_OPS = os.environ.get(
    "AIMAN_EMIBOT_OPS",
    "/usr/local/sbin/emibot-ops",
)


def _parse_object(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _run_json(
    argv: list[str],
    *,
    input_text: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    proc = subprocess.run(
        argv,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "command failed").strip()
        raise RuntimeError(detail[:2000])
    return _parse_object(proc.stdout)


def _kev_analyze(arguments: dict[str, Any]) -> dict[str, Any]:
    process = subprocess.Popen(
        [DECISION_MCP],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def send(message: dict[str, Any]) -> None:
        if process.stdin is None:
            raise RuntimeError("MCP stdin unavailable")
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def receive(request_id: int, timeout: int) -> dict[str, Any]:
        if process.stdout is None:
            raise RuntimeError("MCP stdout unavailable")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            wait = max(0.1, deadline - time.monotonic())
            readable, _, _ = select.select([process.stdout], [], [], wait)
            if not readable:
                continue
            line = process.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            if message.get("id") == request_id:
                return message
        raise RuntimeError(f"MCP response timeout for id={request_id}")

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "aiman-agent-router-bridge",
                        "version": "0.2.0",
                    },
                },
            }
        )
        initialized = receive(1, 30)
        if "error" in initialized:
            raise RuntimeError(f"MCP initialize failed: {initialized['error']}")

        send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "decision_analyze",
                    "arguments": arguments,
                },
            }
        )
        response = receive(2, 180)
        if "error" in response:
            raise RuntimeError(f"MCP tool failed: {response['error']}")

        result = response.get("result") or {}
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured

        for item in result.get("content") or []:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            try:
                parsed = json.loads(item.get("text") or "")
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise RuntimeError("MCP tool result has no structured content")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


def _iwm_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    limit = max(1, min(int(arguments.get("limit", 10)), 50))
    remote = (
        "sudo -n "
        + shlex.quote(EMIBOT_OPS)
        + " timeline search --query "
        + shlex.quote(query)
        + " --limit "
        + str(limit)
    )
    return _run_json(
        [SSH, "-F", SSH_CONFIG, PRODUCTION, remote],
        timeout=60,
    )


def _health() -> dict[str, Any]:
    mac = _run_json(
        [SSH, "-F", SSH_CONFIG, MAC_WORKNODE],
        input_text=json.dumps({"action": "ping"}),
        timeout=20,
    )
    production = subprocess.run(
        [
            SSH,
            "-F",
            SSH_CONFIG,
            PRODUCTION,
            "sudo -n " + EMIBOT_OPS + " health",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    codes: dict[str, int] = {}
    for line in production.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            codes[parts[0]] = int(parts[1])
    production_ok = (
        production.returncode == 0
        and bool(codes)
        and all(value == 200 for value in codes.values())
    )
    return {
        "ok": bool(mac.get("ok")) and production_ok,
        "executor": "agentdock-vps",
        "mac": {
            "ok": bool(mac.get("ok")),
            "node": (mac.get("result") or {}).get("node"),
        },
        "production": {
            "ok": production_ok,
            "health": codes,
        },
    }


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    operation = str(request.get("operation") or "")
    arguments = request.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")

    if operation == "agentdock.health":
        result = _health()
    elif operation == "kev.analyze":
        result = _kev_analyze(arguments)
    elif operation == "iwm.timeline.search":
        result = _iwm_search(arguments)
    else:
        raise ValueError(f"operation is not allowlisted: {operation}")

    return {
        "ok": True,
        "operation": operation,
        "result": result,
    }


def main() -> int:
    try:
        request = _parse_object(sys.stdin.read())
        print(json.dumps(dispatch(request), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
