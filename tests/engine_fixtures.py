# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""A synthetic external engine for contract tests. It is not a model of any real engine."""

from __future__ import annotations

from typing import Any, Mapping

from bio_ce.engine.external import TransportError


ALL_CAPABILITIES = {
    "memory_search": "supported", "memory_get": "supported", "memory_list": "supported",
    "memory_history": "supported", "context_pack": "supported", "memory_propose": "supported",
    "direct_user_edit": "supported", "review_queue": "supported", "backup_restore": "supported",
    "host_auth": "supported",
}


def synthetic_memory(index: int) -> dict[str, Any]:
    return {"memory_id": f"syn-{index}", "revision_id": f"syn-rev-{index}", "revision_number": 1,
            "kind": "assertion", "title": f"Synthetic engine note {index}",
            "content": f"Synthetic engine content number {index}.", "source_type": "synthetic",
            "recorded_at": "2026-11-07T00:00:00.000000Z"}


class SyntheticTransport:
    """Answers protocol v1 requests from fixed data and records every request it receives."""

    def __init__(self, *, engine_id: str = "core", protocol=(1, 1), capabilities: Mapping[str, str] | None = None,
                 proposal_status: str = "pending_review", running: bool = True, token: str = "synthetic-token"):
        self.engine_id = engine_id
        self.protocol = protocol
        self.capabilities = dict(ALL_CAPABILITIES if capabilities is None else capabilities)
        self.proposal_status = proposal_status
        self.running = running
        self.token = token
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.memories = [synthetic_memory(index) for index in range(3)]
        self.sessions: set[str] = set()
        self.closed = False

    def request(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.running:
            raise TransportError("not running")
        self.requests.append((operation, dict(payload)))
        if operation == "engine.describe":
            return {"engine_id": self.engine_id, "display_name": "Synthetic engine", "engine_version": "0.0-test",
                    "protocol_min": self.protocol[0], "protocol_max": self.protocol[1],
                    "capabilities": self.capabilities, "database_label": "Synthetic engine database"}
        if operation == "engine.health":
            return {"state": "ready"}
        if operation == "memory.list":
            return {"memories": self.memories}
        if operation == "memory.search":
            return {"results": [{**memory, "rank": rank, "score": 1.0 / rank, "preview": memory["content"]}
                                for rank, memory in enumerate(self.memories, start=1)
                                if any(word in memory["content"].lower() for word in payload["query"].lower().split())]}
        if operation == "memory.get":
            return next((m for m in self.memories if m["memory_id"] == payload["memory_id"]),
                        {"error": {"code": "not_found"}})
        if operation == "memory.history":
            return {"revisions": [m for m in self.memories if m["memory_id"] == payload["memory_id"]]}
        if operation == "session.open":
            if payload.get("token") != self.token:
                return {"error": {"code": "unauthorized"}}
            session = f"session-{len(self.sessions) + 1}"
            self.sessions.add(session)
            return {"session_id": session}
        if operation == "session.close":
            self.sessions.discard(payload["session_id"])
            return {}
        if payload.get("session_id") not in self.sessions:
            return {"error": {"code": "unauthorized"}}
        if operation == "session.context":
            return {"text": "Synthetic engine context."}
        if operation == "session.propose":
            answer: dict[str, Any] = {"status": self.proposal_status, "reasons": ["synthetic"]}
            if self.proposal_status == "pending_review":
                answer["review_id"] = "syn-review-1"
            if self.proposal_status == "saved":
                answer.update(memory_id="syn-new", revision_id="syn-new-rev")
            return answer
        return {"error": {"code": "not_supported"}}

    def close(self) -> None:
        self.closed = True
