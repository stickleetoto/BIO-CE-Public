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
        self.assertEqual(outcome, {"approved": 2, "skipped": 0})
        self.assertEqual(len(self.service.inbox()), 2)
        self.assertTrue(self.page.empty.winfo_manager())

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
