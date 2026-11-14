# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 B in the app: the import page on a real Tk window with synthetic data.

The destination starts empty, Personal is recommended but needs turning on, General needs the user's own choice and
shows one more sentence, and nothing can be imported before a destination is chosen.
"""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.ui.pages.importing import GENERAL_NOTE, PERSONAL_CHOICE
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

    def test_the_inbox_page_opens_the_import_page(self):
        self.app.show_page("inbox")
        self.app.inbox.import_button.invoke()
        self.assertIs(self.app.current, self.page)


if __name__ == "__main__":
    unittest.main()
