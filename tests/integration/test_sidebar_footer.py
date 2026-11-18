# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""rc3 (owner, 2026-11-18): the sidebar's footer "Local only · Version …" stays on one line, in Korean and English,
in the smallest window and with large text. It keeps the caption size where it fits and gets only as small as the
sidebar needs; the words are never cut."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import bio_ce
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.ui import i18n
from bio_ce.ui.app import MINIMUM_SIZE
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


class SidebarFooterTests(unittest.TestCase):
    def open(self, language: str):
        temp = tempfile.TemporaryDirectory(prefix="bio-ce-footer-")
        self.addCleanup(temp.cleanup)
        paths = AppDataPaths.under(temp.name)
        service = DesktopMemoryService(paths.user_database)
        connections = FakeManagedConnections(paths.user_database)
        self.addCleanup(connections.close)
        root = new_root()
        with patch.dict(os.environ, {"BIO_CE_UI_LANGUAGE": language}):
            app = BIOCEDesktop(root, service, paths, connections)
        self.addCleanup(lambda: i18n.set_language("en"))
        self.addCleanup(app.close)
        self.addCleanup(lambda: app.tasks.wait(10))
        root.after_cancel(app._maintenance_after)
        theme = app.theme
        root.geometry(f"{theme.px(MINIMUM_SIZE[0] + 200)}x{theme.px(MINIMUM_SIZE[1])}")  # wide enough for the full sidebar
        self.settle(root)
        # A small screen (the CI runner) can't show that width, and the sidebar there shows icons only (the footer
        # text is hidden by design): show the full sidebar so the line itself is checked (mirror CI 2026-11-18).
        app._apply_compact(False)
        self.settle(root)
        app.fit_footer_line()
        self.settle(root)
        return app, root

    @staticmethod
    def settle(root) -> None:
        for _ in range(6):
            root.update()

    def assert_one_line(self, app, label: str) -> None:
        line, room = app.footer_line, app.sidebar_footer_text.winfo_width()
        self.assertTrue(line.winfo_ismapped(), label)
        self.assertLessEqual(line.winfo_reqwidth(), room, label)
        self.assertEqual(line.winfo_height(), line.winfo_reqheight(), label)  # one line, not cut in height
        self.assertIn(bio_ce.display_version(), str(line.cget("text")), label)

    def test_one_line_in_both_languages_and_with_large_text(self):
        for language in ("ko", "en"):
            with self.subTest(language=language):
                app, root = self.open(language)
                self.assert_one_line(app, f"{language} normal")
                for factor in (1.25, 1.2):  # 1.25x, then 1.5x the original size
                    for font in app.theme.fonts.values():
                        size = int(font.cget("size"))
                        font.configure(size=round(size * factor) if size > 0 else -round(-size * factor))
                    app.fit_footer_line()
                    self.settle(root)
                    self.assert_one_line(app, f"{language} x{factor}")
                    # Positive control: at the larger caption size the line would not have fitted.
                    base = app.theme.font("caption")
                    self.assertGreater(base.measure(str(app.footer_line.cget("text"))),
                                       app.sidebar_footer_text.winfo_width())


if __name__ == "__main__":
    unittest.main()
