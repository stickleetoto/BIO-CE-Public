# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""POLISH §3.0: the shared "Details ▸" part. Closed by default, opened and closed by its label (also with the keys),
by a click anywhere on its row, and filled when it opens; nothing inside is shown while closed."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from bio_ce.ui.theme import Theme
from bio_ce.ui.widgets import Disclosure
from tests.tk_support import new_tk_root


class DisclosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = new_tk_root()
        with patch.dict(os.environ, {"BIO_CE_UI_LANGUAGE": "en"}):
            self.theme = Theme(self.root)
        self.filled = 0
        self.part = Disclosure(self.root, self.theme, "Details", on_open=self.fill, hint="Source · ID · dates")
        self.part.pack(fill="x")
        self.inside = self.part.body
        for _ in range(3):
            self.root.update()

    def tearDown(self) -> None:
        self.root.destroy()

    def fill(self) -> None:
        self.filled += 1

    def test_closed_by_default_with_a_hint_of_what_is_inside(self):
        self.assertFalse(self.part.opened)
        self.assertEqual(self.inside.winfo_manager(), "")
        self.assertEqual(self.part.hint_label.cget("text"), "Source · ID · dates")
        self.assertEqual(self.part.hint_label.winfo_manager(), "pack")

    def test_the_label_opens_and_closes_it_and_fills_it_on_opening(self):
        self.part.toggle.invoke()
        self.assertTrue(self.part.opened)
        self.assertEqual(self.inside.winfo_manager(), "pack")
        self.assertEqual(self.filled, 1)
        # The keyboard: the label is a focusable Button bound to Enter and Space (UI tests never take the focus, so
        # the bound handler is called rather than a key sent).
        self.assertEqual(int(self.part.toggle.cget("takefocus")), 1)
        self.assertTrue(self.part.toggle.bind("<Return>") and self.part.toggle.bind("<space>"))
        self.part.toggle._on_key()
        self.assertFalse(self.part.opened)
        self.assertEqual(self.inside.winfo_manager(), "")

    def test_a_click_on_the_row_opens_it(self):
        self.part.head.event_generate("<ButtonRelease-1>")
        self.assertTrue(self.part.opened)
        self.part.hint_label.event_generate("<ButtonRelease-1>")
        self.assertFalse(self.part.opened)

    def test_the_hint_can_change_or_go(self):
        self.part.set_hint("")
        self.assertEqual(self.part.hint_label.winfo_manager(), "")
        self.part.set_hint("3 versions")
        self.assertEqual(self.part.hint_label.winfo_manager(), "pack")


if __name__ == "__main__":
    unittest.main()
