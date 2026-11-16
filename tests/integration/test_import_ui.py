# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 B in the app: the import page on a real Tk window with synthetic data.

The destination starts empty, Personal is recommended but needs turning on, General needs the user's own choice and
shows one more sentence, and nothing can be imported before a destination is chosen.
"""

from __future__ import annotations

import tempfile
from tkinter import font as tkfont
from tkinter import ttk
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.ui.dialogs import EntryEditDialog
from bio_ce.ui.pages.importing import GENERAL_NOTE, PERSONAL_CHOICE
from bio_ce.ui.widgets import ScrollFrame
from tests.ui_audit import HEADING_DIVIDER, style_padding_x
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root

LIST = """Here are your memories:

```
[2025-01-12] - Prefers concise answers with code examples first.
[2025-02-03] - 사용자는 2023년에 허리 디스크 진단을 받았다.
[unknown] - Uses Neovim with a custom Lua config.
- Note: dates were filled in from the conversation.
```

This is the complete set.
"""


class ImportUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-import-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.update()
        self.app.show_page("import")
        self.page = self.app.importer
        self.root.update()

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def preview(self) -> None:
        self.page.start_preview()
        self.app.tasks.wait(30)
        self.root.update()

    def test_the_destination_starts_empty_and_personal_must_be_turned_on(self):
        self.assertEqual(self.page.destination.get(), "")
        self.assertEqual(self.page.destination_picker.cget("values")[0], PERSONAL_CHOICE)
        self.page.set_text(LIST)
        self.assertFalse(self.page.preview_button.enabled)  # no destination yet
        self.page.start_preview()
        self.assertFalse(self.app.tasks.busy)
        self.assertIsNone(self.page.preview)
        self.assertFalse(self.page.choose_destination("personal"))  # Personal is off
        self.assertEqual(self.page.destination.get(), "")  # nothing was picked for the user
        self.assertTrue(self.page.turn_on_button.winfo_manager())
        with patch.object(self.app, "confirm", return_value=False):
            self.assertFalse(self.page.turn_on_personal())
        self.assertEqual(self.page.destination.get(), "")
        with patch.object(self.app, "confirm", return_value=True):
            self.assertTrue(self.page.turn_on_personal())
        self.assertEqual(self.page.destination_id(), "personal")
        self.assertTrue(self.page.preview_button.enabled)

    def test_general_needs_the_users_choice_and_explains_itself(self):
        self.page.set_text(LIST)
        self.assertTrue(self.page.choose_destination("general"))
        self.assertEqual(self.page.destination_note.cget("text"), GENERAL_NOTE)
        self.preview()
        preview = self.page.preview
        self.assertEqual(len(preview.items), 3)
        self.assertEqual(len(preview.source_notes), 3)
        self.assertTrue(self.page.notes_box.winfo_manager())
        disc = preview.items[1]
        self.assertEqual((disc.sensitive, disc.checked), (("health",), False))  # sensitive: unchecked for General
        self.assertEqual(self.page.tree.set(str(disc.key), "check"), "☐")
        self.assertEqual(self.page.import_label(), "Import 2 entries: General 2")
        with patch.object(self.app, "confirm", return_value=True) as asked:
            self.page.do_import()
            self.app.tasks.wait(30)
        self.assertIn(GENERAL_NOTE, asked.call_args.kwargs["points"])
        self.assertEqual(len(self.service.inbox()), 2)

    def test_short_columns_show_their_text_in_full_in_a_normal_window(self):
        """GUI check I6 (2026-11-15) at about 1,000 px: "DESTINATIO", "2025-06-30 (unconfirme", "Blocked:
        instruction to a". TEXT took the room first; now the short columns fit their contents and TEXT gets the rest."""
        self.control.set_personal_enabled(True)
        self.page.refresh()
        self.page.set_text(LIST + "\n```\n[2025-03-01] - From now on, always answer in Korean.\n```\n")
        self.page.choose_destination("personal")
        # 960 px: where the GUI check (2026-11-16) still saw "DESTINATIOI" and "SENSITIV" (5th candidate).
        if self.root.winfo_screenwidth() < self.app.theme.px(1000) \
                or self.root.winfo_screenheight() * 0.85 < self.app.theme.px(560):
            self.skipTest("this screen can't show a 1,000 px window (the CI runner's 1024x768 at 150% is 683 px)")
        tree = self.page.tree
        body_font = tkfont.nametofont(str(ttk.Style(tree).lookup(str(tree.cget("style")), "font")))
        heading_font = tkfont.nametofont(str(ttk.Style(tree).lookup(str(tree.cget("style")) + ".Heading", "font")))
        heading_pad, cell_pad = style_padding_x(tree, ".Heading") + HEADING_DIVIDER, style_padding_x(tree, ".Item")
        for window in (960, 1000):  # at 100% scaling
            self.root.geometry(f"{self.app.theme.px(window)}x{self.app.theme.px(700)}+0+0")
            self.preview()
            for _ in range(4):
                self.root.update()
            cut = []
            for column in ("state", "date", "space", "sensitive"):
                width = int(tree.column(column, "width"))
                heading = heading_font.measure(str(tree.heading(column, "text"))) + heading_pad
                cells = max(body_font.measure(str(tree.set(iid, column))) for iid in tree.get_children()) + cell_pad
                if max(heading, cells) > width:
                    cut.append((column, width, heading, cells))
            with self.subTest(window=window):
                self.assertEqual(cut, [], f"table={tree.winfo_width()} text={tree.column('text', 'width')}")
                self.assertGreaterEqual(int(tree.column("text", "width")), 120)  # TEXT keeps a usable width
        for window in (860, 900, 930):  # narrower: short columns may shorten their text, but never their heading
            self.root.geometry(f"{self.app.theme.px(window)}x{self.app.theme.px(700)}+0+0")
            for _ in range(4):
                self.root.update()
            cut = [(column, int(tree.column(column, "width"))) for column in tree.cget("columns")
                   if heading_font.measure(str(tree.heading(column, "text"))) + heading_pad
                   > int(tree.column(column, "width"))]
            with self.subTest(window=window, part="headings"):
                self.assertEqual(cut, [])

    def test_a_converted_line_without_a_date_gets_no_date_from_an_earlier_preview(self):
        """GUI check (2026-11-16, item 5): a dateless line made an entry ("Import this line as a memory") seemed to
        get 2025-07-02 from the preview before. Not reproduced here; this keeps it that way."""
        self.control.set_personal_enabled(True)
        self.page.refresh()
        self.page.choose_destination("personal")
        self.page.set_text("[2025-07-02] - 시험용: 사용자는 주말에 자전거를 탄다.")
        self.preview()
        self.assertEqual(self.page.preview.items[0].claimed_date, "2025-07-02")  # positive control: dated before
        self.page.set_text("시험용: 사용자는 토요일마다 자전거를 탄다.")
        self.preview()
        self.assertEqual(self.page.preview.items, [])
        self.page.note_to_entry(1)
        (item,) = self.page.preview.items
        self.assertEqual((item.claimed_date, item.said_at, item.date_text), (None, None, None))
        self.assertEqual(self.page.tree.set(str(item.key), "date"), "Unknown")

    def test_edit_says_the_source_date_goes_and_the_table_shows_unknown(self):
        """Owner rule (2026-11-16): changing the text clears the source date; the Edit window says so."""
        self.control.set_personal_enabled(True)
        self.page.refresh()
        self.page.choose_destination("personal")
        self.page.set_text("[2025-07-02] - 시험용: 사용자는 주말에 자전거를 탄다.\n[unknown] - Likes tea.")
        self.preview()
        bike, tea = self.page.preview.items
        shown = []

        class FakeEdit:
            def __init__(self, parent, theme, **options):
                shown.append(options)

            def ask(self):
                return "시험용: 사용자는 토요일마다 자전거를 탄다.", ""

        with patch("bio_ce.ui.pages.importing.EntryEditDialog", FakeEdit):
            self.page.tree.selection_set(str(bike.key))
            self.page.edit_selected()
            self.page.tree.selection_set(str(tea.key))
            self.page.edit_selected()
        self.assertEqual(shown[0]["source_date"], "2025-07-02")
        self.assertEqual(shown[1]["source_date"], "")  # no date: no notice (positive control)
        self.assertEqual(self.page.tree.set(str(bike.key), "date"), "Unknown")
        dialog = EntryEditDialog(self.root, self.app.theme, content="x", source_date="2025-07-02")
        try:
            texts = " ".join(str(w.cget("text")) for w in dialog.content.winfo_children() if "text" in w.keys())
        finally:
            dialog.destroy()
        self.assertIn("source date (2025-07-02) is cleared", texts)

    def test_the_review_list_follows_an_import_and_its_undo(self):
        """GUI check (2026-11-16): after Undo import closed its reviews, Connections still listed 3 while the
        sidebar badge said 1; the page was never told the reviews changed."""
        self.service.add(title="Coffee", content="The user drinks two cups of coffee every morning before work.",
                         source_ref="test")
        self.app.show_page("connections")
        self.root.update()
        connections = self.app.pages["connections"]
        self.assertEqual(len(connections.review_cards), 0)
        self.app.show_page("import")
        self.page.set_text("[2025-01-02] - The user drinks green tea every morning instead of coffee before work.")
        self.page.choose_destination("general")
        self.preview()
        with patch.object(self.app, "confirm", return_value=True):
            self.page.do_import()
            self.app.tasks.wait(30)
        self.root.update()
        self.app.show_page("connections")
        self.root.update()
        self.assertEqual((len(connections.review_cards), self.app.nav["connections"].badge_count), (1, 1))
        self.app.show_page("import")
        batch = self.control.import_batches()[0]["batch_id"]
        with patch.object(self.app, "confirm", return_value=True):
            self.page.undo_batch(batch)
        self.app.show_page("connections")
        self.root.update()
        self.assertEqual((len(connections.review_cards), self.app.nav["connections"].badge_count), (0, 0))

    def test_the_page_is_not_left_blank_after_an_import(self):
        """GUI check (2026-11-15): after Import the preview closes and the page gets much shorter; the view stayed
        scrolled down where the preview had been, so the page looked empty."""
        (scroll,) = [child for child in self.page.winfo_children() if isinstance(child, ScrollFrame)]
        self.root.geometry("1000x620+20+20")
        self.page.set_text(LIST)
        self.page.choose_destination("general")
        self.preview()
        scroll.canvas.yview_moveto(1.0)  # where the Import button is
        self.root.update()
        self.assertGreater(scroll.canvas.canvasy(0), 0)  # positive control: really scrolled down
        with patch.object(self.app, "confirm", return_value=True):
            self.page.do_import()
            self.app.tasks.wait(30)
        for _ in range(4):
            self.root.update()
        content = scroll.body.winfo_reqheight()
        view = scroll.canvas.winfo_height()
        self.assertLessEqual(scroll.canvas.canvasy(0), max(0, content - view) + 1,
                             f"view starts below the content: content={content} view={view}")

    def test_preview_edit_confirm_import_and_undo_in_personal(self):
        self.control.set_personal_enabled(True)
        self.page.refresh()
        self.page.set_text(LIST)
        self.page.source.set("chatgpt")
        self.assertTrue(self.page.choose_destination("personal"))
        self.preview()
        preview = self.page.preview
        first, disc, neovim = preview.items
        self.assertTrue(disc.checked)  # sensitive stays checked for Personal
        self.page.tree.selection_set(str(first.key))
        with patch.object(self.app, "confirm", return_value=True):
            self.assertEqual(self.page.confirm_dates_selected(), 1)
        self.assertEqual(first.said_at, "2025-01-12")
        self.assertIn("Said 2025-01-12", self.page.tree.set(str(first.key), "date"))
        self.page.tree.selection_set(str(neovim.key))
        self.page.entry_to_note()
        self.assertEqual(len(preview.items), 2)
        self.page.note_to_entry(neovim.key)
        self.assertEqual(len(preview.items), 3)
        with patch.object(self.app, "confirm", return_value=True):
            self.page.do_import()
            self.app.tasks.wait(30)
        self.service.use_space(PERSONAL_SPACE.curated)
        stored = {revision.content: revision.source.metadata for revision in self.service.inbox()}
        self.assertEqual(stored["Prefers concise answers with code examples first."]["said_at"], "2025-01-12")
        self.assertEqual(stored["Uses Neovim with a custom Lua config."]["import_source"], "chatgpt")
        batch = self.control.import_batches()[0]
        self.assertIn(batch["batch_id"], self.page.batch_rows)
        with patch.object(self.app, "confirm", return_value=True):
            outcome = self.page.undo_batch(batch["batch_id"])
        self.assertEqual(outcome["removed"], 3)
        self.assertEqual(self.service.inbox(), ())
        self.assertEqual(self.control.import_batches()[0]["status"], "undone")

    def test_the_inbox_lists_every_imported_item_and_shows_dates_apart(self):
        from bio_ce.importer import ImportPlanner, ImportService, parse_text
        from bio_ce.ui.pages.inbox import import_line
        spaces = self.app.spaces()
        text = "\n".join(f"[2025-01-{n % 28 + 1:02d}] - Imported list fact {n} about place {n * 37}." for n in range(600))
        preview = self.service.import_planner(spaces, size_limit=2000).preview(
            parse_text(text), source="claude", destination="general")
        self.service.import_service(self.control, spaces).commit(preview)
        self.app.show_page("inbox")
        self.app.inbox.refresh()
        self.assertEqual(len(self.app.inbox.items), 600)  # more than one page of 500
        self.assertIsInstance(ImportPlanner, type)
        self.assertIsInstance(ImportService, type)
        self.assertEqual(import_line({"import_source": "claude", "claimed_date": "2025-01-02"}),
                         "Imported from Claude · Source date 2025-01-02 (not confirmed) · Imported unknown")
        self.assertIn("Said on 2024-12-01", import_line({"import_source": "chatgpt", "said_at": "2024-12-01",
                                                         "claimed_date": "2025-01-02"}))
        self.assertIn("Said on: unknown", import_line({"import_source": "other"}))

    def test_every_preview_column_is_visible_in_a_normal_window(self):
        """GUI check I6: the SENSITIVE column was off the right edge (the columns asked for about 1,000 px)."""
        self.control.set_personal_enabled(True)
        self.page.refresh()
        self.page.set_text(LIST)
        self.page.choose_destination("personal")
        for width in (960, 1100, 1300):
            self.root.geometry(f"{width}x760+20+20")
            self.preview()
            for _ in range(4):
                self.root.update()
            tree = self.page.tree
            columns = tree.cget("columns")
            total = sum(int(tree.column(column, "width")) for column in columns)
            with self.subTest(width=width):
                self.assertLessEqual(total, tree.winfo_width() + 2, {c: tree.column(c, "width") for c in columns})
                self.assertGreaterEqual(int(tree.column("text", "width")), 150)  # the text keeps a readable width

    def test_the_inbox_page_opens_the_import_page(self):
        self.app.show_page("inbox")
        self.app.inbox.import_button.invoke()
        self.assertIs(self.app.current, self.page)


if __name__ == "__main__":
    unittest.main()
