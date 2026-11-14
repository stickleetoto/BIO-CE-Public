# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 E in the app: the Claude desktop app card, its connect message, and saving the skill as a ZIP."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from bio_ce.connections import ConnectionResult
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


class ClaudeDesktopUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-claude-desktop-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.update()
        self.page = self.app.pages["connections"]
        self.app.show_page("connections")
        self.page.refresh()
        self.root.update()

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def test_the_card_exists_and_says_how_to_finish(self):
        from bio_ce.ui.pages.connections import HOST_DESCRIPTIONS
        card = self.page.cards["claude_desktop"]
        self.assertEqual(card.status.host, "claude_desktop")
        self.assertIn("settings file", HOST_DESCRIPTIONS["claude_desktop"])
        self.assertEqual(card.skill_button.text, "Save skill as ZIP…")
        self.assertIn("claude_desktop", self.app.host_statuses(refresh=True))
        self.assertIn("Claude desktop app", [label.cget("text") for label in _labels(self.app.dashboard)])
        with patch.object(self.app, "notify") as told:
            self.page._connected("claude_desktop", ConnectionResult("claude_desktop", True, False, None))
        message = told.call_args.args[1]
        self.assertIn("Quit the Claude desktop app completely", message)
        self.assertIn("Customize → Skills", message)

    def test_save_skill_as_zip_never_overwrites(self):
        target = Path(self.temp.name) / "bio-ce-memory.zip"
        with patch.object(self.app, "confirm", return_value=True), \
                patch.object(self.app, "ask_save_path", return_value=str(target)):
            saved = self.page.save_skill_zip()
        self.assertEqual(zipfile.ZipFile(saved).namelist(), ["bio-ce-memory/SKILL.md"])
        before = target.read_bytes()
        with patch.object(self.app, "confirm", return_value=True), \
                patch.object(self.app, "ask_save_path", return_value=str(target)):
            self.assertIsNone(self.page.save_skill_zip())
        self.assertEqual(target.read_bytes(), before)

    def test_a_missing_app_says_so(self):
        self.connections.desktop_installed = False
        self.page.refresh()
        self.root.update()
        self.assertIn("didn't find the Claude desktop app", self.page.cards["claude_desktop"].message.cget("text"))


def _labels(widget):
    for child in widget.winfo_children():
        if child.winfo_class() == "Label":
            yield child
        yield from _labels(child)


if __name__ == "__main__":
    unittest.main()
