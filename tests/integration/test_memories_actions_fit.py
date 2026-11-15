# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The Memories page's buttons are never cut off, even in the smallest window (v0.4.3-rc1 GUI check P13).

A button that pack has to shrink still shows part of its label, but a click on it does nothing (the click must land
inside the button). In 0.4.3-rc1 "Move to…" joined Edit, History, and Retract in one row of the reading pane, and at
a normal window size Move to… and Retract were cut off.
"""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.spaces import PERSONAL_SPACE
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


class MemoriesActionsFitTests(unittest.TestCase):
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
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.page = self.app.memories

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def show(self, width: int, height: int, page: str = "memories") -> None:
        self.root.geometry(f"{width}x{height}+20+20")
        self.app.show_page(page)
        if page == "memories":
            self.page.refresh()
            rows = self.page.tree.get_children()
            self.page.select(rows[0])  # a memory of the space shown, so the reading pane is open
        for _ in range(6):
            self.root.update()

    def buttons(self, page: str) -> dict:
        target = self.app.memories if page == "memories" else self.app.inbox
        found = {f"{page}.space_bar.{name}": getattr(target.space_bar, name)
                 for name in ("memories_tab", "inbox_tab", "suggestions_tab", "picker")}
        if page == "memories":
            found.update({f"memories.{name}": getattr(target, name) for name in (
                "edit_button", "history_button", "retract_button", "move_button", "export_button", "add_button")})
        else:
            found["inbox.import_button"] = target.import_button
        return found

    def check_every_width(self, label: str) -> None:
        # Every 20 px from the smallest window up: the sidebar switches modes at 1000 px, which an earlier version
        # of this test skipped (and where Retract was cut off).
        for space in ("general", "personal"):
            self.app.set_space(space)
            for page in ("memories", "inbox"):
                for width in range(860, 1301, 20):
                    self.show(width, 700, page)
                    for name, widget in self.buttons(page).items():
                        with self.subTest(fonts=label, space=space, width=width, widget=name):
                            self.assertTrue(widget.winfo_ismapped(), "not shown")
                            self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth(), "cut off")

    def test_no_button_is_cut_off_at_any_width(self):
        self.check_every_width("default")

    def widen_fonts(self, factor: float) -> None:
        for font in self.app.theme.fonts.values():
            size = int(font.cget("size"))
            font.configure(size=round(size * factor) if size > 0 else -round(-size * factor))

    def test_no_button_is_cut_off_with_wider_fonts_either(self):
        """CI runners and other PCs render wider text; 25% wider fonts must still fit (wrapping is fine)."""
        self.widen_fonts(1.25)
        self.check_every_width("125%")

    def test_no_button_is_cut_off_with_much_wider_fonts(self):
        """A margin beyond what the CI runner showed (its text was about 15-25% wider than this PC's)."""
        self.widen_fonts(1.5)
        self.check_every_width("150%")

    def test_move_works_from_the_list_and_from_the_right_click_menu(self):
        self.show(960, 760)
        self.page.tree.selection_set((self.first.memory_id, self.second.memory_id))
        self.root.update()
        with patch.object(self.app, "ask_choice", return_value="personal"):
            self.page.move_button.invoke()
        self.assertEqual(self.service.list(), ())
        self.service.use_space(PERSONAL_SPACE.curated)
        self.assertEqual({r.memory_id for r in self.service.list()},
                         {self.first.memory_id, self.second.memory_id, self.private.memory_id})
        self.app.set_space("personal")
        self.page.refresh()
        self.page.tree.selection_set((self.first.memory_id,))
        menu = self.page.context_menu()
        labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)
                  if menu.type(index) in ("command", "cascade")]
        self.assertEqual(labels, ["Edit", "History", "Move to", "Retract…"])
        submenu = self.page.nametowidget(menu.entrycget(labels.index("Move to"), "menu"))
        spaces = [submenu.entrycget(index, "label") for index in range(submenu.index("end") + 1)]
        self.assertEqual(spaces, ["General"])  # the space shown now (Personal) is not offered
        with patch.object(self.app, "ask_choice", side_effect=AssertionError("the submenu already chose")):
            submenu.invoke(0)
        self.service.use_space(self.connections.control.space("general").curated)
        self.assertEqual([r.memory_id for r in self.service.list()], [self.first.memory_id])

    def test_right_click_on_an_unselected_row_selects_it_first(self):
        self.show(960, 760)
        self.page.tree.selection_set((self.first.memory_id,))
        self.root.update()
        bbox = self.page.tree.bbox(self.second.memory_id)
        event = type("Event", (), {"x": bbox[0] + 5, "y": bbox[1] + 5, "x_root": 0, "y_root": 0})()
        with patch.object(tk_menu_type(), "tk_popup") as popped:
            self.page._right_click(event)
        self.assertEqual(self.page.tree.selection(), (self.second.memory_id,))
        popped.assert_called_once()
        self.page.tree.selection_set((self.first.memory_id, self.second.memory_id))
        with patch.object(tk_menu_type(), "tk_popup"):
            self.page._right_click(event)
        self.assertEqual(set(self.page.tree.selection()), {self.first.memory_id, self.second.memory_id})


def tk_menu_type():
    import tkinter as tk
    return tk.Menu


if __name__ == "__main__":
    unittest.main()
