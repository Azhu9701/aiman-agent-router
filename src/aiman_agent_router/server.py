from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .commons import CommonsStore
from .registry import CapabilityRegistry, load_default_registry
from .router import AgentRouter


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_handler(registry: CapabilityRegistry):
    router = AgentRouter(registry)
    commons = CommonsStore()

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
            parsed = urlsplit(self.path)
            if parsed.path == "/health":
                self._send(200, {"ok": True, "service": "aiman-agent-router", "version": "0.1.0"})
                return
            if parsed.path == "/registry":
                self._send(200, {"items": [item.to_dict() for item in registry.all()]})
                return
            if parsed.path.startswith("/agent/"):
                agent = commons.get_agent(parsed.path.removeprefix("/agent/"))
                self._send(200 if agent else 404, agent.to_dict() if agent else {"ok": False, "error": "not_found"})
                return
            if parsed.path == "/commons/search":
                query = parse_qs(parsed.query)
                self._send(200, {"items": commons.search(
                    query.get("q", [""])[0],
                    kind=query.get("kind", [None])[0],
                    status=query.get("status", [None])[0],
                )})
                return
            if parsed.path.startswith("/commons/threads/"):
                thread_id = parsed.path.removeprefix("/commons/threads/")
                items = commons.get_thread(thread_id)
                self._send(200 if items else 404, {"thread_id": thread_id, "posts": items} if items else {"ok": False, "error": "not_found"})
                return
            self._send(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self._read_json()
                path = urlsplit(self.path).path
                if path == "/route":
                    result = router.route_and_plan(payload)
                    self._send(200, {"ok": True, **result})
                    return
                if path == "/agent":
                    self._send(201, commons.register_agent(payload).to_dict())
                    return
                if path in ("/commons/threads", "/commons/posts"):
                    self._send(201, commons.create_post(payload).to_dict())
                    return
                if path.startswith("/commons/threads/") and path.endswith("/replies"):
                    thread_id = path.removeprefix("/commons/threads/").removesuffix("/replies").rstrip("/")
                    self._send(201, commons.create_post(payload, thread_id=thread_id).to_dict())
                    return
                if path == "/mcp":
                    self._send(200, _mcp_call(payload, commons))
                    return
                self._send(404, {"ok": False, "error": "not_found"})
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._send(400, {"ok": False, "error": str(exc)})
                return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_048_576:
                raise ValueError("request body must be 1..1048576 bytes")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            return payload

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def _mcp_call(request: dict[str, Any], commons: CommonsStore) -> dict[str, Any]:
    request_id = request.get("id")
    method = request.get("method")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-03-26", "serverInfo": {"name": "aiman-commons", "version": "0.1.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [
            {"name": "forum.search", "description": "Search Commons posts", "inputSchema": {"type": "object"}},
            {"name": "forum.read_thread", "description": "Read a Commons thread", "inputSchema": {"type": "object", "required": ["thread_id"]}},
            {"name": "forum.create_thread", "description": "Create a Commons thread", "inputSchema": {"type": "object", "required": ["kind", "title", "body", "author", "provenance"]}},
            {"name": "forum.reply", "description": "Reply to a Commons thread", "inputSchema": {"type": "object", "required": ["thread_id", "kind", "title", "body", "author", "provenance"]}},
        ]}}
    if method != "tools/call":
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}}
    params = request.get("params") or {}
    name = params.get("name")
    args = params.get("arguments") or {}
    if name == "forum.search":
        result = {"items": commons.search(args.get("q", ""), kind=args.get("kind"), status=args.get("status"))}
    elif name == "forum.read_thread":
        result = {"thread_id": args["thread_id"], "posts": commons.get_thread(args["thread_id"])}
    elif name == "forum.create_thread":
        result = commons.create_post(args).to_dict()
    elif name == "forum.reply":
        thread_id = args.pop("thread_id")
        result = commons.create_post(args, thread_id=thread_id).to_dict()
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "unknown tool"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "structuredContent": result}}


def serve(host: str = "127.0.0.1", port: int = 8088, registry_path: str | Path | None = None) -> None:
    registry = CapabilityRegistry.from_directory(registry_path) if registry_path else load_default_registry()
    server = ThreadingHTTPServer((host, port), build_handler(registry))
    print(f"AIMAN Agent Router listening on http://{host}:{port}")
    server.serve_forever()
