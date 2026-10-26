# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Run slow host operations off the Tk thread and deliver results back to it."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable
import tkinter as tk


class TaskRunner:
    """Execute callables on worker threads; callbacks always run on the Tk thread.

    Workers must not touch Tk widgets. Only the ``on_success``/``on_error``
    callbacks, which run from ``after`` polling, may update the UI.
    """

    POLL_MS = 60

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self._results: queue.Queue[tuple[Callable[[Any], None], Any]] = queue.Queue()
        self._active = 0
        self._polling = False

    @property
    def busy(self) -> bool:
        return self._active > 0

    def submit(
        self,
        work: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        def run() -> None:
            try:
                outcome: tuple[Callable[[Any], None], Any] = (on_success, work())
            except BaseException as exc:  # noqa: BLE001 - reported to the UI thread
                outcome = (on_error, exc)
            self._results.put(outcome)

        self._active += 1
        threading.Thread(target=run, name="bio-ce-ui-task", daemon=True).start()
        if not self._polling:
            self._polling = True
            self.root.after(self.POLL_MS, self._drain)

    def _drain(self) -> None:
        while True:
            try:
                callback, value = self._results.get_nowait()
            except queue.Empty:
                break
            self._active -= 1
            try:
                callback(value)
            except tk.TclError:
                pass
        if self._active > 0:
            self.root.after(self.POLL_MS, self._drain)
        else:
            self._polling = False

    def wait(self, timeout: float = 60.0) -> None:
        """Pump Tk events until all submitted work has finished (tests only)."""
        deadline = time.monotonic() + timeout
        while self._active > 0:
            if time.monotonic() > deadline:
                raise TimeoutError("UI background task did not finish")
            self.root.update()
            time.sleep(0.01)
        self.root.update()


__all__ = ["TaskRunner"]
