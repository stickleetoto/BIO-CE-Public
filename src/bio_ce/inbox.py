# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Discarding inbox items, and forgetting a curated memory completely.

Inbox items are deleted physically when discarded; curated memories are retracted and keep their history, unless
the user forgets one completely (v0.4.4, :func:`forget_memory`, desktop app only), which deletes it the same way.
A discard removes the item's rows with secure_delete on, merges the search index, removes what the
control file kept about it (audit titles and details, usage rows), and empties both write-ahead logs. It is
recorded as done only after both checkpoints succeed; while another process holds an older snapshot (a
connected MCP server, which lets go after a minute without calls), the discard waits as "cleanup pending" and
:func:`finish_pending_cleanups` completes it later.

This removes the items from BIO CE's files as far as the app can. It cannot guarantee erasure from the drive
itself (SSD wear leveling, the Windows page file, file system journals), and backups made earlier still contain
the items.

Kept items: approving a suggestion or moving an inbox item to the memories keeps the inbox items it used aside
("<space>.inbox.kept") so it can be undone, instead of deleting them. Their result names them (source metadata
``kept``). When the result is deleted (a discard, or retracting the memory: :func:`erase_kept_for`), they are
discarded the same way, first, so an interruption never leaves them behind a deleted result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bio_ce.control_store import (
    CURATION_CLEANUP_PENDING,
    CURATION_DISCARDED,
    ControlStore,
)
from bio_ce.core.models import MemoryNotFoundError, MemoryScope, RevisionKind
from bio_ce.storage.sqlite_store import INBOX_SUFFIX, KEPT_SUFFIX, SQLiteMemoryStore, is_inbox_namespace


DESKTOP_HOST = "bio-ce-desktop"

DISCARD_NOTICE = (
    "BIO CE removes discarded items from its database as far as the app can: it overwrites the freed space in the "
    "database file and its log. It cannot guarantee erasure from the drive itself (for example SSD wear leveling, "
    "the Windows page file, or file system journals). Backups you made earlier still contain these items; delete "
    "old backups you no longer need."
)


@dataclass(frozen=True, slots=True)
class DiscardResult:
    item_id: int
    deleted: int
    completed: bool


def inbox_scope(curated: MemoryScope) -> MemoryScope:
    """The inbox that belongs to a curated scope: bio-ce-personal/default -> bio-ce-personal/default.inbox."""
    if curated.namespace.endswith(INBOX_SUFFIX):
        return curated
    return MemoryScope(curated.project, curated.namespace + INBOX_SUFFIX)


def kept_scope(inbox: MemoryScope) -> MemoryScope:
    """Where the inbox items of a suggestion or a move are kept, so it can be undone (never a space or an inbox)."""
    return MemoryScope(inbox.project, inbox_scope(inbox).namespace + KEPT_SUFFIX)


def _kept_in(metadata: dict) -> list[str]:
    ids = list(metadata.get("kept") or ())
    if "suggestion" in metadata:  # results approved before "kept" was recorded (0.4.3-rc1 fourth candidate)
        for key in ("merged_from", "from_inbox"):
            value = metadata.get(key)
            ids += list(value) if isinstance(value, (list, tuple)) else []
    return [str(memory_id) for memory_id in ids]


def kept_originals(store: SQLiteMemoryStore, scope: MemoryScope, memory_ids: list[str] | tuple[str, ...]) -> list[str]:
    """The kept items that ``memory_ids`` (in ``scope``) were made from, and in turn what those were made from.

    From the current revision: the store carries ``kept`` over to every later revision unless a write sets it (an
    undo sets the earlier list), so an item an undo gave back is never claimed by its old result. Read before a
    retraction: a retracted memory can't be read any more."""
    return _kept_chain(store, scope, [(scope, memory_id) for memory_id in memory_ids])


def _kept_chain(store: SQLiteMemoryStore, scope: MemoryScope, queue: list[tuple[MemoryScope, str]], *,
                found: list[str] | None = None) -> list[str]:
    aside = kept_scope(scope)
    found = [] if found is None else found
    for kept_id in found:
        queue.append((aside, kept_id))
    while queue:
        where, memory_id = queue.pop()
        try:
            current = store.read(where, memory_id)
        except MemoryNotFoundError:
            continue
        for kept_id in _kept_in(dict(current.source.metadata)):
            if kept_id not in found:
                found.append(kept_id)
                queue.append((aside, kept_id))
    present = []
    for memory_id in found:
        try:
            store.read(aside, memory_id)
            present.append(memory_id)
        except MemoryNotFoundError:
            continue  # already gone (an undone import, or an earlier delete)
    return sorted(present)


def erase_kept_for(store: SQLiteMemoryStore, control: ControlStore, scope: MemoryScope, kept: list[str], *,
                   host: str = DESKTOP_HOST, connection_id: str | None = None) -> int:
    """Discard ``kept`` (from :func:`kept_originals`) after their result was deleted; returns how many."""
    if not kept:
        return 0
    return discard_inbox_items(store, control, kept_scope(scope), kept, host=host,
                               connection_id=connection_id).deleted


def discard_inbox_items(store: SQLiteMemoryStore, control: ControlStore, scope: MemoryScope,
                        memory_ids: list[str] | tuple[str, ...], *, host: str = DESKTOP_HOST,
                        connection_id: str | None = None, item_id: int | None = None) -> DiscardResult:
    """Discard now. ``item_id`` carries out an existing proposal instead of recording a new one.

    The items kept for what is discarded go first (see the module notes)."""
    ids = sorted(set(memory_ids))
    if not scope.namespace.endswith(KEPT_SUFFIX):
        erase_kept_for(store, control, scope, kept_originals(store, scope, ids), host=host,
                       connection_id=connection_id)
    if item_id is None:
        item_id = control.open_discard(ids, status=CURATION_CLEANUP_PENDING)
    else:
        control.set_curation_status(item_id, CURATION_CLEANUP_PENDING)
    purged = store.purge(scope, ids)
    control.forget_memories(ids)
    completed = purged.checkpointed and control.checkpoint()
    if completed:
        control.set_curation_status(item_id, CURATION_DISCARDED)
    # Count and space only: the audit log never keeps what a discarded item said.
    control.record(host=host, connection_id=connection_id, action="discard",
                   outcome="discarded" if completed else "cleanup-pending",
                   detail={"count": purged.deleted, "project": scope.project, "item_id": item_id})
    if completed:
        control.checkpoint()
    return DiscardResult(item_id, purged.deleted, completed)


@dataclass(frozen=True, slots=True)
class ForgetResult:
    item_id: int
    deleted: int
    kept: int
    reviews: int
    completed: bool


def forget_memory(store: SQLiteMemoryStore, control: ControlStore, scope: MemoryScope, memory_id: str, *,
                  host: str = DESKTOP_HOST) -> ForgetResult:
    """Forget a curated memory completely (v0.4.4 §7.1): no undo, and only a person asks for it. A retracted memory
    can be forgotten too: its earlier revisions still hold what it said.

    In this order: the inbox items kept for it are discarded first (as a retraction does); the review items about
    it are closed and lose their text; the control file's other text about it goes (:meth:`forget_memories`); the
    memory, every revision, and its search rows are erased like a discard. The erase is recorded as a clean-up
    first, so an interruption, or another process that holds a snapshot, leaves it to
    :func:`finish_pending_cleanups`. The audit entry keeps counts only.
    """
    if is_inbox_namespace(scope.namespace):
        raise PermissionError("inbox items are discarded, not forgotten")
    try:
        history = store.history(scope, memory_id)
        originals = kept_originals(store, scope, [memory_id])
    except MemoryNotFoundError:
        # A retracted memory (owner decision 2026-11-16): its earlier revisions still say what it said. The kept
        # originals come from its last revision before the retraction. Retracting in this version discards them
        # (the app and an approved host request both do), but a memory retracted by an earlier build, or by a
        # direct store write, may still have some. A missing memory raises here before anything changes.
        history = store.retracted_history(scope, memory_id)
        live = [revision for revision in history if revision.kind is not RevisionKind.RETRACTION]
        seeds = _kept_in(dict(live[-1].source.metadata)) if live else []
        originals = _kept_chain(store, scope, [], found=list(dict.fromkeys(seeds)))
    review_ids = sorted({int(revision.source.metadata["review_id"]) for revision in history
                         if type(revision.source.metadata.get("review_id")) is int})
    kept = erase_kept_for(store, control, scope, originals, host=host)
    reviews = control.forget_reviews([memory_id], review_ids=review_ids)
    control.forget_memories([memory_id])
    item_id = control.open_discard([memory_id], status=CURATION_CLEANUP_PENDING)
    erased = store.erase(scope, [memory_id])
    completed = erased.checkpointed and control.checkpoint()
    if completed:
        control.set_curation_status(item_id, CURATION_DISCARDED)
    control.record(host=host, connection_id=None, action="forget",
                   outcome="forgotten" if completed else "cleanup-pending",
                   detail={"count": erased.deleted, "kept": kept, "reviews": reviews, "project": scope.project,
                           "item_id": item_id})
    if completed:
        control.checkpoint()
    return ForgetResult(item_id, erased.deleted, kept, reviews, completed)


def finish_pending_cleanups(store: SQLiteMemoryStore, control: ControlStore) -> int:
    """Retry the checkpoints of discards (and forgotten memories) that were waiting; returns how many are now done."""
    waiting = control.curation_items(statuses=(CURATION_CLEANUP_PENDING,))
    if not waiting:
        return 0
    # A discard or a forget interrupted before its delete (for example the app was closed) is carried out first.
    # Only those two open a clean-up, and a forget is the only one that names a curated memory (ids never change
    # stage), so the namespace decides the path: purge for inbox items, erase for a forgotten memory.
    present = {memory_id: MemoryScope(project, namespace) for memory_id, project, namespace in store.inventory()}
    for item in waiting:
        by_scope: dict[MemoryScope, list[str]] = {}
        for memory_id in item["memory_ids"]:
            if memory_id in present:
                by_scope.setdefault(present[memory_id], []).append(memory_id)
        for scope, ids in by_scope.items():
            if is_inbox_namespace(scope.namespace):
                store.purge(scope, ids)
            else:
                store.erase(scope, ids)
        control.forget_memories(item["memory_ids"])
    if not (store.checkpoint() and control.checkpoint()):
        return 0
    for item in waiting:
        control.set_curation_status(int(item["item_id"]), CURATION_DISCARDED)
    control.checkpoint()
    return len(waiting)


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ExpiryResult:
    proposed: int
    discarded: int
    waiting_cleanup: bool


def run_expiry(store: SQLiteMemoryStore, control: ControlStore, *, now: datetime | None = None) -> ExpiryResult:
    """The daily inbox pass (D7).

    1. Items unused for ``inbox_expire_days`` (last use, or when they were saved) are proposed for discarding,
       due after ``inbox_wait_days``. Items already waiting are left alone.
    2. Proposals the user did not answer by their due time are discarded.
    3. Discards whose final clean-up was blocked earlier are retried.
    """
    now = now or datetime.now(timezone.utc)
    settings = control.inbox_settings()
    usage = control.inbox_usage()
    items = store.inbox_items()
    cutoff = now - timedelta(days=settings["inbox_expire_days"])
    stale = []
    for memory_id, _project, _namespace, created_at in items:
        row = usage.get(memory_id, {})
        last = _parse(row.get("last_used_at")) or _parse(row.get("first_seen")) or _parse(created_at)
        if last is not None and last <= cutoff:
            stale.append(memory_id)
    proposed = 0
    if stale and control.propose_discard(stale, due_at=_stamp(now + timedelta(days=settings["inbox_wait_days"]))):
        proposed = len(stale)
    where = {memory_id: MemoryScope(project, namespace) for memory_id, project, namespace, _ in items}
    discarded = 0
    for item in control.curation_items():
        due = _parse(item.get("due_at"))
        if due is None or due > now:
            continue
        ids = [memory_id for memory_id in item["memory_ids"] if memory_id in where]
        by_scope: dict[MemoryScope, list[str]] = {}
        for memory_id in ids:
            by_scope.setdefault(where[memory_id], []).append(memory_id)
        if not by_scope:
            control.set_curation_status(int(item["item_id"]), CURATION_DISCARDED)
            continue
        for scope, scoped in by_scope.items():
            result = discard_inbox_items(store, control, scope, scoped, item_id=int(item["item_id"]))
            discarded += result.deleted
    finish_pending_cleanups(store, control)
    waiting = bool(control.curation_items(statuses=(CURATION_CLEANUP_PENDING,)))
    return ExpiryResult(proposed, discarded, waiting)


__all__ = ["DISCARD_NOTICE", "ExpiryResult", "run_expiry", "DiscardResult", "discard_inbox_items", "finish_pending_cleanups", "inbox_scope",
           "ForgetResult", "forget_memory"]
