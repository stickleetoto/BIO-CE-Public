# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 D in the app: the export dialog, the Personal warning, and never overwriting a file."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.exporter import SOURCE_KINDS
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.ui.dialogs import ExportDialog, export_sources
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


class ExportUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-export-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.service.add(title="Units", content="Prefers metric units.", source_ref="test")
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.control.set_personal_enabled(True)
        self.service.use_space(PERSONAL_SPACE.curated)
        self.service.add(title="Clinic", content="The user's clinic is on Elm Street.", source_ref="test")
        self.service.use_space(self.control.space("general").curated)
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.update()
        self.target = Path(self.temp.name) / "out" / "export.md"
        self.target.parent.mkdir()

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def choose(self, **values):
        options = {"space_ids": ("general",), "include_inbox": False, "sources": frozenset(SOURCE_KINDS),
                   "date_from": None, "date_to": None, "include_claimed": False, **values}
        return patch.object(self.app, "ask_export", return_value=options)

    def test_export_writes_a_new_file_and_never_overwrites(self):
        with self.choose(), patch.object(self.app, "ask_save_path", return_value=str(self.target)):
            written = self.app.export_memories()
        text = written.read_text(encoding="utf-8")
        self.assertIn("] - Units: Prefers metric units.", text)
        self.assertNotIn("Clinic", text)
        with self.choose(), patch.object(self.app, "ask_save_path", return_value=str(self.target)), \
                patch.object(self.app, "notify") as told:
            self.assertIsNone(self.app.export_memories())
        self.assertIn("never overwrites", told.call_args.args[1])
        self.assertEqual(self.target.read_text(encoding="utf-8"), text)

    def test_personal_needs_a_second_yes_and_is_in_the_file_only_then(self):
        with self.choose(space_ids=("general", "personal")), \
                patch.object(self.app, "confirm", return_value=False), \
                patch.object(self.app, "ask_save_path", side_effect=AssertionError("not asked")):
            self.assertIsNone(self.app.export_memories())
        self.assertFalse(self.target.exists())
        with self.choose(space_ids=("general", "personal")), patch.object(self.app, "confirm", return_value=True), \
                patch.object(self.app, "ask_save_path", return_value=str(self.target)):
            written = self.app.export_memories()
        self.assertIn("Clinic", written.read_text(encoding="utf-8"))

    def test_dialog_defaults_and_the_personal_warning(self):
        dialog = ExportDialog(self.root, self.app.theme, spaces=self.app.spaces(), current="general",
                              sources=export_sources())
        try:
            self.assertTrue(dialog.space_vars["general"].get())
            self.assertFalse(dialog.space_vars["personal"].get())  # never ticked for the user
            self.assertTrue(all(variable.get() for variable in dialog.source_vars.values()))
            self.assertFalse(dialog.include_claimed.get())
            dialog.space_vars["personal"].set(True)
            self.root.update()
            self.assertTrue(dialog.personal_warning.winfo_manager())
            dialog.date_from.set("next week")
            dialog._done()
            self.assertIn("Use dates such as", dialog.error.cget("text"))
            dialog.date_from.set("2025-01-01")
            dialog._done()
            self.assertEqual(dialog.result["space_ids"], ("general", "personal"))
        finally:
            if dialog.winfo_exists():
                dialog.destroy()


if __name__ == "__main__":
    unittest.main()
