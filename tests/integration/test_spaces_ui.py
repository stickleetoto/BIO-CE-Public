# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Settings → Spaces and the host card's project-space switch, on a real Tk window with synthetic data."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bio_ce.connections import ConnectionResult
from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


class SpacesUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-spaces-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.connections.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.update()
        self.settings = self.app.pages["settings"]

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def test_create_rename_link_unlink_and_archive_a_project_space(self):
        control = self.connections.control
        self.app.show_page("settings")
        self.assertEqual(list(self.settings.space_rows), ["general"])
        with patch.object(self.app, "ask_name", return_value="Alpha App"):
            self.settings.new_space()
        alpha = next(space for space in control.spaces() if space.display_name == "Alpha App")
        self.assertIn(alpha.space_id, self.settings.space_rows)
        folder = Path(self.temp.name) / "work" / "alpha"
        folder.mkdir(parents=True)
        with patch.object(self.app, "ask_folder", return_value=str(folder)):
            self.settings.link_folder(alpha)
        self.assertEqual([label for _id, _key, label in control.folder_links()], ["alpha"])
        with patch.object(self.app, "ask_name", return_value="Alpha"):
            self.settings.rename_space(alpha)
        self.assertEqual(control.space(alpha.space_id).display_name, "Alpha")
        with patch.object(self.app, "ask_name", return_value="alpha"):
            self.settings.new_space()  # same name in another case: refused, shown as an error
        self.assertEqual(len(control.spaces()), 2)
        self.settings.unlink_folder(alpha, control.folder_links()[0][1])
        self.assertEqual(control.folder_links(), ())
        with patch.object(self.app, "confirm", return_value=True):
            self.settings.archive_space(control.space(alpha.space_id))
        self.assertEqual(list(self.settings.space_rows), ["general"])

    def test_connect_message_names_the_settings_that_apply(self):
        page = self.app.pages["connections"]
        page.refresh()
        self.root.update()
        result = ConnectionResult("codex", True, False, None)
        with patch.object(self.app, "notify") as told:
            page._connected("codex", result)
        message = told.call_args.args[1]
        self.assertIn("Use all project spaces: on.", message)
        self.assertIn("Saving: Curated.", message)
        self.connections.control.set_connection_settings(self.connections.grant.connection_id, all_projects=False,
                                                         save_mode="collect")
        with patch.object(self.app, "notify") as told:
            page._connected("codex", result)
        message = told.call_args.args[1]
        self.assertIn("Use all project spaces: off (General only).", message)
        self.assertIn("Saving: Collect (to your inbox).", message)

    def test_host_card_switches_project_spaces_for_the_connection(self):
        self.app.show_page("connections")
        page = self.app.pages["connections"]
        page.refresh()
        self.root.update()
        card = page.cards["codex"]
        self.assertEqual(card.spaces_label.cget("text"), "General and all project spaces")
        page.toggle_projects("codex")
        self.root.update()
        self.assertFalse(self.connections.control.connection_settings(
            self.connections.grant.connection_id)["all_projects"])
        self.assertEqual(page.cards["codex"].spaces_label.cget("text"), "General only")


if __name__ == "__main__":
    unittest.main()
