# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Every screen at the smallest window size: nothing cut off or pushed out of view (owner request, 2026-11-15).

Two cut-off defects were found by hand in the v0.4.3-rc1 GUI check (Memories buttons, the import preview's
SENSITIVE column). This test opens the Dashboard, Memories (list and reading pane), the Inbox, the import preview,
the Suggestions, the Export dialog, the Connections cards, and Settings at the app's minimum size (860x560), filled
with synthetic data, and fails on any button, table column, badge, or label that is cut off or out of view.
A positive control makes a label long on purpose and expects the audit to catch it. The same test is meant to check
the Korean texts of v0.4.4.
"""

from __future__ import annotations

import tempfile
import unittest

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.exporter import SOURCE_KINDS, SOURCE_LABELS
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from bio_ce.ui.app import MINIMUM_SIZE
from bio_ce.ui.dialogs import ExportDialog
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
        self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.control.set_personal_enabled(True)
        self.control.set_personal_access(self.connections.grant.connection_id, can_read=True, can_write=True)
        self.control.create_space("Alpha Project With A Long Name")
        self.service.use_space(PERSONAL_SPACE.curated)
        self.service.add(title="시험용: 개인 메모", content="개인", source_ref="test")
        self.service.use_space(self.control.space("general").curated)
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        theme = self.app.theme
        self.root.geometry(f"{theme.px(MINIMUM_SIZE[0])}x{theme.px(MINIMUM_SIZE[1])}+20+20")
        self.settle()

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def settle(self) -> None:
        for _ in range(6):
            self.root.update()

    def visit(self, page: str) -> list[str]:
        self.app.show_page(page)
        self.settle()
        # The sidebar counts arrive in the background; show them every time so the audit always sees them
        # (in the narrow sidebar at this size a count beside the icon was once cut to 2 px).
        for key, count in (("memories", 12), ("connections", 3)):
            if not self.app.nav[key].badge_count:
                self.app.nav[key].set_badge(count)
        self.settle()
        return audit(self.root, page)

    def all_screens(self) -> list[str]:
        problems: list[str] = []
        problems += self.visit("dashboard")
        self.app.show_page("memories")
        self.app.memories.refresh()
        self.app.memories.select(self.first.memory_id)
        problems += self.visit("memories")
        self.app.set_space("personal")
        problems += self.visit("memories")
        self.app.set_space("general")
        self.app.show_page("inbox")
        self.app.inbox.refresh()
        children = self.app.inbox.tree.get_children()
        if children:
            self.app.inbox.tree.selection_set(children[0])
        problems += [p.replace("inbox:", "inbox (item selected):", 1) for p in self.visit("inbox")]
        self.app.show_page("import")
        importer = self.app.importer
        importer.refresh()
        importer.set_text(SAMPLE)
        importer.choose_destination("personal")
        importer.start_preview()
        self.app.tasks.wait(30)
        problems += [p.replace("import:", "import preview:", 1) for p in self.visit("import")]
        self.app.suggestions.find()
        problems += self.visit("suggestions")
        self.app.pages["connections"].refresh()
        problems += self.visit("connections")
        problems += self.visit("settings")
        dialog = ExportDialog(self.root, self.app.theme, spaces=self.app.spaces(), current="general",
                              sources=[(key, SOURCE_LABELS[key]) for key in SOURCE_KINDS])
        try:
            dialog.space_vars["personal"].set(True)
            for _ in range(6):
                dialog.update()
            problems += audit(dialog, "export dialog")
        finally:
            dialog.destroy()
        return problems

    def test_nothing_is_cut_off_at_the_minimum_window_size(self):
        problems = self.all_screens()
        newline = chr(10)
        self.assertEqual(problems, [], f"{len(problems)} problems:{newline}" + newline.join(problems))

    def test_the_audit_catches_a_label_made_too_long_on_purpose(self):
        """Positive control: a long button text and a long badge must be reported."""
        self.app.show_page("memories")
        self.app.memories.refresh()
        self.settle()
        self.assertEqual([p for p in audit(self.root, "memories") if "Move to" in p], [])
        self.app.memories.move_button.set_text("Move to a space with a deliberately very long name " * 3)
        self.app.set_space("personal")
        self.app.memories.space_bar.personal_pill.configure(text="Personal: " + "a very long note " * 12)
        self.app.memories.space_bar.relayout()
        self.settle()
        found = audit(self.root, "memories")
        self.assertTrue(any("button" in p and "Move to a space" in p for p in found), found)
        self.assertTrue(any("badge" in p and "a very long note" in p for p in found), found)

    def test_a_long_line_is_shortened_not_cut(self):
        """The one-line labels end in "…" instead of being cut; turning that off is caught."""
        self.app.show_page("memories")
        self.app.memories.refresh()
        self.app.memories.select(self.first.memory_id)
        self.settle()
        label = self.app.memories.meta_label
        label.set_text("Updated 2026-11-15 16:24 · Source: " + "a very long source name " * 8)
        self.settle()
        self.assertTrue(str(label.cget("text")).endswith("…"))
        self.assertEqual([p for p in audit(self.root, "memories") if "meta" in p or "very long source" in p], [])
        label.configure(text="Updated · Source: " + "a very long source name " * 8)  # skips the shortening
        self.root.update_idletasks()
        self.assertTrue(any("not shortened to fit" in p for p in audit(self.root, "memories")))


if __name__ == "__main__":
    unittest.main()
