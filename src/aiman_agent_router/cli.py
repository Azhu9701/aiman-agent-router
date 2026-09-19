from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex

from .bridge import CommandBridge
from .live import LiveRouterRuntime
from .registry import CapabilityRegistry, load_default_registry
from .router import AgentRouter
from .server import serve
from .trace import TraceStore


def _registry(path: str | None) -> CapabilityRegistry:
    return CapabilityRegistry.from_directory(path) if path else load_default_registry()


def main() -> int:
    parser = argparse.ArgumentParser(prog="aiman-router")
    parser.add_argument("--registry", help="registry directory override")
    sub = parser.add_subparsers(dest="command", required=True)

    route = sub.add_parser("route", help="route one TaskEnvelope JSON file")
    route.add_argument("task")

    live = sub.add_parser(
        "live",
        help="run one read-only live task through the AgentDock bridge",
    )
    live.add_argument("task")
    live.add_argument(
        "--bridge",
        default=os.environ.get(
            "AIMAN_ROUTER_BRIDGE",
            "/srv/agentdock/.local/bin/aiman-router-bridge",
        ),
        help="bridge command; parsed as argv without a shell",
    )
    live.add_argument(
        "--trace-dir",
        default=os.environ.get(
            "AIMAN_ROUTER_TRACE_DIR",
            "/srv/agentdock/.local/state/aiman-router/traces",
        ),
    )

    replay = sub.add_parser(
        "replay",
        help="load a saved trace and recompute its deterministic route",
    )
    replay.add_argument("trace")

    sub.add_parser("registry", help="print the capability registry")

    server = sub.add_parser("serve", help="serve /health, /registry and /route")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8088)

    args = parser.parse_args()
    registry = _registry(args.registry)
    router = AgentRouter(registry)

    if args.command == "route":
        payload = json.loads(Path(args.task).read_text(encoding="utf-8"))
        result = router.route_and_plan(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "live":
        payload = json.loads(Path(args.task).read_text(encoding="utf-8"))
        command = shlex.split(args.bridge)
        if not command:
            raise SystemExit("bridge command is empty")
        runtime = LiveRouterRuntime(
            router,
            CommandBridge(command),
            TraceStore(args.trace_dir),
        )
        trace = runtime.run(payload)
        print(json.dumps(trace, ensure_ascii=False, indent=2))
        return 0 if trace.get("result", {}).get("status") == "verified" else 2

    if args.command == "replay":
        trace = TraceStore(Path(args.trace).parent).load(args.trace)
        task = trace.get("task")
        if not isinstance(task, dict):
            raise SystemExit("trace has no task object")
        current = router.route_and_plan(task)
        output = {
            "trace_id": trace.get("trace_id"),
            "saved_decision": trace.get("decision"),
            "current_decision": current["decision"],
            "same_selected": (
                (trace.get("decision") or {}).get("selected")
                == current["decision"].get("selected")
            ),
            "current_plan": current["plan"],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    if args.command == "registry":
        print(
            json.dumps(
                {"items": [item.to_dict() for item in registry.all()]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "serve":
        serve(args.host, args.port, args.registry)
        return 0

    return 2
