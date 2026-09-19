from __future__ import annotations

import argparse
import json
from pathlib import Path

from .registry import CapabilityRegistry, load_default_registry
from .router import AgentRouter
from .server import serve


def _registry(path: str | None) -> CapabilityRegistry:
    return CapabilityRegistry.from_directory(path) if path else load_default_registry()


def main() -> int:
    parser = argparse.ArgumentParser(prog="aiman-router")
    parser.add_argument("--registry", help="registry directory override")
    sub = parser.add_subparsers(dest="command", required=True)

    route = sub.add_parser("route", help="route one TaskEnvelope JSON file")
    route.add_argument("task")

    sub.add_parser("registry", help="print the capability registry")

    server = sub.add_parser("serve", help="serve /health, /registry and /route")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8088)

    args = parser.parse_args()
    registry = _registry(args.registry)

    if args.command == "route":
        payload = json.loads(Path(args.task).read_text(encoding="utf-8"))
        result = AgentRouter(registry).route_and_plan(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "registry":
        print(json.dumps({"items": [item.to_dict() for item in registry.all()]}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "serve":
        serve(args.host, args.port, args.registry)
        return 0

    return 2
