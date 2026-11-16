# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Which BIO CE MCP servers are running, and ending the ones idle for long (v0.4.4 §9.2).

Hosts start one stdio server per conversation or session and keep it while that stays open (the owner once saw 11).
A server ends when its host closes stdin or its parent process ends; idle servers are kept on purpose (Codex does
not start a new one, see ``server_lifetime``). So that the user can see them and end the long-idle ones, each server
keeps a small record in the data folder: ``runtime/servers/<pid>.json`` with its parent, connection, executable,
start time and last request. The record goes when the server ends; a record whose process is gone is removed when
read. Ending a server is the user's choice in the app, and only a process whose executable is still the one the
record names is ended, so a reused process id never ends another program.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time

from bio_ce.server_lifetime import process_alive

RUNTIME_FOLDER = ("runtime", "servers")
TOUCH_EVERY_SECONDS = 60.0  # a request updates the record at most once a minute
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerRecord:
    pid: int
    parent_pid: int | None
    parent_name: str
    connection_id: str | None
    executable: str
    started_at: str
    last_request_at: str

    def idle_seconds(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        try:
            last = datetime.fromisoformat(self.last_request_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        return max(0.0, (now - last).total_seconds())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def folder(data_folder: str | Path) -> Path:
    return Path(data_folder).joinpath(*RUNTIME_FOLDER)


def process_image(pid: int) -> str | None:
    """The executable path of a running process, or None (gone, or not readable)."""
    if pid <= 0:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            return buffer.value
        finally:
            kernel32.CloseHandle(handle)
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return None


def _same_file(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class ServerRegistration:
    """This server's own record: written at start, touched on requests, removed at the end. Never raises."""

    def __init__(self, data_folder: str | Path, *, connection_id: str | None, parent_pid: int | None,
                 clock=time.monotonic) -> None:
        self.path = folder(data_folder) / f"{os.getpid()}.json"
        self._clock = clock
        self._touched = clock()
        parent_name = ""
        if parent_pid:
            parent_name = Path(process_image(parent_pid) or "").name
        now = _now()
        self._record = ServerRecord(os.getpid(), parent_pid, parent_name, connection_id,
                                    process_image(os.getpid()) or sys.executable, now, now)
        self._write()

    def _write(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)  # inside the data folder, which already exists
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(asdict(self._record)), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            _logger.warning("BIO CE MCP server could not write its record in %s", self.path.parent)

    def touch(self) -> None:
        """A request came in: update the last-request time (at most once a minute)."""
        if self._clock() - self._touched < TOUCH_EVERY_SECONDS:
            return
        self._touched = self._clock()
        self._record = ServerRecord(**{**asdict(self._record), "last_request_at": _now()})
        self._write()

    def remove(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def running(data_folder: str | Path) -> list[ServerRecord]:
    """The servers whose process is still running; records of ended ones are removed."""
    found = []
    base = folder(data_folder)
    if not base.is_dir():
        return found
    for path in sorted(base.glob("*.json")):
        try:
            record = ServerRecord(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            continue
        if process_alive(record.pid) and _same_file(process_image(record.pid), record.executable):
            found.append(record)
        else:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return found


def end_idle(data_folder: str | Path, idle_seconds: float, *, now: datetime | None = None) -> list[int]:
    """End the servers with no request for at least ``idle_seconds``; returns their process ids. The user asks for
    this in the app; a conversation that used one of them may fail its next memory call."""
    ended = []
    for record in running(data_folder):
        if record.pid == os.getpid() or record.idle_seconds(now) < idle_seconds:
            continue
        if _terminate(record):
            ended.append(record.pid)
            (folder(data_folder) / f"{record.pid}.json").unlink(missing_ok=True)
    return ended


def _terminate(record: ServerRecord) -> bool:
    if not _same_file(process_image(record.pid), record.executable):
        return False  # not that program any more
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x0001, False, record.pid)  # PROCESS_TERMINATE
        if not handle:
            return False
        try:
            return bool(kernel32.TerminateProcess(handle, 0))
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(record.pid, 15)
        return True
    except OSError:
        return False


__all__ = ["ServerRecord", "ServerRegistration", "end_idle", "folder", "process_image", "running"]
