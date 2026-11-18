# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 A in the app: turning Personal on and off, a host's Personal access with consent, the space picker, and
moving memories between spaces. Real Tk window, synthetic data only."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.spaces import PERSONAL_SPACE
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


class PersonalUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-personal-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.update()
        self.settings = self.app.pages["settings"]
        self.page = self.app.pages["connections"]

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def names(self) -> list[str]:
        return [space.display_name for space in self.app.spaces()]

    def test_personal_is_off_until_turned_on_and_off_keeps_memories_and_shows_general(self):
        self.assertEqual(self.names(), ["General"])
        self.app.show_page("settings")
        with patch.object(self.app, "confirm", return_value=False):
            self.assertFalse(self.settings.turn_on_personal())
        self.assertFalse(self.control.personal_enabled())
        with patch.object(self.app, "confirm", return_value=True):
            self.assertTrue(self.settings.turn_on_personal())
        self.assertEqual(self.names(), ["General", "Personal"])
        self.app.set_space("personal")
        self.app.show_page("memories")
        self.root.update()
        hub = self.app.memories
        self.assertEqual(hub.space_filter, "personal")
        self.assertIn("personal", hub.chips)  # the Personal chip shows only while Personal is on
        self.assertEqual(hub.chips["personal"].text, "Personal")  # the one name on every screen (rc3)
        self.service.add(title="Clinic", content="The user's clinic is on Elm Street.", source_ref="test")
        with patch.object(self.app, "confirm", return_value=True):
            self.assertTrue(self.settings.turn_off_personal())
        self.root.update()
        self.assertEqual(self.names(), ["General"])
        self.assertEqual(self.service.scope, self.control.space("general").curated)  # back on General
        hub.refresh()
        self.assertNotIn("personal", hub.chips)
        self.assertNotIn("Clinic", {item.title for item in hub.items})
        self.service.use_space(PERSONAL_SPACE.curated)
        self.assertEqual([r.title for r in self.service.list()], ["Clinic"])  # the memory stayed

    def test_host_personal_access_needs_the_consent_box_and_the_row_shows_only_while_on(self):
        self.app.show_page("connections")
        self.page.refresh()
        self.root.update()
        card = self.page.cards["codex"]
        self.assertFalse(card.personal_row.winfo_manager())  # Personal is off: no row
        self.control.set_personal_enabled(True)
        self.page.refresh()
        self.root.update()
        self.assertTrue(card.personal_row.winfo_manager())
        self.assertEqual(card.personal_label.cget("text"), "Off")
        connection = self.connections.grant.connection_id
        with patch.object(self.app, "ask_choice", return_value="write"), \
                patch.object(self.app, "confirm", return_value=True):  # confirmed without ticking the box
            self.page.change_personal("codex")
        self.assertEqual(self.control.personal_access(connection), (False, False))

        def tick(**options):
            options["choices"]["consent"] = True
            return True

        with patch.object(self.app, "ask_choice", return_value="write"), patch.object(self.app, "confirm", tick):
            self.page.change_personal("codex")
        self.assertEqual(self.control.personal_access(connection), (True, True))
        self.root.update()
        self.assertEqual(card.personal_label.cget("text"), "Read and save")
        with patch.object(self.app, "ask_choice", return_value="read"), \
                patch.object(self.app, "confirm", side_effect=AssertionError("no second consent")):
            self.page.change_personal("codex")  # narrowing needs no new consent
        self.assertEqual(self.control.personal_access(connection), (True, False))
        with patch.object(self.app, "ask_choice", return_value="off"):
            self.page.change_personal("codex")
        self.assertEqual(self.control.personal_access(connection), (False, False))

    def test_move_selected_memories_to_personal_with_a_backup(self):
        first = self.service.add(title="Allergy", content="The user is allergic to peanuts.", source_ref="test")
        second = self.service.add(title="Blood type", content="The user's blood type is O.", source_ref="test")
        keep = self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        self.app.show_page("memories")
        hub = self.app.memories
        hub.refresh()
        self.root.update()
        chosen = [item for item in hub.items if item.item_id in (first.memory_id, second.memory_id)]
        self.assertEqual(hub.move_targets(chosen), [])  # Personal is off: there is nowhere to move
        self.assertEqual(hub.drop_targets(chosen), set())
        self.control.set_personal_enabled(True)
        hub.refresh()
        chosen = [item for item in hub.items if item.item_id in (first.memory_id, second.memory_id)]
        self.assertEqual([space.space_id for space in hub.move_targets(chosen)], ["personal"])
        self.assertEqual(hub.do.move(chosen, PERSONAL_SPACE), 2)
        self.assertEqual([r.memory_id for r in self.service.list()], [keep.memory_id])
        backups = list((self.paths.user_database.parent / "backups").glob("auto-before-move-*.sqlite3"))
        self.assertEqual(len([b for b in backups if not b.name.endswith(".control.sqlite3")]), 1)
        self.service.use_space(PERSONAL_SPACE.curated)
        self.assertEqual({r.memory_id for r in self.service.list()}, {first.memory_id, second.memory_id})


if __name__ == "__main__":
    unittest.main()
