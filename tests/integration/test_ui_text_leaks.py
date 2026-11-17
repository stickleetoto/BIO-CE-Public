# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The Korean app shows no internal values and no English beyond product names (owner decision 2026-11-17, rc2).

The v0.4.4-rc1 GUI check found "출처: user-input" in the memory drawer and an English paragraph on the Codex card.
This opens every screen the layout audit opens (dashboard, the memory screen in each state with the drawer, history,
and details, the edit form, Personal, the inbox, suggestions, reviews, deleted memories, the import preview,
connections, settings) plus the export and shortcuts dialogs, in Korean, and reads the text the widgets show
(tests/ui_text_scan.py). Positive controls put an internal value and an English sentence on screen and expect both
to be reported.
"""

from __future__ import annotations

import tkinter as tk
import unittest
from unittest.mock import patch

from bio_ce.exporter import SOURCE_KINDS, SOURCE_LABELS
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.ui.dialogs import Dialog, ExportDialog
from bio_ce.ui.hub.data import INBOX as INBOX_TAB, MEMORIES, REVIEWS, SUGGESTIONS
from bio_ce.ui.format import DEFAULT_SOURCE
from tests.integration import test_ui_layout_audit as layout  # the module: its tests aren't collected here again
from tests.ui_text_scan import leaks, shown_texts


class _KoreanScreens(layout.LayoutAuditTests):
    """The layout audit's screens in Korean; a helper (its own layout tests are not collected again here)."""

    __test__ = False
    LANGUAGE = "ko"

    def runTest(self) -> None:  # noqa: N802 - unittest name
        pass

    def setUp(self) -> None:
        super().setUp()
        self.found: list[str] = []
        self.visited: list[str] = []
        self.seen: list[str] = []
        # Added the way the app adds a memory, with the source the app writes itself ("user-input" in rc1's drawer).
        self.plain = self.service.add(title="시험용: 앱에서 추가", content="앱에서 바로 추가한 기억",
                                      source_ref=DEFAULT_SOURCE)
        self.hub.refresh()

    def memory_screens(self) -> list[str]:
        problems = super().memory_screens()
        self.app.open_memory(self.plain.memory_id)
        self.hub.drawer.history.set_open(True)
        self.hub.drawer.details.set_open(True)
        problems += self.visit("memories", "memories (drawer of a memory added in the app)")
        self.hub.close_drawer(force=True)
        return problems

    def user_data(self) -> list[str]:
        """Everything the test put in as the user's (or an AI tool's) words."""
        data = ["Plants", "Invoices", "The user waters the balcony plants every Sunday morning.",
                "Invoices go out to clients on the first business day of a month.", "Editor",
                "The user edits in helix.", "The user writes meeting notes in Markdown.",
                "Alpha Project With A Long Name", "test"]
        lines = [line for line in layout.SAMPLE.splitlines() if line.strip()]
        data += lines + [line.split(" - ", 1)[1] for line in lines if " - " in line]  # an entry as the preview shows it
        data += [sentence.rstrip(".") + " without fail." for sentence in data if sentence.endswith(".")]
        return data

    def scan(self, window, label: str) -> None:
        texts = shown_texts(window)
        self.visited.append(label)
        self.seen.extend(text for _path, text in texts)
        self.found += [f"{label}: {problem}" for problem in leaks(texts, self.user_data())]

    def visit(self, page: str, label: str | None = None) -> list[str]:
        problems = super().visit(page, label)
        self.scan(self.root, label or page)
        return problems

    def every_screen(self) -> list[str]:
        self.all_screens()
        dialog = ExportDialog(self.root, self.app.theme, spaces=self.app.spaces(), current="general",
                              sources=[(key, SOURCE_LABELS[key]) for key in SOURCE_KINDS])
        try:
            dialog.space_vars["personal"].set(True)
            for _ in range(6):
                dialog.update()
            self.scan(dialog, "export dialog")
        finally:
            dialog.destroy()
        shortcuts = self.app.show_shortcuts()
        try:
            self.settle()
            self.scan(shortcuts, "shortcuts dialog")
        finally:
            shortcuts.destroy()
        return self.found


class KoreanTextLeakTests(unittest.TestCase):
    def open(self) -> _KoreanScreens:
        case = _KoreanScreens()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.addCleanup(case.tearDown)
        return case

    def test_no_screen_shows_an_internal_value_or_english_in_korean(self):
        case = self.open()
        found = case.every_screen()
        newline = chr(10)
        self.assertEqual(found, [], f"{len(found)} leaks:{newline}" + newline.join(found))
        # It really went through the screens and read the places rc1 got wrong, now in Korean.
        for label in ("dashboard", "memories (drawer of a memory added in the app)", "import", "connections",
                      "settings", "export dialog", "shortcuts dialog"):
            self.assertIn(label, case.visited)
        seen = newline.join(case.seen)
        self.assertIn("출처: 직접 추가", seen)  # D1: was "출처: user-input"
        self.assertIn("코드 모드로 실행", seen)  # D2: the Codex card's explanation
        self.assertIn("Ctrl+클릭", seen)

    def test_no_dialog_notice_or_menu_of_the_main_actions_shows_an_internal_value_or_english(self):
        """The main actions in Korean: each confirmation dialog is read and cancelled (nothing changes), each
        notice is read, and the card menus are read. File pickers answer "cancelled"."""
        case = self.open()
        seen: list[tuple[str, str]] = []
        found: list[str] = []
        data = case.user_data()

        def read(label: str, texts: list[tuple[str, str]]) -> None:
            seen.extend(texts)
            found.extend(f"{label}: {problem}" for problem in leaks(texts, data))

        def dialog_waits(dialog, *_args) -> None:
            for _ in range(3):
                dialog.update()
            read(f"dialog «{dialog.title()}»", shown_texts(dialog))
            dialog.cancel()

        shown = case.app.infobar.show

        def notified(kind, message, *, title="", action=None):
            read("notice", [("notice", message), ("notice", title)] + ([("notice", action[0])] if action else []))
            return shown(kind, message, title=title, action=action)

        def menu(label: str, widget: tk.Menu) -> None:
            texts = []
            for index in range((widget.index("end") or -1) + 1):
                if widget.type(index) in ("command", "cascade", "checkbutton", "radiobutton"):
                    texts.append((label, widget.entrycget(index, "label")))
            read(label, texts)

        app, hub = case.app, case.hub
        patches = (patch.object(Dialog, "wait_window", dialog_waits), patch.object(app.infobar, "show", notified),
                   patch.object(app, "ask_save_path", return_value=""),
                   patch.object(app, "ask_open_path", return_value=""), patch.object(app, "ask_folder", return_value=""))
        for each in patches:
            each.start()
            self.addCleanup(each.stop)
        settle = case.settle

        # Memories: the card menu, forget completely (cancelled), delete, move to Personal.
        app.open_state(MEMORIES)
        settle()
        item = next(i for i in hub.items if i.item_id == case.plain.memory_id)
        menu("card menu", hub.context_menu([item]))
        hub.forget_item(item)
        other = next(i for i in hub.items if i.item_id == case.editor_note.memory_id)
        hub.do.move([other], PERSONAL_SPACE)
        settle()
        hub.delete_items([item])
        settle()
        # Quick add of a password (refused) and of a memory.
        hub.quick_add.text.set("password=hunter2abc99")
        hub.quick_add.save()
        hub.quick_add.text.set("시험용: 빠른 추가 확인")
        hub.quick_add.save()
        settle()
        # The inbox: to memories, discard.
        app.open_state(INBOX_TAB)
        settle()
        first, second = hub.items[:2]
        hub.do.to_memories(first)
        settle()
        hub.do.discard([second])
        settle()
        # Reviews: approve one, reject the other.
        app.open_state(REVIEWS)
        settle()
        reviews = list(hub.items)
        hub.reviews.approve(reviews[0])
        settle()
        if len(reviews) > 1:
            hub.reviews.reject(reviews[1])
            settle()
        # Suggestions: approve all shown (cancelled), reject one.
        app.suggestions.find()
        app.open_state(SUGGESTIONS)
        settle()
        hub.suggestions.approve_shown()
        settle()
        # Settings: turn Personal off (cancelled), a new space (cancelled), check the engines, the language.
        settings = app.settings
        app.show_page("settings")
        settle()
        settings.turn_off_personal()
        settings.new_space()
        settings.check_engines()
        settings.language_choice.set("en")
        settings.choose_language()
        settle()
        read("settings after choosing a language", shown_texts(case.root))
        # Connections: each host's actions that ask first (all cancelled), diagnostics, idle servers.
        page = app.pages["connections"]
        app.show_page("connections")
        settle()
        for host in ("codex", "claude", "claude_desktop"):
            for action in (page.disconnect_host, page.change_personal, page.toggle_hooks, page.toggle_save_mode,
                           page.toggle_skill):
                action(host)
                settle()
        page.end_idle_servers()
        page.pause_all()
        settle()
        # Import: import the previewed entries, then undo it (cancelled).
        app.show_page("import")
        importer = app.importer
        importer.refresh()
        importer.set_text(layout.SAMPLE)
        importer.choose_destination("personal")
        importer.start_preview()
        app.tasks.wait(30)
        settle()
        importer.do_import()
        app.tasks.wait(30)
        settle()
        read("import after importing", shown_texts(case.root))

        newline = chr(10)
        self.assertEqual(found, [], f"{len(found)} leaks:{newline}" + newline.join(found))
        texts = newline.join(text for _path, text in seen)
        for expected in ("완전히 잊기", "삭제한 기억에 남습니다", "비밀번호·토큰·키로 보이는", "되돌릴 수 없습니다"):
            self.assertIn(expected, texts)  # the dialogs and notices were really read

    def test_positive_control_an_internal_value_and_an_english_sentence_are_reported(self):
        case = self.open()
        case.app.open_memory(case.first.memory_id)
        case.settle()
        case.hub.drawer.meta_label.set_text("출처: user-input")
        case.hub.drawer.title_label.set_text("This is not translated")
        case.settle()
        found = leaks(shown_texts(case.root), case.user_data())
        self.assertTrue(any("'user-input'" in p for p in found), found)
        self.assertTrue(any("'translated'" in p for p in found), found)
        self.assertFalse(any("'Codex'" in p or "memories.sqlite3" in p for p in found), found)


if __name__ == "__main__":
    unittest.main()
