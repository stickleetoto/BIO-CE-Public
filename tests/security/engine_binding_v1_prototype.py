# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""TEST-ONLY prototype of the proposed ``engine_binding_v1`` extension. NOT product code.

BIO CE does not apply this extension; the product's ``ControlStore`` is unchanged.
This module exists so the safety claims of the design can be tested on
temporary copies before anyone approves a real migration:

* the extension is additive and keeps ``control.sqlite3`` at ``user_version`` 2,
  so the released ``ControlStore`` still opens it;
* a grant bound to a non-Community engine stores ``e1:``-prefixed token hashes,
  which the released ``ControlStore`` can never authenticate;
* every check reads the persisted engine state, so separate MCP and hook
  processes see a switch;
* a writer fence lives in the engine's own memory database and is checked
  inside the writer's ``BEGIN IMMEDIATE`` transaction, so no stale writer can
  commit after the fence (no check-then-commit gap).
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
import uuid


EXTENSION = "engine_binding_v1"
CORE_HASH_PREFIX = "e1:"
LEASE_TTL = timedelta(seconds=15)
_TABLES = (
    "CREATE TABLE IF NOT EXISTS control_extensions ("
    " name TEXT PRIMARY KEY, version INTEGER NOT NULL, applied_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS engine_state ("
    " id INTEGER PRIMARY KEY CHECK (id = 1), active_engine_id TEXT, generation INTEGER NOT NULL,"
    " phase TEXT NOT NULL, target_engine_id TEXT, message TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS writer_leases ("
    " lease_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, engine_id TEXT NOT NULL,"
    " generation INTEGER NOT NULL, acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL)",
)


class StaleBinding(RuntimeError):
    """The grant's engine or generation is not the active one."""


class Fenced(RuntimeError):
    """The writer's generation is older than the engine's write fence."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=10.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def token_hash(token: str, engine_id: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return digest if engine_id == "community" else CORE_HASH_PREFIX + digest


# Migration -----------------------------------------------------------------------------------------

def migrate(control_path: Path) -> Path:
    """Apply the extension idempotently; returns the pre-migration backup path."""
    control_path = Path(control_path)
    backup = control_path.with_name(f"{control_path.name}.pre-{EXTENSION}-{uuid.uuid4().hex[:8]}.bak")
    with closing(_connect(control_path)) as source, closing(sqlite3.connect(str(backup))) as target:
        source.backup(target)
    with closing(_connect(control_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            if int(connection.execute("PRAGMA user_version").fetchone()[0]) != 2:
                raise RuntimeError("only a version 2 control database is extended")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(connections)")}
            if "engine_id" not in columns:
                connection.execute("ALTER TABLE connections ADD COLUMN engine_id TEXT NOT NULL DEFAULT 'community'")
            if "binding_generation" not in columns:
                connection.execute("ALTER TABLE connections ADD COLUMN binding_generation INTEGER NOT NULL DEFAULT 0")
            # One execute() per statement: executescript() would COMMIT the open transaction first.
            for statement in _TABLES:
                connection.execute(statement)
            connection.execute("INSERT OR IGNORE INTO engine_state VALUES (1, 'community', 0, 'active', NULL, '', ?)",
                               (_stamp(),))
            connection.execute("INSERT OR IGNORE INTO control_extensions VALUES (?, 1, ?)", (EXTENSION, _stamp()))
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return backup


def ensure_fence(memory_path: Path) -> None:
    """The write fence lives in the engine's own database (memories.sqlite3 for Community)."""
    with closing(_connect(memory_path)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS engine_write_fence "
                           "(id INTEGER PRIMARY KEY CHECK (id = 1), generation INTEGER NOT NULL)")
        connection.execute("INSERT OR IGNORE INTO engine_write_fence VALUES (1, 0)")


# Grants and engine state ------------------------------------------------------------------------------

def create_bound_grant(control_path: Path, host: str, engine_id: str, generation: int) -> tuple[str, str]:
    connection_id = f"conn_{secrets.token_hex(8)}"
    token = secrets.token_urlsafe(32)
    stamp = _stamp()
    with closing(_connect(control_path)) as connection:
        connection.execute(
            "INSERT INTO connections (connection_id, host, token_sha256, mode, created_at, updated_at, revoked_at, "
            "project, namespace, engine_id, binding_generation) VALUES (?, ?, ?, 'read_only', ?, ?, NULL, "
            "'bio-ce-personal', 'default', ?, ?)",
            (connection_id, host, token_hash(token, engine_id), stamp, stamp, engine_id, generation))
    return connection_id, token


def engine_state(control_path: Path) -> sqlite3.Row:
    with closing(_connect(control_path)) as connection:
        return connection.execute("SELECT * FROM engine_state WHERE id = 1").fetchone()


def set_phase(control_path: Path, phase: str, *, engine_id: str | None, bump: bool = False) -> int:
    with closing(_connect(control_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if bump:
            connection.execute("UPDATE engine_state SET generation = generation + 1 WHERE id = 1")
        connection.execute("UPDATE engine_state SET phase = ?, active_engine_id = ?, updated_at = ? WHERE id = 1",
                           (phase, engine_id, _stamp()))
        generation = int(connection.execute("SELECT generation FROM engine_state WHERE id = 1").fetchone()[0])
        connection.execute("COMMIT")
    return generation


def recover_on_start(control_path: Path) -> sqlite3.Row:
    """An unfinished switch found at start-up always ends disconnected, with a new generation."""
    state = engine_state(control_path)
    if state["phase"] not in ("active", "safe_disconnected"):
        set_phase(control_path, "safe_disconnected", engine_id=None, bump=True)
    return engine_state(control_path)


def check_binding(control_path: Path, connection_id: str, token: str) -> sqlite3.Row:
    """What every MCP call and hook would do: authenticate and compare with the persisted engine state."""
    with closing(_connect(control_path)) as connection:
        grant = connection.execute("SELECT * FROM connections WHERE connection_id = ?", (connection_id,)).fetchone()
        state = connection.execute("SELECT * FROM engine_state WHERE id = 1").fetchone()
    if grant is None or grant["revoked_at"] is not None:
        raise StaleBinding("unknown or revoked connection")
    if not hmac.compare_digest(grant["token_sha256"], token_hash(token, grant["engine_id"])):
        raise StaleBinding("bad credentials")
    if (state["phase"] != "active" or grant["engine_id"] != state["active_engine_id"]
            or int(grant["binding_generation"]) != int(state["generation"])):
        raise StaleBinding("this connection is bound to an engine generation that is no longer active")
    return grant


# Writer fence -----------------------------------------------------------------------------------------

def raise_fence(memory_path: Path, generation: int) -> None:
    """Commit the new generation into the engine DB. Every write ordered after this commit is refused."""
    with closing(_connect(memory_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")  # waits for an in-flight writer to commit or roll back
        connection.execute("UPDATE engine_write_fence SET generation = MAX(generation, ?) WHERE id = 1",
                           (generation,))
        connection.execute("COMMIT")


def fenced_write(memory_path: Path, generation: int, statement: str, values: tuple, *, before_commit=None) -> None:
    """Run one write inside ``BEGIN IMMEDIATE`` only if ``generation`` is not older than the fence."""
    with closing(_connect(memory_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            fence = int(connection.execute("SELECT generation FROM engine_write_fence WHERE id = 1").fetchone()[0])
            if generation < fence:
                raise Fenced(f"writer generation {generation} is older than fence {fence}")
            connection.execute(statement, values)
            if before_commit is not None:
                before_commit()
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


# Leases (track in-flight writers so the switch can wait for them) ------------------------------------

def acquire_lease(control_path: Path, connection_id: str, engine_id: str, generation: int,
                  *, ttl: timedelta = LEASE_TTL) -> str:
    lease_id = uuid.uuid4().hex
    with closing(_connect(control_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        state = connection.execute("SELECT * FROM engine_state WHERE id = 1").fetchone()
        if state["phase"] != "active" or int(state["generation"]) != generation:
            connection.execute("ROLLBACK")
            raise StaleBinding("no new writes during or after a switch")
        connection.execute("INSERT INTO writer_leases VALUES (?, ?, ?, ?, ?, ?)",
                           (lease_id, connection_id, engine_id, generation, _stamp(), _stamp(_now() + ttl)))
        connection.execute("COMMIT")
    return lease_id


def release_lease(control_path: Path, lease_id: str) -> None:
    with closing(_connect(control_path)) as connection:
        connection.execute("DELETE FROM writer_leases WHERE lease_id = ?", (lease_id,))


def live_leases(control_path: Path, generation: int) -> int:
    """Count unexpired leases of ``generation``; expired ones (crashed writers) are removed."""
    with closing(_connect(control_path)) as connection:
        connection.execute("DELETE FROM writer_leases WHERE expires_at <= ?", (_stamp(),))
        return int(connection.execute("SELECT COUNT(*) FROM writer_leases WHERE generation = ?",
                                      (generation,)).fetchone()[0])


__all__ = [
    "CORE_HASH_PREFIX", "EXTENSION", "Fenced", "StaleBinding", "acquire_lease", "check_binding",
    "create_bound_grant", "engine_state", "ensure_fence", "fenced_write", "live_leases", "migrate", "raise_fence",
    "recover_on_start", "release_lease", "set_phase", "token_hash",
]
