# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U1+U2: the unified memory screen on a real Tk window with synthetic data.

Cards and their hover / focus buttons, the drawer (opens on a click, closes with Esc, ×, or the same card; pushes the
cards aside from 1600 px, lies over them below), the window size table (§3.3), keys (E, M, Delete, Esc, Ctrl+Z),
drag and drop onto space chips (only valid chips light up; Undo moves back), retracted memories and Forget
completely (no Undo), the Connections "!", automatic backups in Settings, and the shortcut table.
"""

from __future__ import annotations

import re
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.core.models import MemoryNotFoundError, SourceProvenance
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.inbox import inbox_scope
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from bio_ce.ui.hub import common
from bio_ce.ui.hub.data import ALL_SPACES, INBOX, MEMORIES, RETRACTED, HubData
from bio_ce.ui.shortcuts import SHORTCUTS
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.tk_support import new_tk_root

HOST = SourceProvenance("ai-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})


class FakeTheme:
    def __init__(self, scale: float) -> None:
        self.scale = scale

    def px(self, value: float) -> int:
        return int(round(value * self.scale))


class WindowTableTests(unittest.TestCase):
    """§3.3 as numbers, at 100% and 150% scaling."""

    def test_columns_and_drawer_width_follow_the_window_width(self):
        for scale in (1.0, 1.5):
            theme = FakeTheme(scale)
            rows = ((1000, 1, False), (1100, 2, False), (1599, 2, False), (1600, 3, True), (2199, 3, True),
                    (2200, 4, True), (3000, 4, True))
            for width, columns, push in rows:
                with self.subTest(scale=scale, width=width):
                    window = theme.px(width)
                    self.assertEqual(common.columns_for(window, theme), columns)
                    self.assertEqual(common.pushes(window, theme), push)
            self.assertEqual(common.drawer_width(theme.px(1000), theme), max(theme.px(420), int(theme.px(1000) * .6)))
            self.assertEqual(common.drawer_width(theme.px(1200), theme), theme.px(520))
            self.assertEqual(common.drawer_width(theme.px(1700), theme), theme.px(600))
            self.assertEqual(common.drawer_width(theme.px(2400), theme), theme.px(680))


class HubUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-hub-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.control.set_personal_enabled(True)
        self.general = self.control.space("general")
        self.first = self.service.add(title="Editor", content="The user edits in helix with a dark theme.",
                                      source_ref="test")
        self.second = self.service.add(title="Indent", content="Four spaces, never tabs.", source_ref="test")
        gone = self.service.add(title="Old phone", content="The user's phone number was 555-0100.",
                                source_ref="test")
        self.gone = self.service.retract(gone)
        self.gone_id = gone.memory_id
        self.service.use_space(PERSONAL_SPACE.curated)
        self.private = self.service.add(title="Running", content="The user runs every morning.", source_ref="test")
        self.service.use_space(self.general.curated)
        store = SQLiteMemoryStore(self.paths.user_database)
        self.inbox_item = store.add(inbox_scope(self.general.curated), title="Weekly sync",
                                    content="The team syncs on Mondays.", source=HOST)
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

    def press(self, widget: tk.Misc, sequence: str) -> None:
        """Run ``widget``'s own binding for ``sequence``: generated key events are dropped while another program
        has the keyboard focus (common on a developer desktop)."""
        script = str(widget.bind(sequence))
        self.assertTrue(script, f"{sequence} is not bound on {widget}")
        try:
            widget.tk.eval(re.sub(r"%(.)", lambda m: str(widget) if m.group(1) == "W" else "0", script))
        except tk.TclError as exc:
            if "break" not in str(exc):
                raise
        self.settle()

    def focus(self, widget: tk.Misc) -> None:
        """Keyboard focus without bringing the window forward (tests run off screen, 2026-11-17): Tk gives the
        widget the focus when the window has it, so a card's FocusIn is told to the screen here as Tk would."""
        widget.focus_set()
        if widget in self.hub.grid.cards.values():
            self.hub.card_focused(widget)
        self.settle()

    def card(self, memory_id: str, state: str = MEMORIES):
        return self.hub.grid.cards[f"{state}:{memory_id}"]

    # The screen ---------------------------------------------------------------------------------------------

    def test_one_screen_with_search_chips_tabs_and_cards_from_every_space(self):
        hub = self.hub
        self.assertEqual(list(hub.chips), [ALL_SPACES, "general", "personal"])  # Personal only while it is on
        self.assertEqual({key: tab.text for key, tab in hub.tabs.items()},
                         {"memories": "Memories 3", "inbox": "Inbox 1", "suggestions": "Suggestions 0",
                          "reviews": "Reviews 0"})
        self.assertEqual({item.title for item in hub.items}, {"Editor", "Indent", "Running"})
        self.assertNotIn("Old phone", {item.title for item in hub.items}, "a retracted memory is never current")
        card = self.card(self.private.memory_id)
        self.assertIn("Personal (locked)", card.meta_label._full)
        self.assertEqual(int(card.text_label.max_lines), 2)
        hub.set_space_filter("personal")
        self.assertEqual([item.title for item in hub.items], ["Running"])
        self.assertEqual(self.app.current_space().space_id, "personal")  # new memories go to the chosen space
        hub.query.set("helix")
        hub.set_space_filter(ALL_SPACES)
        self.assertEqual([item.title for item in hub.items], ["Editor"])
        hub.show_state(INBOX)
        self.assertEqual(hub.query.get(), "helix", "the search stays when the tab changes")
        self.assertEqual(hub.items, [])
        hub.search.clear()
        self.assertEqual([item.title for item in hub.items], ["Weekly sync"])

    def test_card_buttons_show_on_hover_and_on_keyboard_focus(self):
        card = self.card(self.first.memory_id)
        self.assertFalse(card.buttons_shown())  # positive control: hidden until the pointer or focus comes
        card.event_generate("<Enter>")
        self.settle()
        self.assertTrue(card.buttons_shown())
        self.assertEqual([b.text for b in card.buttons.values()], ["Edit", "Move", "Delete"])
        card.show_buttons(False)
        self.hub.focus_key = None
        card.focus_set()  # no helper here: only the card's own FocusIn binding may show the buttons and mark it
        card.event_generate("<FocusIn>")
        self.settle()
        self.assertTrue(card.buttons_shown())
        self.assertEqual(self.hub.focus_key, card.key)

    def test_the_drawer_opens_on_a_click_and_closes_with_the_same_card_x_or_esc(self):
        card = self.card(self.first.memory_id)
        self.hub.card_clicked(card)
        self.settle()
        self.assertTrue(self.hub.drawer_open)
        self.assertEqual(self.hub.drawer.record.memory_id, self.first.memory_id)
        self.assertTrue(card.opened)
        self.hub.card_clicked(card)  # the same card again
        self.assertFalse(self.hub.drawer_open)
        self.hub.card_clicked(card)
        self.hub.drawer.close_button.invoke()
        self.assertFalse(self.hub.drawer_open)
        self.hub.card_clicked(card)
        self.focus(card)
        self.hub.keys.escape()
        self.assertFalse(self.hub.drawer_open)
        self.assertFalse(card.opened)

    def test_a_narrow_window_overlaps_the_cards_and_a_wide_one_pushes_them(self):
        hub = self.hub
        self.root.geometry(f"{self.app.theme.px(1000)}x{self.app.theme.px(700)}")
        self.settle()
        before = hub.content.winfo_width()
        hub.card_clicked(self.card(self.first.memory_id))
        self.settle()
        self.assertTrue(hub.drawer_overlaps())
        self.assertEqual(hub.content.winfo_width(), before, "overlapping: the cards keep their width")
        self.assertEqual(hub.grid.columns, 1)
        with patch.object(hub, "window_width", return_value=self.app.theme.px(1700)):
            hub.relayout()
            self.settle()
            self.assertEqual(hub.drawer.winfo_manager(), "pack", "1600 px and wider: pushed aside")
            self.assertFalse(hub.drawer_overlaps())
        with patch.object(hub, "window_width", return_value=self.app.theme.px(1000)):
            hub.relayout()
            hub.close_drawer()
            self.settle()
        self.assertEqual(hub.drawer.winfo_manager(), "")
        self.assertEqual(hub.content.winfo_width(), before, "closed: the cards use the whole width again")

    def test_card_columns_follow_the_window(self):
        with patch.object(self.hub, "window_width", return_value=self.app.theme.px(1200)):
            self.hub.relayout()
        self.assertEqual(self.hub.grid.columns, 2)
        self.root.geometry(f"{self.app.theme.px(900)}x{self.app.theme.px(700)}")
        self.settle()
        self.hub.relayout()
        self.assertEqual(self.hub.grid.columns, 1)

    def test_the_drawer_keeps_a_reading_width_and_its_actions_on_top(self):
        hub = self.hub
        long_text = "A very long line of memory text that keeps going. " * 80
        record = self.service.read(self.second.memory_id)
        self.service.revise(record, title="Indent", content=long_text, source_ref="test")
        hub.refresh()
        hub.card_clicked(self.card(self.second.memory_id))
        self.settle()
        drawer = hub.drawer
        self.assertEqual(drawer.reader.get_text(), long_text)
        self.assertLessEqual(drawer.column.winfo_width(), self.app.theme.px(common.READING_WIDTH) + 2)
        top = drawer.action_row.winfo_rooty()
        drawer.scroll.canvas.yview_moveto(1.0)  # scrolled to the end: the action row does not move
        self.settle()
        self.assertEqual(drawer.action_row.winfo_rooty(), top)
        self.assertTrue(drawer.edit_button.winfo_viewable())

    # Edit, add ------------------------------------------------------------------------------------------------

    def test_edit_in_place_saves_with_enter_and_keeps_history(self):
        hub = self.hub
        hub.card_clicked(self.card(self.first.memory_id))
        self.settle()
        hub.drawer.title_label.event_generate("<Button-1>")  # clicking the title edits it there
        self.settle()
        self.assertTrue(hub.drawer.editing)
        self.app.title_value.set("Editor (helix)")
        self.press(hub.drawer.editor.title_field.entry, "<Return>")  # Enter in the title saves
        self.assertEqual(self.service.read(self.first.memory_id).title, "Editor (helix)")
        self.assertEqual(self.service.read(self.first.memory_id).revision_number, 2)
        self.assertFalse(hub.drawer.editing)
        self.assertEqual(hub.drawer.record.title, "Editor (helix)")
        hub.drawer.open_history()
        self.settle()
        self.assertIn("2 revisions", hub.drawer.history.label)

    def test_ctrl_n_adds_to_the_space_chosen_in_the_form(self):
        self.hub.keys.app.start_new_memory()
        self.settle()
        editor = self.hub.drawer.editor
        self.assertTrue(editor.space_row.winfo_manager())
        editor.space_picker.current(1)  # Personal
        editor._space_chosen()
        self.app.title_value.set("Dentist")
        self.app.content_value.insert("1.0", "The dentist is on Elm Street.")
        self.press(editor.content.text, "<Control-Return>")  # Ctrl+Enter in the text saves
        self.service.use_space(PERSONAL_SPACE.curated)
        self.assertIn("Dentist", {r.title for r in self.service.list()})
        self.service.use_space(self.general.curated)
        self.assertNotIn("Dentist", {r.title for r in self.service.list()})

    # Keys -------------------------------------------------------------------------------------------------------

    def test_keys_e_delete_and_ctrl_z_act_on_the_focused_card_but_not_while_typing(self):
        hub = self.hub
        card = self.card(self.first.memory_id)
        self.focus(card)
        hub.keys.edit()  # E
        self.assertTrue(hub.drawer.editing)
        self.app.editor.cancel_edit()
        hub.close_drawer(force=True)
        self.focus(hub.search.entry)
        hub.focus_key = card.key
        hub.keys.delete()  # Delete while typing in the search box: nothing happens
        self.assertEqual(self.app.pending.hidden(), frozenset())
        self.focus(card)
        hub.keys.delete()
        self.assertEqual(self.app.pending.hidden(), {self.first.memory_id})  # positive control
        hub.keys.undo()  # Ctrl+Z
        self.assertEqual(self.app.pending.hidden(), frozenset())
        self.assertEqual(self.service.read(self.first.memory_id).revision_number, 1)

    def test_m_opens_the_move_menu_for_the_selected_cards(self):
        hub = self.hub
        hub.card_clicked(self.card(self.first.memory_id))
        hub.toggle_select(self.card(self.second.memory_id))
        self.focus(self.card(self.first.memory_id))
        with patch.object(tk.Menu, "tk_popup") as popped:
            hub.keys.move()
        popped.assert_called_once()

    # Drag and drop ----------------------------------------------------------------------------------------------

    def test_dragging_cards_onto_a_chip_moves_them_after_a_backup_and_undo_moves_them_back(self):
        hub = self.hub
        items = [self.card(self.first.memory_id).item, self.card(self.second.memory_id).item]
        self.assertTrue(hub.drag.begin(items))
        self.assertEqual(hub.drop_highlight, {"personal"})  # not All spaces, not General (where they are)
        self.assertFalse(hub.chips["general"].enabled)
        self.assertTrue(hub.chips["personal"].enabled)
        hub.drag.hover("personal")
        self.assertEqual(hub.chips["personal"].variant, "primary")
        with patch.object(self.app, "notify") as notice:
            self.assertEqual(hub.drag.finish("personal"), 2)
        self.assertEqual(hub.drop_highlight, set())
        self.service.use_space(PERSONAL_SPACE.curated)
        self.assertEqual({r.title for r in self.service.list()}, {"Editor", "Indent", "Running"})
        backups = list((self.paths.user_database.parent / "backups").glob("auto-before-move-*.sqlite3"))
        self.assertEqual(len([b for b in backups if not b.name.endswith(".control.sqlite3")]), 1)
        label, undo = notice.call_args.kwargs["action"]
        self.assertEqual(label, "Undo")
        self.assertEqual(undo(), 2)
        self.service.use_space(self.general.curated)
        self.assertEqual({r.title for r in self.service.list()}, {"Editor", "Indent"})

    def test_a_drop_on_the_chip_they_are_in_does_nothing(self):
        hub = self.hub
        items = [self.card(self.first.memory_id).item]
        self.assertTrue(hub.drag.begin(items))
        self.assertIsNone(hub.drag.finish("general"))
        self.assertIsNone(hub.drag.finish(None))
        self.assertEqual({r.title for r in self.service.list()}, {"Editor", "Indent"})
        self.assertFalse((self.paths.user_database.parent / "backups").exists(), "no move, no backup")
        self.assertFalse(hub.drag.begin([]))  # positive control: nothing to drag lights up nothing

    def test_an_inbox_card_can_be_dragged_to_another_space_inbox(self):
        hub = self.hub
        hub.show_state(INBOX)
        item = self.card(self.inbox_item.memory_id, INBOX).item
        self.assertTrue(hub.drag.begin([item]))
        self.assertEqual(hub.drag.finish("personal"), 1)
        self.service.use_space(PERSONAL_SPACE.curated)
        self.assertEqual([i.title for i in self.service.inbox()], ["Weekly sync"])

    # Retracted memories and Forget completely -------------------------------------------------------------------

    def test_retracted_memories_are_found_and_can_only_be_forgotten(self):
        hub = self.hub
        self.assertTrue(hub.retracted_tab.winfo_manager())
        self.assertEqual(hub.retracted_tab.text, "Deleted memories 1")
        hub.show_state(RETRACTED)
        self.assertEqual([item.title for item in hub.items], ["Old phone"])
        card = self.card(self.gone_id, RETRACTED)
        self.assertEqual(list(card.buttons), ["forget"])
        self.assertIn("deleted", card.meta_label._full)
        hub.card_clicked(card)
        self.settle()
        self.assertEqual(hub.drawer.reader.get_text(), "The user's phone number was 555-0100.")  # its last text
        self.assertTrue(hub.drawer.forget_action.winfo_manager())
        self.assertFalse(hub.drawer.edit_button.winfo_manager() or hub.drawer.delete_button.winfo_manager())
        self.assertEqual(hub.drop_targets([card.item]), set(), "a retracted card can't be dragged")
        with patch.object(self.app, "confirm", return_value=False) as asked:
            self.assertFalse(hub.forget_item(card.item))
        self.assertEqual(len(self.service.retracted()), 1, "cancelled: nothing erased")
        points = " ".join(asked.call_args.kwargs["points"])
        self.assertIn("can't be undone", points)
        self.assertIn("Backups and exports you made earlier still contain it", points)
        with patch.object(self.app, "confirm", return_value=True), patch.object(self.app, "notify") as notice:
            self.assertTrue(hub.forget_item(card.item))
        self.assertIsNone(notice.call_args.kwargs.get("action"), "Forget completely has no Undo")
        self.assertEqual(self.service.retracted(), ())
        self.assertEqual(hub.items, [])
        self.assertTrue(hub.empty_retracted.winfo_manager())

    def test_forget_completely_from_the_drawer_erases_a_current_memory(self):
        hub = self.hub
        hub.card_clicked(self.card(self.first.memory_id))
        self.settle()
        self.assertTrue(hub.drawer.danger.winfo_manager())  # the danger area, since the service can forget
        with patch.object(self.app, "confirm", return_value=True) as asked, \
                patch.object(self.app, "notify") as notice:
            hub.drawer.forget_button.invoke()
        self.assertEqual(asked.call_args.kwargs["quote"], "Editor")
        self.assertTrue(asked.call_args.kwargs["danger"])
        self.assertIsNone(notice.call_args.kwargs.get("action"))
        with self.assertRaises(MemoryNotFoundError):
            self.service.read(self.first.memory_id)
        self.assertNotIn(self.first.memory_id, {entry.last.memory_id for entry in self.service.retracted()})
        self.assertFalse(hub.drawer_open)

    def test_a_forget_that_waits_for_another_reader_says_so(self):
        hub = self.hub
        hub.card_clicked(self.card(self.first.memory_id))
        from bio_ce.inbox import ForgetResult
        waiting = ForgetResult(item_id=1, deleted=1, kept=0, reviews=0, completed=False)
        with patch.object(self.app, "confirm", return_value=True), \
                patch.object(self.app.service, "forget", return_value=waiting), \
                patch.object(self.app, "schedule_cleanup_retry") as retry, patch.object(self.app, "notify") as notice:
            self.assertTrue(hub.forget_item(hub.drawer.item))
        self.assertIn("finishes erasing it", notice.call_args.args[1])
        retry.assert_called_once()

    def test_without_forget_in_the_service_the_button_is_not_shown(self):
        # A service without the method (an older one): neither the danger area nor the retracted view appears.
        service = self.app.service

        class Older:
            def __getattr__(self, name):
                if name in ("forget", "retracted", "retracted_count"):
                    raise AttributeError(name)
                return getattr(service, name)

        with patch.object(self.app, "service", Older()):
            self.hub.refresh()
            self.hub.card_clicked(self.card(self.first.memory_id))
            self.settle()
            self.assertFalse(self.hub.drawer.danger.winfo_manager())
            self.assertFalse(self.hub.retracted_tab.winfo_manager())
            self.assertEqual(HubData(self.app).items(RETRACTED, ALL_SPACES), [])
        self.hub.refresh()
        self.hub.open_item(self.card(self.first.memory_id).item)
        self.settle()
        self.assertTrue(self.hub.drawer.danger.winfo_manager())  # positive control
        self.assertTrue(self.hub.retracted_tab.winfo_manager())

    # Shell: badges, settings, shortcuts -------------------------------------------------------------------------

    def test_connections_shows_an_alert_only_for_a_connection_problem(self):
        nav = self.app.nav["connections"]
        self.app.refresh_badges()
        self.assertFalse(nav.badge.winfo_manager())
        conflict = type("Status", (), {"configuration_conflict": True})()
        with patch.dict(self.app._host_statuses, {"codex": conflict}):
            self.app.refresh_badges()
            self.assertTrue(nav.badge.winfo_manager())
            self.assertEqual(nav.badge.cget("text"), "!")
        self.app.refresh_badges()
        self.assertFalse(nav.badge.winfo_manager())

    def test_settings_keeps_the_chosen_number_of_automatic_backups(self):
        self.app.show_page("settings")
        settings = self.app.settings
        self.assertEqual(settings.auto_backup_value.get(), str(self.control.auto_backup_keep()))
        settings.auto_backup_value.set("5")
        self.assertEqual(settings.save_auto_backup_keep(), 5)
        self.assertEqual(self.control.auto_backup_keep(), 5)
        for wrong in ("0", "101", "ten"):
            settings.auto_backup_value.set(wrong)
            with patch.object(self.app, "notify") as notice:
                self.assertIsNone(settings.save_auto_backup_keep())
            self.assertEqual(notice.call_args.args[0], "error")
            self.assertEqual(self.control.auto_backup_keep(), 5)

    def test_every_window_key_in_the_shortcut_table_is_bound_and_listed(self):
        for shortcut in SHORTCUTS:
            for sequence in shortcut.sequences:
                with self.subTest(sequence=sequence):
                    self.assertTrue(self.root.bind(sequence), f"{sequence} is listed but not bound")
        self.app.show_page("settings")
        self.assertEqual(len(self.app.settings.shortcut_rows), len(SHORTCUTS))
        self.assertFalse(self.root.bind("<Control-q>"))  # positive control: an unbound key reads as empty


if __name__ == "__main__":
    unittest.main()
