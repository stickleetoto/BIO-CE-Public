# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""POLISH §2.5 V4: rounded corners on panels and big cards, drawn as four small images over a square frame.

The image at a corner is the window's color outside the curve and the card's color inside it; a click on a corner
still reaches the card; nothing in the corners takes the focus; memory cards stay square (spike S1: 20.9% slower to
build 60 of them with corners, more than the 15% the owner allowed)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from bio_ce.ui import widgets
from bio_ce.ui.hub.cards import HubCard
from bio_ce.ui.theme import Palette, Theme
from bio_ce.ui.widgets import Card, corner_images
from tests.tk_support import new_tk_root


def pixel(image, x: int, y: int) -> tuple[int, int, int]:
    value = image.get(x, y)
    return tuple(int(v) for v in (value if isinstance(value, tuple) else str(value).split()))


def rgb(color: str) -> tuple[int, int, int]:
    return widgets._rgb(color)


class CornerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = new_tk_root()
        with patch.dict(os.environ, {"BIO_CE_UI_LANGUAGE": "en"}):
            self.theme = Theme(self.root)
        self.colors = Palette()

    def tearDown(self) -> None:
        self.root.destroy()

    def test_a_corner_is_the_outside_color_at_its_tip_and_the_fill_inside(self):
        c = self.colors
        size = self.theme.px(8)
        images = corner_images(self.root, size, c.bg, c.border, c.surface, self.theme.px(1))
        self.assertEqual(pixel(images["nw"], 0, 0), rgb(c.bg))
        self.assertEqual(pixel(images["nw"], size - 1, size - 1), rgb(c.surface))
        self.assertEqual(pixel(images["se"], size - 1, size - 1), rgb(c.bg))
        self.assertEqual(pixel(images["se"], 0, 0), rgb(c.surface))
        # Positive control: with the fill as outside too the corner would be invisible; ours are not.
        self.assertNotEqual(pixel(images["nw"], 0, 0), pixel(images["nw"], size - 1, size - 1))
        self.assertIs(corner_images(self.root, size, c.bg, c.border, c.surface, self.theme.px(1)), images)  # cached

    def test_a_card_has_four_covers_that_pass_clicks_and_take_no_focus(self):
        card = Card(self.root, self.theme)
        card.pack()
        clicked = []
        card.bind("<Button-1>", lambda _e: clicked.append(True))
        for _ in range(3):
            self.root.update()
        self.assertEqual(len(card.corners), 4)
        for cover in card.corners:
            self.assertEqual(int(cover.cget("takefocus")), 0)
            self.assertEqual(cover.bindtags()[0], str(card))
        card.corners[0].event_generate("<Button-1>", x=1, y=1)
        self.assertEqual(clicked, [True])
        se = card.corners[3]
        self.assertEqual(se.winfo_x() + se.winfo_width(), card.winfo_width())
        self.assertEqual(se.winfo_y() + se.winfo_height(), card.winfo_height())

    def test_memory_cards_stay_square(self):
        self.assertFalse(hasattr(HubCard, "corners"))


if __name__ == "__main__":
    unittest.main()
