# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 C in the app, on the memory screen's Suggestions tab since v0.4.4: bulk decisions, counts, Undo for approve
and (new) reject, merge extras (K11), and "review and keep" for an import."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.importer import parse_text
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from bio_ce.ui.hub.data import INBOX as INBOX_TAB, SUGGESTIONS
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
        self.hub = self.app.memories

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def open(self) -> None:
        self.app.open_state(SUGGESTIONS)
        self.root.update()

    def test_find_shows_cards_and_the_tab_counts_them(self):
        self.open()
        self.assertEqual(self.page.cards, {})
        self.assertTrue(self.page.empty.winfo_manager())
        self.assertEqual(self.page.find(), 2)
        self.assertEqual(len(self.page.cards), 2)
        self.assertEqual(self.app.pending_cleanup_count(), 2)
        self.assertEqual(self.hub.tabs[SUGGESTIONS].text, "Suggestions 2")
        self.assertEqual(self.app.nav["memories"].badge_count, 0, "suggestions are not in the badge (owner Q1)")
        first = next(iter(self.page.cards))
        parts = self.page.cards[first]
        parts["text"].set("Edited merged text about the topic.")
        self.assertTrue(self.page.approve(first, edited=True))
        contents = [item.content for item in self.service.inbox()]
        self.assertIn("Edited merged text about the topic.", contents)
        self.assertEqual(len(contents), 3)
        self.assertEqual(self.app.pending_cleanup_count(), 1)

    def test_approve_and_reject_all_shown_say_what_they_do(self):
        self.open()
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
        self.open()
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

    def test_reject_has_an_undo_that_makes_it_wait_again(self):
        """v0.4.4 (inventory §13 item 9): Reject used to be silent and final; now its notice offers Undo."""
        self.open()
        self.page.find()
        first = next(iter(self.page.cards))
        with patch.object(self.app, "notify") as notice:
            self.assertTrue(self.page.reject(first))
        label, undo = notice.call_args.kwargs["action"]
        self.assertEqual(label, "Undo")
        self.assertNotIn(first, self.page.cards)
        self.assertEqual(len(self.service.inbox()), 4, "a rejection changes no item")
        self.assertEqual(undo(), 1)
        self.assertIn(first, self.page.cards)  # waiting again
        with patch.object(self.app, "confirm", return_value=True), patch.object(self.app, "notify") as notice:
            self.assertEqual(self.page.reject_shown(), 2)
        label, undo_all = notice.call_args.kwargs["action"]
        self.assertEqual((label, undo_all()), ("Undo all", 2))
        self.assertEqual(len(self.page.cards), 2)

    def test_a_merge_card_offers_what_only_the_other_items_say(self):
        """K11 (v0.4.4 §9.1): the draft is the most detailed item; the rest is offered apart, added only on Add."""
        store = SQLiteMemoryStore(self.paths.user_database)
        store.add(INBOX, title="Deploys", content="The team deploys on Fridays.", source=HOST)
        store.add(INBOX, title="Deploys", content="The team deploys on Fridays. Hotfixes ship any day.",
                  source=HOST)
        store.add(INBOX, title="Deploys", content="The team deploys on Fridays. Releases need a signed tag.",
                  source=HOST)
        store.close()
        self.open()
        self.page.find()
        card = next(parts for parts in self.page.cards.values() if "Fridays" in parts["text"].get())
        draft = card["text"].get()
        extras = card["extras"]
        self.assertTrue(extras, "a sentence only another item has is offered")
        sentence, button = next(iter(extras.items()))
        self.assertNotIn(sentence, draft)  # not added by default
        button.invoke()
        self.assertIn(sentence, card["text"].get())
        self.assertFalse(button.enabled)

    def test_undo_merge_from_the_inbox_and_undo_an_update_from_history(self):
        self.open()
        self.page.find()
        first = next(iter(self.page.cards))
        self.page.approve(first)
        self.app.open_state(INBOX_TAB)
        items = self.hub.items
        merged = [item for item in items if item.record.source.metadata.get("merged_from")]
        self.assertEqual(len(merged), 1)
        other = next(item for item in items if item not in merged)
        self.hub.open_item(other)
        self.root.update()
        self.assertFalse(self.undo_merge_shown())  # positive control: not for an ordinary item
        self.hub.open_item(merged[0])
        self.root.update()
        self.assertTrue(self.undo_merge_shown())
        with patch.object(self.app, "confirm", return_value=True):
            self.assertEqual(self.hub.drawer.undo_merge(), 1)
        self.assertEqual(len(self.service.inbox()), 4)

        coffee = self.service.add(title="Coffee", content="The user drinks two cups of coffee every morning.",
                                  source_ref="test")
        store = SQLiteMemoryStore(self.paths.user_database)
        store.add(INBOX, title="Coffee", content="The user now drinks one cup of coffee every morning and green tea "
                  "after lunch.", source=HOST)
        store.close()
        self.open()
        self.page.find()
        update = next(s for s in self.page.shown if s.action == "update_existing")
        self.page.approve(update.proposal_id)
        self.app.open_memory(coffee.memory_id)
        dialog = self.app.show_history()
        self.assertIsNotNone(dialog.undo_button)
        self.hub.drawer.open_history()  # the drawer's History keeps the same undo (v0.4.3) as a button
        self.assertTrue(self.hub.drawer.undo_suggestion_button.winfo_exists())
        with patch.object(self.app, "confirm", return_value=True):
            dialog._undo_clicked()
        self.assertEqual(self.service.read(coffee.memory_id).content, coffee.content)

    def test_delete_notices_say_the_kept_items_go_too(self):
        """Owner request (2026-11-16): the delete notices say what is kept for an undo is deleted with it."""
        self.open()
        self.page.find()
        self.page.approve(next(iter(self.page.cards)))
        self.app.open_state(INBOX_TAB)
        merged = next(item for item in self.hub.items if item.record.source.metadata.get("merged_from"))
        plain = next(item for item in self.hub.items if item is not merged)
        for item, expected in ((plain, False), (merged, True)):  # an ordinary item: no such line (positive control)
            with patch.object(self.app, "confirm", return_value=False) as asked:
                self.assertTrue(self.hub.delete_items([item]))
            asked.assert_not_called()  # v0.4.4: no dialog; the Undo notice says it
            said = self.app.infobar.message
            self.assertEqual("merged into it, kept so the merge could be undone" in said, expected, said)
            self.assertTrue(self.app.pending.undo())
        self.assertEqual(len(self.service.inbox()), 3, "nothing was discarded: both were undone")

        item = self.service.inbox()[0]
        memory = self.service.move_inbox(self.control, item.memory_id, title=item.title, content=item.content)
        self.app.open_memory(memory.memory_id)
        self.app.retract_selected()
        self.assertIn("it was made from, kept so that could be undone, go", self.app.infobar.message)
        self.assertTrue(self.app.pending.undo())

    def undo_merge_shown(self) -> bool:
        return bool(self.hub.drawer.undo_merge_button.winfo_manager())

    def test_reject_all_keeps_the_items_and_the_groups_are_not_suggested_again(self):
        self.open()
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
        self.assertIs(self.app.current, self.hub)
        self.assertEqual(self.hub.state, SUGGESTIONS)
        self.assertTrue(self.page.filter.get().startswith("From the import of"))
        self.assertEqual(len(self.page.cards), 2)  # only this import's entries, not the other inbox items


if __name__ == "__main__":
    unittest.main()
