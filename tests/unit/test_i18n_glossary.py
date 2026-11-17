# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U5: the Korean texts follow the glossary (tests/i18n_glossary.py). Every merge of translated texts must
leave zero violations (owner, 2026-11-17)."""

from __future__ import annotations

import unittest

from bio_ce.ui.i18n import en, ko
from tests.i18n_glossary import EXCEPTIONS, violations


class GlossaryTests(unittest.TestCase):
    def test_the_korean_texts_use_the_glossary_terms(self):
        found = violations(en.STRINGS, ko.STRINGS)
        newline = chr(10)
        self.assertEqual(found, [], f"{len(found)} glossary violations:{newline}" + newline.join(found))

    def test_positive_control_a_wrong_term_and_a_retired_form_are_caught(self):
        english = {"x.delete": "Delete this memory?", "x.revision": "Revision {number}", "x.ok": "Undo"}
        korean = {"x.delete": "이 메모를 지울까요?", "x.revision": "판 {number}", "x.ok": "실행 취소"}
        found = violations(english, korean)
        self.assertTrue(any(line.startswith("x.delete:") for line in found), found)  # 기억 is missing
        self.assertTrue(any(line.startswith("x.revision:") for line in found), found)  # 판 is retired
        self.assertFalse(any(line.startswith("x.ok:") for line in found), found)

    def test_every_exception_still_names_a_text(self):
        for key in EXCEPTIONS:
            self.assertIn(key, en.STRINGS, f"{key} is gone; remove its exception")


if __name__ == "__main__":
    unittest.main()
