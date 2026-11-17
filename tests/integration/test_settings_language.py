# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4: the app language in Settings (Auto, 한국어, English). A new choice applies on the next start (owner
decision 2026-11-17, instead of redrawing every page at once); Restart now closes BIO CE the usual way and starts it
again, and the new process waits for the closing one to let go of the single-instance lock."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from bio_ce import cli
from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService, claim_single_instance
from bio_ce.ui import app as app_module
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.tk_support import new_tk_root


class SettingsLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-language-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.root = new_tk_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.after_cancel(self.app._maintenance_after)
        self.app.show_page("settings")
        self.page = self.app.pages["settings"]
        self.closed = False
        self.settle()

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        if not self.closed:
            self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def settle(self) -> None:
        for _ in range(4):
            self.root.update()

    def test_the_choice_is_saved_and_the_restart_note_shows_only_for_another_language(self):
        self.assertEqual(set(self.page.language_buttons), {"auto", "ko", "en"})
        self.assertEqual(self.page.language_choice.get(), "auto")
        self.assertFalse(self.page.restart_row.winfo_manager())  # the tests show English, and auto resolves to it
        self.page.language_choice.set("ko")
        self.page.choose_language()
        self.settle()
        self.assertEqual(self.control.ui_language(), "ko")
        self.assertTrue(self.page.restart_row.winfo_ismapped())
        self.assertEqual(self.page.restart_note.cget("text"), "The new language applies when BIO CE restarts.")
        self.assertEqual(self.page.restart_button.text, "Restart now")
        self.page.language_choice.set("en")
        self.page.choose_language()
        self.settle()
        self.assertEqual(self.control.ui_language(), "en")
        self.assertFalse(self.page.restart_row.winfo_manager())  # English is what the app shows already

    def test_restart_closes_the_app_and_starts_it_again(self):
        with patch.object(app_module.subprocess, "Popen") as started:
            self.assertTrue(self.app.restart())
        self.closed = True
        started.assert_called_once()
        self.assertEqual(started.call_args.args[0], app_module.restart_command())
        with self.assertRaises(Exception):
            self.root.winfo_exists()  # the window is gone

    def test_nothing_restarts_while_the_app_can_not_close(self):
        with patch.object(type(self.app.tasks), "busy", new=True), \
                patch.object(app_module.subprocess, "Popen") as started:
            self.assertFalse(self.app.restart())
        started.assert_not_called()
        self.assertTrue(self.root.winfo_exists())


class RestartCommandTests(unittest.TestCase):
    def test_the_command_starts_the_same_program_with_restarted(self):
        with patch.object(sys, "frozen", True, create=True):
            self.assertEqual(app_module.restart_command(), [sys.executable, "--restarted"])
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(app_module.restart_command(), [sys.executable, "-m", "bio_ce", "desktop", "--restarted"])

    def test_the_cli_passes_restarted_on(self):
        with patch("bio_ce.desktop.run_desktop", return_value=0) as run:
            cli.main(["desktop", "--restarted"])
            cli.main(["desktop"])
        self.assertEqual([call.args[0] for call in run.call_args_list], [["--restarted"], []])

    @unittest.skipUnless(os.name == "nt", "a Windows named mutex")
    def test_a_restarted_app_waits_for_the_closing_one(self):
        name = f"BIO-CE-test-{uuid.uuid4().hex}"
        first = claim_single_instance(name)
        self.assertTrue(first)
        self.assertIsNone(claim_single_instance(name))  # positive control: a plain second start is refused
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        threading.Timer(0.6, kernel32.CloseHandle, args=(first,)).start()
        started = time.monotonic()
        second = claim_single_instance(name, wait_seconds=10)
        try:
            self.assertTrue(second)
            self.assertLess(time.monotonic() - started, 5)
        finally:
            kernel32.CloseHandle(second)


if __name__ == "__main__":
    unittest.main()
