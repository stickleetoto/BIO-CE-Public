# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""A scrolling area keeps its view on the content when the content gets shorter (GUI check, 2026-11-15).

After an import the preview closed while the view was scrolled down to it, and the page looked empty. The same
happens to any list whose items are removed while scrolled down (Suggestions after "Approve all shown…").
"""

from __future__ import annotations

import tkinter as tk
import unittest

from bio_ce.ui.theme import Theme
from bio_ce.ui.widgets import ScrollFrame
from tests.integration.test_desktop_ui_redesign import new_root


class ScrollFrameShrinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = new_root()
        self.root.geometry("400x300+20+20")
        self.scroll = ScrollFrame(self.root, Theme(self.root))
        self.scroll.pack(fill="both", expand=True)
        self.section = tk.Frame(self.scroll.body)
        self.section.pack(fill="x")
        self.rows = [tk.Label(self.section, text=f"Row {n}") for n in range(60)]
        for row in self.rows:
            row.pack(fill="x")
        tk.Label(self.scroll.body, text="Always here").pack(fill="x")
        self.settle()
        self.scroll.canvas.yview_moveto(1.0)
        self.settle()
        self.assertGreater(self.scroll.canvas.canvasy(0), 300)  # positive control: scrolled far down

    def tearDown(self) -> None:
        self.root.destroy()

    def settle(self) -> None:
        for _ in range(4):
            self.root.update()

    def assert_view_on_content(self) -> None:
        content = self.scroll.body.winfo_reqheight()
        lowest = max(0, content - self.scroll.canvas.winfo_height())
        self.assertLessEqual(self.scroll.canvas.canvasy(0), lowest + 1, f"content={content}")

    def test_a_section_that_closes(self):
        self.section.pack_forget()
        self.settle()
        self.assert_view_on_content()

    def test_items_that_are_removed(self):
        for row in self.rows[5:]:
            row.destroy()
        self.settle()
        self.assert_view_on_content()


if __name__ == "__main__":
    unittest.main()
