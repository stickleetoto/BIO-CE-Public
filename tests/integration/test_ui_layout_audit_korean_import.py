# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U5-C, §6.3: the Dashboard and the import preview in Korean, at the minimum window and at the CI screen.

Korean text is wider than English, so the layout audit of tests/integration/test_ui_layout_audit.py runs these two
screens again with the app in Korean. A positive control makes the import screen's Preview button long on purpose and
expects the audit to catch it in Korean too.
"""

from __future__ import annotations

import unittest

from tests.integration.test_desktop_ui_redesign import new_root  # noqa: F401 - marks a UI module (tests/bundles.py)
from tests.integration import test_ui_layout_audit as layout  # the module, so its tests aren't collected twice
from tests.ui_audit import audit


class KoreanImportDashboardAuditTests(unittest.TestCase):
    def run_screens(self, base: type) -> None:
        class Korean(base):  # type: ignore[misc, valid-type]
            LANGUAGE = "ko"

            def runTest(self) -> None:  # noqa: N802 - unittest name
                pass

        case = Korean()
        case.setUp()
        try:
            self.assertEqual(case.app.dashboard.heading()[0], "대시보드")
            problems = case.visit("dashboard")
            case.app.show_page("import")
            importer = case.app.importer
            self.assertEqual(importer.heading()[0], "기억 가져오기")
            importer.refresh()
            importer.set_text(layout.SAMPLE)
            self.assertTrue(importer.choose_destination("personal"))
            importer.start_preview()
            case.app.tasks.wait(30)
            self.assertIsNotNone(importer.preview)
            self.assertIn("새 항목", importer.summary.cget("text"))  # the preview is shown in Korean
            problems += [p.replace("import:", "import preview (ko):", 1) for p in case.visit("import")]
            newline = chr(10)
            self.assertEqual(problems, [], f"{len(problems)} problems:{newline}" + newline.join(problems))
            importer.preview_button.set_text("아주 긴 미리 보기 단추 이름 " * 12)  # positive control in Korean
            case.settle()
            self.assertTrue(any("button" in p and "아주 긴" in p for p in audit(case.root, "import")))
        finally:
            case.tearDown()
            case.doCleanups()

    def test_dashboard_and_import_preview_in_korean_at_the_minimum_window(self):
        self.run_screens(layout.LayoutAuditTests)

    def test_dashboard_and_import_preview_in_korean_at_the_ci_screen(self):
        self.run_screens(layout.CiScreenLayoutAuditTests)


if __name__ == "__main__":
    unittest.main()
