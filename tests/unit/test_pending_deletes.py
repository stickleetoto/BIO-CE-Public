# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 §3.2: a delete waits a few seconds for Undo, and is never left behind (it runs or it is undone)."""

from __future__ import annotations

import unittest

from bio_ce.ui.pending import UNDO_SECONDS, PendingDeletes


class FakeRoot:
    def __init__(self) -> None:
        self.timers: dict[str, tuple[int, object]] = {}
        self.cancelled: list[str] = []

    def after(self, ms, callback):
        name = f"after#{len(self.timers)}"
        self.timers[name] = (ms, callback)
        return name

    def after_cancel(self, name):
        self.cancelled.append(name)
        self.timers.pop(name, None)

    def fire(self):
        for name, (_ms, callback) in list(self.timers.items()):
            self.timers.pop(name, None)
            callback()


class FakeApp:
    def __init__(self) -> None:
        self.root = FakeRoot()
        self.notices: list[tuple] = []

    def notify(self, kind, message, *, title="", action=None):
        self.notices.append((kind, message, title, action))


class PendingDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FakeApp()
        self.pending = PendingDeletes(self.app)
        self.ran: list[str] = []

    def defer(self, name: str, ids=("a",), on_undo=None):
        self.pending.defer(ids, lambda: self.ran.append(name), message=f"{name} deleted", title="Deleted",
                           on_undo=on_undo)

    def test_it_runs_when_the_notice_times_out(self):
        self.defer("first", ids=("m1", "m2"))
        self.assertEqual(self.ran, [])  # nothing deleted yet ...
        self.assertEqual(self.pending.hidden(), {"m1", "m2"})  # ... but the items are hidden
        (ms, _callback), = self.app.root.timers.values()
        self.assertEqual(ms, UNDO_SECONDS * 1000)
        label, undo = self.app.notices[-1][3]
        self.assertEqual(label, "Undo")
        self.app.root.fire()
        self.assertEqual(self.ran, ["first"])
        self.assertEqual(self.pending.hidden(), frozenset())

    def test_undo_keeps_everything_and_shows_the_items_again(self):
        shown = []
        self.defer("first", on_undo=lambda: shown.append(True))
        _label, undo = self.app.notices[-1][3]
        self.assertTrue(undo())
        self.assertEqual((self.ran, shown, self.pending.hidden()), ([], [True], frozenset()))
        self.app.root.fire()  # the timer was cancelled: nothing runs later
        self.assertEqual(self.ran, [])
        self.assertFalse(self.pending.undo())  # nothing left to undo

    def test_a_new_delete_runs_the_waiting_one_first(self):
        self.defer("first")
        self.defer("second")
        self.assertEqual(self.ran, ["first"])
        self.assertEqual(self.pending.flush(), None)  # flush runs the second
        self.assertEqual(self.ran, ["first", "second"])

    def test_flush_with_nothing_waiting_does_nothing(self):
        self.assertIsNone(self.pending.flush())
        self.assertEqual(self.ran, [])


if __name__ == "__main__":
    unittest.main()
