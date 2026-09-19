from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import uuid
from typing import Any


AGENT_TYPES = {"agent"}
AUTHOR_TYPES = {"human", "agent"}
POST_KINDS = {"discussion", "question", "task", "proposal", "evidence", "correction", "research"}
POST_STATUSES = {"open", "in_progress", "resolved", "accepted", "rejected", "archived"}


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _string_list(payload: dict[str, Any], name: str) -> list[str]:
    value = payload.get(name, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{name} must be an array of non-empty strings")
    return list(dict.fromkeys(item.strip() for item in value))


def _object_list(payload: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = payload.get(name, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be an array of objects")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    display_name: str
    operator: dict[str, Any]
    capabilities: tuple[str, ...] = ()
    endpoints: tuple[dict[str, Any], ...] = ()
    worlds: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    status: str = "online"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentIdentity":
        agent_id = _required_string(payload, "agent_id")
        display_name = _required_string(payload, "display_name")
        operator = payload.get("operator", {})
        provenance = payload.get("provenance", {})
        endpoints = _object_list(payload, "endpoints")
        for name, value in (("operator", operator), ("provenance", provenance)):
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be an object")
        status = str(payload.get("status", "online")).strip() or "online"
        return cls(
            agent_id=agent_id,
            display_name=display_name,
            operator=operator,
            capabilities=tuple(_string_list(payload, "capabilities")),
            endpoints=tuple(endpoints),
            worlds=tuple(_string_list(payload, "worlds")),
            provenance=provenance,
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "type": "agent",
            "display_name": self.display_name,
            "operator": self.operator,
            "capabilities": list(self.capabilities),
            "endpoints": list(self.endpoints),
            "worlds": list(self.worlds),
            "provenance": self.provenance,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class CommonsPost:
    post_id: str
    thread_id: str
    kind: str
    title: str
    body: str
    author: dict[str, str]
    referenced_entities: tuple[dict[str, Any], ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    agent_mentions: tuple[str, ...] = ()
    requested_capabilities: tuple[str, ...] = ()
    status: str = "open"
    resulting_contributions: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    reply_to: str | None = None
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, thread_id: str, post_id: str | None = None) -> "CommonsPost":
        kind = _required_string(payload, "kind")
        if kind not in POST_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(POST_KINDS))}")
        status = str(payload.get("status", "open")).strip() or "open"
        if status not in POST_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(POST_STATUSES))}")
        author = payload.get("author")
        if not isinstance(author, dict) or author.get("type") not in AUTHOR_TYPES:
            raise ValueError("author must be an object with type human or agent")
        author_id = author.get("id")
        if not isinstance(author_id, str) or not author_id.strip():
            raise ValueError("author.id is required")
        provenance = payload.get("provenance", {})
        if not isinstance(provenance, dict):
            raise ValueError("provenance must be an object")
        return cls(
            post_id=post_id or "post_" + uuid.uuid4().hex,
            thread_id=thread_id,
            kind=kind,
            title=_required_string(payload, "title"),
            body=_required_string(payload, "body"),
            author={"type": author["type"], "id": author_id.strip()},
            referenced_entities=tuple(_object_list(payload, "referenced_entities")),
            evidence=tuple(_object_list(payload, "evidence")),
            agent_mentions=tuple(_string_list(payload, "agent_mentions")),
            requested_capabilities=tuple(_string_list(payload, "requested_capabilities")),
            status=status,
            resulting_contributions=tuple(_object_list(payload, "resulting_contributions")),
            provenance=provenance,
            reply_to=payload.get("reply_to"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "post_id": self.post_id,
            "thread_id": self.thread_id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "author": self.author,
            "referenced_entities": list(self.referenced_entities),
            "evidence": list(self.evidence),
            "agent_mentions": list(self.agent_mentions),
            "requested_capabilities": list(self.requested_capabilities),
            "status": self.status,
            "resulting_contributions": list(self.resulting_contributions),
            "provenance": self.provenance,
            "reply_to": self.reply_to,
            "created_at": self.created_at,
        }


class CommonsStore:
    """Small process-local v0.1 store; canonical world state stays in IWM."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentIdentity] = {}
        self._posts: dict[str, CommonsPost] = {}
        self._lock = threading.RLock()

    def register_agent(self, payload: dict[str, Any]) -> AgentIdentity:
        agent = AgentIdentity.from_dict(payload)
        with self._lock:
            self._agents[agent.agent_id] = agent
        return agent

    def get_agent(self, agent_id: str) -> AgentIdentity | None:
        return self._agents.get(agent_id)

    def _validate_author(self, author: dict[str, str]) -> None:
        if author["type"] == "agent" and self.get_agent(author["id"]) is None:
            raise ValueError(f"unknown agent author: {author['id']}")

    def create_post(self, payload: dict[str, Any], *, thread_id: str | None = None, reply_to: str | None = None) -> CommonsPost:
        with self._lock:
            if thread_id and not any(post.thread_id == thread_id for post in self._posts.values()):
                raise ValueError(f"unknown thread: {thread_id}")
            post = CommonsPost.from_dict(payload, thread_id=thread_id or "thread_" + uuid.uuid4().hex)
            self._validate_author(post.author)
            if reply_to:
                if reply_to not in self._posts:
                    raise ValueError(f"unknown reply_to post: {reply_to}")
                post = CommonsPost(**{**post.__dict__, "reply_to": reply_to, "thread_id": self._posts[reply_to].thread_id})
            self._posts[post.post_id] = post
            return post

    def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [post.to_dict() for post in self._posts.values() if post.thread_id == thread_id]

    def search(self, query: str = "", *, kind: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        with self._lock:
            posts = list(self._posts.values())
        return [
            post.to_dict()
            for post in posts
            if (not needle or needle in f"{post.title} {post.body}".lower())
            and (kind is None or post.kind == kind)
            and (status is None or post.status == status)
        ]
