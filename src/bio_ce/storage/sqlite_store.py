# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

"""Transactional SQLite storage for explicit local memory operations."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Iterator, Sequence
from urllib.parse import quote

from bio_ce.core.models import (
    MemoryNotFoundError,
    MemoryRevision,
    MemoryScope,
    RevisionConflictError,
    RevisionKind,
    SearchHit,
    SnapshotChangedError,
    SourceProvenance,
    ValidationError,
    normalize_timestamp,
    utc_now,
    validate_memory_id,
    validate_memory_text,
    validate_revision_id,
)
from bio_ce.retrieval.fts5 import FTS5Retriever


_SCHEMA_VERSION = 1


class SQLiteMemoryStore:
    """An exact-scope, append-only revision store backed by SQLite FTS5.

    Writes are explicit method calls. The package has no agent hook, network
    service, automatic capture, or sharing route.
    """

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = str(path)
        self.read_only = read_only
        if self.path != ":memory:" and not read_only:
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        if read_only:
            if self.path == ":memory:":
                raise ValueError("an in-memory database cannot be opened read-only")
            database_path = Path(self.path).expanduser().resolve()
            if not database_path.is_file():
                raise FileNotFoundError("read-only database does not exist")
            database_uri = f"file:{quote(database_path.as_posix(), safe='/:')}?mode=ro"
        else:
            database_uri = self.path
        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            database_uri,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
            uri=read_only,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA temp_store = MEMORY")
        if not read_only:
            self._connection.execute("PRAGMA synchronous = FULL")
        if self.path != ":memory:" and not read_only:
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._lock:
            current_version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if self.read_only:
                tables = {
                    str(row[0])
                    for row in self._connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                if current_version != _SCHEMA_VERSION or not {
                    "memories", "revisions", "memory_fts"
                }.issubset(tables):
                    raise RuntimeError("read-only database does not contain a supported BIO CE schema")
                return
            if current_version not in (0, _SCHEMA_VERSION):
                raise RuntimeError(f"database schema {current_version} is not supported")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    current_revision_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(memory_id, project, namespace)
                );

                CREATE TABLE IF NOT EXISTS revisions (
                    revision_id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL REFERENCES memories(memory_id),
                    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
                    kind TEXT NOT NULL CHECK (kind IN ('assertion', 'revision', 'retraction')),
                    title TEXT NOT NULL,
                    content TEXT,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    source_metadata_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    valid_from TEXT,
                    valid_until TEXT,
                    previous_revision_id TEXT,
                    UNIQUE(memory_id, revision_number),
                    UNIQUE(revision_id, memory_id),
                    CHECK ((kind = 'retraction' AND content IS NULL)
                        OR (kind IN ('assertion', 'revision') AND content IS NOT NULL))
                );

                CREATE INDEX IF NOT EXISTS revisions_memory_order
                    ON revisions(memory_id, revision_number);

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    memory_id UNINDEXED,
                    revision_id UNINDEXED,
                    project UNINDEXED,
                    namespace UNINDEXED,
                    title,
                    content,
                    tokenize = 'unicode61 remove_diacritics 2'
                );
                """
            )
            self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def add(
        self,
        scope: MemoryScope,
        *,
        title: str,
        content: str,
        source: SourceProvenance,
        memory_id: str | None = None,
        recorded_at: str | datetime | None = None,
        valid_from: str | datetime | None = None,
        valid_until: str | datetime | None = None,
    ) -> MemoryRevision:
        title = validate_memory_text(title, "title", 512)
        content = validate_memory_text(content, "content", 100_000, allow_empty=True)
        resolved_id = validate_memory_id(memory_id or f"mem_{uuid.uuid4().hex}")
        recorded = normalize_timestamp(recorded_at, "recorded_at") or utc_now()
        start = normalize_timestamp(valid_from, "valid_from")
        end = normalize_timestamp(valid_until, "valid_until")
        _validate_interval(start, end)
        if not isinstance(scope, MemoryScope) or not isinstance(source, SourceProvenance):
            raise ValidationError("scope and source must use BIO CE model types")

        values = {
            "memory_id": resolved_id,
            "revision_number": 1,
            "kind": RevisionKind.ASSERTION.value,
            "title": title,
            "content": content,
            "source_type": source.source_type,
            "source_ref": source.source_ref,
            "source_metadata_json": source.to_json(),
            "recorded_at": recorded,
            "valid_from": start,
            "valid_until": end,
            "previous_revision_id": None,
        }
        revision_id = _revision_id(values)
        with self._write_transaction():
            try:
                self._connection.execute(
                    "INSERT INTO memories(memory_id, project, namespace, current_revision_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, NULL, ?, ?)",
                    (resolved_id, scope.project, scope.namespace, recorded, recorded),
                )
            except sqlite3.IntegrityError as exc:
                raise RevisionConflictError("memory_id already exists") from exc
            self._insert_revision(values, scope, revision_id)
            self._connection.execute(
                "UPDATE memories SET current_revision_id = ? WHERE memory_id = ?",
                (revision_id, resolved_id),
            )
            row = self._connection.execute(
                "SELECT * FROM revisions WHERE revision_id = ?", (revision_id,)
            ).fetchone()
        return _row_to_revision(row, scope)

    def revise(
        self,
        scope: MemoryScope,
        memory_id: str,
        *,
        expected_revision_id: str,
        title: str,
        content: str,
        source: SourceProvenance,
        recorded_at: str | datetime | None = None,
        valid_from: str | datetime | None = None,
        valid_until: str | datetime | None = None,
    ) -> MemoryRevision:
        memory_id = validate_memory_id(memory_id)
        expected_revision_id = validate_revision_id(expected_revision_id)
        title = validate_memory_text(title, "title", 512)
        content = validate_memory_text(content, "content", 100_000, allow_empty=True)
        recorded = normalize_timestamp(recorded_at, "recorded_at") or utc_now()
        start = normalize_timestamp(valid_from, "valid_from")
        end = normalize_timestamp(valid_until, "valid_until")
        _validate_interval(start, end)
        if not isinstance(scope, MemoryScope) or not isinstance(source, SourceProvenance):
            raise ValidationError("scope and source must use BIO CE model types")

        with self._write_transaction():
            current = self._current_row(scope, memory_id)
            self._assert_expected_active(current, expected_revision_id)
            values = {
                "memory_id": memory_id,
                "revision_number": int(current["revision_number"]) + 1,
                "kind": RevisionKind.REVISION.value,
                "title": title,
                "content": content,
                "source_type": source.source_type,
                "source_ref": source.source_ref,
                "source_metadata_json": source.to_json(),
                "recorded_at": recorded,
                "valid_from": start,
                "valid_until": end,
                "previous_revision_id": expected_revision_id,
            }
            revision_id = _revision_id(values)
            self._insert_revision(values, scope, revision_id)
            self._connection.execute(
                "UPDATE memories SET current_revision_id = ?, updated_at = ? WHERE memory_id = ?",
                (revision_id, recorded, memory_id),
            )
            row = self._connection.execute(
                "SELECT * FROM revisions WHERE revision_id = ?", (revision_id,)
            ).fetchone()
        return _row_to_revision(row, scope)

    def retract(
        self,
        scope: MemoryScope,
        memory_id: str,
        *,
        expected_revision_id: str,
        source: SourceProvenance,
        recorded_at: str | datetime | None = None,
    ) -> MemoryRevision:
        memory_id = validate_memory_id(memory_id)
        expected_revision_id = validate_revision_id(expected_revision_id)
        recorded = normalize_timestamp(recorded_at, "recorded_at") or utc_now()
        if not isinstance(scope, MemoryScope) or not isinstance(source, SourceProvenance):
            raise ValidationError("scope and source must use BIO CE model types")

        with self._write_transaction():
            current = self._current_row(scope, memory_id)
            self._assert_expected_active(current, expected_revision_id)
            values = {
                "memory_id": memory_id,
                "revision_number": int(current["revision_number"]) + 1,
                "kind": RevisionKind.RETRACTION.value,
                "title": str(current["title"]),
                "content": None,
                "source_type": source.source_type,
                "source_ref": source.source_ref,
                "source_metadata_json": source.to_json(),
                "recorded_at": recorded,
                "valid_from": None,
                "valid_until": None,
                "previous_revision_id": expected_revision_id,
            }
            revision_id = _revision_id(values)
            self._insert_revision(values, scope, revision_id)
            self._connection.execute(
                "UPDATE memories SET current_revision_id = ?, updated_at = ? WHERE memory_id = ?",
                (revision_id, recorded, memory_id),
            )
            row = self._connection.execute(
                "SELECT * FROM revisions WHERE revision_id = ?", (revision_id,)
            ).fetchone()
        return _row_to_revision(row, scope)

    def read(
        self,
        scope: MemoryScope,
        memory_id: str,
        *,
        revision_id: str | None = None,
    ) -> MemoryRevision:
        memory_id = validate_memory_id(memory_id)
        if revision_id is not None:
            revision_id = validate_revision_id(revision_id)
        _validate_scope(scope)
        with self._read_transaction():
            current = self._current_row(scope, memory_id)
            if current["kind"] == RevisionKind.RETRACTION.value:
                raise MemoryNotFoundError("memory is unavailable in the requested scope")
            resolved_revision = revision_id or str(current["revision_id"])
            row = self._connection.execute(
                "SELECT * FROM revisions WHERE memory_id = ? AND revision_id = ?",
                (memory_id, resolved_revision),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("memory is unavailable in the requested scope")
            revision = _row_to_revision(row, scope)
        self._verify_active_snapshot(
            scope,
            ((memory_id, revision.revision_id if revision_id is None else None),),
        )
        return revision

    def history(self, scope: MemoryScope, memory_id: str) -> tuple[MemoryRevision, ...]:
        memory_id = validate_memory_id(memory_id)
        _validate_scope(scope)
        with self._read_transaction():
            current = self._current_row(scope, memory_id)
            if current["kind"] == RevisionKind.RETRACTION.value:
                raise MemoryNotFoundError("memory is unavailable in the requested scope")
            current_revision_id = str(current["revision_id"])
            rows = self._connection.execute(
                "SELECT * FROM revisions WHERE memory_id = ? ORDER BY revision_number ASC",
                (memory_id,),
            ).fetchall()
            history = tuple(_row_to_revision(row, scope) for row in rows)
        self._verify_active_snapshot(scope, ((memory_id, current_revision_id),))
        return history

    def list_current(
        self,
        scope: MemoryScope,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[MemoryRevision, ...]:
        """List current, non-retracted rows in one exact scope.

        Expired and not-yet-valid rows remain visible here so a user can manage
        them. Temporal filtering is reserved for search with an explicit
        ``valid_at`` instant.
        """
        _validate_scope(scope)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("limit must be an integer from 1 to 500")
        if type(offset) is not int or offset < 0:
            raise ValidationError("offset must be a non-negative integer")
        with self._read_transaction():
            rows = self._connection.execute(
                """SELECT r.*
                   FROM memories AS m
                   JOIN revisions AS r ON r.revision_id = m.current_revision_id
                   WHERE m.project = ? AND m.namespace = ?
                     AND r.kind IN ('assertion', 'revision')
                   ORDER BY m.updated_at DESC, m.memory_id COLLATE BINARY ASC
                   LIMIT ? OFFSET ?""",
                (scope.project, scope.namespace, limit, offset),
            ).fetchall()
            revisions = tuple(_row_to_revision(row, scope) for row in rows)
        if revisions:
            self._verify_active_snapshot(
                scope,
                tuple((revision.memory_id, revision.revision_id) for revision in revisions),
            )
        return revisions

    def count_current(self, scope: MemoryScope) -> int:
        """Count current, non-retracted rows in one exact scope."""
        _validate_scope(scope)
        with self._read_transaction():
            row = self._connection.execute(
                """SELECT COUNT(*)
                   FROM memories AS m
                   JOIN revisions AS r ON r.revision_id = m.current_revision_id
                   WHERE m.project = ? AND m.namespace = ?
                     AND r.kind IN ('assertion', 'revision')""",
                (scope.project, scope.namespace),
            ).fetchone()
        return int(row[0])

    def prepare_for_database_replacement(self) -> None:
        """Checkpoint WAL and fail if another connection still holds a snapshot."""
        self._ensure_open()
        if self.read_only:
            raise PermissionError("a read-only store cannot prepare a database replacement")
        with self._lock:
            result = self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result is None or int(result[0]) != 0:
            raise RuntimeError("database is in use; close connected readers and retry")

    def read_many(
        self,
        scope: MemoryScope,
        memory_ids: Sequence[str],
    ) -> tuple[MemoryRevision, ...]:
        """Read 1-100 current memories and reject any snapshot stale at final check.

        The data snapshot is established by the first current-row SELECT.
        A second read transaction validates every selected revision immediately
        before returning. A concurrent revision or retraction committed before
        that final validation fails the whole read closed.
        """
        _validate_scope(scope)
        if isinstance(memory_ids, (str, bytes)) or not isinstance(memory_ids, Sequence):
            raise ValidationError("memory_ids must be a sequence of IDs")
        if not 1 <= len(memory_ids) <= 100:
            raise ValidationError("read_many requires between 1 and 100 memory IDs")
        resolved_ids = tuple(validate_memory_id(memory_id) for memory_id in memory_ids)
        with self._read_transaction():
            revisions: list[MemoryRevision] = []
            for memory_id in resolved_ids:
                current = self._current_row(scope, memory_id)
                if current["kind"] == RevisionKind.RETRACTION.value:
                    raise MemoryNotFoundError("memory is unavailable in the requested scope")
                revisions.append(_row_to_revision(current, scope))
        self._verify_active_snapshot(
            scope,
            tuple((revision.memory_id, revision.revision_id) for revision in revisions),
        )
        return tuple(revisions)

    def search(
        self,
        scope: MemoryScope,
        query: str,
        *,
        limit: int = 10,
        valid_at: str | datetime | None = None,
    ) -> tuple[SearchHit, ...]:
        _validate_scope(scope)
        if not isinstance(query, str) or len(query) > 8192:
            raise ValidationError("query must be text of at most 8192 characters")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValidationError("limit must be an integer from 1 to 50")
        timestamp = normalize_timestamp(valid_at, "valid_at") or utc_now()
        with self._read_transaction():
            hits = FTS5Retriever(self._connection).search(
                scope, query, limit=limit, valid_at=timestamp
            )
        if hits:
            self._verify_active_snapshot(
                scope,
                tuple((hit.memory_id, hit.revision_id) for hit in hits),
            )
        return hits

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "SQLiteMemoryStore":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            if self.read_only:
                raise PermissionError("memory store was opened read-only")
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    @contextmanager
    def _read_transaction(self) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            self._connection.execute("BEGIN")
            try:
                yield
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def _current_row(self, scope: MemoryScope, memory_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            """SELECT r.* FROM memories AS m
               JOIN revisions AS r ON r.revision_id = m.current_revision_id
               WHERE m.memory_id = ? AND m.project = ? AND m.namespace = ?""",
            (memory_id, scope.project, scope.namespace),
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError("memory is unavailable in the requested scope")
        return row

    def _verify_active_snapshot(
        self,
        scope: MemoryScope,
        expected_revisions: Sequence[tuple[str, str | None]],
    ) -> None:
        """Fail closed if selected content changed or became unavailable.

        The first SELECT in this validation transaction is the read operation's
        final freshness linearization point. A write committed before it is
        observed here; a write committed afterward is ordered after this read.
        """
        with self._read_transaction():
            for memory_id, expected_revision_id in expected_revisions:
                try:
                    current = self._current_row(scope, memory_id)
                except MemoryNotFoundError as exc:
                    raise SnapshotChangedError(
                        "memory changed during read; retry the request"
                    ) from exc
                if current["kind"] == RevisionKind.RETRACTION.value:
                    raise SnapshotChangedError(
                        "memory changed during read; retry the request"
                    )
                if (
                    expected_revision_id is not None
                    and str(current["revision_id"]) != expected_revision_id
                ):
                    raise SnapshotChangedError(
                        "memory changed during read; retry the request"
                    )

    def _assert_expected_active(self, current: sqlite3.Row, expected_revision_id: str) -> None:
        if str(current["revision_id"]) != expected_revision_id:
            raise RevisionConflictError("expected revision is stale")
        if current["kind"] == RevisionKind.RETRACTION.value:
            raise MemoryNotFoundError("memory is unavailable in the requested scope")

    def _insert_revision(
        self,
        values: dict[str, object],
        scope: MemoryScope,
        revision_id: str,
    ) -> None:
        self._connection.execute(
            """INSERT INTO revisions(
                   revision_id, memory_id, revision_number, kind, title, content,
                   source_type, source_ref, source_metadata_json, recorded_at,
                   valid_from, valid_until, previous_revision_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                revision_id,
                values["memory_id"],
                values["revision_number"],
                values["kind"],
                values["title"],
                values["content"],
                values["source_type"],
                values["source_ref"],
                values["source_metadata_json"],
                values["recorded_at"],
                values["valid_from"],
                values["valid_until"],
                values["previous_revision_id"],
            ),
        )
        if values["content"] is not None:
            self._connection.execute(
                "INSERT INTO memory_fts(memory_id, revision_id, project, namespace, title, content) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    values["memory_id"], revision_id, scope.project, scope.namespace,
                    values["title"], values["content"],
                ),
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("memory store is closed")


def _validate_scope(scope: MemoryScope) -> None:
    if not isinstance(scope, MemoryScope):
        raise ValidationError("scope must be a MemoryScope")


def _validate_interval(start: str | None, end: str | None) -> None:
    if start is not None and end is not None and end <= start:
        raise ValidationError("valid_until must be later than valid_from")


def _revision_id(values: dict[str, object]) -> str:
    canonical = json.dumps(
        values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "rev_" + hashlib.sha256(canonical).hexdigest()


def _row_to_revision(row: sqlite3.Row, scope: MemoryScope) -> MemoryRevision:
    source = SourceProvenance(
        source_type=str(row["source_type"]),
        source_ref=str(row["source_ref"]),
        metadata=json.loads(row["source_metadata_json"]),
    )
    return MemoryRevision(
        memory_id=str(row["memory_id"]),
        revision_id=str(row["revision_id"]),
        revision_number=int(row["revision_number"]),
        kind=RevisionKind(str(row["kind"])),
        scope=scope,
        title=str(row["title"]),
        content=None if row["content"] is None else str(row["content"]),
        source=source,
        recorded_at=str(row["recorded_at"]),
        valid_from=None if row["valid_from"] is None else str(row["valid_from"]),
        valid_until=None if row["valid_until"] is None else str(row["valid_until"]),
        previous_revision_id=(
            None if row["previous_revision_id"] is None else str(row["previous_revision_id"])
        ),
    )


__all__ = ["SQLiteMemoryStore"]
