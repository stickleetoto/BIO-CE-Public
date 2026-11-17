# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U4, the conveniences the owner chose (design §5): search above every page and / (F1), the ? list of keys
(F3), filters and sort that are remembered (F4), quick add (F5), several cards at once with Shift+click and a bar
(F7), and copying a memory's text (F10). Real Tk window, synthetic data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY, ControlStore, control_database_for
from bio_ce.core.models import MemoryNotFoundError, SourceProvenance
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from bio_ce.ui.dialogs import ShortcutsDialog
from bio_ce.ui.hub import filters
from bio_ce.ui.hub.data import MEMORIES
from bio_ce.ui.hub.quick import copy_items, split_quick_text
from bio_ce.ui.shortcuts import SHORTCUTS
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.tk_support import new_tk_root

OLD = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds").replace("+00:00", "Z")


class ConveniencesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-u4-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        general = self.control.space("general").curated
        self.added = self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        store = SQLiteMemoryStore(self.paths.user_database)
        self.imported = store.add(general, title="Clinic", content="The user's clinic visit is in May.",
                                  source=SourceProvenance("user-imported", "import:batch-1",
                                                          {"sensitive": ["health"]}), recorded_at=OLD)
        self.codex = store.add(general, title="Deploys", content="The team deploys on Fridays.",
                               source=SourceProvenance("ai-auto-memory", "codex:conn-1", {"host": "codex"}))
        self.claude = store.add(general, title="Answers", content="Answers are short and direct.",
                                source=SourceProvenance("ai-suggested-user-approved", "claude:review-3",
                                                        {"host": "claude"}))
        store.close()
        self.root = new_tk_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.after_cancel(self.app._maintenance_after)
        self.root.geometry(f"{self.app.theme.px(1300)}x{self.app.theme.px(800)}+0+0")
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

    def titles(self) -> list[str]:
        return [item.title for item in self.hub.items]

    # F4 ---------------------------------------------------------------------------------------------------------

    def test_filters_narrow_the_cards_and_the_sort_orders_them(self):
        bar = self.hub.filter_bar
        self.assertTrue(bar.winfo_ismapped())
        self.assertEqual(len(self.hub.items), 4)  # positive control: everything without a filter
        for key, value, wanted in (("source", "imported", ["Clinic"]), ("source", "ai", None),
                                   ("source", "added", ["Editor"])):
            bar.set(key, value)
            self.settle()
            if wanted is None:
                self.assertEqual(sorted(self.titles()), ["Answers", "Deploys"])
            else:
                self.assertEqual(self.titles(), wanted)
        bar.set("source", "any")
        bar.set("host", "codex")
        self.settle()
        self.assertEqual(self.titles(), ["Deploys"])
        bar.set("host", "claude")
        self.assertEqual(self.titles(), ["Answers"])
        bar.set("host", "any")
        bar.set("period", "30d")
        self.assertNotIn("Clinic", self.titles())  # changed 60 days ago
        bar.set("period", "any")
        bar.set("sensitive", "only")
        self.assertEqual(self.titles(), ["Clinic"])
        bar.clear()
        self.settle()
        self.assertEqual(len(self.hub.items), 4)
        self.assertFalse(bar.clear_button.winfo_ismapped())  # nothing to clear
        bar.set("sort", "title")
        self.assertEqual(self.titles(), ["Answers", "Clinic", "Deploys", "Editor"])
        bar.set("sort", "created")
        self.assertEqual(self.titles()[-1], "Clinic")  # saved with a date 60 days back: the oldest
        bar.set("sort", "changed")
        self.assertEqual(self.titles()[-1], "Clinic")

    def test_a_filter_with_no_match_says_so_and_offers_nothing_else(self):
        self.hub.filter_bar.set("host", "claude_desktop")
        self.settle()
        self.assertEqual(self.hub.items, [])
        self.assertTrue(self.hub.no_results.winfo_ismapped())

    def test_the_filters_are_remembered(self):
        self.hub.filter_bar.set("source", "imported")
        self.hub.filter_bar.set("sort", "title")
        self.assertEqual(self.control.hub_view()["source"], "imported")
        again = filters.FilterBar(self.hub.tools, self.app, lambda _v: None)
        self.assertEqual((again.view["source"], again.view["sort"]), ("imported", "title"))
        again.destroy()

    def test_a_damaged_or_unknown_stored_view_reads_as_the_default(self):
        with self.assertRaises(ValueError):
            self.control.set_hub_view({"source": "everywhere"})
        self.control._connection.execute("INSERT OR REPLACE INTO app_settings (key, value, updated_at) "
                                         "VALUES ('hub_view', '{not json', '2026-11-17T00:00:00Z')")
        self.assertEqual(self.control.hub_view(), filters.DEFAULT)

    # F5 ---------------------------------------------------------------------------------------------------------

    def test_quick_add_saves_in_the_shown_space_and_can_be_undone(self):
        quick = self.hub.quick_add
        self.assertTrue(quick.winfo_ismapped())
        quick.text.set("The user prefers decaf after 3 pm. It helps with sleep.")
        saved = quick.save()
        self.settle()
        self.assertEqual((saved.title, saved.content),
                         ("The user prefers decaf after 3 pm.", "The user prefers decaf after 3 pm. It helps with "
                                                                "sleep."))
        self.assertEqual(quick.text.get(), "")
        self.assertIn("The user prefers decaf after 3 pm.", self.titles())
        undo = self.app.infobar.action_button
        undo.invoke()
        self.settle()
        with self.assertRaises(MemoryNotFoundError):
            self.service.read(saved.memory_id)

    def test_quick_add_refuses_a_secret(self):
        before = len(self.service.list())
        self.hub.quick_add.text.set("github token ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8")
        self.assertIsNone(self.hub.quick_add.save())
        self.assertEqual(len(self.service.list()), before)

    def test_a_long_line_gets_a_short_title(self):
        title, text = split_quick_text("word " * 40)
        self.assertLessEqual(len(title), 61)
        self.assertTrue(title.endswith("…"))
        self.assertEqual(text, " ".join(["word"] * 40))

    # F7 ---------------------------------------------------------------------------------------------------------

    def cards(self):
        return self.hub.grid.card_list()

    def test_shift_click_selects_a_range_and_the_bar_acts_on_all(self):
        cards = self.cards()
        self.hub.card_clicked(cards[0])
        self.hub.close_drawer(force=True)
        self.assertFalse(self.hub.selection_bar.winfo_ismapped())  # one card: no bar
        self.hub.card_clicked(cards[2], extend=True)
        self.settle()
        self.assertEqual(self.hub.selected_keys, {card.key for card in cards[:3]})
        self.assertTrue(self.hub.selection_bar.winfo_ismapped())
        self.assertEqual(self.hub.selection_bar.count_label.cget("text"), "3 selected")
        self.hub.selection_bar.delete_button.invoke()
        self.settle()
        self.assertEqual(len(self.app.pending.hidden()), 3)  # all three wait for Undo together
        self.app.pending.undo()
        self.hub.refresh()
        self.settle()
        self.assertEqual(len(self.hub.items), 4)

    def test_the_bar_exports_the_chosen_memories_and_clear_hides_it(self):
        cards = self.cards()
        self.hub.card_clicked(cards[0], toggle=True)
        self.hub.card_clicked(cards[1], toggle=True)
        target = Path(self.temp.name) / "chosen.md"
        with patch.object(self.app, "ask_save_path", return_value=str(target)):
            written = self.hub.selection_bar.export()
        lines = Path(written).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.startswith("[") and "] - " in line for line in lines))
        self.hub.selection_bar.clear_button.invoke()
        self.settle()
        self.assertEqual(self.hub.selected_keys, set())
        self.assertFalse(self.hub.selection_bar.winfo_ismapped())

    # F10 --------------------------------------------------------------------------------------------------------

    def test_copy_puts_the_title_and_text_on_the_clipboard(self):
        item = next(item for item in self.hub.items if item.title == "Editor")
        self.assertTrue(copy_items(self.app, [item]))
        self.assertEqual(self.root.clipboard_get(), "Editor\nThe user edits in helix.")
        self.hub.open_item(item)
        self.settle()
        self.assertTrue(self.hub.drawer.copy_button.winfo_ismapped())

    # F1 and F3 --------------------------------------------------------------------------------------------------

    def test_the_search_above_other_pages_opens_the_results_on_the_memory_screen(self):
        self.app.show_page("dashboard")
        self.settle()
        self.assertTrue(self.app.header_search.winfo_ismapped())
        self.app.header_query.set("Fridays")
        self.app._search_from_header()
        self.settle()
        self.assertIs(self.app.current, self.hub)
        self.assertFalse(self.app.header_search.winfo_ismapped())  # the screen's own search is there
        self.assertEqual(self.titles(), ["Deploys"])

    def test_slash_and_ctrl_f_go_to_the_search_and_question_mark_lists_the_keys(self):
        self.app.show_page("dashboard")
        self.settle()
        with patch.object(self.app.header_search, "focus_set") as focused:
            self.app.focus_search()
        focused.assert_called_once()
        self.app.show_page("memories")
        with patch.object(self.hub.search, "focus_set") as focused:
            self.app.focus_search()
        focused.assert_called_once()
        bound = {sequence for sequence in ("<slash>", "<question>") if self.root.bind(sequence)}
        self.assertEqual(bound, {"<slash>", "<question>"})
        dialog = self.app.show_shortcuts()
        try:
            self.assertIsInstance(dialog, ShortcutsDialog)
            self.assertEqual(len(dialog.rows), len(SHORTCUTS))
        finally:
            dialog.destroy()

    def test_single_keys_type_in_a_text_box_instead_of_acting(self):
        self.hub.search.entry.focus_set()
        self.settle()
        with patch.object(self.app, "typing", return_value=True), patch.object(self.app, "show_shortcuts") as shown:
            self.root.event_generate("<question>")
            self.settle()
        shown.assert_not_called()


class StoreFactsTests(unittest.TestCase):
    def test_sensitive_marks_and_created_dates_are_read_for_one_space(self):
        with tempfile.TemporaryDirectory(prefix="bio-ce-u4-facts-") as folder:
            database = Path(folder) / "data" / "memories.sqlite3"
            service = DesktopMemoryService(database)
            try:
                plain = service.add(title="Plain", content="Nothing sensitive.", source_ref="test")
                marked = service._store.add(service.scope, title="Clinic", content="Clinic in May.",
                                            source=SourceProvenance("user-imported", "import:1",
                                                                    {"sensitive": ["health"]}))
                facts = service.memory_facts()
                self.assertEqual((facts[plain.memory_id]["sensitive"], facts[marked.memory_id]["sensitive"]),
                                 (False, True))
                self.assertTrue(facts[plain.memory_id]["created_at"])
                text = service.export_selected([marked.memory_id, "mem_missingmissing"])
                self.assertEqual(len(text.splitlines()), 1)
            finally:
                service.close()
                control = ControlStore(control_database_for(database))
                control.close()


if __name__ == "__main__":
    unittest.main()
