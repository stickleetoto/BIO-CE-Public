# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""rc4 (owner decision 2026-11-19): Forget completely through the app never takes an item another memory keeps.

The night random run's data loss (see ``test_kept_still_referenced.py``), on a real Tk window with synthetic data:
"To memories" makes M1 from inbox item A and the notice's Undo takes it back (M1 retracted, still listing A); A
then updates memory M2 ("To memories" again, with its Undo notice); the user forgets M1 from Deleted memories.
The forget's notice covers the move's Undo. Then:

- Ctrl+Z right after the forget changes nothing: the forget has no Undo, and a delete that was waiting ran before
  the forget (it is not brought back either);
- the move's Undo, offered before its notice was covered, still gives M2 its earlier text and A back to the inbox.
"""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.core.models import MemoryNotFoundError, SourceProvenance
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.inbox import inbox_scope, kept_scope
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from bio_ce.ui.hub.data import INBOX, RETRACTED
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.tk_support import new_tk_root

HOST = SourceProvenance("ai-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})
SAID = "The user likes miso ramen with extra corn."


class ForgetKeptUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-forget-kept-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.general = self.control.space("general")
        self.food = self.service.add(title="Food", content="The user likes noodles.", source_ref="test")
        self.other = self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        store = SQLiteMemoryStore(self.paths.user_database)
        self.item = store.add(inbox_scope(self.general.curated), title="Ramen", content=SAID,
                              source=HOST).memory_id
        store.close()
        self.root = new_tk_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.after_cancel(self.app._maintenance_after)
        self.root.geometry(f"{self.app.theme.px(1200)}x{self.app.theme.px(760)}+0+0")
        self.hub = self.app.memories
        self.app.show_page("memories")
        self.settle()

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def settle(self) -> None:
        for _ in range(5):
            self.root.update()

    def hub_item(self, state: str, memory_id: str):
        self.hub.show_state(state)
        self.settle()
        return next(item for item in self.hub.items if item.item_id == memory_id)

    def kept_text(self) -> str:
        return self.service._store.read(kept_scope(self.general.inbox), self.item).content

    def reuse_then_forget(self):
        """The night run's steps through the app; returns the move's Undo (offered before its notice was covered)
        and M1's id."""
        with patch.object(self.app, "edit_before_saving", return_value=("Ramen", SAID)), \
                patch.object(self.app.service, "similar_curated", return_value=None):
            self.assertTrue(self.hub.do.to_memories(self.hub_item(INBOX, self.item)))
        first = next(r for r in self.service.list(limit=50) if r.title == "Ramen")
        self.app.infobar.action_button.invoke()  # Undo on the notice: M1 retracted, A back in the inbox
        self.settle()
        self.assertEqual(self.service.read_inbox(self.item).content, SAID)
        offered = []
        notify = self.app.notify

        def keep_action(kind, message, **options):
            if options.get("action") is not None:
                offered.append(options["action"])
            notify(kind, message, **options)

        with patch.object(self.app, "edit_before_saving", return_value=("Food", SAID)), \
                patch.object(self.app.service, "similar_curated", return_value=self.service.read(self.food.memory_id)), \
                patch.object(self.app, "confirm", return_value=True), patch.object(self.app, "notify", keep_action):
            self.assertTrue(self.hub.do.to_memories(self.hub_item(INBOX, self.item)))
        self.assertEqual(self.service.read(self.food.memory_id).content, SAID)  # M2 updated with A
        self.assertIsNotNone(self.app.infobar.action_button, "positive control: the move offers Undo")
        (undo_move,) = offered
        with patch.object(self.app, "confirm", return_value=True):
            self.assertTrue(self.hub.forget_item(self.hub_item(RETRACTED, first.memory_id)))
        self.settle()
        return undo_move, first.memory_id

    def assert_forgotten_and_kept(self, forgotten: str) -> None:
        self.assertNotIn(forgotten, {entry.last.memory_id for entry in self.service.retracted()})
        with self.assertRaises(MemoryNotFoundError):
            self.service._store.read(self.general.curated, forgotten)
        self.assertEqual(self.kept_text(), SAID, "A is kept for M2, so forgetting M1 must leave it")
        self.assertEqual(self.service.read(self.food.memory_id).content, SAID)

    def test_ctrl_z_right_after_forget_changes_nothing(self):
        self.hub.do.retract([self.hub_item("memories", self.other.memory_id)])  # a delete waiting for Undo
        self.assertEqual(self.app.pending.hidden(), {self.other.memory_id})
        _undo_move, forgotten = self.reuse_then_forget()
        self.assertEqual(self.app.pending.hidden(), frozenset(), "the waiting delete ran before the forget")
        self.hub.keys.undo()  # Ctrl+Z
        self.settle()
        self.assert_forgotten_and_kept(forgotten)
        with self.assertRaises(MemoryNotFoundError):  # the delete that ran is not brought back by Ctrl+Z
            self.service.read(self.other.memory_id)
        self.assertEqual(self.app.infobar.title_label.cget("text"), "Forgotten")

    def test_the_covered_undo_of_the_move_still_gives_the_item_back(self):
        undo_move, forgotten = self.reuse_then_forget()
        self.assertIsNone(self.app.infobar.action_button, "the forget's notice has no Undo and covers the move's")
        self.assert_forgotten_and_kept(forgotten)
        label, callback = undo_move
        self.assertEqual(label, "Undo")
        self.assertTrue(callback())
        self.settle()
        self.assertEqual(self.service.read(self.food.memory_id).content, "The user likes noodles.")
        self.assertEqual(self.service.read_inbox(self.item).content, SAID)
        with self.assertRaises(MemoryNotFoundError):
            self.kept_text()


if __name__ == "__main__":
    unittest.main()
