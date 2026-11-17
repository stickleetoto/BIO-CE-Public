# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The memory screen's buttons are never cut off, even in the smallest window (v0.4.3-rc1 GUI check P13).

A button that pack has to shrink still shows part of its label, but a click on it does nothing (the click must land
inside the button). In 0.4.3-rc1 "Move to…" joined Edit, History, and Retract in one row of the reading pane, and at
a normal window size Move to… and Retract were cut off. v0.4.4 replaced that pane with the drawer (its action row is
fixed at the top) and the Memories / Inbox / Suggestions bar with space chips and state tabs; the same sweep covers
them.
"""

from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.ui.hub.data import ALL_SPACES, INBOX, MEMORIES
from bio_ce.ui.widgets import FlowFrame
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


class MemoriesActionsFitTests(unittest.TestCase):
    SCREEN: tuple[int, int] | None = None
    DPI = 96.0

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-actions-fit-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.first = self.service.add(title="시험용: 이동 A", content="난 천재다", source_ref="test")
        self.second = self.service.add(title="시험용: 이동 B", content="둘째", source_ref="test")
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.connections.control.set_personal_enabled(True)
        self.service.use_space(PERSONAL_SPACE.curated)
        self.private = self.service.add(title="시험용: 개인 메모", content="개인", source_ref="test")
        self.service.use_space(self.connections.control.space("general").curated)
        self.root = new_root()
        if self.SCREEN is None:
            self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        else:  # the app sizes its first window from the screen; pretend the screen is small, as on a CI runner
            screen = (patch.object(self.root, "winfo_screenwidth", return_value=self.SCREEN[0]),
                      patch.object(self.root, "winfo_screenheight", return_value=self.SCREEN[1]),
                      patch.object(self.root, "winfo_fpixels", return_value=self.DPI))
            with screen[0], screen[1], screen[2]:
                self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.hub = self.app.memories

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def show(self, width: int, height: int, state: str = MEMORIES) -> None:
        self.root.geometry(f"{width}x{height}+20+20")
        self.app.open_state(state)
        if state == MEMORIES and self.hub.items:
            self.hub.open_item(self.hub.items[0])  # the drawer is open, so its action row is checked
        for _ in range(6):
            self.root.update()

    def buttons(self, state: str) -> dict:
        hub = self.hub
        found = {"toolbar.add": hub.add_button, "toolbar.import": hub.import_button, "toolbar.export": hub.export_button}
        found.update({f"chip.{key}": chip for key, chip in hub.chips.items()})
        found.update({f"tab.{key}": tab for key, tab in hub.tabs.items()})
        if state == MEMORIES:
            drawer = hub.drawer
            found.update({f"drawer.{name}": getattr(drawer, name) for name in (
                "edit_button", "move_button", "history_button", "delete_button", "close_button")})
        return found

    def check_every_width(self, label: str) -> None:
        """Every 20 px from the smallest window up, for all spaces and Personal alone, on Memories and Inbox.

        The sidebar switches modes at 1000 px, which an earlier version of this test skipped (Retract was cut off
        there). All problems are collected and reported together with the geometry, so a CI failure says exactly
        which widget, at which size, and why.
        """
        problems: list[str] = []
        for space in (ALL_SPACES, "personal"):
            self.hub.set_space_filter(space)
            for state in (MEMORIES, INBOX):
                for width in range(860, 1301, 20):
                    self.show(width, 700, state)
                    for name, widget in self.buttons(state).items():
                        mapped = bool(widget.winfo_ismapped())
                        if mapped and widget.winfo_width() >= widget.winfo_reqwidth():
                            continue
                        master = widget.nametowidget(widget.winfo_parent())
                        problems.append(
                            f"{label} {space} {state} {width}px {name}: mapped={mapped} viewable="
                            f"{bool(widget.winfo_viewable())} size={widget.winfo_width()}/{widget.winfo_reqwidth()} at "
                            f"{widget.winfo_x()},{widget.winfo_y()} manager={widget.winfo_manager()} master="
                            f"{master.winfo_width()}x{master.winfo_height()} root={self.root.winfo_width()}x"
                            f"{self.root.winfo_height()} screen={self.root.winfo_screenwidth()}x"
                            f"{self.root.winfo_screenheight()} root_state={self.root.state()}")
        newline = chr(10)
        self.assertEqual(problems, [], f"{len(problems)} problems; first ones:{newline}"
                         + newline.join(problems[:25]))

    def test_no_button_is_cut_off_at_any_width(self):
        self.check_every_width("default")

    def widen_fonts(self, factor: float) -> None:
        """Wider text, as on another PC. The app never changes fonts while it runs, so lay out again afterwards,
        as a restart would."""
        for font in self.app.theme.fonts.values():
            size = int(font.cget("size"))
            font.configure(size=round(size * factor) if size > 0 else -round(-size * factor))
        self.root.update()
        pending = [self.root]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, FlowFrame):
                widget.relayout()
        self.root.update()

    def test_no_button_is_cut_off_with_wider_fonts_either(self):
        """CI runners and other PCs render wider text; 25% wider fonts must still fit (wrapping is fine)."""
        self.widen_fonts(1.25)
        self.check_every_width("125%")

    def test_no_button_is_cut_off_with_much_wider_fonts(self):
        """A margin beyond what the CI runner showed (its text was about 15-25% wider than this PC's). Before v0.4.4
        this needed a tall screen (the reading pane's height); the drawer's action row does not."""
        self.widen_fonts(1.5)
        self.check_every_width("150%")

    def test_move_works_from_the_card_menu_and_from_the_right_click_menu(self):
        self.show(960, 760)
        cards = {card.item.item_id: card for card in self.hub.grid.card_list()}
        self.hub.card_clicked(cards[self.first.memory_id])
        self.hub.toggle_select(cards[self.second.memory_id])  # Ctrl+click: two selected
        with patch.object(tk.Menu, "tk_popup"):
            menu = self.hub.move_menu([cards[self.first.memory_id].item], cards[self.first.memory_id])
        labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)]
        self.assertEqual(labels, ["Personal"])  # the space they are in (General) is not offered
        menu.invoke(0)
        self.service.use_space(self.connections.control.space("general").curated)
        self.assertEqual(self.service.list(), ())
        self.service.use_space(PERSONAL_SPACE.curated)
        self.assertEqual({r.memory_id for r in self.service.list()},
                         {self.first.memory_id, self.second.memory_id, self.private.memory_id})
        self.app.set_space("personal")
        card = next(card for card in self.hub.grid.card_list() if card.item.item_id == self.first.memory_id)
        menu = self.hub.context_menu([card.item])
        labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)
                  if menu.type(index) in ("command", "cascade")]
        self.assertEqual(labels, ["Edit", "History", "Move to", "Copy", "Delete", "Forget completely…"])
        submenu = self.hub.nametowidget(menu.entrycget(labels.index("Move to"), "menu"))
        spaces = [submenu.entrycget(index, "label") for index in range(submenu.index("end") + 1)]
        self.assertEqual(spaces, ["General"])  # the space it is in (Personal) is not offered
        with patch.object(self.app, "ask_choice", side_effect=AssertionError("the submenu already chose")):
            submenu.invoke(0)
        self.service.use_space(self.connections.control.space("general").curated)
        self.assertEqual([r.memory_id for r in self.service.list()], [self.first.memory_id])

    def test_right_click_on_an_unselected_card_selects_it_first(self):
        self.show(960, 760)
        cards = {card.item.item_id: card for card in self.hub.grid.card_list()}
        self.hub.card_clicked(cards[self.first.memory_id])
        event = type("Event", (), {"x_root": 0, "y_root": 0})()
        with patch.object(tk.Menu, "tk_popup") as popped:
            self.hub.context_menu_at(cards[self.second.memory_id], event)
        self.assertEqual(self.hub.selected_keys, {cards[self.second.memory_id].key})
        popped.assert_called_once()
        self.hub.toggle_select(cards[self.first.memory_id])
        with patch.object(tk.Menu, "tk_popup"):
            self.hub.context_menu_at(cards[self.second.memory_id], event)
        self.assertEqual(self.hub.selected_keys, {cards[self.first.memory_id].key, cards[self.second.memory_id].key})


class SmallScreenFitTests(MemoriesActionsFitTests):
    """The window first opens small, as on a 1024x768 screen (the CI runner). There the reading pane once got only
    42 px, because the wrapping button row asked for no width at all."""

    SCREEN = (1024, 768)
    DPI = 120.0  # 125% display scaling: the app's 860 px minimum becomes 1075 px, so the window stays 972 px wide

    test_move_works_from_the_card_menu_and_from_the_right_click_menu = None
    test_right_click_on_an_unselected_card_selects_it_first = None


if __name__ == "__main__":
    unittest.main()
