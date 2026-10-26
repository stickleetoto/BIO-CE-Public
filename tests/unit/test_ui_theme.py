# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from bio_ce.ui.theme import Palette, cjk_ui_fonts


@unittest.skipUnless(sys.platform == "win32", "Windows language detection")
class ThemeLanguageTests(unittest.TestCase):
    def _fonts_for(self, ui_language: int, locale: int = 0x0409) -> tuple[str, ...]:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        with patch.object(kernel32, "GetUserDefaultUILanguage", return_value=ui_language), \
                patch.object(kernel32, "GetUserDefaultLCID", return_value=locale):
            return cjk_ui_fonts()

    def test_cjk_languages_pick_a_matching_windows_ui_font(self):
        self.assertEqual(self._fonts_for(0x0412), ("Malgun Gothic",))
        self.assertEqual(self._fonts_for(0x0411)[0], "Yu Gothic UI")
        self.assertEqual(self._fonts_for(0x0804), ("Microsoft YaHei UI",))
        self.assertEqual(self._fonts_for(0x0404), ("Microsoft JhengHei UI",))
        self.assertEqual(self._fonts_for(0x0409, locale=0x0412), ("Malgun Gothic",))
        self.assertEqual(self._fonts_for(0x0409), ())


class PaletteContrastTests(unittest.TestCase):
    @staticmethod
    def _luminance(color: str) -> float:
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def _contrast(self, foreground: str, background: str) -> float:
        light, dark = sorted((self._luminance(foreground), self._luminance(background)), reverse=True)
        return (light + 0.05) / (dark + 0.05)

    def test_text_colors_meet_wcag_aa_on_their_surfaces(self):
        palette = Palette()
        for foreground in (palette.text, palette.text_secondary, palette.text_muted, palette.accent_text,
                           palette.danger, palette.success, palette.warning):
            for background in (palette.bg, palette.surface, palette.surface_alt):
                with self.subTest(foreground=foreground, background=background):
                    self.assertGreaterEqual(self._contrast(foreground, background), 4.5)
        self.assertGreaterEqual(self._contrast(palette.on_accent, palette.accent), 4.5)
        self.assertGreaterEqual(self._contrast(palette.on_accent, palette.danger_solid), 4.5)


if __name__ == "__main__":
    unittest.main()
