# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 rc3 (owner, 2026-11-18): a title and a body that say the same thing are shown once on cards and in the
drawer. The same, or a body that starts with the title (ignoring spaces and punctuation), shows the title and only
the rest of the body. Stored memories are not changed; only what the screen shows."""

from __future__ import annotations

import unittest

from bio_ce.ui.format import body_without_title


class BodyWithoutTitleTests(unittest.TestCase):
    def test_the_same_text_is_shown_once(self):
        for title, body in (("사용자는 한국어 답변을 선호한다.", "사용자는 한국어 답변을 선호한다."),
                            ("사용자는 한국어 답변을 선호한다", "사용자는 한국어 답변을 선호한다."),
                            ("Prefers tea", "prefers  tea!"),
                            ("시험용: 이동 A", "시험용 이동 A")):
            with self.subTest(title=title):
                self.assertEqual(body_without_title(title, body), "")

    def test_a_body_that_starts_with_the_title_keeps_only_the_rest(self):
        self.assertEqual(body_without_title("Editor", "Editor: the user edits in helix."), "the user edits in helix.")
        self.assertEqual(body_without_title("주간 회의", "주간 회의 — 매주 금요일 10시, 회의록은 마크다운."),
                         "매주 금요일 10시, 회의록은 마크다운.")
        self.assertEqual(body_without_title("사용자는 차를 좋아한다", "사용자는 차를 좋아한다. 아침에는 녹차."),
                         "아침에는 녹차.")

    def test_a_different_body_is_shown_whole(self):
        # Positive control: the rule only removes a repeated title, never other text.
        for title, body in (("Editor", "The user edits in helix."), ("Indent", "Four spaces, never tabs."),
                            ("회의", "회의록은 마크다운으로 쓴다."), ("tea", "teapot is blue")):
            with self.subTest(title=title):
                self.assertEqual(body_without_title(title, body), body)

    def test_empty_or_punctuation_only_titles_change_nothing(self):
        self.assertEqual(body_without_title("", "Body"), "Body")
        self.assertEqual(body_without_title("…", "… body"), "… body")
        self.assertEqual(body_without_title("Title", ""), "")
        self.assertEqual(body_without_title("Title", None), "")


if __name__ == "__main__":
    unittest.main()
