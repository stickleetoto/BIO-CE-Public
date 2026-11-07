# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Public, engine-neutral contract between the BIO CE client and a memory engine.

The BIO CE desktop app, MCP server, and hooks are the *client*. A memory engine
owns memory truth: storage, retrieval, revisions, policy, review, and backup.
Two engines are planned: the built-in Community Engine (this package) and an
optional, separately installed engine that speaks the same public protocol.

Rules this module encodes:

* Capabilities are negotiated, never assumed. The support the client shows is
  the *lower* of what the engine declares and what this client release has
  verified for that engine. Anything else is not offered to the user.
* Memory IDs are opaque and engine-scoped. Every view carries ``engine_id`` so a
  record from one engine is never mistaken for a record of another.
* A write returns a typed outcome. Only :attr:`WriteStatus.SAVED` means a
  memory was stored; a proposal waiting for review is never shown as saved.
* Incompatibility fails closed. Nothing here falls back to another engine.

Status: contract candidate (protocol version 1). It is exercised by the
Community Engine and by synthetic engines in tests only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Mapping, Protocol, runtime_checkable


CLIENT_PROTOCOL_MIN = 1
CLIENT_PROTOCOL_MAX = 1
_ENGINE_ID = re.compile(r"[a-z][a-z0-9_-]{1,31}\Z")


class Capability(StrEnum):
    MEMORY_SEARCH = "memory_search"
    MEMORY_GET = "memory_get"
    MEMORY_LIST = "memory_list"
    MEMORY_HISTORY = "memory_history"
    CONTEXT_PACK = "context_pack"
    MEMORY_PROPOSE = "memory_propose"
    DIRECT_USER_EDIT = "direct_user_edit"
    REVIEW_QUEUE = "review_queue"
    BACKUP_RESTORE = "backup_restore"
    HOST_AUTH = "host_auth"


class Support(StrEnum):
    """How far a capability can be used through this client."""

    SUPPORTED = "supported"      # verified end to end; offered normally
    LIMITED = "limited"          # works with a documented limitation; offered with a note
    UNVERIFIED = "unverified"    # declared but not verified by this client release; not offered
    UNSUPPORTED = "unsupported"  # not available; not offered

    @property
    def usable(self) -> bool:
        return self in (Support.SUPPORTED, Support.LIMITED)


_SUPPORT_ORDER = (Support.UNSUPPORTED, Support.UNVERIFIED, Support.LIMITED, Support.SUPPORTED)


def weaker(left: Support, right: Support) -> Support:
    """The lower of two support levels."""
    return min(left, right, key=_SUPPORT_ORDER.index)


class EngineState(StrEnum):
    READY = "ready"
    NOT_INSTALLED = "not_installed"
    NOT_RUNNING = "not_running"
    INCOMPATIBLE = "incompatible"
    UNAUTHORIZED = "unauthorized"
    ERROR = "error"


class WriteStatus(StrEnum):
    SAVED = "saved"                    # a memory revision was stored
    PENDING_REVIEW = "pending_review"  # queued for the user; nothing stored yet
    DUPLICATE = "duplicate"            # an equivalent memory exists; nothing stored
    REJECTED = "rejected"              # refused by the engine's policy; nothing stored
    CONFLICT = "conflict"              # the memory changed meanwhile; nothing stored
    NOT_SUPPORTED = "not_supported"    # the engine does not offer this write


class EngineError(RuntimeError):
    """Base class for expected engine-contract failures."""


class UnsupportedCapability(EngineError):
    def __init__(self, engine_id: str, capability: Capability) -> None:
        super().__init__(f"The {engine_id} engine does not offer {capability.value} through BIO CE.")
        self.engine_id = engine_id
        self.capability = capability


class EngineUnavailable(EngineError):
    """The engine is not installed, not running, incompatible, or refused access."""


class EngineProtocolError(EngineError):
    """The engine answered with something outside the contract; the result is discarded."""


class StaleEngineBinding(EngineError):
    """A request was made for an engine binding that is no longer current."""


@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    engine_id: str
    display_name: str
    engine_version: str
    protocol_min: int
    protocol_max: int
    capabilities: Mapping[Capability, Support]
    database_label: str

    def __post_init__(self) -> None:
        if not isinstance(self.engine_id, str) or _ENGINE_ID.fullmatch(self.engine_id) is None:
            raise EngineProtocolError("engine_id must be 2-32 lowercase letters, digits, '-' or '_'")
        if type(self.protocol_min) is not int or type(self.protocol_max) is not int \
                or not 1 <= self.protocol_min <= self.protocol_max:
            raise EngineProtocolError("protocol range must be integers with 1 <= min <= max")
        for capability, support in self.capabilities.items():
            if not isinstance(capability, Capability) or not isinstance(support, Support):
                raise EngineProtocolError("capabilities must map Capability to Support")

    def support(self, capability: Capability) -> Support:
        return self.capabilities.get(capability, Support.UNSUPPORTED)


@dataclass(frozen=True, slots=True)
class Negotiation:
    compatible: bool
    protocol_version: int | None
    reason: str


def negotiate(
    descriptor: EngineDescriptor,
    *,
    client_min: int = CLIENT_PROTOCOL_MIN,
    client_max: int = CLIENT_PROTOCOL_MAX,
) -> Negotiation:
    """Pick the highest protocol both sides speak, or refuse."""
    low, high = max(client_min, descriptor.protocol_min), min(client_max, descriptor.protocol_max)
    if low > high:
        return Negotiation(False, None, (
            f"{descriptor.display_name} speaks protocol {descriptor.protocol_min}-{descriptor.protocol_max}; "
            f"this BIO CE client speaks {client_min}-{client_max}."
        ))
    return Negotiation(True, high, f"protocol {high}")


def effective_capabilities(
    declared: Mapping[Capability, Support],
    verified: Mapping[Capability, Support],
) -> dict[Capability, Support]:
    """What the client may offer: the weaker of the engine's claim and this client's verification."""
    return {
        capability: weaker(declared.get(capability, Support.UNSUPPORTED),
                           verified.get(capability, Support.UNVERIFIED))
        for capability in Capability
    }


@dataclass(frozen=True, slots=True)
class EngineStatus:
    engine_id: str
    state: EngineState
    message: str
    descriptor: EngineDescriptor | None = None
    protocol_version: int | None = None

    @property
    def ready(self) -> bool:
        return self.state is EngineState.READY


@dataclass(frozen=True, slots=True)
class MemoryView:
    engine_id: str
    memory_id: str  # opaque and engine-scoped; never compared across engines
    revision_id: str
    revision_number: int
    kind: str
    title: str
    content: str | None
    source_type: str
    recorded_at: str
    valid_from: str | None = None
    valid_until: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResultView:
    engine_id: str
    memory_id: str
    revision_id: str
    rank: int
    score: float
    title: str
    preview: str
    source_type: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class ContextView:
    engine_id: str
    text: str


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """Something a connected AI host proposes to remember. It is a proposal, not a stored memory."""

    title: str
    content: str
    category: str
    confidence: str
    evidence: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    engine_id: str
    status: WriteStatus
    memory_id: str | None = None
    revision_id: str | None = None
    review_id: str | None = None
    reasons: tuple[str, ...] = field(default=())

    @property
    def persisted(self) -> bool:
        """True only when a memory revision was actually stored."""
        return self.status is WriteStatus.SAVED


@dataclass(frozen=True, slots=True)
class EngineBinding:
    """Which engine a host connection is routed to, and in which switch generation."""

    engine_id: str
    generation: int


@runtime_checkable
class HostSession(Protocol):
    """Operations on behalf of one authenticated AI host connection.

    Every call re-checks the connection's permission and its engine binding.
    """

    @property
    def engine_id(self) -> str: ...
    @property
    def binding(self) -> EngineBinding: ...
    def search(self, query: str, *, limit: int = 10) -> tuple[SearchResultView, ...]: ...
    def get(self, memory_id: str) -> MemoryView: ...
    def history(self, memory_id: str) -> tuple[MemoryView, ...]: ...
    def context(self, text: str, *, char_budget: int) -> ContextView: ...
    def propose(self, candidate: MemoryCandidate, *, request_id: str) -> WriteOutcome: ...
    def close(self) -> None: ...


@runtime_checkable
class EngineBackend(Protocol):
    """User-facing operations of one memory engine (desktop side)."""

    engine_id: str

    @property
    def descriptor(self) -> EngineDescriptor: ...
    def status(self) -> EngineStatus: ...
    def support(self, capability: Capability) -> Support: ...
    def list(self, *, limit: int = 100, offset: int = 0) -> tuple[MemoryView, ...]: ...
    def search(self, query: str, *, limit: int = 50) -> tuple[SearchResultView, ...]: ...
    def get(self, memory_id: str) -> MemoryView: ...
    def history(self, memory_id: str) -> tuple[MemoryView, ...]: ...
    # Direct user edits (Capability.DIRECT_USER_EDIT); an engine without it raises UnsupportedCapability.
    def create(self, *, title: str, content: str, source_ref: str) -> WriteOutcome: ...
    def revise(self, memory_id: str, *, expected_revision_id: str, title: str, content: str,
               source_ref: str) -> WriteOutcome: ...
    def retract(self, memory_id: str, *, expected_revision_id: str) -> WriteOutcome: ...
    def open_host_session(self, connection_id: str, token: str, *, binding: EngineBinding,
                          binding_guard) -> HostSession: ...
    def close(self) -> None: ...


def require(backend: EngineBackend, capability: Capability) -> None:
    """Raise unless ``capability`` is usable on ``backend``."""
    if not backend.support(capability).usable:
        # An engine that never connected has no descriptor; its configured ID still names it.
        raise UnsupportedCapability(getattr(backend, "engine_id", "unknown"), capability)


__all__ = [
    "CLIENT_PROTOCOL_MAX", "CLIENT_PROTOCOL_MIN", "Capability", "ContextView", "EngineBackend", "EngineBinding",
    "EngineDescriptor", "EngineError", "EngineProtocolError", "EngineState", "EngineStatus", "EngineUnavailable",
    "HostSession", "MemoryCandidate", "MemoryView", "Negotiation", "SearchResultView", "StaleEngineBinding",
    "Support", "UnsupportedCapability", "WriteOutcome", "WriteStatus", "effective_capabilities", "negotiate",
    "require", "weaker",
]
