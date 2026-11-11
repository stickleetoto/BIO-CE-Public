# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Keep a stdio MCP server from outliving the host that started it.

A host normally ends a stdio server by closing its stdin. A host that is killed can leave the pipe
open in another process, so the server also ends when the process that started it has ended (parent
watch).

Long-lived hosts (for example the Codex desktop app, which starts one server per conversation) keep a
server for as long as the conversation exists and do not start a new one if it ends: a server that left
on its own would break the next memory call in that conversation (checked with Codex 0.166 and the
desktop app's 0.167). So an idle server stays, but after ``BIO_CE_MCP_RELEASE_SECONDS`` without a
request (default 60) it closes its database connections, so restores and upgrades are not blocked; the
next request opens them again. ``BIO_CE_MCP_IDLE_SECONDS`` (default 0, off) can still end an idle server.

A request in progress always finishes first: releasing and ending wait for the lock every request holds.
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
DEFAULT_IDLE_SECONDS = 0.0
RELEASE_ENVIRONMENT_VARIABLE = "BIO_CE_MCP_RELEASE_SECONDS"
DEFAULT_RELEASE_SECONDS = 60.0

_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0

_logger = logging.getLogger(__name__)


def _seconds(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def idle_seconds_from(env: Mapping[str, str]) -> float:
    """Seconds without a request before the server ends; 0 (the default) never ends it."""
    return _seconds(env, IDLE_ENVIRONMENT_VARIABLE, DEFAULT_IDLE_SECONDS)


def release_seconds_from(env: Mapping[str, str]) -> float:
    """Seconds without a request before the server closes its database connections; 0 keeps them open."""
    return _seconds(env, RELEASE_ENVIRONMENT_VARIABLE, DEFAULT_RELEASE_SECONDS)


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
    """Watches the parent process and idle time.

    Calls ``on_release()`` once per idle period (after ``release_seconds``) and ``on_exit(reason)`` once
    when the server should end.
    """

    def __init__(
        self,
        on_exit: Callable[[str], None],
        *,
        idle_seconds: float,
        parent_pid: int | None,
        release_seconds: float = 0.0,
        on_release: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_exit = on_exit
        self._idle_seconds = idle_seconds
        self._release_seconds = release_seconds if on_release is not None else 0.0
        self._on_release = on_release
        self._parent_pid = parent_pid
        self._clock = clock
        self._lock = threading.RLock()
        self._last_activity = clock()
        self._released = False
        self._ended = threading.Event()

    @contextmanager
    def activity(self) -> Iterator[None]:
        """Hold this around every request: it resets the idle timer and delays an exit until it finishes."""
        with self._lock:
            self._last_activity = self._clock()
            self._released = False  # the request reopens what it needs
            try:
                yield
            finally:
                self._last_activity = self._clock()

    def start(self) -> None:
        if self._idle_seconds > 0 or self._release_seconds > 0:
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
        limits = [value for value in (self._idle_seconds, self._release_seconds) if value > 0]
        interval = max(0.2, min(30.0, min(limits) / 4))
        while not self._ended.is_set():
            time.sleep(interval)
            idle = self.idle_for()
            if self._idle_seconds > 0 and idle >= self._idle_seconds:
                self._end(f"no request for {self._idle_seconds:g} seconds")
                return
            if self._release_seconds > 0 and not self._released and idle >= self._release_seconds:
                self._release()

    def _release(self) -> None:
        with self._lock:  # never in the middle of a request
            if self._released or self._ended.is_set() or self.idle_for() < self._release_seconds:
                return
            self._released = True
            try:
                assert self._on_release is not None
                self._on_release()
                _logger.info("BIO CE MCP server released its database connections while idle")
            except Exception:  # noqa: BLE001 - releasing is best effort; the next request reopens anyway
                _logger.warning("BIO CE MCP server could not release its database connections")

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
    "DEFAULT_RELEASE_SECONDS",
    "IDLE_ENVIRONMENT_VARIABLE",
    "RELEASE_ENVIRONMENT_VARIABLE",
    "ServerLifetime",
    "idle_seconds_from",
    "release_seconds_from",
    "parent_process_id",
    "process_alive",
]
