# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Validated, local SQLite backup and restore helpers for BIO CE."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote


_SCHEMA_VERSION = 1
_REQUIRED_TABLES = {"memories", "revisions", "memory_fts"}


class BackupError(RuntimeError):
    """A backup or restore could not be completed safely."""


class BackupConflictError(BackupError):
    """The destination exists or the operation conflicts with the live DB."""


class BackupValidationError(BackupError):
    """The selected database is not a healthy supported BIO CE database."""


def validate_database(path: str | Path, *, standalone: bool = False) -> None:
    """Check SQLite integrity and the supported BIO CE schema without writes.

    ``standalone`` marks a backup file that no BIO CE process has open. It is
    read as immutable so validation cannot leave ``-wal``/``-shm`` files beside
    it, and a backup that still depends on a pending write-ahead log is refused.
    """
    database = Path(path).expanduser().resolve()
    if not database.is_file():
        raise BackupValidationError("The selected database file does not exist.")
    if standalone:
        _require_no_pending_wal(database)
    connection = _open_read_only(database, immutable=standalone)
    try:
        integrity = connection.execute("PRAGMA quick_check").fetchall()
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    except sqlite3.Error as exc:
        raise BackupValidationError("The selected database could not be validated.") from exc
    finally:
        connection.close()
    if integrity != [("ok",)] or version != _SCHEMA_VERSION or not _REQUIRED_TABLES.issubset(tables):
        raise BackupValidationError("The selected file is corrupt or has an unsupported BIO CE schema.")


def create_backup(source: str | Path, destination: str | Path) -> Path:
    """Create a consistent SQLite snapshot without overwriting any file."""
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if source_path == destination_path:
        raise BackupConflictError("The backup destination must differ from the active database.")
    validate_database(source_path)
    if destination_path.exists():
        raise BackupConflictError("The backup destination already exists; choose a new filename.")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_database(destination_path.parent)
    try:
        _copy_snapshot(source_path, temporary)
        validate_database(temporary)
        try:
            if os.name == "nt":
                # Windows rename is atomic on the same volume and refuses an existing target.
                os.rename(temporary, destination_path)
            else:
                # POSIX hard-link creation is atomic and refuses an existing target.
                os.link(temporary, destination_path)
        except FileExistsError as exc:
            raise BackupConflictError(
                "The backup destination already exists; choose a new filename."
            ) from exc
        except OSError as exc:
            raise BackupError(
                "BIO CE could not create a safe no-overwrite backup at this location."
            ) from exc
        if os.name != "nt":
            temporary.unlink(missing_ok=True)
        return destination_path
    finally:
        temporary.unlink(missing_ok=True)
        remove_sqlite_sidecars(temporary)


def stage_restore(source: str | Path, target_directory: str | Path) -> Path:
    """Validate a backup and make a complete staging copy beside the live DB."""
    source_path = Path(source).expanduser().resolve()
    validate_database(source_path, standalone=True)
    directory = Path(target_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    staged = _temporary_database(directory, prefix=".bio-ce-restore-")
    try:
        _copy_snapshot(source_path, staged, source_immutable=True)
        validate_database(staged)
    except Exception:
        staged.unlink(missing_ok=True)
        remove_sqlite_sidecars(staged)
        raise
    return staged


def remove_sqlite_sidecars(database: str | Path) -> None:
    """Delete leftover journal files of a BIO CE temporary database copy."""
    for suffix in ("-wal", "-shm", "-journal"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)


def _copy_snapshot(source: Path, destination: Path, *, source_immutable: bool = False) -> None:
    source_connection = _open_read_only(source, immutable=source_immutable)
    destination_connection: sqlite3.Connection | None = None
    try:
        destination_connection = sqlite3.connect(str(destination), timeout=5.0)
        source_connection.backup(destination_connection, pages=128, sleep=0.05)
        destination_connection.commit()
        # The page copy keeps the live database's WAL flag. A backup is a single
        # self-contained file, so switch it to a rollback journal; otherwise every
        # later read-only open would leave -wal/-shm files beside it.
        mode = destination_connection.execute("PRAGMA journal_mode = DELETE").fetchone()
        if mode is None or str(mode[0]).lower() != "delete":
            raise BackupError("BIO CE could not finalize the SQLite snapshot.")
    except sqlite3.Error as exc:
        raise BackupError("BIO CE could not create the SQLite snapshot.") from exc
    finally:
        source_connection.close()
        if destination_connection is not None:
            destination_connection.close()


def _require_no_pending_wal(path: Path) -> None:
    wal = Path(f"{path}-wal")
    try:
        pending = wal.stat().st_size > 0
    except FileNotFoundError:
        return
    except OSError as exc:
        raise BackupValidationError("The selected backup could not be checked.") from exc
    if pending:
        raise BackupValidationError(
            "The selected file still has unsaved SQLite changes in a -wal file. Choose a backup created by BIO CE."
        )


def _open_read_only(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    uri = f"file:{quote(path.as_posix(), safe='/:')}?mode=ro"
    if immutable:
        uri += "&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.execute("PRAGMA query_only = ON")
        return connection
    except sqlite3.Error as exc:
        raise BackupValidationError("The selected database could not be opened read-only.") from exc


def _temporary_database(directory: Path, *, prefix: str = ".bio-ce-backup-") -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".sqlite3", dir=directory)
    os.close(descriptor)
    return Path(name)


__all__ = [
    "BackupConflictError",
    "BackupError",
    "BackupValidationError",
    "create_backup",
    "remove_sqlite_sidecars",
    "stage_restore",
    "validate_database",
]
