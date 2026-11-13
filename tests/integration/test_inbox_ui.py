# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Inbox tab, space picker, saving mode, inbox settings, and clean-up counts on a real Tk window (synthetic data)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.inbox import inbox_scope
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


GENERAL = MemoryScope("bio-ce-personal", "default")
HOST = SourceProvenance("ai-auto-memory", "codex:test", {"host": "codex", "guess": True, "stage": "inbox"})


class InboxUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-inbox-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.alpha = self.control.create_space("Alpha")
        store = SQLiteMemoryStore(self.paths.user_database)
        self.first = store.add(inbox_scope(GENERAL), title="Dark themes", content="The user seems to like dark "
                               "themes for long sessions.", source=HOST)
        self.second = store.add(inbox_scope(GENERAL), title="Weekly sync", content="The team syncs every Monday "
                                "morning about releases.", source=HOST)
        store.add(self.alpha.curated, title="Alpha only", content="Alpha builds with the release script.",
                  source=SourceProvenance("user-entered", "test"))
        store.close()
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.update()

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def test_inbox_tab_lists_items_and_marks_guesses(self):
        self.app.show_page("inbox")
        page = self.app.inbox
        self.assertEqual(set(page.items), {self.first.memory_id, self.second.memory_id})
        self.assertTrue(self.app.nav["memories"].selected)  # the tab lives under Memories in the sidebar
        page.tree.selection_set(self.first.memory_id)
        self.root.update()
        self.assertIn("a guess the host made", page.detail_meta.cget("text"))
        self.assertEqual(page.space_bar.inbox_tab.label.cget("text"), "Inbox (2)")

    def test_move_to_memories_then_the_inbox_copy_is_gone(self):
        self.app.show_page("inbox")
        page = self.app.inbox
        page.tree.selection_set(self.second.memory_id)
        self.root.update()
        with patch.object(self.app, "edit_before_saving", return_value=("Weekly sync", "The team syncs every "
                                                                         "Monday morning.")):
            page.move_selected()
        self.assertNotIn(self.second.memory_id, page.items)
        titles = {revision.title for revision in self.service.list(limit=50)}
        self.assertIn("Weekly sync", titles)

    def test_move_offers_to_update_a_similar_memory(self):
        existing = self.service.add(title="Dark themes", content="The user seems to like dark themes for long "
                                    "sessions.", source_ref="test")
        self.app.show_page("inbox")
        page = self.app.inbox
        page.tree.selection_set(self.first.memory_id)
        with patch.object(self.app, "edit_before_saving",
                          return_value=("Dark themes", "The user seems to like dark themes for long sessions.")), \
                patch.object(self.app, "confirm", return_value=True):
            page.move_selected()
        current = self.service.read(existing.memory_id)
        self.assertEqual(current.revision_number, 2)
        self.assertEqual(len([r for r in self.service.list(limit=50) if r.title == "Dark themes"]), 1)

    def test_discard_needs_confirmation_and_shows_the_limits(self):
        self.app.show_page("inbox")
        page = self.app.inbox
        page.tree.selection_set(self.first.memory_id, self.second.memory_id)
        with patch.object(self.app, "confirm", return_value=False) as asked:
            page.discard_selected()
        points = asked.call_args.kwargs["points"][0]
        self.assertIn("as far as the app can", points)
        self.assertNotIn("permanently", points.lower())
        self.assertEqual(len(page.items), 2)
        with patch.object(self.app, "confirm", return_value=True):
            page.discard_selected()
        self.assertEqual(page.items, {})

    def test_cleanup_proposals_badge_dashboard_keep_and_discard_now(self):
        due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat().replace("+00:00", "Z")
        self.control.propose_discard([self.first.memory_id], due_at=due)
        self.app.refresh_badges()
        self.assertEqual(self.app.nav["memories"].badge_count, 1)
        self.assertEqual(self.app.dashboard.review_detail.label.cget("text"), "Inbox items to clean up: 1")
        self.assertEqual(self.app.dashboard.review_value.cget("text"), "1")
        self.app.show_page("inbox")
        page = self.app.inbox
        self.assertTrue(page.cleanup.winfo_manager())
        page.keep_proposal(self.control.curation_items()[0])
        self.assertEqual(self.app.nav["memories"].badge_count, 0)
        self.control.propose_discard([self.second.memory_id], due_at=due)
        page.refresh()
        with patch.object(self.app, "confirm", return_value=True):
            page.discard_proposal(self.control.curation_items()[0])
        self.assertEqual(set(page.items), {self.first.memory_id})

    def test_space_picker_switches_memories_and_new_memories_go_there(self):
        self.app.show_page("memories")
        self.assertNotIn("Alpha only", {r.title for r in self.service.list(limit=50)})
        self.app.set_space(self.alpha.space_id)
        self.assertEqual(self.app.memories.space_bar.space.get(), "Alpha")
        self.assertIn("Alpha only", {r.title for r in self.service.list(limit=50)})
        created = self.service.add(title="Alpha rule", content="Alpha releases need two reviewers.",
                                   source_ref="test")
        self.assertEqual(created.scope, self.alpha.curated)
        self.app.set_space("general")
        self.assertNotIn("Alpha rule", {r.title for r in self.service.list(limit=50)})

    def test_saving_mode_switch_needs_confirmation(self):
        self.app.show_page("connections")
        page = self.app.connections
        page.refresh()
        self.root.update()
        with patch.object(self.app, "confirm", return_value=False):
            page.toggle_save_mode("codex")
        self.assertEqual(self.control.connection_settings(self.connections.grant.connection_id)["save_mode"],
                         "curated")
        with patch.object(self.app, "confirm", return_value=True) as asked:
            page.toggle_save_mode("codex")
        self.assertIn("inbox", " ".join(asked.call_args.kwargs["points"]))
        self.assertEqual(self.control.connection_settings(self.connections.grant.connection_id)["save_mode"],
                         "collect")
        self.root.update()
        self.assertIn("Collect", page.cards["codex"].saving_label.cget("text"))

    def test_inbox_settings_are_saved_within_their_ranges(self):
        self.app.show_page("settings")
        settings = self.app.settings
        self.assertEqual(settings.inbox_values["inbox_expire_days"].get(), "30")
        settings.inbox_values["inbox_expire_days"].set("14")
        settings.save_inbox_settings()
        self.assertEqual(self.control.inbox_settings()["inbox_expire_days"], 14)
        settings.inbox_values["file_content_limit"].set("5000")
        settings.save_inbox_settings()
        self.assertEqual(self.control.inbox_settings()["file_content_limit"], 2000)
        self.assertEqual(settings.inbox_values["file_content_limit"].get(), "2000")


if __name__ == "__main__":
    unittest.main()
