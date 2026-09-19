from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any

from .registry import CapabilityRegistry, load_default_registry
from .router import AgentRouter


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_handler(registry: CapabilityRegistry):
    router = AgentRouter(registry)

    class Handler(BaseHTTPRequestHandler):
        server_version = "AIMANAgentRouter/0.1"

        def _send(self, status: int, payload: Any) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send(200, {"ok": True, "service": "aiman-agent-router", "version": "0.1.0"})
                return
            if self.path == "/registry":
                self._send(200, {"items": [item.to_dict() for item in registry.all()]})
                return
            self._send(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/route":
                self._send(404, {"ok": False, "error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_048_576:
                    raise ValueError("request body must be 1..1048576 bytes")
                payload = json.loads(self.rfile.read(length))
                result = router.route_and_plan(payload)
            except (ValueError, json.JSONDecodeError) as exc:
                self._send(400, {"ok": False, "error": str(exc)})
                return
            self._send(200, {"ok": True, **result})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8088, registry_path: str | Path | None = None) -> None:
    registry = CapabilityRegistry.from_directory(registry_path) if registry_path else load_default_registry()
    server = ThreadingHTTPServer((host, port), build_handler(registry))
    print(f"AIMAN Agent Router listening on http://{host}:{port}")
    server.serve_forever()
