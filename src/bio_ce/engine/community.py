# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The built-in Community Engine behind the public engine contract.

This adapter adds no memory behavior of its own. User operations delegate to
the desktop service the app already uses (:class:`bio_ce.desktop.DesktopMemoryService`),
and host operations delegate to the same grant checks and Auto memory policy
the MCP server uses (:class:`ControlStore`, :class:`AutoMemoryWriter`). The
adapter only converts results to engine-neutral views and typed outcomes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from bio_ce.auto_memory import AutoMemoryWriter
from bio_ce.control_store import AccessDenied, ControlStore, MODE_AUTO_MEMORY, control_database_for
from bio_ce.core.models import (
    MemoryNotFoundError,
    MemoryRevision,
    MemoryScope,
    RevisionConflictError,
    SearchHit,
)
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
    EngineUnavailable,
    MemoryCandidate,
    MemoryView,
    SearchResultView,
    Support,
    WriteOutcome,
    WriteStatus,
    require,
)
from bio_ce.storage.sqlite_store import SQLiteMemoryStore

if TYPE_CHECKING:  # the desktop module imports Tk; the host side must not need it
    from bio_ce.desktop import DesktopMemoryService


COMMUNITY_ENGINE_ID = "community"

# What the Community Engine offers through BIO CE today, with the evidence in
# the test suite. "limited" context: lexical hook context, not a ranked context pack.
COMMUNITY_CAPABILITIES: dict[Capability, Support] = {
    Capability.MEMORY_SEARCH: Support.SUPPORTED,
    Capability.MEMORY_GET: Support.SUPPORTED,
    Capability.MEMORY_LIST: Support.SUPPORTED,
    Capability.MEMORY_HISTORY: Support.SUPPORTED,
    Capability.CONTEXT_PACK: Support.LIMITED,
    Capability.MEMORY_PROPOSE: Support.SUPPORTED,
    Capability.DIRECT_USER_EDIT: Support.SUPPORTED,
    Capability.REVIEW_QUEUE: Support.SUPPORTED,
    Capability.BACKUP_RESTORE: Support.SUPPORTED,
    Capability.HOST_AUTH: Support.SUPPORTED,
}

_WRITER_STATUS = {
    "created": WriteStatus.SAVED,
    "updated": WriteStatus.SAVED,
    "duplicate": WriteStatus.DUPLICATE,
    "unchanged": WriteStatus.DUPLICATE,
    "rejected": WriteStatus.REJECTED,
    "queued_for_review": WriteStatus.PENDING_REVIEW,
    "conflict": WriteStatus.CONFLICT,
}


def community_descriptor(database: Path, version: str | None = None) -> EngineDescriptor:
    if version is None:
        from bio_ce import __version__ as version
    return EngineDescriptor(
        engine_id=COMMUNITY_ENGINE_ID,
        display_name="Community Engine",
        engine_version=str(version),
        protocol_min=CLIENT_PROTOCOL_MIN,
        protocol_max=CLIENT_PROTOCOL_MAX,
        capabilities=dict(COMMUNITY_CAPABILITIES),
        database_label=f"BIO CE local database ({Path(database).name})",
    )


def memory_view(revision: MemoryRevision) -> MemoryView:
    return MemoryView(
        engine_id=COMMUNITY_ENGINE_ID,
        memory_id=revision.memory_id,
        revision_id=revision.revision_id,
        revision_number=revision.revision_number,
        kind=revision.kind.value,
        title=revision.title,
        content=revision.content,
        source_type=revision.source.source_type,
        recorded_at=revision.recorded_at,
        valid_from=revision.valid_from,
        valid_until=revision.valid_until,
    )


def search_view(hit: SearchHit) -> SearchResultView:
    return SearchResultView(
        engine_id=COMMUNITY_ENGINE_ID,
        memory_id=hit.memory_id,
        revision_id=hit.revision_id,
        rank=hit.rank,
        score=hit.score,
        title=hit.title,
        preview=hit.preview,
        source_type=hit.source.source_type,
        recorded_at=hit.recorded_at,
    )


def writer_outcome(result: dict) -> WriteOutcome:
    """Map an :class:`AutoMemoryWriter` result to a typed outcome; anything unknown is an error."""
    status = _WRITER_STATUS.get(result.get("status"))
    if status is None:
        raise EngineProtocolError("the Community Engine returned an unknown write status")
    review_id = result.get("review_id")
    return WriteOutcome(
        engine_id=COMMUNITY_ENGINE_ID,
        status=status,
        memory_id=result.get("memory_id"),
        revision_id=result.get("revision_id") if status is WriteStatus.SAVED else None,
        review_id=None if review_id is None else str(review_id),
        reasons=tuple(str(reason) for reason in result.get("reasons", ())),
    )


class CommunityEngineAdapter:
    """User-facing Community Engine operations over the existing desktop service."""

    engine_id = COMMUNITY_ENGINE_ID

    def __init__(self, service: "DesktopMemoryService") -> None:
        self._service = service
        self._descriptor = community_descriptor(service.database)

    @property
    def descriptor(self) -> EngineDescriptor:
        return self._descriptor

    @property
    def database(self) -> Path:
        return self._service.database

    def status(self) -> EngineStatus:
        try:
            self._service.count()
        except Exception:
            return EngineStatus(COMMUNITY_ENGINE_ID, EngineState.ERROR,
                                "The BIO CE local database could not be read.", self._descriptor)
        return EngineStatus(COMMUNITY_ENGINE_ID, EngineState.READY, "Ready", self._descriptor,
                            CLIENT_PROTOCOL_MAX)

    def support(self, capability: Capability) -> Support:
        return self._descriptor.support(capability)

    # Reads ----------------------------------------------------------------

    def list(self, *, limit: int = 100, offset: int = 0) -> tuple[MemoryView, ...]:
        return tuple(memory_view(revision) for revision in self._service.list(limit=limit, offset=offset))

    def search(self, query: str, *, limit: int = 50) -> tuple[SearchResultView, ...]:
        return tuple(search_view(hit) for hit in self._service.search(query, limit=limit))

    def get(self, memory_id: str) -> MemoryView:
        return memory_view(self._service.read(memory_id))

    def history(self, memory_id: str) -> tuple[MemoryView, ...]:
        return tuple(memory_view(revision) for revision in self._service.history(memory_id))

    # User edits -----------------------------------------------------------

    def create(self, *, title: str, content: str, source_ref: str) -> WriteOutcome:
        require(self, Capability.DIRECT_USER_EDIT)
        saved = self._service.add(title=title, content=content, source_ref=source_ref)
        return WriteOutcome(COMMUNITY_ENGINE_ID, WriteStatus.SAVED, saved.memory_id, saved.revision_id)

    def revise(self, memory_id: str, *, expected_revision_id: str, title: str, content: str,
               source_ref: str) -> WriteOutcome:
        require(self, Capability.DIRECT_USER_EDIT)
        current = self._service.read(memory_id)
        if current.revision_id != expected_revision_id:
            return WriteOutcome(COMMUNITY_ENGINE_ID, WriteStatus.CONFLICT, memory_id,
                                reasons=("the memory changed since it was opened",))
        try:
            saved = self._service.revise(current, title=title, content=content, source_ref=source_ref)
        except RevisionConflictError:
            return WriteOutcome(COMMUNITY_ENGINE_ID, WriteStatus.CONFLICT, memory_id,
                                reasons=("the memory changed while saving",))
        return WriteOutcome(COMMUNITY_ENGINE_ID, WriteStatus.SAVED, saved.memory_id, saved.revision_id)

    def retract(self, memory_id: str, *, expected_revision_id: str) -> WriteOutcome:
        require(self, Capability.DIRECT_USER_EDIT)
        current = self._service.read(memory_id)
        if current.revision_id != expected_revision_id:
            return WriteOutcome(COMMUNITY_ENGINE_ID, WriteStatus.CONFLICT, memory_id,
                                reasons=("the memory changed since it was opened",))
        try:
            saved = self._service.retract(current)
        except RevisionConflictError:
            return WriteOutcome(COMMUNITY_ENGINE_ID, WriteStatus.CONFLICT, memory_id,
                                reasons=("the memory changed while saving",))
        return WriteOutcome(COMMUNITY_ENGINE_ID, WriteStatus.SAVED, saved.memory_id, saved.revision_id)

    # Host side ------------------------------------------------------------

    def open_host_session(self, connection_id: str, token: str, *, binding: EngineBinding,
                          binding_guard: Callable[[EngineBinding], None]) -> "CommunityHostSession":
        return CommunityHostSession(self._service.database, connection_id, token,
                                    binding=binding, binding_guard=binding_guard)

    def close(self) -> None:
        """The desktop service is owned by the app; closing the adapter leaves it open."""


class CommunityHostSession:
    """One AI host connection on the Community Engine.

    Authentication happens once; every call then re-reads the grant (mode,
    revocation, scope) exactly like the MCP server, and first asks
    ``binding_guard`` whether this engine binding is still the current one.
    """

    def __init__(self, database: Path, connection_id: str, token: str, *, binding: EngineBinding,
                 binding_guard: Callable[[EngineBinding], None]) -> None:
        if binding.engine_id != COMMUNITY_ENGINE_ID:
            raise EngineProtocolError("a Community session needs a Community engine binding")
        self._database = Path(database).expanduser().resolve()
        self._binding = binding
        self._guard = binding_guard
        self._guard(binding)
        self._control = ControlStore(control_database_for(self._database))
        try:
            grant = self._control.authenticate(connection_id, token)
        except AccessDenied:
            self._control.close()
            raise EngineUnavailable("BIO CE rejected this connection's credentials.") from None
        self._connection_id = connection_id
        self._scope = MemoryScope(grant.project, grant.namespace)
        self._store: SQLiteMemoryStore | None = None

    @property
    def engine_id(self) -> str:
        return COMMUNITY_ENGINE_ID

    @property
    def binding(self) -> EngineBinding:
        return self._binding

    def _read_store(self) -> SQLiteMemoryStore:
        self._guard(self._binding)
        grant = self._control.grant(self._connection_id)
        if (grant.project, grant.namespace) != (self._scope.project, self._scope.namespace) or not grant.can_read:
            raise AccessDenied("BIO CE access for this connection is unavailable.")
        if self._store is None:
            self._store = SQLiteMemoryStore(self._database, read_only=True)
        return self._store

    def search(self, query: str, *, limit: int = 10) -> tuple[SearchResultView, ...]:
        store = self._read_store()
        return tuple(search_view(hit) for hit in store.search(self._scope, query, limit=limit))

    def get(self, memory_id: str) -> MemoryView:
        return memory_view(self._read_store().read(self._scope, memory_id))

    def history(self, memory_id: str) -> tuple[MemoryView, ...]:
        return tuple(memory_view(revision) for revision in self._read_store().history(self._scope, memory_id))

    def context(self, text: str, *, char_budget: int) -> ContextView:
        from bio_ce import host_hooks

        store = self._read_store()
        auto = self._control.grant(self._connection_id).mode == MODE_AUTO_MEMORY
        budget = max(0, min(int(char_budget), host_hooks.PROMPT_CONTEXT_LIMIT))
        body = host_hooks._prompt_context(store, self._scope, {"prompt": text}, auto)
        return ContextView(COMMUNITY_ENGINE_ID, host_hooks._limit(body, budget) if budget else "")

    def propose(self, candidate: MemoryCandidate, *, request_id: str) -> WriteOutcome:
        """Send a host proposal through the Auto memory policy. ``request_id`` is not used by this engine."""
        self._guard(self._binding)
        writer = AutoMemoryWriter(self._database, self._control, scope=self._scope,
                                  connection_id=self._connection_id)
        try:
            result = writer.create(title=candidate.title, content=candidate.content, category=candidate.category,
                                   confidence=candidate.confidence, evidence=candidate.evidence,
                                   reason=candidate.reason)
        except MemoryNotFoundError:
            return WriteOutcome(COMMUNITY_ENGINE_ID, WriteStatus.CONFLICT,
                                reasons=("a matching memory changed during the request",))
        return writer_outcome(result)

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None
        self._control.close()


__all__ = [
    "COMMUNITY_CAPABILITIES", "COMMUNITY_ENGINE_ID", "CommunityEngineAdapter", "CommunityHostSession",
    "community_descriptor", "memory_view", "search_view", "writer_outcome",
]
