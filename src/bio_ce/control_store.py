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
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Any, Iterator, Mapping


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
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version not in (0, 1, _SCHEMA_VERSION):
            raise ControlStoreError("BIO CE control database has an unsupported version.")
        # Every statement is idempotent, so concurrent first opens are safe.
        self._connection.executescript(_SCHEMA)
        with self._write():
            # v1 grants predate scope binding; the desktop app only ever granted the personal scope.
            existing = {row["name"] for row in self._connection.execute("PRAGMA table_info(connections)")}
            for column, definition in _SCOPE_COLUMNS:
                if column not in existing:
                    self._connection.execute(f"ALTER TABLE connections ADD COLUMN {column} {definition}")
            self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

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
