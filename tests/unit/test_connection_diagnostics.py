# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from bio_ce.connections import MCPConnectionManager
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


class ConnectionDiagnosticsTests(unittest.TestCase):
    """``diagnose`` explains host state without changing any configuration."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-diagnose-")
        self.root = Path(self.temp.name).resolve()
        self.database = self.root / "personal.sqlite3"
        SQLiteMemoryStore(self.database).close()
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.verified: list[Path] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _manager(self, *, with_cli: bool) -> MCPConnectionManager:
        if with_cli:
            (self.bin / "codex.exe").write_bytes(b"")
        env = {
            "PATH": str(self.bin),
            "PATHEXT": os.environ.get("PATHEXT", ".EXE"),
            "CODEX_HOME": str(self.codex_home),
            "USERPROFILE": str(self.root / "profile"),
        }
        return MCPConnectionManager(
            self.database,
            self.root / "appdata",
            env=env,
            sdk_verifier=lambda database, *_args: self.verified.append(database),
        )

    def _outcomes(self, checks) -> dict[str, str]:
        return {check.name: check.outcome for check in checks}

    def test_missing_host_command_is_reported_with_next_step(self):
        checks = self._manager(with_cli=False).diagnose("codex")
        outcomes = self._outcomes(checks)
        self.assertEqual(outcomes["Host command"], "fail")
        self.assertIn("codex --version", checks[0].detail)
        self.assertEqual(outcomes["Memory database"], "pass")
        self.assertEqual(outcomes["Server check"], "pass")
        self.assertFalse((self.codex_home / "config.toml").exists())

    def test_foreign_bio_ce_entry_is_flagged_and_left_untouched(self):
        config = self.codex_home / "config.toml"
        original = '[mcp_servers.bio-ce]\ncommand = "somebody-else.exe"\nargs = []\n'
        config.write_text(original, encoding="utf-8")
        manager = self._manager(with_cli=True)
        outcomes = self._outcomes(manager.diagnose("codex", run_server_check=False))
        self.assertEqual(outcomes["Host command"], "pass")
        self.assertEqual(outcomes["BIO CE entry"], "fail")
        self.assertEqual(outcomes["Server check"], "skip")
        self.assertEqual(config.read_text(encoding="utf-8"), original)
        self.assertEqual(self.verified, [])
        self.assertFalse((self.root / "appdata" / "connections").exists())

    def test_unreadable_host_settings_and_invalid_database_fail_closed(self):
        (self.codex_home / "config.toml").write_text("not = [valid", encoding="utf-8")
        self.database.write_bytes(b"not a database")
        outcomes = self._outcomes(self._manager(with_cli=True).diagnose("codex"))
        self.assertEqual(outcomes["Host settings"], "fail")
        self.assertEqual(outcomes["Memory database"], "fail")
        self.assertEqual(outcomes["Server check"], "skip")
        self.assertEqual(self.verified, [])


if __name__ == "__main__":
    unittest.main()
