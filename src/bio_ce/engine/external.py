# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Client side of an optional, separately installed engine that speaks the public protocol.

BIO CE ships no such engine and no code of one. This adapter only speaks the
public, versioned request/response contract over an injected
:class:`EngineTransport` (for example a local IPC channel provided by that
engine's installer). Until a transport is configured the engine is reported
as not installed and nothing is sent anywhere.

Safety rules enforced here:

* A capability is offered only if the engine declares it *and* this client
  release lists it in ``verified``. The default list is empty, so a real
  external engine is shown with every capability "unverified" until a client
  release has verified it end to end.
* Direct user edits, review decisions, and backup/restore are never sent to an
  external engine through this client; they need that engine's own authority.
* A host proposal is a proposal: only an explicit ``saved`` answer is reported
  as stored. Any unknown answer is a protocol error, never a success.
* The client never falls back to the Community Engine when this one fails.

Status: contract candidate, verified against synthetic transports only.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from bio_ce.engine.contract import (
    CLIENT_PROTOCOL_MAX,
    CLIENT_PROTOCOL_MIN,
    Capability,
    ContextView,
    EngineBinding,
    EngineDescriptor,
    EngineProtocolError,
    EngineState,
    EngineStatus,
    EngineUnauthorized,
    EngineUnavailable,
    MemoryCandidate,
    MemoryView,
    SearchResultView,
    Support,
    UnsupportedCapability,
    WriteOutcome,
    WriteStatus,
    effective_capabilities,
    negotiate,
    require,
)


# Operations of protocol v1 (candidate; names must be confirmed with the engine owner).
OP_DESCRIBE = "engine.describe"
OP_HEALTH = "engine.health"
OP_LIST = "memory.list"
OP_SEARCH = "memory.search"
OP_GET = "memory.get"
OP_HISTORY = "memory.history"
OP_SESSION_OPEN = "session.open"
OP_SESSION_CLOSE = "session.close"
OP_CONTEXT = "session.context"
OP_PROPOSE = "session.propose"

# Capabilities this client never routes to an external engine (they need that engine's own authority).
CLIENT_NEVER_ROUTES = frozenset({Capability.DIRECT_USER_EDIT, Capability.REVIEW_QUEUE, Capability.BACKUP_RESTORE})

_PROPOSAL_STATUS = {
    "saved": WriteStatus.SAVED,
    "pending_review": WriteStatus.PENDING_REVIEW,
    "duplicate": WriteStatus.DUPLICATE,
    "rejected": WriteStatus.REJECTED,
    "conflict": WriteStatus.CONFLICT,
    "not_supported": WriteStatus.NOT_SUPPORTED,
}


class EngineTransport(Protocol):
    """A request/response channel to a locally running engine."""

    def request(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def close(self) -> None: ...


class TransportError(Exception):
    """The transport could not deliver a request (engine not running, channel closed)."""


def parse_descriptor(data: Mapping[str, Any]) -> EngineDescriptor:
    """Validate an ``engine.describe`` answer. Unknown capability names are ignored."""
    try:
        raw = data["capabilities"]
        if not isinstance(raw, Mapping):
            raise TypeError
        capabilities: dict[Capability, Support] = {}
        for name, level in raw.items():
            try:
                capability = Capability(name)
            except ValueError:
                continue
            capabilities[capability] = Support(level)
        return EngineDescriptor(
            engine_id=str(data["engine_id"]),
            display_name=str(data["display_name"])[:80],
            engine_version=str(data["engine_version"])[:40],
            protocol_min=data["protocol_min"],
            protocol_max=data["protocol_max"],
            capabilities=capabilities,
            database_label=str(data.get("database_label") or "Engine-owned database")[:200],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EngineProtocolError("the engine description is not valid protocol v1 data") from exc


class ExternalEngineAdapter:
    """User-facing client for an external engine reached through ``transport``."""

    def __init__(
        self,
        engine_id: str,
        transport: EngineTransport | None,
        *,
        verified: Mapping[Capability, Support] | None = None,
    ) -> None:
        self.engine_id = engine_id
        self._transport = transport
        self._verified = dict(verified or {})
        self._descriptor: EngineDescriptor | None = None
        self._effective: dict[Capability, Support] = {capability: Support.UNSUPPORTED for capability in Capability}
        self._protocol: int | None = None

    # Negotiation ----------------------------------------------------------

    def connect(self) -> EngineStatus:
        """Describe and negotiate. Never raises; the status says what happened."""
        self._descriptor, self._protocol = None, None
        self._effective = {capability: Support.UNSUPPORTED for capability in Capability}
        if self._transport is None:
            return EngineStatus(self.engine_id, EngineState.NOT_INSTALLED, "Not installed.")
        try:
            descriptor = parse_descriptor(self._send(OP_DESCRIBE, {
                "client_protocol_min": CLIENT_PROTOCOL_MIN, "client_protocol_max": CLIENT_PROTOCOL_MAX,
            }))
        except EngineUnauthorized as exc:
            return EngineStatus(self.engine_id, EngineState.UNAUTHORIZED, str(exc))
        except EngineUnavailable as exc:
            return EngineStatus(self.engine_id, EngineState.NOT_RUNNING, str(exc))
        except EngineProtocolError as exc:
            return EngineStatus(self.engine_id, EngineState.INCOMPATIBLE, str(exc))
        if descriptor.engine_id != self.engine_id:
            return EngineStatus(self.engine_id, EngineState.INCOMPATIBLE,
                                "The engine answered with a different engine ID.")
        result = negotiate(descriptor)
        if not result.compatible:
            return EngineStatus(self.engine_id, EngineState.INCOMPATIBLE, result.reason, descriptor)
        effective = effective_capabilities(descriptor.capabilities, self._verified)
        for capability in CLIENT_NEVER_ROUTES:
            effective[capability] = Support.UNSUPPORTED
        self._descriptor, self._protocol, self._effective = descriptor, result.protocol_version, effective
        return EngineStatus(self.engine_id, EngineState.READY, "Ready", descriptor, result.protocol_version)

    @property
    def descriptor(self) -> EngineDescriptor:
        if self._descriptor is None:
            raise EngineUnavailable("The engine is not connected.")
        return self._descriptor

    def status(self) -> EngineStatus:
        if self._descriptor is None:
            return self.connect()
        try:
            answer = self._send(OP_HEALTH, {})
        except EngineUnauthorized as exc:
            return EngineStatus(self.engine_id, EngineState.UNAUTHORIZED, str(exc), self._descriptor)
        except (EngineUnavailable, EngineProtocolError) as exc:
            return EngineStatus(self.engine_id, EngineState.NOT_RUNNING, str(exc), self._descriptor)
        if answer.get("state") != "ready":
            return EngineStatus(self.engine_id, EngineState.ERROR, "The engine reported it is not ready.",
                                self._descriptor, self._protocol)
        return EngineStatus(self.engine_id, EngineState.READY, "Ready", self._descriptor, self._protocol)

    def support(self, capability: Capability) -> Support:
        return self._effective.get(capability, Support.UNSUPPORTED)

    # Reads ----------------------------------------------------------------

    def count(self) -> int | None:
        """Protocol v1 has no count operation, so the total is unknown."""
        return None

    def list(self, *, limit: int = 100, offset: int = 0) -> tuple[MemoryView, ...]:
        require(self, Capability.MEMORY_LIST)
        answer = self._send(OP_LIST, {"limit": limit, "offset": offset})
        return tuple(self._memory(item) for item in _items(answer, "memories"))

    def search(self, query: str, *, limit: int = 50) -> tuple[SearchResultView, ...]:
        require(self, Capability.MEMORY_SEARCH)
        answer = self._send(OP_SEARCH, {"query": query, "limit": limit})
        return tuple(self._hit(item) for item in _items(answer, "results"))

    def get(self, memory_id: str) -> MemoryView:
        require(self, Capability.MEMORY_GET)
        return self._memory(self._send(OP_GET, {"memory_id": memory_id}))

    def history(self, memory_id: str) -> tuple[MemoryView, ...]:
        require(self, Capability.MEMORY_HISTORY)
        answer = self._send(OP_HISTORY, {"memory_id": memory_id})
        return tuple(self._memory(item) for item in _items(answer, "revisions"))

    # User edits are never routed to an external engine by this client ----------

    def create(self, *, title: str, content: str, source_ref: str) -> WriteOutcome:
        raise UnsupportedCapability(self.engine_id, Capability.DIRECT_USER_EDIT)

    def revise(self, memory_id: str, *, expected_revision_id: str, title: str, content: str,
               source_ref: str) -> WriteOutcome:
        raise UnsupportedCapability(self.engine_id, Capability.DIRECT_USER_EDIT)

    def retract(self, memory_id: str, *, expected_revision_id: str) -> WriteOutcome:
        raise UnsupportedCapability(self.engine_id, Capability.DIRECT_USER_EDIT)

    # Host side ------------------------------------------------------------

    def open_host_session(self, connection_id: str, token: str, *, binding: EngineBinding,
                          binding_guard: Callable[[EngineBinding], None]) -> "ExternalHostSession":
        require(self, Capability.HOST_AUTH)
        if binding.engine_id != self.engine_id:
            raise EngineProtocolError("the binding is for a different engine")
        binding_guard(binding)
        answer = self._send(OP_SESSION_OPEN, {"connection_id": connection_id, "token": token,
                                              "generation": binding.generation})
        session_id = answer.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise EngineProtocolError("the engine did not return a session")
        return ExternalHostSession(self, session_id, binding, binding_guard)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()

    # Helpers --------------------------------------------------------------

    def _send(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._transport is None:
            raise EngineUnavailable("Not installed.")
        try:
            answer = self._transport.request(operation, dict(payload))
        except TransportError as exc:
            raise EngineUnavailable("The engine is not running or did not answer.") from exc
        if not isinstance(answer, Mapping):
            raise EngineProtocolError("the engine answer is not an object")
        error = answer.get("error")
        if error is not None:
            code = error.get("code") if isinstance(error, Mapping) else None
            if code == "unauthorized":
                raise EngineUnauthorized("The engine refused this connection.")
            if code == "not_supported":
                raise EngineProtocolError("the engine does not support this operation")
            raise EngineProtocolError("the engine reported an error")
        return answer

    def _memory(self, item: Any) -> MemoryView:
        try:
            return MemoryView(
                engine_id=self.engine_id,
                memory_id=str(item["memory_id"]),
                revision_id=str(item["revision_id"]),
                revision_number=int(item["revision_number"]),
                kind=str(item["kind"]),
                title=str(item["title"]),
                content=None if item.get("content") is None else str(item["content"]),
                source_type=str(item["source_type"]),
                recorded_at=str(item["recorded_at"]),
                valid_from=item.get("valid_from"),
                valid_until=item.get("valid_until"),
                source_ref=str(item.get("source_ref") or "")[:512],
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise EngineProtocolError("the engine returned an invalid memory") from exc

    def _hit(self, item: Any) -> SearchResultView:
        try:
            return SearchResultView(
                engine_id=self.engine_id,
                memory_id=str(item["memory_id"]),
                revision_id=str(item["revision_id"]),
                rank=int(item["rank"]),
                score=float(item["score"]),
                title=str(item["title"]),
                preview=str(item.get("preview") or "")[:240],
                source_type=str(item["source_type"]),
                recorded_at=str(item["recorded_at"]),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise EngineProtocolError("the engine returned an invalid search result") from exc


class ExternalHostSession:
    def __init__(self, adapter: ExternalEngineAdapter, session_id: str, binding: EngineBinding,
                 binding_guard: Callable[[EngineBinding], None]) -> None:
        self._adapter = adapter
        self._session_id = session_id
        self._binding = binding
        self._guard = binding_guard
        self._closed = False

    @property
    def engine_id(self) -> str:
        return self._adapter.engine_id

    @property
    def binding(self) -> EngineBinding:
        return self._binding

    def _call(self, capability: Capability, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._closed:
            raise EngineUnavailable("This host session was closed.")
        self._guard(self._binding)
        require(self._adapter, capability)
        return self._adapter._send(operation, {"session_id": self._session_id,
                                               "generation": self._binding.generation, **payload})

    def search(self, query: str, *, limit: int = 10) -> tuple[SearchResultView, ...]:
        answer = self._call(Capability.MEMORY_SEARCH, OP_SEARCH, {"query": query, "limit": limit})
        return tuple(self._adapter._hit(item) for item in _items(answer, "results"))

    def get(self, memory_id: str) -> MemoryView:
        return self._adapter._memory(self._call(Capability.MEMORY_GET, OP_GET, {"memory_id": memory_id}))

    def history(self, memory_id: str) -> tuple[MemoryView, ...]:
        answer = self._call(Capability.MEMORY_HISTORY, OP_HISTORY, {"memory_id": memory_id})
        return tuple(self._adapter._memory(item) for item in _items(answer, "revisions"))

    def context(self, text: str, *, char_budget: int) -> ContextView:
        answer = self._call(Capability.CONTEXT_PACK, OP_CONTEXT, {"text": text, "char_budget": int(char_budget)})
        body = answer.get("text")
        if not isinstance(body, str):
            raise EngineProtocolError("the engine returned invalid context")
        return ContextView(self.engine_id, body[: max(0, int(char_budget))])

    def propose(self, candidate: MemoryCandidate, *, request_id: str) -> WriteOutcome:
        answer = self._call(Capability.MEMORY_PROPOSE, OP_PROPOSE, {
            "request_id": request_id, "title": candidate.title, "content": candidate.content,
            "category": candidate.category, "confidence": candidate.confidence,
            # The host's own claim, passed as a claim: the engine decides what it is worth.
            "claimed_evidence": candidate.evidence, "reason": candidate.reason,
        })
        status = _PROPOSAL_STATUS.get(answer.get("status"))
        if status is None:
            raise EngineProtocolError("the engine returned an unknown proposal status")
        if status is WriteStatus.SAVED and not (answer.get("memory_id") and answer.get("revision_id")):
            raise EngineProtocolError("the engine reported a saved memory without its revision")
        reasons = answer.get("reasons") or ()
        return WriteOutcome(
            engine_id=self.engine_id,
            status=status,
            memory_id=answer.get("memory_id"),
            revision_id=answer.get("revision_id") if status is WriteStatus.SAVED else None,
            review_id=None if answer.get("review_id") is None else str(answer["review_id"]),
            reasons=tuple(str(reason) for reason in reasons) if isinstance(reasons, (list, tuple)) else (),
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._adapter._send(OP_SESSION_CLOSE, {"session_id": self._session_id})
        except (EngineUnavailable, EngineProtocolError):
            pass


def _items(answer: Mapping[str, Any], key: str) -> list[Any]:
    items = answer.get(key)
    if not isinstance(items, list):
        raise EngineProtocolError(f"the engine answer has no {key} list")
    return items


__all__ = [
    "CLIENT_NEVER_ROUTES", "EngineTransport", "ExternalEngineAdapter", "ExternalHostSession", "TransportError",
    "parse_descriptor",
]
