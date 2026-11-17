# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U5-A: the Connections screen in Korean is not cut off (§6.3), with a positive control in Korean.

Korean text is wider than English, so the screen is audited at the minimum window, at the CI runner's screen
(1024x768 at 150%), and on a big screen, with a connected host whose access rows are all shown.
"""

from __future__ import annotations

import tkinter  # noqa: F401 - the cases below open Tk windows; this import marks the module "ui" (tests/bundles.py)
import unittest

from tests.integration.test_ui_layout_audit import (
    CiScreenLayoutAuditTests,
    HugeScreenLayoutAuditTests,
    LayoutAuditTests,
)
from tests.ui_audit import audit


class KoreanConnectionsLayoutTests(unittest.TestCase):
    def run_screen(self, base: type) -> None:
        class Korean(base):  # type: ignore[misc, valid-type]
            LANGUAGE = "ko"

            def runTest(self) -> None:  # noqa: N802 - unittest name
                pass

        case = Korean()
        case.setUp()
        try:
            page = case.app.pages["connections"]
            self.assertEqual(page.title, "AI 연결")  # the screen really is in Korean
            page.refresh()
            card = page.cards["codex"]
            self.assertTrue(card.access.winfo_manager())  # the access rows of a connected host are shown
            problems = case.visit("connections")
            newline = chr(10)
            self.assertEqual(problems, [], f"{len(problems)} problems:{newline}" + newline.join(problems))
            card.diagnose_button.set_text("아주 긴 진단 실행 단추 이름 " * 8)  # positive control in Korean
            case.settle()
            self.assertTrue(any("아주 긴" in p for p in audit(case.root, "connections")))
        finally:
            case.tearDown()
            case.doCleanups()

    def test_the_connections_screen_in_korean_at_the_minimum_window(self):
        self.run_screen(LayoutAuditTests)

    def test_the_connections_screen_in_korean_at_the_ci_screen(self):
        self.run_screen(CiScreenLayoutAuditTests)

    def test_the_connections_screen_in_korean_on_a_big_screen(self):
        self.run_screen(HugeScreenLayoutAuditTests)


if __name__ == "__main__":
    unittest.main()
