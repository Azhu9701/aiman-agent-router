from __future__ import annotations

import json
import os
import select
import shlex
import subprocess
import sys
import time
import urllib.parse
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


def _decision_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name not in {"decision_analyze", "lineage_analyze", "lineage_metrics"}:
        raise ValueError(f"decision tool is not allowlisted: {tool_name}")

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
                        "version": "0.3.0",
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
                    "name": tool_name,
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


def _kev_analyze(arguments: dict[str, Any]) -> dict[str, Any]:
    return _decision_tool("decision_analyze", arguments)


def _kev_lineage_analyze(arguments: dict[str, Any]) -> dict[str, Any]:
    return _decision_tool("lineage_analyze", arguments)


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


def _production_api(path: str, *, timeout: int = 60) -> dict[str, Any]:
    if not path.startswith("/api/robots"):
        raise ValueError("production API path is not allowlisted")
    remote = "curl -fsS " + shlex.quote("http://127.0.0.1:8082" + path)
    return _run_json(
        [SSH, "-F", SSH_CONFIG, PRODUCTION, remote],
        timeout=timeout,
    )


def _specs_from_robot(robot: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "height_cm": "height",
        "height_mm": "height",
        "weight_kg": "weight",
        "total_dof": "dof",
        "max_speed_mps": "speed",
        "charging_time_h": "charge_time",
        "compute_tops": "compute",
    }
    specs = robot.get("specs")
    if isinstance(specs, dict):
        out: dict[str, Any] = {}
        for raw_key, value in specs.items():
            key = aliases.get(str(raw_key).strip(), str(raw_key).strip())
            if key and value not in (None, "", []):
                out[key] = value
        return out

    evidence = robot.get("specEvidence")
    if not isinstance(evidence, list):
        evidence = (
            robot.get("provenance", {}).get("specEvidence")
            if isinstance(robot.get("provenance"), dict)
            else None
        )
    out: dict[str, Any] = {}
    if not isinstance(evidence, list):
        return out
    for row in evidence:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        value = row.get("value")
        if value is None:
            value = row.get("valueText")
        if value not in (None, ""):
            out[key] = value
    return out


def _product_from_robot(robot: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(robot.get("id") or ""),
        "name": str(robot.get("name") or ""),
        "company": str(robot.get("company") or robot.get("canonicalCompany") or ""),
        "description": str(robot.get("description") or robot.get("fullIntroduction") or ""),
        "launch_date": str(robot.get("entryTime") or robot.get("launch_date") or ""),
        "specs": _specs_from_robot(robot),
    }


def _search_anchor_for_spec(key: str, value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = f"{float(value):g}"
        if key == "height":
            return number
        if key == "weight":
            return number + "kg"
        if key == "speed":
            return number + "m/s"
        if key == "dof":
            return number + "DOF"
        if key in {"battery", "battery_capacity"}:
            return number
        if key in {"compute", "compute_tops"}:
            return number + " TOPS"
        return number
    text = str(value).strip()
    return text[:80] if 2 <= len(text) <= 80 else None


def _robot_anchor_queries(robot: dict[str, Any]) -> list[str]:
    explicit = robot.get("search_anchors")
    if isinstance(explicit, list):
        cleaned = [str(value).strip()[:80] for value in explicit if str(value).strip()]
        if cleaned:
            return list(dict.fromkeys(cleaned))[:8]

    specs = _specs_from_robot(robot)
    priority = (
        "dof", "height", "weight", "speed", "compute_tops", "compute",
        "battery", "battery_capacity", "charge_time",
    )
    anchors: list[str] = []
    for key in priority:
        if key not in specs:
            continue
        value = specs[key]
        generated: list[str] = []
        if key == "dof" and isinstance(value, (int, float)) and not isinstance(value, bool):
            number = f"{float(value):g}"
            generated.extend([number + "个自由度", number + "DOF"])
        elif key == "height" and isinstance(value, (int, float)) and not isinstance(value, bool):
            number = f"{float(value):g}"
            generated.extend([number + "cm", number])
        else:
            anchor = _search_anchor_for_spec(key, value)
            if anchor:
                generated.append(anchor)
        for anchor in generated:
            if anchor and anchor not in anchors:
                anchors.append(anchor)
            if len(anchors) >= 6:
                break
        if len(anchors) >= 6:
            break

    name = str(robot.get("name") or "").strip()
    if name and len(anchors) < 6:
        tokens = [
            token for token in name.replace("-", " ").split()
            if len(token) >= 2 and not token.lower() in {"robot", "机器人", "humanoid"}
        ]
        if tokens:
            anchors.append(tokens[-1][:80])
    return list(dict.fromkeys(anchors))[:6]


def _numeric_similarity(left: float, right: float) -> float:
    denom = max(abs(left), abs(right), 1e-9)
    rel = abs(left - right) / denom
    if rel <= 0.01:
        return 1.0
    if rel <= 0.03:
        return 0.9
    if rel <= 0.08:
        return 0.6
    if rel <= 0.15:
        return 0.3
    return 0.0


def _spec_overlap(left: dict[str, Any], right: dict[str, Any]) -> tuple[int, float]:
    common = sorted(set(left) & set(right))
    if not common:
        return 0, 0.0
    scores: list[float] = []
    for key in common:
        a, b = left[key], right[key]
        if (
            isinstance(a, (int, float)) and not isinstance(a, bool)
            and isinstance(b, (int, float)) and not isinstance(b, bool)
        ):
            scores.append(_numeric_similarity(float(a), float(b)))
            continue
        aa = str(a).strip().lower()
        bb = str(b).strip().lower()
        scores.append(1.0 if aa == bb else (0.8 if aa and bb and (aa in bb or bb in aa) else 0.0))
    return len(common), sum(scores) / len(scores)


def _robot_lineage_admission(arguments: dict[str, Any]) -> dict[str, Any]:
    robot = arguments.get("robot")
    if not isinstance(robot, dict):
        raise ValueError("robot must be an object")
    source_product = _product_from_robot(robot)
    if not (source_product["id"] or source_product["name"]):
        raise ValueError("robot requires id or name")
    if not source_product["specs"]:
        raise ValueError("robot requires canonical specs or specEvidence")

    shortlist_limit = max(1, min(int(arguments.get("shortlist_limit", 3)), 5))
    per_query_limit = max(1, min(int(arguments.get("per_query_limit", 10)), 20))
    anchors = _robot_anchor_queries(robot)
    if not anchors:
        raise ValueError("no safe search anchors could be derived from robot specs")

    hit_counts: dict[str, int] = {}
    candidates: dict[str, dict[str, Any]] = {}
    form = str(robot.get("formCategory") or robot.get("primaryForm") or "").strip()

    for anchor in anchors:
        query = urllib.parse.quote(anchor, safe="")
        payload = _production_api(
            f"/api/robots?search={query}&pageSize={per_query_limit}",
            timeout=60,
        )
        rows = payload.get("robots")
        if not isinstance(rows, list):
            continue
        seen_this_query: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            candidate_id = str(row.get("id") or "").strip()
            if not candidate_id or candidate_id == source_product["id"]:
                continue
            candidate_form = str(row.get("formCategory") or row.get("primaryForm") or "").strip()
            if form and candidate_form and candidate_form != form:
                continue
            candidates[candidate_id] = row
            if candidate_id not in seen_this_query:
                hit_counts[candidate_id] = hit_counts.get(candidate_id, 0) + 1
                seen_this_query.add(candidate_id)

    ranked_ids = sorted(
        candidates,
        key=lambda candidate_id: (
            -hit_counts.get(candidate_id, 0),
            -float(candidates[candidate_id].get("heatScore") or 0.0),
            candidate_id,
        ),
    )
    detail_limit = min(len(ranked_ids), max(shortlist_limit * 3, 6))
    detailed: list[dict[str, Any]] = []

    for candidate_id in ranked_ids[:detail_limit]:
        detail = _production_api(
            "/api/robots/" + urllib.parse.quote(candidate_id, safe=""),
            timeout=60,
        )
        candidate_robot = detail.get("robot")
        if not isinstance(candidate_robot, dict):
            continue
        candidate_robot = dict(candidate_robot)
        provenance = detail.get("provenance")
        if isinstance(provenance, dict):
            candidate_robot["specEvidence"] = provenance.get("specEvidence")
        product = _product_from_robot(candidate_robot)
        comparable, similarity = _spec_overlap(
            source_product["specs"],
            product["specs"],
        )
        detailed.append(
            {
                "id": candidate_id,
                "name": product["name"],
                "company": product["company"],
                "anchor_hits": hit_counts.get(candidate_id, 0),
                "comparable_specs": comparable,
                "spec_similarity": round(similarity, 4),
                "product": product,
            }
        )

    detailed.sort(
        key=lambda row: (
            -int(row["comparable_specs"]),
            -float(row["spec_similarity"]),
            -int(row["anchor_hits"]),
            str(row["id"]),
        )
    )
    shortlist = detailed[:shortlist_limit]
    evidence = arguments.get("evidence")
    evidence = evidence if isinstance(evidence, list) else []

    analyzed: list[dict[str, Any]] = []
    for row in shortlist:
        lineage = _kev_lineage_analyze(
            {
                "pair_id": (
                    f"admission:{source_product['id'] or source_product['name']}:"
                    f"{row['id']}"
                ),
                "left": source_product,
                "right": row["product"],
                "evidence": evidence,
                "mode": "shadow",
            }
        )
        analyzed.append(
            {
                "candidate": {
                    key: row[key]
                    for key in (
                        "id", "name", "company", "anchor_hits",
                        "comparable_specs", "spec_similarity",
                    )
                },
                "safe_relation": lineage.get("safe_relation"),
                "needs_human_review": bool(lineage.get("needs_human_review")),
                "fingerprint": lineage.get("fingerprint"),
                "provider_agreement": lineage.get("provider_agreement"),
                "canonical_write_allowed": bool(lineage.get("canonical_write_allowed")),
                "lineage": lineage,
            }
        )

    relation_rank = {
        "confirmed_rebrand": 5,
        "probable_oem_derivative": 4,
        "same_platform": 3,
        "rebrand_candidate": 2,
        "distinct_product": 1,
        "insufficient_evidence": 0,
    }
    analyzed.sort(
        key=lambda row: (
            -relation_rank.get(str(row.get("safe_relation")), -1),
            -float((row.get("fingerprint") or {}).get("score") or 0.0),
            str((row.get("candidate") or {}).get("id") or ""),
        )
    )

    return {
        "mode": "shadow",
        "production_effect": "none",
        "canonical_write_allowed": False,
        "source_robot": {
            "id": source_product["id"],
            "name": source_product["name"],
            "company": source_product["company"],
        },
        "search_anchors": anchors,
        "candidate_pool_count": len(candidates),
        "detailed_candidate_count": len(detailed),
        "shortlist_limit": shortlist_limit,
        "results": analyzed,
    }


def _deepseek_harness_propose(arguments: dict[str, Any]) -> dict[str, Any]:
    workspace = str(arguments.get("workspace") or "").strip()
    task = str(arguments.get("task") or "").strip()
    if not workspace:
        raise ValueError("workspace is required")
    if not task:
        raise ValueError("task is required")
    timeout = max(10, min(int(arguments.get("timeout", 600)), 1800))
    response = _run_json(
        [SSH, "-F", SSH_CONFIG, MAC_WORKNODE],
        input_text=json.dumps(
            {
                "action": "agent.deepseek.propose",
                "workspace": workspace,
                "task": task,
                "timeout": timeout,
            },
            ensure_ascii=False,
        ),
        timeout=timeout + 30,
    )
    result = response.get("result")
    if response.get("ok") is not True or not isinstance(result, dict):
        raise RuntimeError("DeepSeek Harness worker returned an invalid response")
    return result


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
    elif operation == "kev.lineage.analyze":
        result = _kev_lineage_analyze(arguments)
    elif operation == "iwm.robot.lineage.admission":
        result = _robot_lineage_admission(arguments)
    elif operation == "iwm.timeline.search":
        result = _iwm_search(arguments)
    elif operation == "deepseek.harness.propose":
        result = _deepseek_harness_propose(arguments)
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
