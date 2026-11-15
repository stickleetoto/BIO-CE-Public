# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 C in the app: the Suggestions page, bulk decisions, badges, and "review and keep" for an import."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.importer import parse_text
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root

INBOX = MemoryScope("bio-ce-personal", "default.inbox")
HOST = SourceProvenance("ai-host-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})


class SuggestionsUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-suggestions-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        store = SQLiteMemoryStore(self.paths.user_database)
        for title, text in (("Plants", "The user waters the balcony plants every Sunday morning."),
                            ("Invoices", "Invoices go out to clients on the first business day of a month.")):
            store.add(INBOX, title=title, content=text, source=HOST)
            store.add(INBOX, title=title, content=text.rstrip(".") + " without fail.", source=HOST)
        store.close()
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        # The app's own inbox pass runs 5 s after start and also finds suggestions; a test that ran longer than that
        # saw "0 new" from its own find() (flaky 2 of 6 combined runs, 2026-11-15). These tests call find() themselves.
        self.root.after_cancel(self.app._maintenance_after)
        self.root.update()
        self.page = self.app.suggestions

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def test_find_shows_cards_and_the_badges_count_them(self):
        self.app.show_page("suggestions")
        self.assertEqual(self.page.cards, {})
        self.assertTrue(self.page.empty.winfo_manager())
        self.assertEqual(self.page.find(), 2)
        self.assertEqual(len(self.page.cards), 2)
        self.assertEqual(self.app.pending_cleanup_count(), 2)
        self.assertEqual(self.page.space_bar.suggestions_tab.text, "Suggestions (2)")
        first = next(iter(self.page.cards))
        parts = self.page.cards[first]
        parts["text"].set("Edited merged text about the topic.")
        self.assertTrue(self.page.approve(first, edited=True))
        contents = [item.content for item in self.service.inbox()]
        self.assertIn("Edited merged text about the topic.", contents)
        self.assertEqual(len(contents), 3)
        self.assertEqual(self.app.pending_cleanup_count(), 1)

    def test_approve_and_reject_all_shown_say_what_they_do(self):
        self.app.show_page("suggestions")
        self.page.find()
        with patch.object(self.app, "confirm", return_value=False):
            self.assertIsNone(self.page.approve_shown())
        self.assertEqual(len(self.page.cards), 2)
        with patch.object(self.app, "confirm", return_value=True) as asked:
            outcome = self.page.approve_shown()
        self.assertEqual(asked.call_args.kwargs["points"], ["Merge: 2"])
        self.assertEqual((outcome["approved"], outcome["skipped"], len(outcome["ids"])), (2, 0, 2))
        self.assertEqual(len(self.service.inbox()), 2)
        self.assertTrue(self.page.empty.winfo_manager())

    def test_undo_right_after_approving_and_undo_all(self):
        """Owner request (2026-11-15): a wrong approval can be undone at once from the notice."""
        self.app.show_page("suggestions")
        self.page.find()
        before = sorted((item.title, item.content) for item in self.service.inbox())
        first = next(iter(self.page.cards))
        with patch.object(self.app, "notify") as notice:
            self.assertTrue(self.page.approve(first))
        label, undo = notice.call_args.kwargs["action"]
        self.assertEqual(label, "Undo")
        self.assertEqual(len(self.service.inbox()), 3)
        self.assertEqual(undo(), 1)
        self.assertEqual(sorted((item.title, item.content) for item in self.service.inbox()), before)
        self.page.find()  # the other group is still suggested; the undone one is not
        self.assertEqual(len(self.page.cards), 1)
        with patch.object(self.app, "confirm", return_value=True), patch.object(self.app, "notify") as notice:
            self.page.approve_shown()
        label, undo_all = notice.call_args.kwargs["action"]
        self.assertEqual(label, "Undo all")
        self.assertEqual(undo_all(), 1)
        self.assertEqual(sorted((item.title, item.content) for item in self.service.inbox()), before)

    def test_undo_merge_from_the_inbox_and_undo_an_update_from_history(self):
        self.app.show_page("suggestions")
        self.page.find()
        first = next(iter(self.page.cards))
        self.page.approve(first)
        self.app.show_page("inbox")
        self.app.inbox.refresh()
        inbox = self.app.inbox
        merged = [iid for iid, item in inbox.items.items() if item.source.metadata.get("merged_from")]
        self.assertEqual(len(merged), 1)
        others = [iid for iid in inbox.items if iid not in merged]
        inbox.tree.selection_set(others[0])
        self.root.update()
        self.assertFalse(self.undo_merge_shown())  # positive control: not for an ordinary item
        inbox.tree.selection_set(merged[0])
        self.root.update()
        self.assertTrue(self.undo_merge_shown())
        with patch.object(self.app, "confirm", return_value=True):
            self.assertEqual(inbox.undo_merge(), 1)
        self.assertEqual(len(self.service.inbox()), 4)

        coffee = self.service.add(title="Coffee", content="The user drinks two cups of coffee every morning.",
                                  source_ref="test")
        store = SQLiteMemoryStore(self.paths.user_database)
        store.add(INBOX, title="Coffee", content="The user now drinks one cup of coffee every morning and green tea "
                  "after lunch.", source=HOST)
        store.close()
        self.page.find()
        update = next(s for s in self.page.shown if s.action == "update_existing")
        self.page.approve(update.proposal_id)
        self.app.show_page("memories")
        self.app.memories.refresh()
        self.app.memories.select(coffee.memory_id)
        dialog = self.app.memories.show_history()
        self.assertIsNotNone(dialog.undo_button)
        with patch.object(self.app, "confirm", return_value=True):
            dialog._undo_clicked()
        self.assertEqual(self.service.read(coffee.memory_id).content, coffee.content)

    def undo_merge_shown(self) -> bool:
        return bool(self.app.inbox.undo_merge_button.winfo_manager())

    def test_reject_all_keeps_the_items_and_the_groups_are_not_suggested_again(self):
        self.app.show_page("suggestions")
        self.page.find()
        with patch.object(self.app, "confirm", return_value=True):
            self.assertEqual(self.page.reject_shown(), 2)
        self.assertEqual(len(self.service.inbox()), 4)
        self.assertEqual(self.page.find(), 0)

    def test_review_and_keep_an_import_filters_to_that_import(self):
        spaces = self.app.spaces()
        preview = self.service.import_planner(spaces, size_limit=2000).preview(
            parse_text("[2025-02-01] - The user speaks Korean and English.\n[unknown] - The user is left-handed."),
            source="claude", destination="general")
        batch = self.service.import_service(self.control, spaces).commit(preview)
        self.app.show_page("import")
        self.app.importer.refresh()
        self.assertEqual(self.app.importer.review_and_keep(batch.batch_id), 2)
        self.assertIs(self.app.current, self.page)
        self.assertTrue(self.page.filter.get().startswith("From the import of"))
        self.assertEqual(len(self.page.cards), 2)  # only this import's entries, not the other inbox items


if __name__ == "__main__":
    unittest.main()
