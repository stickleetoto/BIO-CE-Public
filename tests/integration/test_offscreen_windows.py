# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""UI test windows open off the screen and off the taskbar (tests/offscreen.py), and still measure for real."""

from __future__ import annotations

import os
import sys
import tkinter as tk
import unittest

from tests import offscreen
from tests.tk_support import new_tk_root
from tests.ui_audit import audit


class MovedGeometryTests(unittest.TestCase):
    def test_on_screen_positions_move_by_the_same_offset_and_sizes_stay(self):
        o = offscreen.OFFSET
        self.assertEqual(offscreen.moved("+100+50"), f"+{100 + o}+{50 + o}")
        self.assertEqual(offscreen.moved("1400x900+260+90"), f"1400x900+{260 + o}+{90 + o}")
        self.assertEqual(offscreen.moved("1400x900"), "1400x900")  # a size alone
        self.assertEqual(offscreen.moved(f"+{o + 40}+{o + 60}"), f"+{o + 40}+{o + 60}")  # already off the screen
        self.assertEqual(offscreen.moved("-0+0"), "-0+0")  # measured from the right edge: left as it is


@unittest.skipUnless(offscreen.enabled(), "BIO_CE_TEST_ONSCREEN=1")
class OffScreenWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = new_tk_root()

    def tearDown(self) -> None:
        self.root.destroy()

    def test_a_window_the_app_centres_opens_off_the_screen_at_its_real_size(self):
        self.root.geometry("320x200+100+100")
        self.root.update()
        self.assertLess(self.root.winfo_rootx() + self.root.winfo_width(), 0)
        self.assertLess(self.root.winfo_rooty() + self.root.winfo_height(), 0)
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), (320, 200))
        if sys.platform == "win32":
            self.assertTrue(int(self.root.wm_attributes("-toolwindow")))  # no taskbar button
        dialog = tk.Toplevel(self.root)
        dialog.geometry(f"+{self.root.winfo_rootx() + 20}+{self.root.winfo_rooty() + 30}")  # placed over its parent
        dialog.update()
        # Where it sits relative to the parent is unchanged (not moved a second time); the few pixels more are the
        # dialog's own title bar and border, as on the screen (geometry places the frame, rootx is inside it).
        dx, dy = dialog.winfo_rootx() - self.root.winfo_rootx(), dialog.winfo_rooty() - self.root.winfo_rooty()
        self.assertTrue(20 <= dx <= 20 + 40 and 30 <= dy <= 30 + 80, (dx, dy))
        self.root.focus_force()  # becomes focus_set: never takes the foreground

    def test_the_cut_off_check_still_finds_a_cut_widget_off_the_screen(self):
        """Positive control: the layout audit measures real, mapped widgets in an off-screen window."""
        self.root.geometry("240x120+100+100")
        fits = tk.Label(self.root, text="Fits")
        fits.place(x=10, y=10)
        self.root.update()
        self.assertEqual(audit(self.root, "probe"), [])  # negative control
        cut = tk.Label(self.root, text="A label that runs past the right edge of this window")
        cut.place(x=150, y=50)
        self.root.update()
        problems = audit(self.root, "probe")
        self.assertTrue(any("right edge outside the window" in problem for problem in problems), problems)


if __name__ == "__main__":
    os.environ.setdefault("BIO_CE_UI_LANGUAGE", "en")
    unittest.main()
