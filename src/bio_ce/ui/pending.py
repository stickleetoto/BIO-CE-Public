# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""A delete the user can undo for a few seconds (v0.4.4 §3.2).

Deleting (retracting a memory, discarding an inbox item) is not run at once: the items disappear from the list and
a notice offers Undo. The delete runs when the notice times out, when another delete starts, when the user leaves
the page, or when the app closes, so a pending delete is never left behind. Undo forgets it and shows the items
again. Nothing in the storage layer changes: until it runs, nothing was deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

UNDO_SECONDS = 8  # owner decision Q3, 2026-11-16


@dataclass
class _Pending:
    ids: frozenset[str]
    run: Callable[[], object]
    on_undo: Callable[[], object] | None = None
    timer: str | None = field(default=None)


class PendingDeletes:
    """At most one pending delete at a time; a new one runs the earlier one first."""

    def __init__(self, app) -> None:
        self.app = app
        self._pending: _Pending | None = None

    def hidden(self) -> frozenset[str]:
        """Ids the lists should leave out while their delete waits."""
        return self._pending.ids if self._pending is not None else frozenset()

    def defer(self, ids, run: Callable[[], object], *, message: str, title: str,
              on_undo: Callable[[], object] | None = None) -> None:
        self.flush()
        pending = _Pending(frozenset(ids), run, on_undo)
        self._pending = pending
        try:
            pending.timer = self.app.root.after(UNDO_SECONDS * 1000, self.flush)
        except Exception:  # noqa: BLE001 - no event loop (closing): run now
            self.flush()
            return
        from bio_ce.ui.i18n import t  # late: the app sets the language before any page exists
        self.app.notify("info", message, title=title, action=(t("common.undo"), self.undo))

    def flush(self) -> object:
        """Run the pending delete now (timer, next delete, leaving the page, closing the app)."""
        pending, self._pending = self._pending, None
        if pending is None:
            return None
        self._cancel_timer(pending)
        return pending.run()

    def undo(self) -> bool:
        pending, self._pending = self._pending, None
        if pending is None:
            return False
        self._cancel_timer(pending)
        if pending.on_undo is not None:
            pending.on_undo()
        return True

    def _cancel_timer(self, pending: _Pending) -> None:
        if pending.timer is not None:
            try:
                self.app.root.after_cancel(pending.timer)
            except Exception:  # noqa: BLE001 - the timer already ran or the window is gone
                pass
            pending.timer = None


__all__ = ["PendingDeletes", "UNDO_SECONDS"]
