# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Every screen at the smallest window size: nothing cut off or pushed out of view (owner request, 2026-11-15).

Two cut-off defects were found by hand in the v0.4.3-rc1 GUI check (Memories buttons, the import preview's
SENSITIVE column). This test opens the Dashboard, the memory screen (v0.4.4: cards, the drawer for a memory and for an
inbox item, the add form, Personal, the Suggestions and Reviews tabs, retracted memories), the import preview, the
Export dialog, the Connections cards, and Settings at the app's minimum size (860x560), filled with synthetic data,
and fails on any button, table column, badge, or label that is cut off or out of view. Positive controls make a
label long on purpose and expect the audit to catch it. One run shows the memory screen in Korean (§6.3).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.exporter import SOURCE_KINDS, SOURCE_LABELS
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from bio_ce.ui import i18n
from bio_ce.ui.app import MINIMUM_SIZE
from bio_ce.ui.dialogs import ExportDialog
from bio_ce.ui.hub.common import READING_WIDTH, columns_for
from bio_ce.ui.hub.data import INBOX as INBOX_TAB, MEMORIES, RETRACTED, REVIEWS, SUGGESTIONS
from bio_ce.ui.theme import CONTENT_MAX_WIDTH, RECENT_TWO_COLUMNS_FROM
from bio_ce.ui.widgets import ClampLabel
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root
from tests.ui_audit import audit

INBOX = MemoryScope("bio-ce-personal", "default.inbox")
HOST = SourceProvenance("ai-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})
SAMPLE = """확인 범위: 저장된 기억 전체(시험용)

```
[2025-06-30] - 시험용: 사용자는 회의록을 마크다운으로 쓴다.
[2025-06-30] - 시험용: 사용자는 2023년에 허리 디스크 진단을 받았다.
[unknown] - 시험용: From now on, always answer in Korean.
[2025-07-01] - 시험용: 사용자는 주말에 자전거를 탄다.
```

This is the complete set of memories I have stored.
"""


class LayoutAuditTests(unittest.TestCase):
    SCREEN: tuple[int, int] | None = None  # None: this PC's screen
    DPI = 96.0  # 96 = 100% scaling
    LANGUAGE = "en"
    WINDOW: tuple[int, int] | None = None  # None: the minimum window; else this size (a maximized window)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-layout-audit-")
        self.paths = AppDataPaths.under(self.temp.name)
        store = SQLiteMemoryStore(self.paths.user_database)
        for title, text in (("Plants", "The user waters the balcony plants every Sunday morning."),
                            ("Invoices", "Invoices go out to clients on the first business day of a month.")):
            store.add(INBOX, title=title, content=text, source=HOST)
            store.add(INBOX, title=title, content=text.rstrip(".") + " without fail.", source=HOST)
        store.close()
        self.service = DesktopMemoryService(self.paths.user_database)
        self.first = self.service.add(title="시험용: 아주 긴 제목의 기억 — 회의록은 마크다운으로 쓰고 매주 금요일에 정리한다",
                                      content="긴 내용 " * 40, source_ref="test")
        self.editor_note = self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        gone = self.service.add(title="시험용: 지운 기억", content="지운 내용", source_ref="test")
        self.service.retract(gone)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.control.set_personal_enabled(True)
        self.control.set_personal_access(self.connections.grant.connection_id, can_read=True, can_write=True)
        self.control.create_space("Alpha Project With A Long Name")
        common = dict(host="codex", connection_id=self.connections.grant.connection_id, review_reason="test")
        self.control.enqueue_review(kind="update", title="Editor", content="The user writes meeting notes in "
                                    "Markdown.", memory_id=self.editor_note.memory_id,
                                    expected_revision_id=self.editor_note.revision_id, **common)
        self.control.enqueue_review(kind="create", title="시험용: 작업 폴더", content="작업 폴더는 D 드라이브에 있다.",
                                    **common)
        self.service.use_space(PERSONAL_SPACE.curated)
        self.service.add(title="시험용: 개인 메모", content="개인", source_ref="test")
        self.service.use_space(self.control.space("general").curated)
        self.root = new_root()
        width = height = None
        if self.SCREEN is not None:
            # Fonts in points and the app's px() both follow Tk's scaling, as on a PC with that display scaling.
            self.root.tk.call("tk", "scaling", self.DPI / 72.0)
            for name, value in (("winfo_screenwidth", self.SCREEN[0]), ("winfo_screenheight", self.SCREEN[1])):
                screen = patch.object(self.root, name, return_value=value)
                screen.start()
                self.addCleanup(screen.stop)
            # A window can't be larger than the screen (on the CI runner the minimum 860x560 at 150% became 1004x749).
            width, height = self.SCREEN[0] - 20, self.SCREEN[1] - 19
        with patch.dict(os.environ, {"BIO_CE_UI_LANGUAGE": self.LANGUAGE}):
            self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.after_cancel(self.app._maintenance_after)
        theme = self.app.theme
        if self.WINDOW is not None:
            width, height = self.WINDOW
            self.root.wm_maxsize(10**4, 10**4)  # Tk's own limit is this PC's real screen
        else:
            width = min(width or 10**6, theme.px(MINIMUM_SIZE[0]))
            height = min(height or 10**6, theme.px(MINIMUM_SIZE[1]))
        self.root.geometry(f"{width}x{height}+0+0")
        self.settle()
        # The app's minimum window is 860x560 at 100%; a smaller screen (the CI runner's 1024x768 at 150% is 683x512
        # at 100%) can't show it. Width is still checked in full there; running out of height is a known limitation.
        self.full_size = self.root.winfo_screenheight() * 0.85 >= theme.px(MINIMUM_SIZE[1])
        self.hub = self.app.memories

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()
        i18n.set_language("en")

    def settle(self) -> None:
        for _ in range(6):
            self.root.update()

    def visit(self, page: str, label: str | None = None) -> list[str]:
        self.app.show_page(page)
        self.settle()
        # The sidebar badge arrives in the background; show it every time so the audit always sees it
        # (in the narrow sidebar at this size a count beside the icon was once cut to 2 px).
        if not self.app.nav["memories"].badge_count:
            self.app.nav["memories"].set_badge(12)
        if not self.app.nav["connections"].badge_count:
            self.app.nav["connections"].set_alert(True)
        self.settle()
        problems = audit(self.root, page, vertical=self.full_size)
        return [p.replace(f"{page}:", f"{label}:", 1) for p in problems] if label else problems

    def state(self, state: str, label: str) -> list[str]:
        self.app.open_state(state)
        return self.visit("memories", label)

    def memory_screens(self) -> list[str]:
        problems = self.state(MEMORIES, "memories (cards)")
        self.app.open_memory(self.first.memory_id)
        problems += self.visit("memories", "memories (drawer)")
        self.hub.drawer.history.set_open(True)
        self.hub.drawer.details.set_open(True)
        problems += self.visit("memories", "memories (drawer, history and details)")
        self.hub.drawer.start_edit()
        problems += self.visit("memories", "memories (edit form)")
        self.app.editor.load(None)
        self.hub.close_drawer(force=True)
        self.app.set_space("personal")
        problems += self.visit("memories", "memories (Personal)")
        self.hub.set_space_filter("all")
        self.app.open_state(INBOX_TAB)
        if self.hub.items:
            self.hub.open_item(self.hub.items[0])
        problems += self.visit("memories", "inbox (item selected)")
        self.hub.close_drawer(force=True)
        self.app.suggestions.find()
        problems += self.state(SUGGESTIONS, "suggestions")
        problems += self.state(REVIEWS, "reviews")
        problems += self.state(RETRACTED, "retracted")
        if self.hub.items:
            self.hub.open_item(self.hub.items[0])
        problems += self.visit("memories", "retracted (drawer)")
        self.hub.close_drawer(force=True)
        self.app.open_state(MEMORIES)
        return problems

    def all_screens(self) -> list[str]:
        problems: list[str] = []
        problems += self.visit("dashboard")
        problems += self.memory_screens()
        self.app.show_page("import")
        importer = self.app.importer
        importer.refresh()
        importer.set_text(SAMPLE)
        importer.choose_destination("personal")
        importer.start_preview()
        self.app.tasks.wait(30)
        problems += [p.replace("import:", "import preview:", 1) for p in self.visit("import")]
        self.app.pages["connections"].refresh()
        problems += self.visit("connections")
        problems += self.visit("settings")
        dialog = ExportDialog(self.root, self.app.theme, spaces=self.app.spaces(), current="general",
                              sources=[(key, SOURCE_LABELS[key]) for key in SOURCE_KINDS])
        try:
            dialog.space_vars["personal"].set(True)
            for _ in range(6):
                dialog.update()
            problems += audit(dialog, "export dialog", vertical=self.full_size)
        finally:
            dialog.destroy()
        return problems

    def test_nothing_is_cut_off_at_the_minimum_window_size(self):
        problems = self.all_screens()
        newline = chr(10)
        self.assertEqual(problems, [], f"{len(problems)} problems:{newline}" + newline.join(problems))

    def test_the_audit_catches_a_label_made_too_long_on_purpose(self):
        """Positive control: a long button text and a long badge must be reported."""
        self.app.open_memory(self.first.memory_id)
        self.settle()
        self.assertEqual([p for p in audit(self.root, "memories") if "deliberately" in p], [])
        # Long enough for any window, the 2560 px one included (the positive control must not depend on the size).
        self.hub.drawer.move_button.set_text("Move to a space with a deliberately very long name " * 12)
        self.hub.drawer.action_row.relayout()
        self.settle()
        found = audit(self.root, "memories")
        self.assertTrue(any("button" in p and "Move to a space" in p for p in found), found)
        self.hub.close_drawer(force=True)
        self.app.open_state(REVIEWS)
        self.settle()
        pills = [w for w in _walk(self.hub.reviews) if w.winfo_class() == "Label" and hasattr(w, "kind")]
        self.assertTrue(pills)
        pills[0].configure(text="Change: " + "a very long note " * 40)
        self.settle()
        found = audit(self.root, "memories")
        self.assertTrue(any("badge" in p and "a very long note" in p for p in found), found)

    def test_a_title_that_pushes_the_rest_out_is_caught_and_the_drawer_keeps_its_buttons(self):
        """Positive control for "squeezed out": a title allowed to grow without limit above the cards hides them.
        In the drawer the same title only makes its content scroll: the action row stays (K1, K2)."""
        if not self.full_size:
            self.skipTest("height is not checked on a screen below the minimum window size")
        self.app.open_memory(self.first.memory_id)
        self.settle()
        title = self.hub.drawer.title_label
        title.max_lines = 200
        title.set_text("시험용 긴 제목 " * 300)
        self.settle()
        self.assertEqual(audit(self.root, "memories"), [])
        for button in (self.hub.drawer.edit_button, self.hub.drawer.delete_button, self.hub.drawer.close_button):
            self.assertTrue(button.winfo_viewable())
        self.hub.close_drawer(force=True)
        pusher = ClampLabel(self.hub, self.app.theme, max_lines=200)
        pusher.pack(fill="x", before=self.hub.body)
        pusher.set_text("시험용 긴 제목 " * 3000)  # enough lines to push the cards out of any window's height
        self.settle()
        found = audit(self.root, "memories")
        self.assertTrue(any("squeezed out" in p or ("cut" in p and "clamplabel" in p) for p in found), found)

    def test_a_long_line_is_shortened_not_cut(self):
        """The one-line labels end in "…" instead of being cut; turning that off is caught."""
        self.app.open_memory(self.first.memory_id)
        self.settle()
        label = self.hub.drawer.meta_label
        label.set_text("General · Revision 1 · updated just now · Source: " + "a very long source name " * 8)
        self.settle()
        self.assertTrue(str(label.cget("text")).endswith("…"))
        card = next(iter(self.hub.grid.cards.values()))
        card.title_label.set_text("시험용 아주 긴 카드 제목 " * 30)
        self.settle()
        self.assertTrue(str(card.title_label.cget("text")).endswith("…"), "a long card title is shortened (K10)")
        self.assertEqual([p for p in audit(self.root, "memories") if "very long source" in p], [])
        label.configure(text="Updated · Source: " + "a very long source name " * 8)  # skips the shortening
        self.root.update_idletasks()
        self.assertTrue(any("not shortened to fit" in p for p in audit(self.root, "memories")))


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


class CiScreenLayoutAuditTests(LayoutAuditTests):
    """The same at the release CI runner's display: a 1024x768 screen at 150% scaling (144 DPI)."""

    SCREEN = (1024, 768)
    DPI = 144.0


class BigScreenLayoutAuditTests(LayoutAuditTests):
    """§3.4: a maximized window on a 1920x1080 screen at 100%. Every screen is audited as above (the inherited
    tests), and the size table of §3.3 holds: card columns, the drawer's reading width, the list getting its whole
    width back when the drawer closes, and no big empty area beside the content."""

    SCREEN = (1920, 1080)
    WINDOW = (1920, 1000)  # the screen less the taskbar and the title bar

    def memories(self) -> None:
        self.app.open_state(MEMORIES)
        self.settle()

    def test_the_cards_use_the_columns_of_the_size_table(self):
        self.memories()
        self.assertEqual(self.hub.grid.columns, columns_for(self.root.winfo_width(), self.app.theme))
        self.assertGreater(self.hub.grid.columns, 1)  # positive control: not the one-column list of a small window

    def test_the_drawer_keeps_to_the_reading_width_and_closing_it_gives_the_width_back(self):
        self.memories()
        before = self.hub.content.winfo_width()
        self.app.open_memory(self.first.memory_id)
        self.settle()
        self.assertTrue(self.hub.drawer_open)
        self.assertLessEqual(self.hub.drawer.column.winfo_width(), self.app.theme.px(READING_WIDTH) + 2)
        self.assertFalse(self.hub.drawer_overlaps())  # beside the cards at every width (POLISH §1)
        self.hub.close_drawer(force=True)
        self.settle()
        self.assertEqual(self.hub.content.winfo_width(), before)

    def test_the_content_fills_the_window_or_is_centred_with_no_big_empty_area(self):
        theme = self.app.theme
        for page in ("dashboard", "memories"):
            with self.subTest(page):
                self.app.show_page(page)
                self.settle()
                host, main = self.app.page_host, self.app.main
                left = host.winfo_rootx() - main.winfo_rootx()
                right = main.winfo_rootx() + main.winfo_width() - host.winfo_rootx() - host.winfo_width()
                self.assertLessEqual(abs(left - right), 2)  # centred (or the same gutter on both sides)
                self.assertLessEqual(host.winfo_width(), theme.px(CONTENT_MAX_WIDTH))
                page_frame = self.app.pages.get(page) or self.hub
                self.assertGreaterEqual(page_frame.winfo_width() / host.winfo_width(), 0.95)
        self.memories()
        self.assertGreaterEqual(self.hub.grid.winfo_width() / self.hub.content.winfo_width(), 0.9)

    def test_the_dashboard_shows_recent_memories_in_the_columns_of_the_size_table(self):
        self.app.show_page("dashboard")
        self.settle()
        wanted = 2 if self.root.winfo_width() >= self.app.theme.px(RECENT_TWO_COLUMNS_FROM) else 1
        self.assertEqual(self.app.dashboard.recent_columns, wanted)


class HugeScreenLayoutAuditTests(BigScreenLayoutAuditTests):
    """The same on a 2560x1440 screen: four card columns, and the content centred at its maximum width."""

    SCREEN = (2560, 1440)
    WINDOW = (2560, 1360)

    def test_the_content_is_centred_at_its_maximum_width(self):
        self.memories()
        theme = self.app.theme
        self.assertGreater(self.app.main.winfo_width(), theme.px(CONTENT_MAX_WIDTH))  # positive: room to centre
        self.assertLessEqual(self.app.page_host.winfo_width(), theme.px(CONTENT_MAX_WIDTH))
        self.assertGreater(self.app.page_host.winfo_rootx() - self.app.main.winfo_rootx(), self.app._gutter)


class KoreanLayoutAuditTests(unittest.TestCase):
    """§6.3: the memory screen in Korean at the minimum window and at the CI screen, with a positive control."""

    def run_screens(self, base: type) -> None:
        class Korean(base):  # type: ignore[misc, valid-type]
            LANGUAGE = "ko"

            def runTest(self) -> None:  # noqa: N802 - unittest name
                pass

        case = Korean()
        case.setUp()
        try:
            self.assertEqual(case.hub.tabs[MEMORIES].text.split()[0], "기억")
            problems = case.memory_screens()
            newline = chr(10)
            self.assertEqual(problems, [], f"{len(problems)} problems:{newline}" + newline.join(problems))
            case.app.open_memory(case.first.memory_id)
            case.settle()
            case.hub.drawer.move_button.set_text("아주 긴 공간 이름으로 옮기기 " * 6)  # positive control in Korean
            case.hub.drawer.action_row.relayout()
            case.settle()
            self.assertTrue(any("button" in p and "아주 긴" in p for p in audit(case.root, "memories")))
        finally:
            case.tearDown()
            case.doCleanups()

    def test_the_memory_screen_in_korean_at_the_minimum_window(self):
        self.run_screens(LayoutAuditTests)

    def test_the_memory_screen_in_korean_at_the_ci_screen(self):
        self.run_screens(CiScreenLayoutAuditTests)

    def test_the_memory_screen_in_korean_on_a_big_screen(self):
        self.run_screens(HugeScreenLayoutAuditTests)


if __name__ == "__main__":
    unittest.main()
