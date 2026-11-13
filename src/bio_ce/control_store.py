# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Connection grants, AI write audit log, and the review queue.

This lives in its own SQLite file beside the memory database so the memory
schema (and v0.2 databases, backups, and restore) stays unchanged. Each AI host
connection holds a random token; only its SHA-256 hash is stored here. The MCP
server re-reads the grant on every call, so a mode change or revocation in the
desktop app applies to connections that are already running.

Each grant is bound to exactly one memory scope (project and namespace) when
it is created. Servers and hooks take their scope from the authenticated grant;
a scope string supplied by a host never widens what a connection can reach.

Trust boundary: any program running as the same Windows user can read the
host configuration that contains the token and can open these files directly.
The grant protects against an AI host doing more than the user allowed through
BIO CE's tools; it is not protection against local malware.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Any, Iterator, Mapping
from urllib.parse import quote


MODE_READ_ONLY = "read_only"
MODE_AUTO_MEMORY = "auto_memory"
MODE_PAUSED = "paused"
MODES = (MODE_READ_ONLY, MODE_AUTO_MEMORY, MODE_PAUSED)
MODE_LABELS = {
    MODE_READ_ONLY: "Read only",
    MODE_AUTO_MEMORY: "Auto memory",
    MODE_PAUSED: "Paused",
}

DEFAULT_PROJECT = "bio-ce-personal"
DEFAULT_NAMESPACE = "default"

REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_FAILED = "failed"

_SCHEMA_VERSION = 2
_SCOPE_COLUMNS = (
    ("project", f"TEXT NOT NULL DEFAULT '{DEFAULT_PROJECT}'"),
    ("namespace", f"TEXT NOT NULL DEFAULT '{DEFAULT_NAMESPACE}'"),
)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    connection_id TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    token_sha256 TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('read_only', 'auto_memory', 'paused')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    connection_id TEXT,
    host TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    memory_id TEXT,
    revision_id TEXT,
    title TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS audit_log_recent ON audit_log (recorded_at DESC);
CREATE TABLE IF NOT EXISTS review_queue (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    connection_id TEXT,
    host TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('create', 'update', 'retract')),
    memory_id TEXT,
    expected_revision_id TEXT,
    title TEXT NOT NULL,
    content TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    review_reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'failed')),
    resolved_at TEXT,
    resolution TEXT
);
CREATE INDEX IF NOT EXISTS review_queue_status ON review_queue (status, created_at);
"""
# v0.4.2 tables. Added at the same user_version: v0.4.0 and v0.4.1 only run CREATE TABLE IF NOT EXISTS for
# their own tables and ignore these, so a rollback keeps working.
_SCHEMA_V042 = """
CREATE TABLE IF NOT EXISTS spaces (
    space_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('general', 'project')),
    project TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS space_folders (
    space_id TEXT NOT NULL,
    folder_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (space_id, folder_key)
);
CREATE TABLE IF NOT EXISTS connection_spaces (
    connection_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    can_read INTEGER NOT NULL DEFAULT 1,
    can_write INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (connection_id, space_id)
);
CREATE TABLE IF NOT EXISTS connection_settings (
    connection_id TEXT PRIMARY KEY,
    save_mode TEXT NOT NULL DEFAULT 'curated' CHECK (save_mode IN ('curated', 'collect')),
    default_space_id TEXT NOT NULL DEFAULT 'general',
    all_projects INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox_usage (
    memory_id TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_used_at TEXT,
    hit_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS curation_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('discard')),
    memory_ids_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'kept', 'cleanup_pending', 'discarded', 'failed')),
    decided_at TEXT,
    due_at TEXT
);
CREATE INDEX IF NOT EXISTS curation_items_status ON curation_items (status, due_at);
"""
GENERAL_SPACE_ID = "general"
PRE_UPGRADE_SNAPSHOT = "control.before-0.4.2.sqlite3"
CURATION_PENDING = "pending"
CURATION_KEPT = "kept"
CURATION_CLEANUP_PENDING = "cleanup_pending"
CURATION_DISCARDED = "discarded"
CURATION_FAILED = "failed"
RESTORE_KEEP_DAYS = 7


class ControlStoreError(RuntimeError):
    """The control database could not be used safely."""


class AccessDenied(ControlStoreError):
    """The caller's connection is unknown, revoked, paused, or lacks permission."""


@dataclass(frozen=True, slots=True)
class Grant:
    connection_id: str
    host: str
    mode: str
    created_at: str
    updated_at: str
    revoked_at: str | None
    project: str = DEFAULT_PROJECT
    namespace: str = DEFAULT_NAMESPACE

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    @property
    def can_read(self) -> bool:
        return self.active and self.mode in (MODE_READ_ONLY, MODE_AUTO_MEMORY)

    @property
    def can_write(self) -> bool:
        return self.active and self.mode == MODE_AUTO_MEMORY


@dataclass(frozen=True, slots=True)
class AuditEntry:
    entry_id: int
    recorded_at: str
    connection_id: str | None
    host: str
    action: str
    outcome: str
    memory_id: str | None
    revision_id: str | None
    title: str | None
    detail: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ReviewItem:
    review_id: int
    created_at: str
    connection_id: str | None
    host: str
    kind: str
    memory_id: str | None
    expected_revision_id: str | None
    title: str
    content: str | None
    metadata: Mapping[str, Any]
    review_reason: str
    status: str
    resolved_at: str | None
    resolution: str | None


def control_database_for(memory_database: str | Path) -> Path:
    """The control file sits beside the memory database it governs."""
    path = Path(memory_database).expanduser().resolve()
    return path.with_name("control.sqlite3")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ControlStore:
    """Small SQLite store shared by the desktop app, MCP servers, and hooks."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.path), timeout=5.0, isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        # Deleted rows (for example titles of discarded inbox items) are overwritten, not just unlinked.
        self._connection.execute("PRAGMA secure_delete = ON")
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version not in (0, 1, _SCHEMA_VERSION):
            raise ControlStoreError("BIO CE control database has an unsupported version.")
        self._snapshot_before_upgrade()
        # Every statement is idempotent, so concurrent first opens are safe.
        self._connection.executescript(_SCHEMA)
        self._connection.executescript(_SCHEMA_V042)
        with self._write():
            self._connection.execute(
                "INSERT OR IGNORE INTO spaces (space_id, kind, project, display_name, created_at) "
                "VALUES (?, 'general', ?, 'General', ?)",
                (GENERAL_SPACE_ID, DEFAULT_PROJECT, _now()),
            )
            # v1 grants predate scope binding; the desktop app only ever granted the personal scope.
            existing = {row["name"] for row in self._connection.execute("PRAGMA table_info(connections)")}
            for column, definition in _SCOPE_COLUMNS:
                if column not in existing:
                    self._connection.execute(f"ALTER TABLE connections ADD COLUMN {column} {definition}")
            self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _snapshot_before_upgrade(self) -> None:
        """Copy an existing pre-0.4.2 control file once, before the v0.4.2 tables are added."""
        tables = {row[0] for row in self._connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "connections" not in tables or "spaces" in tables:
            return
        target = self.path.with_name(PRE_UPGRADE_SNAPSHOT)
        if target.exists():
            return
        temporary = self.path.with_name(f".{PRE_UPGRADE_SNAPSHOT}.{secrets.token_hex(4)}.tmp")
        try:
            destination = sqlite3.connect(str(temporary))
            try:
                self._connection.backup(destination)
                destination.execute("PRAGMA journal_mode = DELETE")
            finally:
                destination.close()
            os.rename(temporary, target)  # refuses an existing file: another process made it first
        except (OSError, sqlite3.Error):
            pass  # the snapshot is a safety copy; the upgrade itself only adds tables
        finally:
            temporary.unlink(missing_ok=True)

    def checkpoint(self) -> bool:
        """Fold the write-ahead log into the file and empty it; False while another process holds a snapshot."""
        with self._lock:
            row = self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return row is not None and int(row[0]) == 0

    def __enter__(self) -> "ControlStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextmanager
    def _write(self) -> Iterator[None]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    # Grants ---------------------------------------------------------------

    def create_grant(
        self,
        host: str,
        *,
        mode: str = MODE_READ_ONLY,
        project: str = DEFAULT_PROJECT,
        namespace: str = DEFAULT_NAMESPACE,
    ) -> tuple[Grant, str]:
        """Create a connection bound to one scope and return it with its one-time plaintext token."""
        _validate_mode(mode)
        if not project or not namespace:
            raise ValueError("a connection must be bound to a project and namespace")
        connection_id = f"conn_{secrets.token_hex(8)}"
        token = secrets.token_urlsafe(32)
        while token.startswith("-"):  # tokens travel as command-line values in host hook settings
            token = secrets.token_urlsafe(32)
        stamp = _now()
        with self._write():
            self._connection.execute(
                "INSERT INTO connections (connection_id, host, token_sha256, mode, created_at, updated_at, "
                "revoked_at, project, namespace) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (connection_id, host, hash_token(token), mode, stamp, stamp, project, namespace),
            )
        return self.grant(connection_id), token

    def grant(self, connection_id: str) -> Grant:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM connections WHERE connection_id = ?", (connection_id,)
            ).fetchone()
        if row is None:
            raise AccessDenied("This BIO CE connection is unknown. Reconnect the host in BIO CE.")
        return _grant(row)

    def authenticate(self, connection_id: str, token: str) -> Grant:
        """Verify a token without revealing whether the connection exists."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM connections WHERE connection_id = ?", (connection_id,)
            ).fetchone()
        expected = row["token_sha256"] if row is not None else hash_token(secrets.token_hex(16))
        if not hmac.compare_digest(expected, hash_token(token or "")) or row is None:
            raise AccessDenied("BIO CE rejected this connection's credentials.")
        grant = _grant(row)
        if not grant.active:
            raise AccessDenied("Access for this connection was revoked in BIO CE.")
        return grant

    def grants(self, *, include_revoked: bool = False) -> tuple[Grant, ...]:
        query = "SELECT * FROM connections"
        if not include_revoked:
            query += " WHERE revoked_at IS NULL"
        with self._lock:
            rows = self._connection.execute(query + " ORDER BY created_at").fetchall()
        return tuple(_grant(row) for row in rows)

    def active_grant_for(self, host: str) -> Grant | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM connections WHERE host = ? AND revoked_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1",
                (host,),
            ).fetchone()
        return _grant(row) if row is not None else None

    def set_mode(self, connection_id: str, mode: str) -> Grant:
        _validate_mode(mode)
        with self._write():
            changed = self._connection.execute(
                "UPDATE connections SET mode = ?, updated_at = ? "
                "WHERE connection_id = ? AND revoked_at IS NULL",
                (mode, _now(), connection_id),
            ).rowcount
        if not changed:
            raise AccessDenied("That connection no longer exists or was revoked.")
        return self.grant(connection_id)

    def revoke(self, connection_id: str) -> None:
        stamp = _now()
        with self._write():
            self._connection.execute(
                "UPDATE connections SET revoked_at = COALESCE(revoked_at, ?), updated_at = ? "
                "WHERE connection_id = ?",
                (stamp, stamp, connection_id),
            )

    def pause_all(self) -> int:
        with self._write():
            return self._connection.execute(
                "UPDATE connections SET mode = 'paused', updated_at = ? WHERE revoked_at IS NULL",
                (_now(),),
            ).rowcount

    # Audit ------------------------------------------------------------------

    def record(
        self,
        *,
        host: str,
        connection_id: str | None,
        action: str,
        outcome: str,
        memory_id: str | None = None,
        revision_id: str | None = None,
        title: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        payload = json.dumps(dict(detail or {}), ensure_ascii=False, sort_keys=True)
        with self._write():
            self._connection.execute(
                "INSERT INTO audit_log (recorded_at, connection_id, host, action, outcome, memory_id, "
                "revision_id, title, detail_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_now(), connection_id, host, action, outcome, memory_id, revision_id, title, payload),
            )

    def recent_activity(self, *, limit: int = 50) -> tuple[AuditEntry, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_log ORDER BY entry_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return tuple(_audit(row) for row in rows)

    def writes_since(self, connection_id: str, since: timedelta) -> int:
        """Count write attempts that changed or queued something, for rate limiting."""
        cutoff = (datetime.now(timezone.utc) - since).isoformat(timespec="microseconds").replace("+00:00", "Z")
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM audit_log WHERE connection_id = ? AND recorded_at >= ? "
                "AND outcome IN ('created', 'updated', 'queued')",
                (connection_id, cutoff),
            ).fetchone()
        return int(row[0])

    # Review queue -----------------------------------------------------------

    def enqueue_review(
        self,
        *,
        host: str,
        connection_id: str | None,
        kind: str,
        title: str,
        content: str | None,
        review_reason: str,
        memory_id: str | None = None,
        expected_revision_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> int:
        payload = json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True)
        with self._write():
            cursor = self._connection.execute(
                "INSERT INTO review_queue (created_at, connection_id, host, kind, memory_id, "
                "expected_revision_id, title, content, metadata_json, review_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_now(), connection_id, host, kind, memory_id, expected_revision_id, title, content,
                 payload, review_reason),
            )
            return int(cursor.lastrowid)

    def pending_reviews_like(
        self, *, kind: str, memory_id: str | None, expected_revision_id: str | None
    ) -> tuple[ReviewItem, ...]:
        """Pending items of the same kind for the same memory revision (or new memories when IDs are None)."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM review_queue WHERE status = 'pending' AND kind = ? AND memory_id IS ? "
                "AND expected_revision_id IS ? ORDER BY review_id",
                (kind, memory_id, expected_revision_id),
            ).fetchall()
        return tuple(_review(row) for row in rows)

    def reviews(self, *, status: str | None = REVIEW_PENDING, limit: int = 100) -> tuple[ReviewItem, ...]:
        query, values = "SELECT * FROM review_queue", []
        if status is not None:
            query += " WHERE status = ?"
            values.append(status)
        query += " ORDER BY review_id DESC LIMIT ?"
        values.append(limit)
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
        return tuple(_review(row) for row in rows)

    def review(self, review_id: int) -> ReviewItem:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM review_queue WHERE review_id = ?", (review_id,)
            ).fetchone()
        if row is None:
            raise ControlStoreError("That review item no longer exists.")
        return _review(row)

    def pending_review_count(self) -> int:
        with self._lock:
            return int(self._connection.execute(
                "SELECT COUNT(*) FROM review_queue WHERE status = 'pending'"
            ).fetchone()[0])

    def resolve_review(self, review_id: int, status: str, resolution: str) -> None:
        if status not in (REVIEW_APPROVED, REVIEW_REJECTED, REVIEW_FAILED):
            raise ValueError("invalid review status")
        with self._write():
            changed = self._connection.execute(
                "UPDATE review_queue SET status = ?, resolved_at = ?, resolution = ? "
                "WHERE review_id = ? AND status = 'pending'",
                (status, _now(), resolution, review_id),
            ).rowcount
        if not changed:
            raise ControlStoreError("That review item was already handled.")

    # Inbox clean-up ---------------------------------------------------------

    def open_discard(self, memory_ids: list[str] | tuple[str, ...], *, status: str = CURATION_CLEANUP_PENDING,
                     due_at: str | None = None) -> int:
        """Record a discard: a proposal waiting for the user (pending) or one being carried out."""
        if status not in (CURATION_PENDING, CURATION_CLEANUP_PENDING):
            raise ValueError("a new discard is either pending or being cleaned up")
        with self._write():
            cursor = self._connection.execute(
                "INSERT INTO curation_items (created_at, action, memory_ids_json, status, due_at) "
                "VALUES (?, 'discard', ?, ?, ?)",
                (_now(), json.dumps(sorted(set(memory_ids))), status, due_at),
            )
            return int(cursor.lastrowid)

    def set_curation_status(self, item_id: int, status: str) -> None:
        with self._write():
            self._connection.execute(
                "UPDATE curation_items SET status = ?, decided_at = ? WHERE item_id = ?", (status, _now(), item_id)
            )

    def curation_items(self, *, statuses: tuple[str, ...] = (CURATION_PENDING,)) -> tuple[dict[str, Any], ...]:
        marks = ", ".join("?" for _ in statuses)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM curation_items WHERE status IN ({marks}) ORDER BY item_id", statuses
            ).fetchall()
        return tuple({**dict(row), "memory_ids": json.loads(row["memory_ids_json"])} for row in rows)

    def forget_memories(self, memory_ids: list[str] | tuple[str, ...]) -> None:
        """Drop every text this file keeps about discarded inbox items: audit titles and details, usage rows.

        The audit rows themselves stay (with their outcome and time) so the history of changes stays complete.
        """
        ids = sorted(set(memory_ids))
        if not ids:
            return
        marks = ", ".join("?" for _ in ids)
        with self._write():
            self._connection.execute(
                f"UPDATE audit_log SET title = NULL, detail_json = '{{\"discarded\": true}}' "
                f"WHERE memory_id IN ({marks})", ids)
            self._connection.execute(f"DELETE FROM inbox_usage WHERE memory_id IN ({marks})", ids)

    # Restore ----------------------------------------------------------------

    def apply_restore(self, *, memories: list[tuple[str, str, str]], backup_control: Path | None,
                      pair_status: str) -> dict[str, Any]:
        """Bring this control file in line with a memory database that was just restored.

        ``memories`` lists (memory_id, project, namespace) of the restored database. Connections, permissions,
        and the audit log always stay as they are now: a backup must never bring back a revoked connection or a
        wider permission. From a matching pair file, spaces and folder links are merged (current rows win) and
        inbox usage and pending discards come back for the restored inbox items, with a fresh waiting period.
        """
        restored = {memory_id for memory_id, _project, _namespace in memories}
        inbox = {memory_id for memory_id, _project, namespace in memories if namespace.endswith(".inbox")}
        backup_rows: dict[str, list[sqlite3.Row]] = {}
        if backup_control is not None:
            backup_rows = _read_backup_tables(backup_control)
        now = datetime.now(timezone.utc)
        stamp = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
        keep_until = (now + timedelta(days=RESTORE_KEEP_DAYS)).isoformat(timespec="microseconds").replace(
            "+00:00", "Z")
        spaces_added: list[str] = []
        with self._write():
            for row in backup_rows.get("spaces", ()):
                if self._connection.execute(
                    "INSERT OR IGNORE INTO spaces (space_id, kind, project, display_name, created_at, archived_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (row["space_id"], row["kind"], row["project"], row["display_name"], row["created_at"],
                     row["archived_at"]),
                ).rowcount:
                    spaces_added.append(row["project"])
            known_spaces = {row[0] for row in self._connection.execute("SELECT space_id FROM spaces")}
            for row in backup_rows.get("space_folders", ()):
                if row["space_id"] in known_spaces:
                    self._connection.execute(
                        "INSERT OR IGNORE INTO space_folders (space_id, folder_key, label, created_at) "
                        "VALUES (?, ?, ?, ?)", (row["space_id"], row["folder_key"], row["label"], row["created_at"]))
            for row in backup_rows.get("inbox_usage", ()):
                if row["memory_id"] in inbox:
                    self._connection.execute(
                        "INSERT OR REPLACE INTO inbox_usage (memory_id, first_seen, last_used_at, hit_count) "
                        "VALUES (?, ?, ?, ?)", (row["memory_id"], row["first_seen"], row["last_used_at"],
                                                row["hit_count"]))
            restored_discards = 0
            for row in backup_rows.get("curation_items", ()):
                if row["status"] != CURATION_PENDING:
                    continue
                wanted = [memory_id for memory_id in json.loads(row["memory_ids_json"]) if memory_id in inbox]
                if wanted:
                    self._connection.execute(
                        "INSERT INTO curation_items (created_at, action, memory_ids_json, status, due_at) "
                        "VALUES (?, ?, ?, 'pending', ?)", (row["created_at"], row["action"], json.dumps(wanted),
                                                           keep_until))
                    restored_discards += 1
            # Project spaces the restored memories use but this file does not know get a visible placeholder name.
            projects = {project for _memory_id, project, _namespace in memories if project.startswith("project:")}
            have = {row[0] for row in self._connection.execute("SELECT project FROM spaces")}
            for project in sorted(projects - have):
                slug = project.split(":", 1)[1]
                self._connection.execute(
                    "INSERT INTO spaces (space_id, kind, project, display_name, created_at) "
                    "VALUES (?, 'project', ?, ?, ?)", (secrets.token_hex(8), project, f"Restored: {slug}", stamp))
                spaces_added.append(project)
            # Work that pointed at memories the restore removed can no longer be carried out.
            failed_reviews = 0
            for row in self._connection.execute(
                "SELECT review_id, memory_id FROM review_queue WHERE status = 'pending' AND memory_id IS NOT NULL"
            ).fetchall():
                if row["memory_id"] not in restored:
                    self._connection.execute(
                        "UPDATE review_queue SET status = 'failed', resolved_at = ?, resolution = ? "
                        "WHERE review_id = ?", (stamp, "the memory is not in the restored backup", row["review_id"]))
                    failed_reviews += 1
            for row in self._connection.execute(
                "SELECT item_id, memory_ids_json FROM curation_items WHERE status IN ('pending', 'cleanup_pending')"
            ).fetchall():
                if not set(json.loads(row["memory_ids_json"])) & restored:
                    self._connection.execute(
                        "UPDATE curation_items SET status = 'failed', decided_at = ? WHERE item_id = ?",
                        (stamp, row["item_id"]))
            gone = [row[0] for row in self._connection.execute("SELECT memory_id FROM inbox_usage")
                    if row[0] not in inbox]
            for memory_id in gone:
                self._connection.execute("DELETE FROM inbox_usage WHERE memory_id = ?", (memory_id,))
            summary = {"pair": pair_status, "spaces_added": len(spaces_added), "reviews_failed": failed_reviews,
                       "discards_restored": restored_discards}
            self._connection.execute(
                "INSERT INTO audit_log (recorded_at, connection_id, host, action, outcome, detail_json) "
                "VALUES (?, NULL, 'bio-ce-desktop', 'restore', 'restored', ?)",
                (stamp, json.dumps(summary, sort_keys=True)))
        return {**summary, "restored_spaces": spaces_added}


def _read_backup_tables(path: Path) -> dict[str, list[sqlite3.Row]]:
    uri = f"file:{quote(Path(path).resolve().as_posix(), safe='/:')}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return {name: connection.execute(f"SELECT * FROM {name}").fetchall()
                for name in ("spaces", "space_folders", "inbox_usage", "curation_items") if name in tables}
    finally:
        connection.close()


def _validate_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")


def _grant(row: sqlite3.Row) -> Grant:
    return Grant(row["connection_id"], row["host"], row["mode"], row["created_at"], row["updated_at"],
                 row["revoked_at"], row["project"], row["namespace"])


def _audit(row: sqlite3.Row) -> AuditEntry:
    return AuditEntry(row["entry_id"], row["recorded_at"], row["connection_id"], row["host"], row["action"],
                      row["outcome"], row["memory_id"], row["revision_id"], row["title"],
                      json.loads(row["detail_json"] or "{}"))


def _review(row: sqlite3.Row) -> ReviewItem:
    return ReviewItem(row["review_id"], row["created_at"], row["connection_id"], row["host"], row["kind"],
                      row["memory_id"], row["expected_revision_id"], row["title"], row["content"],
                      json.loads(row["metadata_json"] or "{}"), row["review_reason"], row["status"],
                      row["resolved_at"], row["resolution"])


__all__ = [
    "AccessDenied",
    "PRE_UPGRADE_SNAPSHOT",
    "GENERAL_SPACE_ID",
    "CURATION_PENDING",
    "CURATION_KEPT",
    "CURATION_FAILED",
    "CURATION_DISCARDED",
    "CURATION_CLEANUP_PENDING",
    "AuditEntry",
    "ControlStore",
    "ControlStoreError",
    "DEFAULT_NAMESPACE",
    "DEFAULT_PROJECT",
    "Grant",
    "MODES",
    "MODE_AUTO_MEMORY",
    "MODE_LABELS",
    "MODE_PAUSED",
    "MODE_READ_ONLY",
    "REVIEW_APPROVED",
    "REVIEW_FAILED",
    "REVIEW_PENDING",
    "REVIEW_REJECTED",
    "ReviewItem",
    "control_database_for",
    "hash_token",
]
