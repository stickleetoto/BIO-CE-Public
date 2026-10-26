# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Apply memory changes proposed by a connected AI host, and user review of them.

Every proposal passes :mod:`bio_ce.memory_policy` first. Accepted changes are
written through the normal :class:`SQLiteMemoryStore` API (atomic, revision
checked) with the host, connection, category, confidence, and evidence kept in
the revision's source metadata. Everything else is either refused or parked in
the review queue, and every outcome is written to the audit log.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from bio_ce.control_store import (
    AccessDenied,
    ControlStore,
    REVIEW_APPROVED,
    REVIEW_FAILED,
    REVIEW_REJECTED,
    ReviewItem,
)
from bio_ce.core.models import (
    MemoryNotFoundError,
    MemoryRevision,
    MemoryScope,
    RevisionConflictError,
    SourceProvenance,
)
from bio_ce.memory_policy import (
    DUPLICATE,
    REJECT,
    REVIEW,
    decide_create,
    decide_update,
    detect_secrets,
)
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


AUTO_SOURCE_TYPE = "ai-auto-memory"
APPROVED_SOURCE_TYPE = "ai-suggested-user-approved"
MAX_WRITES_PER_HOUR = 30


class AutoMemoryWriter:
    """Write path for one authenticated host connection."""

    def __init__(
        self,
        database: str | Path,
        control: ControlStore,
        *,
        scope: MemoryScope,
        connection_id: str,
        max_writes_per_hour: int = MAX_WRITES_PER_HOUR,
    ) -> None:
        self.database = Path(database).expanduser().resolve()
        self.control = control
        self.scope = scope
        self.connection_id = connection_id
        self.max_writes_per_hour = max_writes_per_hour

    # Public operations ------------------------------------------------------

    def create(
        self,
        *,
        title: str,
        content: str,
        category: str,
        confidence: str,
        evidence: str,
        reason: str = "",
    ) -> dict[str, Any]:
        host = self._authorize_write()
        store = SQLiteMemoryStore(self.database)
        try:
            existing = self._similar(store, f"{title}\n{content}")
            decision = decide_create(
                title=title, content=content, category=category, confidence=confidence,
                evidence=evidence, existing=existing,
            )
            detail = self._detail(category=category, confidence=confidence, evidence=evidence, reason=reason,
                                  decision=decision.summary)
            if decision.action == REJECT:
                return self._rejected(host, "create", decision, title, detail)
            if decision.action == DUPLICATE:
                self.control.record(host=host, connection_id=self.connection_id, action="create",
                                    outcome="duplicate", memory_id=decision.duplicate_of, title=title, detail=detail)
                current = store.read(self.scope, decision.duplicate_of)
                return {"status": "duplicate", "memory_id": current.memory_id,
                        "revision_id": current.revision_id, "reasons": list(decision.reasons)}
            self._check_rate(host)
            if decision.action == REVIEW:
                return self._queue(host, "create", title, content, decision.summary, detail)
            revision = store.add(self.scope, title=title, content=content,
                                 source=self._source(category, confidence, evidence, reason))
        finally:
            store.close()
        self.control.record(host=host, connection_id=self.connection_id, action="create", outcome="created",
                            memory_id=revision.memory_id, revision_id=revision.revision_id, title=title,
                            detail=detail)
        return {"status": "created", "memory_id": revision.memory_id, "revision_id": revision.revision_id,
                "revision_number": revision.revision_number}

    def update(
        self,
        *,
        memory_id: str,
        expected_revision_id: str,
        title: str,
        content: str,
        change_type: str,
        confidence: str,
        evidence: str,
        reason: str = "",
    ) -> dict[str, Any]:
        host = self._authorize_write()
        store = SQLiteMemoryStore(self.database)
        try:
            current = store.read(self.scope, memory_id)
            if current.revision_id != expected_revision_id:
                self.control.record(host=host, connection_id=self.connection_id, action="update",
                                    outcome="conflict", memory_id=memory_id, title=current.title,
                                    detail={"reason": "stale expected_revision_id"})
                return {"status": "conflict", "memory_id": memory_id, "current_revision_id": current.revision_id,
                        "reasons": ["the memory changed since it was read; read it again and retry"]}
            decision = decide_update(
                title=title, content=content, change_type=change_type, confidence=confidence, evidence=evidence,
                current_text=f"{current.title}\n{current.content or ''}",
            )
            detail = self._detail(change_type=change_type, confidence=confidence, evidence=evidence, reason=reason,
                                  decision=decision.summary, previous_revision_id=expected_revision_id)
            if decision.action == REJECT:
                return self._rejected(host, "update", decision, title, detail, memory_id=memory_id)
            if decision.action == DUPLICATE:
                self.control.record(host=host, connection_id=self.connection_id, action="update",
                                    outcome="duplicate", memory_id=memory_id, title=title, detail=detail)
                return {"status": "unchanged", "memory_id": memory_id, "revision_id": current.revision_id,
                        "reasons": list(decision.reasons)}
            self._check_rate(host)
            if decision.action == REVIEW:
                return self._queue(host, "update", title, content, decision.summary, detail, memory_id=memory_id,
                                   expected_revision_id=expected_revision_id)
            try:
                revision = store.revise(
                    self.scope, memory_id, expected_revision_id=expected_revision_id, title=title,
                    content=content, source=self._source(change_type, confidence, evidence, reason),
                )
            except RevisionConflictError:
                self.control.record(host=host, connection_id=self.connection_id, action="update",
                                    outcome="conflict", memory_id=memory_id, title=title, detail=detail)
                return {"status": "conflict", "memory_id": memory_id,
                        "reasons": ["the memory changed while saving; read it again and retry"]}
        finally:
            store.close()
        self.control.record(host=host, connection_id=self.connection_id, action="update", outcome="updated",
                            memory_id=memory_id, revision_id=revision.revision_id, title=title, detail=detail)
        return {"status": "updated", "memory_id": memory_id, "revision_id": revision.revision_id,
                "revision_number": revision.revision_number}

    def request_retract(self, *, memory_id: str, expected_revision_id: str, reason: str = "") -> dict[str, Any]:
        """Automatic retraction is disabled; the request waits for the user."""
        host = self._authorize_write()
        store = SQLiteMemoryStore(self.database, read_only=True)
        try:
            current = store.read(self.scope, memory_id)
        finally:
            store.close()
        if current.revision_id != expected_revision_id:
            return {"status": "conflict", "memory_id": memory_id, "current_revision_id": current.revision_id,
                    "reasons": ["the memory changed since it was read; read it again and retry"]}
        self._check_rate(host)
        detail = self._detail(reason=reason)
        return self._queue(host, "retract", current.title, None, "retraction always needs the user's approval",
                           detail, memory_id=memory_id, expected_revision_id=expected_revision_id)

    # Helpers ----------------------------------------------------------------

    def _authorize_write(self) -> str:
        grant = self.control.grant(self.connection_id)
        if not grant.active:
            raise AccessDenied("Access for this connection was revoked in BIO CE.")
        if not grant.can_write:
            self.control.record(host=grant.host, connection_id=self.connection_id, action="write",
                                outcome="denied", detail={"mode": grant.mode})
            raise AccessDenied(
                "Auto memory is off for this connection. The user can turn it on in BIO CE → Connections."
                if grant.mode != "paused" else "BIO CE access is paused for this connection."
            )
        return grant.host

    def _check_rate(self, host: str) -> None:
        if self.control.writes_since(self.connection_id, timedelta(hours=1)) >= self.max_writes_per_hour:
            self.control.record(host=host, connection_id=self.connection_id, action="write", outcome="rate-limited")
            raise AccessDenied("Too many automatic memory changes in the last hour; BIO CE paused writes for now.")

    def _similar(self, store: SQLiteMemoryStore, text: str) -> tuple[tuple[str, str], ...]:
        hits = store.search(self.scope, text[:4000], limit=5)
        result = []
        for hit in hits:
            try:
                revision = store.read(self.scope, hit.memory_id)
            except MemoryNotFoundError:
                continue
            result.append((revision.memory_id, f"{revision.title}\n{revision.content or ''}"))
        return tuple(result)

    def _source(self, kind: str, confidence: str, evidence: str, reason: str) -> SourceProvenance:
        grant = self.control.grant(self.connection_id)
        return SourceProvenance(
            AUTO_SOURCE_TYPE,
            f"{grant.host}:{self.connection_id}",
            {"host": grant.host, "connection_id": self.connection_id, "kind": kind, "confidence": confidence,
             "evidence": evidence, "reason": (reason or "")[:500]},
        )

    @staticmethod
    def _detail(**values: Any) -> dict[str, Any]:
        return {key: (value[:500] if isinstance(value, str) else value) for key, value in values.items()
                if value not in (None, "")}

    def _rejected(self, host: str, action: str, decision, title: str, detail: dict[str, Any],
                  memory_id: str | None = None) -> dict[str, Any]:
        # Never keep text that contained a secret, not even its title.
        logged_title = None if decision.secret_kinds else title
        self.control.record(host=host, connection_id=self.connection_id, action=action, outcome="rejected",
                            memory_id=memory_id, title=logged_title, detail=detail)
        return {"status": "rejected", "reasons": list(decision.reasons)}

    def _queue(self, host: str, kind: str, title: str, content: str | None, why: str, detail: dict[str, Any],
               *, memory_id: str | None = None, expected_revision_id: str | None = None) -> dict[str, Any]:
        review_id = self.control.enqueue_review(
            host=host, connection_id=self.connection_id, kind=kind, title=title, content=content,
            review_reason=why, memory_id=memory_id, expected_revision_id=expected_revision_id, metadata=detail,
        )
        self.control.record(host=host, connection_id=self.connection_id, action=kind, outcome="queued",
                            memory_id=memory_id, title=title, detail={**detail, "review_id": review_id})
        return {"status": "queued_for_review", "review_id": review_id, "reasons": [why],
                "message": "The user will review this in BIO CE before anything changes."}


class ReviewService:
    """User decisions on queued AI proposals (desktop side)."""

    def __init__(self, store: SQLiteMemoryStore, control: ControlStore, scope: MemoryScope) -> None:
        self.store = store
        self.control = control
        self.scope = scope

    def approve(self, review_id: int, *, title: str | None = None, content: str | None = None) -> MemoryRevision:
        """Apply a queued proposal, optionally with the user's edits."""
        item = self.control.review(review_id)
        final_title = title if title is not None else item.title
        final_content = content if content is not None else (item.content or "")
        if item.kind != "retract" and detect_secrets(final_title, final_content):
            self.control.resolve_review(review_id, REVIEW_FAILED, "contains a secret; not stored")
            raise ValueError("This text contains a password, token, or key, so BIO CE won't store it.")
        source = SourceProvenance(
            APPROVED_SOURCE_TYPE, f"{item.host}:review-{item.review_id}",
            {"host": item.host, "review_id": item.review_id, "kind": item.kind,
             "edited": final_title != item.title or final_content != (item.content or "")},
        )
        try:
            if item.kind == "create":
                revision = self.store.add(self.scope, title=final_title, content=final_content, source=source)
            elif item.kind == "update":
                revision = self.store.revise(self.scope, item.memory_id, expected_revision_id=item.expected_revision_id,
                                             title=final_title, content=final_content, source=source)
            else:
                revision = self.store.retract(self.scope, item.memory_id,
                                              expected_revision_id=item.expected_revision_id, source=source)
        except (RevisionConflictError, MemoryNotFoundError) as exc:
            self.control.resolve_review(review_id, REVIEW_FAILED, "the memory changed after the request")
            self.control.record(host=item.host, connection_id=item.connection_id, action=f"review-{item.kind}",
                                outcome="failed", memory_id=item.memory_id, title=item.title)
            raise RevisionConflictError("The memory changed after this request was made. Nothing was changed.") \
                from exc
        self.control.resolve_review(review_id, REVIEW_APPROVED, "approved by the user")
        self.control.record(host=item.host, connection_id=item.connection_id, action=f"review-{item.kind}",
                            outcome="approved", memory_id=revision.memory_id, revision_id=revision.revision_id,
                            title=final_title)
        return revision

    def reject(self, review_id: int) -> ReviewItem:
        item = self.control.review(review_id)
        self.control.resolve_review(review_id, REVIEW_REJECTED, "rejected by the user")
        self.control.record(host=item.host, connection_id=item.connection_id, action=f"review-{item.kind}",
                            outcome="rejected-by-user", memory_id=item.memory_id, title=item.title)
        return item


__all__ = ["APPROVED_SOURCE_TYPE", "AUTO_SOURCE_TYPE", "AutoMemoryWriter", "MAX_WRITES_PER_HOUR", "ReviewService"]
