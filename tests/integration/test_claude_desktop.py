# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 E: connecting the Claude desktop app by editing its settings file, and the rule that the server never
creates the BIO CE data folder. Synthetic settings files and data in a scratch folder only."""

from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from bio_ce import claude_desktop, host_check, memory_skill
from bio_ce.connections import DESKTOP, MCPConnectionConflict, MCPConnectionError, MCPConnectionManager
from bio_ce.control_store import MODE_AUTO_MEMORY, ControlStore, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.host_hooks import HookRequest, build_context
from bio_ce.mcp_server import EXIT_NO_DATA, TOKEN_ENVIRONMENT_VARIABLE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore

APP_SETTINGS = {"preferences": {"menuBarEnabled": False, "coworkScheduledTasksEnabled": True},
                "coworkFolder": "C:\\Users\\someone\\Cowork",
                "mcpServers": {"other": {"command": "other.exe", "args": ["--x"]}}}


class ClaudeDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-claude-desktop-")
        self.root = Path(self.temp.name)
        self.local = self.root / "Local"
        self.roaming = self.root / "Roaming"
        self.local.mkdir()
        self.roaming.mkdir()
        self.database = self.local / "BIO-CE" / "data" / "memories.sqlite3"
        store = SQLiteMemoryStore(self.database)
        store.add(MemoryScope("bio-ce-personal", "default"), title="Units", content="Prefers metric units.",
                  source=SourceProvenance("user-entered", "test"))
        store.close()
        self.env = {"LOCALAPPDATA": str(self.local), "APPDATA": str(self.roaming), "USERPROFILE": str(self.root),
                    "PATH": ""}
        self.verified: list[tuple] = []
        self.fail_verify = False

        def verifier(database, scope, command, args, env):
            if self.fail_verify:
                raise RuntimeError("probe failed")
            self.verified.append((command, tuple(args), dict(env)))

        self.manager = MCPConnectionManager(self.database, self.local / "BIO-CE", env=self.env, sdk_verifier=verifier)

    def tearDown(self) -> None:
        self.manager.close()
        self.temp.cleanup()

    def store_app(self, settings: dict | None = APP_SETTINGS, *, raw: bytes | None = None) -> Path:
        folder = self.local / "Claude-Data" / "claude_pzs8sxrjxfjjc"
        folder.mkdir(parents=True)
        (self.local / "Packages" / "Claude_pzs8sxrjxfjjc").mkdir(parents=True)
        path = folder / claude_desktop.CONFIG_NAME
        if raw is not None:
            path.write_bytes(raw)
        elif settings is not None:
            path.write_bytes(json.dumps(settings, indent=2).encode("utf-8"))
        return path

    def test_finds_the_store_and_installer_versions(self):
        self.assertEqual(claude_desktop.locate(self.env), (False, None, None))
        (self.local / "Packages" / "Claude_pzs8sxrjxfjjc").mkdir(parents=True)
        installed, path, kind = claude_desktop.locate(self.env)
        self.assertEqual((installed, kind), (True, "msix"))
        self.assertEqual(path, self.local / "Claude-Data" / "claude_pzs8sxrjxfjjc" / "claude_desktop_config.json")
        classic = {"LOCALAPPDATA": str(self.root / "L2"), "APPDATA": str(self.roaming)}
        (self.roaming / "Claude").mkdir()
        self.assertEqual(claude_desktop.locate(classic), (True, self.roaming / "Claude" / "claude_desktop_config.json",
                                                          "classic"))

    def test_connect_adds_only_bio_ces_entry_after_a_backup_and_disconnect_removes_only_it(self):
        path = self.store_app()
        original = path.read_bytes()
        result = self.manager.connect(DESKTOP, approved=True)
        self.assertTrue(result.connected)
        self.assertEqual(result.backup_file.read_bytes(), original)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({k: v for k, v in data.items() if k != "mcpServers"},
                         {k: v for k, v in APP_SETTINGS.items() if k != "mcpServers"})
        self.assertEqual(data["mcpServers"]["other"], APP_SETTINGS["mcpServers"]["other"])
        entry = data["mcpServers"]["bio-ce"]
        self.assertIn("mcp-stdio", entry["args"])
        self.assertIn(TOKEN_ENVIRONMENT_VARIABLE, entry["env"])
        self.assertFalse(path.read_bytes().endswith(b"\n"))  # the app's own style: two spaces, no final newline
        self.assertEqual(len(self.verified), 1)
        status = self.manager.status(DESKTOP)
        self.assertTrue(status.connected)
        self.assertEqual(status.mode, "read_only")
        self.manager.set_mode(DESKTOP, MODE_AUTO_MEMORY)
        self.assertEqual(self.manager.status(DESKTOP).mode, MODE_AUTO_MEMORY)
        again = self.manager.connect(DESKTOP, approved=True)
        self.assertTrue(again.already_configured)
        removed = self.manager.disconnect(DESKTOP, approved=True)
        self.assertFalse(removed.connected)
        after = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(after, APP_SETTINGS)
        self.assertFalse(self.manager.status(DESKTOP).connected)
        self.assertEqual([grant for grant in self.manager.control.grants() if grant.host == DESKTOP], [])

    def test_unreadable_settings_are_never_changed(self):
        path = self.store_app(raw=b'{"preferences": {broken')
        with self.assertRaises(MCPConnectionError):
            self.manager.connect(DESKTOP, approved=True)
        self.assertEqual(path.read_bytes(), b'{"preferences": {broken')
        self.assertEqual(self.manager.control.grants(), ())
        self.assertTrue(self.manager.status(DESKTOP).configuration_conflict)

    def test_a_failed_check_revokes_the_grant_and_puts_the_file_back(self):
        path = self.store_app()
        original = path.read_bytes()
        self.fail_verify = True
        with self.assertRaises(MCPConnectionError):
            self.manager.connect(DESKTOP, approved=True)
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(all(not grant.active for grant in self.manager.control.grants(include_revoked=True)))

    def test_an_app_that_was_never_opened_is_not_touched(self):
        (self.local / "Packages" / "Claude_pzs8sxrjxfjjc").mkdir(parents=True)
        with self.assertRaisesRegex(MCPConnectionError, "Open the Claude desktop app once"):
            self.manager.connect(DESKTOP, approved=True)
        self.assertFalse((self.local / "Claude-Data").exists())

    def test_a_foreign_bio_ce_entry_is_left_alone(self):
        foreign = {**APP_SETTINGS, "mcpServers": {"bio-ce": {"command": "someone-else.exe", "args": []}}}
        path = self.store_app(foreign)
        before = path.read_bytes()
        with self.assertRaises(MCPConnectionConflict):
            self.manager.connect(DESKTOP, approved=True)
        with self.assertRaises(MCPConnectionConflict):
            self.manager.disconnect(DESKTOP, approved=True)
        self.assertEqual(path.read_bytes(), before)

    def test_uninstall_check_counts_the_desktop_entry(self):
        path = self.store_app()
        app_dir = self.root / "Program"
        executable = host_check.server_executable(app_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["mcpServers"]["bio-ce"] = {"command": str(executable), "args": ["mcp-stdio"]}
        path.write_text(json.dumps(data), encoding="utf-8")
        mask = host_check.references(app_dir, self.env)
        self.assertEqual(mask, host_check.CLAUDE_DESKTOP_MCP)
        self.assertEqual(host_check.main(str(app_dir), self.env), 116)
        self.assertEqual(host_check.describe(mask), ["Claude desktop app MCP server"])

    def test_skill_zip_has_the_fixed_skill_text_only(self):
        archive = zipfile.ZipFile(io.BytesIO(memory_skill.skill_zip(version="0.4.3-rc1")))
        self.assertEqual(archive.namelist(), ["bio-ce-memory/SKILL.md"])
        text = archive.read("bio-ce-memory/SKILL.md").decode("utf-8")
        self.assertEqual(text, memory_skill.render("0.4.3-rc1"))
        self.assertIn("## Personal", text)


class NoNewDataFolderTests(unittest.TestCase):
    """The server and hooks never create the BIO CE data folder or database (owner rule, 2026-11-14)."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-no-root-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def start(self, database: Path) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "bio_ce", "mcp-stdio", "--db", str(database), "--project",
                               "bio-ce-personal", "--namespace", "default"], input="", capture_output=True,
                              text=True, timeout=60)

    def test_a_missing_data_folder_fails_with_open_the_app_first_and_nothing_is_created(self):
        database = self.root / "BIO-CE" / "data" / "memories.sqlite3"
        done = self.start(database)
        self.assertEqual(done.returncode, EXIT_NO_DATA)
        self.assertIn("Open the BIO CE app first", done.stderr)
        self.assertIn("BIO CE 앱을 먼저 실행하세요", done.stderr)
        self.assertFalse((self.root / "BIO-CE").exists())

    def test_a_folder_without_a_database_gets_no_new_database(self):
        folder = self.root / "BIO-CE" / "data"
        folder.mkdir(parents=True)
        done = self.start(folder / "memories.sqlite3")
        self.assertEqual(done.returncode, EXIT_NO_DATA)
        self.assertEqual(list(folder.iterdir()), [])

    def test_with_data_the_server_starts(self):
        database = self.root / "BIO-CE" / "data" / "memories.sqlite3"
        SQLiteMemoryStore(database).close()
        done = self.start(database)
        self.assertEqual(done.returncode, 0, done.stderr)  # positive control: empty stdin ends a running server

    def test_hooks_never_create_the_folder(self):
        database = self.root / "BIO-CE" / "data" / "memories.sqlite3"
        context = build_context(HookRequest("session-start", "claude", database, "conn_x", "token"), {"cwd": "C:\\"})
        self.assertEqual(context, "")
        self.assertFalse((self.root / "BIO-CE").exists())
        self.assertFalse(control_database_for(database).exists())
        self.assertIsNotNone(ControlStore)


if __name__ == "__main__":
    unittest.main()
