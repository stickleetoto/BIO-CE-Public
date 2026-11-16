# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Validated, local SQLite backup and restore helpers for BIO CE."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import quote


_SCHEMA_VERSION = 1
_REQUIRED_TABLES = {"memories", "revisions", "memory_fts"}
_CONTROL_SCHEMA_VERSION = 2
PAIR_SUFFIX = ".control.sqlite3"
PAIR_MATCHED = "matched"
PAIR_MISSING = "missing"
PAIR_MISMATCH = "mismatch"


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


def pair_path(backup: str | Path) -> Path:
    """The connection-records file that belongs to a memory backup: X.sqlite3 -> X.control.sqlite3."""
    path = Path(backup)
    stem = path.name[: -len(".sqlite3")] if path.name.lower().endswith(".sqlite3") else path.name
    return path.with_name(stem + PAIR_SUFFIX)


def create_backup(source: str | Path, destination: str | Path, *, control: str | Path | None = None,
                  app_version: str = "") -> Path:
    """Create a consistent SQLite snapshot without overwriting any file.

    With ``control``, a second file X.control.sqlite3 holds a snapshot of the control database and a
    ``backup_info`` row with the memory file's SHA-256. The memory file keeps the old format, so earlier BIO CE
    versions can still restore it. Neither file overwrites anything; if either cannot be made, neither is kept.
    """
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if source_path == destination_path:
        raise BackupConflictError("The backup destination must differ from the active database.")
    control_path = Path(control).expanduser().resolve() if control is not None else None
    if control_path is not None and not control_path.is_file():
        control_path = None
    pair = pair_path(destination_path) if control_path is not None else None
    if pair is not None and pair in (source_path, control_path):
        raise BackupConflictError("The backup destination must differ from the active database.")
    validate_database(source_path)
    if destination_path.exists() or (pair is not None and pair.exists()):
        raise BackupConflictError("The backup destination already exists; choose a new filename.")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_database(destination_path.parent)
    temporary_pair = _temporary_database(destination_path.parent) if pair is not None else None
    placed: Path | None = None
    try:
        _copy_snapshot(source_path, temporary)
        validate_database(temporary)
        if temporary_pair is not None:
            _copy_control_snapshot(control_path, temporary_pair, memory_sha256=file_sha256(temporary),
                                   app_version=app_version)
        _place(temporary, destination_path)
        placed = destination_path
        if temporary_pair is not None:
            _place(temporary_pair, pair)
        placed = None
        return destination_path
    finally:
        if placed is not None:
            placed.unlink(missing_ok=True)  # the pair failed: do not leave half a backup behind
        for path in (temporary, temporary_pair):
            if path is not None:
                path.unlink(missing_ok=True)
                remove_sqlite_sidecars(path)


def check_pair(backup: str | Path) -> tuple[str, Path | None]:
    """Whether a memory backup has its control file and the two belong together.

    Returns (PAIR_MATCHED, path), (PAIR_MISSING, None), or (PAIR_MISMATCH, None). A pair file that is damaged,
    from another version, or made for a different memory file counts as a mismatch: only memories are restored.
    """
    backup_path = Path(backup).expanduser().resolve()
    pair = pair_path(backup_path)
    if not pair.is_file():
        return PAIR_MISSING, None
    try:
        _require_no_pending_wal(pair)
        connection = _open_read_only(pair, immutable=True)
        try:
            healthy = connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            row = connection.execute("SELECT memory_sha256 FROM backup_info LIMIT 1").fetchone()
        finally:
            connection.close()
    except (BackupError, sqlite3.Error, OSError):
        return PAIR_MISMATCH, None
    if not healthy or version != _CONTROL_SCHEMA_VERSION or row is None:
        return PAIR_MISMATCH, None
    if str(row[0]) != file_sha256(backup_path):
        return PAIR_MISMATCH, None
    return PAIR_MATCHED, pair


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _place(temporary: Path, destination: Path) -> None:
    try:
        if os.name == "nt":
            # Windows rename is atomic on the same volume and refuses an existing target.
            os.rename(temporary, destination)
        else:
            # POSIX hard-link creation is atomic and refuses an existing target.
            os.link(temporary, destination)
            temporary.unlink(missing_ok=True)
    except FileExistsError as exc:
        raise BackupConflictError("The backup destination already exists; choose a new filename.") from exc
    except OSError as exc:
        raise BackupError("BIO CE could not create a safe no-overwrite backup at this location.") from exc


def _copy_control_snapshot(source: Path, destination: Path, *, memory_sha256: str, app_version: str) -> None:
    source_connection = _open_read_only(source)
    destination_connection: sqlite3.Connection | None = None
    try:
        destination_connection = sqlite3.connect(str(destination), timeout=5.0)
        source_connection.backup(destination_connection, pages=128, sleep=0.05)
        destination_connection.commit()
        mode = destination_connection.execute("PRAGMA journal_mode = DELETE").fetchone()
        if mode is None or str(mode[0]).lower() != "delete":
            raise BackupError("BIO CE could not finalize the connection records snapshot.")
        destination_connection.execute(
            "CREATE TABLE backup_info (format INTEGER NOT NULL, memory_sha256 TEXT NOT NULL, "
            "created_at TEXT NOT NULL, app_version TEXT NOT NULL)"
        )
        destination_connection.execute(
            "INSERT INTO backup_info VALUES (1, ?, ?, ?)",
            (memory_sha256, datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
             app_version),
        )
        destination_connection.commit()
        if destination_connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise BackupError("BIO CE could not verify the connection records snapshot.")
    except sqlite3.Error as exc:
        raise BackupError("BIO CE could not create the connection records snapshot.") from exc
    finally:
        source_connection.close()
        if destination_connection is not None:
            destination_connection.close()


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


# "auto-<reason>-<YYYYmmdd-HHMMSS-ffffff>.sqlite3": the only names BIO CE gives its own backups. A backup the user
# saved under another name, even one that starts with "auto-", never matches.
_AUTOMATIC_NAME = re.compile(r"^auto-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*-(\d{8}-\d{6}-\d{6})\.sqlite3$")


def automatic_backups(folder: str | Path) -> list[Path]:
    """BIO CE's own backups (memory files) in ``folder``, oldest first, whatever their reason."""
    directory = Path(folder)
    if not directory.is_dir():
        return []
    found = []
    for path in directory.iterdir():
        match = _AUTOMATIC_NAME.match(path.name)
        if match is not None and path.is_file():
            found.append((match.group(1), path.name, path))
    return [path for _stamp, _name, path in sorted(found)]


def prune_automatic_backups(folder: str | Path, keep: int, *,
                            protect: tuple[str | Path, ...] = ()) -> tuple[int, int]:
    """Keep the newest ``keep`` automatic backup pairs in ``folder``; returns (pairs removed, pairs that failed).

    A pair goes as a pair: the control file first, and the memory file only after it, so a failure never leaves a
    control file without its memories. ``protect`` names backups that must stay this time (one being restored).
    A file that cannot be removed is left for the next automatic backup; it never raises.
    """
    if type(keep) is not int or keep < 1:
        raise ValueError("keep at least one automatic backup")
    shielded = {Path(path).expanduser().resolve() for path in protect}
    removed = failed = 0
    for path in automatic_backups(folder)[:-keep]:
        if path.resolve() in shielded:
            continue
        try:
            pair = pair_path(path)
            if pair.exists():
                remove_backup_file(pair)
            remove_backup_file(path)
            removed += 1
        except OSError:
            failed += 1
    return removed, failed


def remove_backup_file(path: str | Path) -> None:
    """Overwrite a backup file with zeros, flush it to the drive, then delete it (as far as the app can: on an SSD
    the zeros may not reach the original blocks)."""
    target = Path(path)
    size = target.stat().st_size
    block = b"\0" * (1 << 20)
    with open(target, "r+b") as stream:
        written = 0
        while written < size:
            step = min(len(block), size - written)
            stream.write(block[:step])
            written += step
        stream.flush()
        os.fsync(stream.fileno())
    _unlink(target)


def _unlink(path: Path) -> None:
    path.unlink()


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
    "PAIR_MATCHED",
    "PAIR_MISMATCH",
    "PAIR_MISSING",
    "PAIR_SUFFIX",
    "check_pair",
    "file_sha256",
    "pair_path",
    "BackupConflictError",
    "BackupError",
    "BackupValidationError",
    "create_backup",
    "remove_sqlite_sidecars",
    "stage_restore",
    "validate_database",
]
