# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Discarding inbox items.

Inbox items are the only memories BIO CE deletes physically; curated memories are retracted and keep their
history. A discard removes the item's rows with secure_delete on, merges the search index, removes what the
control file kept about it (audit titles and details, usage rows), and empties both write-ahead logs. It is
recorded as done only after both checkpoints succeed; while another process holds an older snapshot (a
connected MCP server, which lets go after a minute without calls), the discard waits as "cleanup pending" and
:func:`finish_pending_cleanups` completes it later.

This removes the items from BIO CE's files as far as the app can. It cannot guarantee erasure from the drive
itself (SSD wear leveling, the Windows page file, file system journals), and backups made earlier still contain
the items.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bio_ce.control_store import (
    CURATION_CLEANUP_PENDING,
    CURATION_DISCARDED,
    ControlStore,
)
from bio_ce.core.models import MemoryScope
from bio_ce.storage.sqlite_store import INBOX_SUFFIX, SQLiteMemoryStore


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


def discard_inbox_items(store: SQLiteMemoryStore, control: ControlStore, scope: MemoryScope,
                        memory_ids: list[str] | tuple[str, ...], *, host: str = DESKTOP_HOST,
                        connection_id: str | None = None, item_id: int | None = None) -> DiscardResult:
    """Discard now. ``item_id`` carries out an existing proposal instead of recording a new one."""
    ids = sorted(set(memory_ids))
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


def finish_pending_cleanups(store: SQLiteMemoryStore, control: ControlStore) -> int:
    """Retry the checkpoints of discards that were waiting; returns how many are now done."""
    waiting = control.curation_items(statuses=(CURATION_CLEANUP_PENDING,))
    if not waiting:
        return 0
    # A discard interrupted before its delete (for example the app was closed) is carried out first.
    present = {memory_id: MemoryScope(project, namespace) for memory_id, project, namespace in store.inventory()
               if namespace.endswith(INBOX_SUFFIX)}
    for item in waiting:
        by_scope: dict[MemoryScope, list[str]] = {}
        for memory_id in item["memory_ids"]:
            if memory_id in present:
                by_scope.setdefault(present[memory_id], []).append(memory_id)
        for scope, ids in by_scope.items():
            store.purge(scope, ids)
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


__all__ = ["DISCARD_NOTICE", "ExpiryResult", "run_expiry", "DiscardResult", "discard_inbox_items", "finish_pending_cleanups", "inbox_scope"]
