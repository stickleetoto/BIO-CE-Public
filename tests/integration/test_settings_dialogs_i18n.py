# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U5-B: Settings and the dialogs in Korean, on a real Tk window with synthetic data.

In Korean nothing is cut off (Korean is wider), no English text of these screens is left, and the first-run notice
says the same things; in English the texts read as before (the other UI tests pin English and check them).
"""

from __future__ import annotations

import tkinter as tk
import unittest
from unittest.mock import patch

from bio_ce.ui import i18n
from bio_ce.ui.dialogs import (
    WELCOME_POINTS,
    ConfirmDialog,
    EntryEditDialog,
    ExportDialog,
    HistoryDialog,
    NameDialog,
    ReviewEditDialog,
    export_sources,
    ask_privacy_consent,
)
from bio_ce.ui.i18n import en, ko
from bio_ce.ui.pages.settings import PRIVACY_POINTS
from bio_ce.ui.theme import Theme
from tests.integration import test_ui_layout_audit as layout
from tests.integration.test_desktop_ui_redesign import new_root
from tests.ui_audit import audit

# The keys of this part (Settings and dialogs) whose English is a whole widget text (no placeholder) and differs
# from the Korean: in Korean none of them may still show.
_KEYS = tuple(key for key, value in en.STRINGS.items()
              if key.startswith(("settings.", "dialog.")) and isinstance(value, str) and "{" not in value
              and value != ko.STRINGS[key])


def texts(top: tk.Misc) -> list[str]:
    """Every text a widget under ``top`` shows (labels, buttons, check boxes, text areas)."""
    found = []
    stack = [top]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        if isinstance(widget, tk.Text):
            found.append(widget.get("1.0", "end").strip())
        elif "text" in widget.keys():
            text = str(widget.cget("text")).strip()
            if text:
                found.append(text)
    return found


def english_left(shown: list[str]) -> list[str]:
    lines = {line.strip() for text in shown for line in text.splitlines()} | set(shown)
    return [en.STRINGS[key] for key in _KEYS if en.STRINGS[key].strip() in lines]


class SettingsAndDialogsInKoreanTests(unittest.TestCase):
    def korean(self, base: type = layout.LayoutAuditTests):
        class Korean(base):  # type: ignore[misc, valid-type]
            LANGUAGE = "ko"

            def runTest(self) -> None:  # noqa: N802 - unittest name
                pass

        case = Korean()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.addCleanup(case.tearDown)
        return case

    def show(self, case, dialog, name: str, size: tuple[int, int] | None = None) -> list[str]:
        """Present ``dialog`` without a grab (the tests never take focus), audit it, and close it."""
        try:
            theme = case.app.theme
            dialog.present(modal=False, size=(theme.px(size[0]), theme.px(size[1])) if size else None)
            for _ in range(6):
                dialog.update()
            problems = audit(dialog, name, vertical=case.full_size)
            left = english_left(texts(dialog))
            self.assertEqual(left, [], f"{name}: English left in Korean")
            return problems
        finally:
            dialog.destroy()

    def test_the_settings_page_in_korean_is_not_cut_and_has_no_english_left(self):
        case = self.korean()
        problems = case.visit("settings")
        self.assertEqual(problems, [], "\n".join(problems))
        settings = case.app.pages["settings"]
        self.assertEqual(settings.heading(), ("설정", "데이터가 있는 곳과 보호하는 방법"))
        shown = texts(settings)
        for text in ("기억 데이터베이스", "백업과 복원", "백업 복원…", "개인정보와 보안", "이 PC에만 저장", "공간", "일반", "개인",
                     "보관 처리", "개인 켜기…" if not case.control.personal_enabled() else "끄기…", "수집함",
                     "기억 엔진", "단축키", "BIO CE 정보"):
            self.assertIn(text, shown)
        self.assertEqual(english_left(shown), [])
        self.assertIn("활성 기억", settings.storage_stats.cget("text"))
        # positive control: a Korean button made far too long is caught
        settings.engine_check_button.set_text("아주 긴 버튼 이름으로 다시 확인하기 " * 8)
        case.settle()
        self.assertTrue(any("button" in p and "아주 긴" in p for p in audit(case.root, "settings")))

    def test_the_settings_page_in_korean_at_the_ci_screen(self):
        case = self.korean(layout.CiScreenLayoutAuditTests)
        problems = case.visit("settings")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_dialogs_in_korean_are_not_cut_and_have_no_english_left(self):
        case = self.korean()
        app, theme, root = case.app, case.app.theme, case.root
        settings = app.pages["settings"]
        asked: list[dict] = []
        with patch.object(app, "confirm", side_effect=lambda **kw: asked.append(kw) and False), \
                patch.object(app, "ask_name", side_effect=lambda **kw: asked.append(kw)), \
                patch.object(app, "ask_folder", side_effect=lambda **kw: asked.append(kw) or ""):
            settings.turn_off_personal()
            settings.turn_on_personal()
            alpha = next(space for space in app.spaces() if space.display_name.startswith("Alpha"))
            settings.archive_space(alpha)
            settings.new_space()
            settings.rename_space(alpha)
            settings.link_folder(alpha)
        self.assertEqual(len(asked), 6)
        self.assertEqual(asked[0]["title"], "개인을 끌까요?")
        self.assertEqual(asked[2]["title"], "Alpha Project With A Long Name을(를) 보관 처리할까요?")
        self.assertEqual(asked[5]["title"], "Alpha Project With A Long Name에 연결할 폴더 선택")
        problems: list[str] = []
        for index, options in enumerate(asked[:3]):
            problems += self.show(case, ConfirmDialog(root, theme, **options), f"confirm {index}")
        for index, options in enumerate(asked[3:5]):
            problems += self.show(case, NameDialog(root, theme, **options), f"name {index}", (480, 260))
        revisions = app.memory_engine().history(case.editor_note.memory_id)
        problems += self.show(case, HistoryDialog(root, theme, revisions, undo=lambda: False), "history", (720, 560))
        problems += self.show(case, ReviewEditDialog(root, theme, title="편집기", content="helix로 편집한다.",
                                                     reason="test"), "review edit", (560, 440))
        problems += self.show(case, EntryEditDialog(root, theme, content="자전거를 탄다.", source_date="2025-07-02"),
                              "entry edit", (560, 420))
        export = ExportDialog(root, theme, spaces=app.spaces(), current="general",
                              sources=export_sources())
        export.space_vars["personal"].set(True)
        self.assertIn("개인", texts(export))  # General and Personal by their one Korean names (Q5, rc3)
        self.assertNotIn("개인 (내 개인 기억)", texts(export))
        self.assertIn("일반", texts(export))
        self.assertIn("직접 추가", texts(export))  # the sources in Korean too (rc3: they were English)
        problems += self.show(case, export, "export", (520, 640))
        self.assertEqual(problems, [], "\n".join(problems))
        # positive control: the dialog audit sees a shown dialog, so a Korean button made far too long is caught
        caught = self.show(case, NameDialog(root, theme, title="이름", label="이름",
                                            confirm_text="아주 긴 확인 버튼 이름 " * 10), "control", (480, 260))
        self.assertTrue(any("button" in p and "아주 긴" in p for p in caught), caught)

    def test_the_history_dialog_counts_versions_in_both_languages(self):
        case = self.korean()
        revisions = case.app.memory_engine().history(case.editor_note.memory_id)
        dialog = HistoryDialog(case.root, case.app.theme, revisions)
        try:
            shown = texts(dialog)
            self.assertIn(f"Editor · 버전 {len(revisions)}개", shown)
            self.assertTrue(any(text.startswith("버전 1 · ") and "현재" in text for text in shown))
            self.assertIn("버전 기록", shown)
        finally:
            dialog.destroy()
        i18n.set_language("en")
        dialog = HistoryDialog(case.root, case.app.theme, revisions)
        try:
            shown = texts(dialog)
            self.assertIn("Editor · 1 revision", shown)  # the English plural form, as before
            self.assertTrue(any(text.startswith("Revision 1 · ") and "   CURRENT" in text for text in shown))
        finally:
            dialog.destroy()


class FirstRunNoticeTests(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_language("en")

    def notice(self, language: str) -> tuple[bool, list[str], list[str]]:
        i18n.set_language(language)
        root = new_root()
        try:
            root.geometry("860x560+0+0")
            theme = Theme(root)
            seen: dict[str, list[str]] = {}

            def look_then_quit() -> None:
                try:
                    root.update()
                    seen["texts"] = texts(root)
                    seen["problems"] = audit(root, "first-run notice", vertical=False)
                finally:  # always answer, or the notice would wait for ever
                    root.tk.call(root.protocol("WM_DELETE_WINDOW"))  # the window's close box: Quit

            root.after(200, look_then_quit)
            accepted = ask_privacy_consent(root, theme)
            return accepted, seen.get("texts", []), seen.get("problems", ["the notice was not looked at"])
        finally:
            root.destroy()

    def test_the_notice_says_the_same_in_korean_and_quitting_still_declines(self):
        accepted, shown, problems = self.notice("ko")
        self.assertFalse(accepted)
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertEqual(english_left(shown), [])
        for _icon, heading, text in WELCOME_POINTS:
            self.assertIn(ko.STRINGS[heading], shown)
            self.assertIn(ko.STRINGS[text], shown)
        for text in ("BIO CE에 오신 것을 환영합니다", "계속", "종료", "AI 접근은 기본이 읽기 전용"):
            self.assertIn(text, shown)
        joined = " ".join(shown)
        # the consent's points are all there: local only, no recording, read only by default, sent to the
        # AI tool's model provider, backups not encrypted, deletion is not a secure erase
        for phrase in ("업로드되지 않습니다", "대화를 기록하지 않습니다", "읽기 전용", "AI 모델 제공자에게 보내질 수",
                       "암호화되지 않은 채", "안전하게 지우지는 않습니다"):
            self.assertIn(phrase, joined)

    def test_the_notice_in_english_reads_as_before(self):
        accepted, shown, _problems = self.notice("en")
        self.assertFalse(accepted)
        self.assertIn("Welcome to BIO CE", shown)
        self.assertIn("A connected AI host can search and read your memories. It can save or update them only after "
                      "you turn on Auto memory for it, and it can never retract one without you. Memories a host "
                      "reads or saves become part of that conversation and may be sent to the host's AI model "
                      "provider.", shown)
        self.assertIn("Select Continue to create your local BIO CE data folder.", shown)


class PointTablesTests(unittest.TestCase):
    def test_the_point_tables_hold_keys_present_in_both_languages(self):
        for _icon, heading, text in PRIVACY_POINTS + WELCOME_POINTS:
            for key in (heading, text):
                self.assertIn(key, en.STRINGS)
                self.assertIn(key, ko.STRINGS)


if __name__ == "__main__":
    unittest.main()
