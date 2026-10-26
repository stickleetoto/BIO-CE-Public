# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from bio_ce.core.models import MemoryNotFoundError
from bio_ce.connections import MCPConnectionManager
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from tests.tk_support import new_tk_root


class DesktopUIIntegrationTests(unittest.TestCase):
    def test_real_tk_ui_drives_sqlite_add_edit_search_read_and_confirmed_retract(self):
        with tempfile.TemporaryDirectory(prefix="bio-ce-desktop-ui-") as scratch:
            paths = AppDataPaths.under(scratch)
            service = DesktopMemoryService(paths.user_database)
            profile_root = Path(scratch) / "isolated-profiles"
            codex_home = profile_root / "codex"
            claude_home = profile_root / "claude"
            claude_config = claude_home / ".claude"
            for directory in (codex_home, claude_home, claude_config):
                directory.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env.update(
                {
                    "CODEX_HOME": str(codex_home),
                    "USERPROFILE": str(claude_home),
                    "HOME": str(claude_home),
                    "CLAUDE_CONFIG_DIR": str(claude_config),
                }
            )
            connection_manager = MCPConnectionManager(
                paths.user_database,
                paths.root,
                env=env,
            )
            root = new_tk_root()
            app = None
            try:
                app = BIOCEDesktop(root, service, paths, connection_manager)
                root.update()
                self.assertEqual(set(app.pages), {"dashboard", "memories", "connections", "settings"})

                app.start_new_memory()
                app.title_value.set("Desktop integration memory")
                app.source_value.set("user-input")
                app.content_value.insert(
                    "1.0",
                    "Synthetic desktopmarkeralpha content entered through the Tk form.",
                )
                app.save_memory()
                root.update()
                self.assertEqual(service.count(), 1)
                first = app.selected
                self.assertIsNotNone(first)
                self.assertEqual(first.revision_number, 1)
                self.assertEqual(len(service.search("desktopmarkeralpha")), 1)
                self.assertEqual(service.read(first.memory_id).revision_id, first.revision_id)

                app.start_edit_memory()
                app.title_value.set("Desktop integration memory revised")
                app.content_value.delete("1.0", tk.END)
                app.content_value.insert("1.0", "Synthetic desktopmarkeralpharevised revision two.")
                app.save_memory()
                root.update()
                self.assertEqual(service.count(), 1)
                current = app.selected
                self.assertIsNotNone(current)
                self.assertEqual(current.revision_number, 2)
                self.assertEqual(service.read(first.memory_id).revision_id, current.revision_id)

                with patch.object(app, "confirm", return_value=True) as confirm:
                    app.retract_selected()
                confirm.assert_called_once()
                self.assertEqual(service.count(), 0)
                with self.assertRaises(MemoryNotFoundError):
                    service.read(first.memory_id)
                self.assertFalse(paths.demo_database.exists())
            finally:
                if app is not None:
                    app.close()
                else:
                    service.close()
                    root.destroy()


if __name__ == "__main__":
    unittest.main()
