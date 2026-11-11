# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Keep a stdio MCP server from outliving the host that started it.

A host normally ends a stdio server by closing its stdin. Long-lived hosts (for example the Codex
desktop app, which starts one server per thread) may keep stdin open for good, and a host that is
killed can leave the pipe open in another process. So the server also ends when:

* the process that started it has ended (parent watch), or
* it has had no request for ``BIO_CE_MCP_IDLE_SECONDS`` seconds (default one hour; 0 turns this off).

A host that needs BIO CE again starts a new server. A request that is in progress always finishes
first: the exit waits for the same lock that every request holds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import ctypes
import logging
import os
import sys
import threading
import time

IDLE_ENVIRONMENT_VARIABLE = "BIO_CE_MCP_IDLE_SECONDS"
DEFAULT_IDLE_SECONDS = 3600.0

_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0

_logger = logging.getLogger(__name__)


def idle_seconds_from(env: Mapping[str, str]) -> float:
    """The idle limit in seconds; 0 means no limit. Invalid values fall back to the default."""
    raw = env.get(IDLE_ENVIRONMENT_VARIABLE, "").strip()
    if not raw:
        return DEFAULT_IDLE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_IDLE_SECONDS
    return value if value >= 0 else DEFAULT_IDLE_SECONDS


def process_alive(pid: int) -> bool:
    """True while the process with this ID is running."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ServerLifetime:
    """Watches the parent process and idle time; calls ``on_exit(reason)`` once when the server should end."""

    def __init__(
        self,
        on_exit: Callable[[str], None],
        *,
        idle_seconds: float,
        parent_pid: int | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_exit = on_exit
        self._idle_seconds = idle_seconds
        self._parent_pid = parent_pid
        self._clock = clock
        self._lock = threading.RLock()
        self._last_activity = clock()
        self._ended = threading.Event()

    @contextmanager
    def activity(self) -> Iterator[None]:
        """Hold this around every request: it resets the idle timer and delays an exit until it finishes."""
        with self._lock:
            self._last_activity = self._clock()
            try:
                yield
            finally:
                self._last_activity = self._clock()

    def start(self) -> None:
        if self._idle_seconds > 0:
            threading.Thread(target=self._watch_idle, name="bio-ce-idle", daemon=True).start()
        if self._parent_pid:
            threading.Thread(target=self._watch_parent, name="bio-ce-parent", daemon=True).start()

    def idle_for(self) -> float:
        return self._clock() - self._last_activity

    def _end(self, reason: str) -> None:
        with self._lock:  # never in the middle of a request
            if self._ended.is_set():
                return
            self._ended.set()
            _logger.info("BIO CE MCP server is ending: %s", reason)
            self._on_exit(reason)

    def _watch_idle(self) -> None:
        interval = max(0.2, min(30.0, self._idle_seconds / 4))
        while not self._ended.is_set():
            time.sleep(interval)
            if self.idle_for() >= self._idle_seconds:
                self._end(f"no request for {self._idle_seconds:g} seconds")
                return

    def _watch_parent(self) -> None:
        pid = self._parent_pid
        assert pid is not None
        if sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
            if not handle:
                if not process_alive(pid):
                    self._end("the process that started it has already ended")
                return  # cannot watch (for example access denied): rely on stdin and the idle limit
            try:
                # The handle pins this exact process, so a reused process ID cannot fool the watch.
                if kernel32.WaitForSingleObject(handle, _INFINITE) == _WAIT_OBJECT_0:
                    self._end("the process that started it has ended")
            finally:
                kernel32.CloseHandle(handle)
            return
        while not self._ended.is_set():
            time.sleep(2)
            if os.getppid() != pid or not process_alive(pid):
                self._end("the process that started it has ended")
                return


def parent_process_id() -> int | None:
    try:
        pid = os.getppid()
    except OSError:
        return None
    return pid if pid > 1 else None


__all__ = [
    "DEFAULT_IDLE_SECONDS",
    "IDLE_ENVIRONMENT_VARIABLE",
    "ServerLifetime",
    "idle_seconds_from",
    "parent_process_id",
    "process_alive",
]
