# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from bio_ce import cli
from bio_ce.host_hooks import HookCommand


class HookCommandLineTests(unittest.TestCase):
    def test_tokens_starting_with_a_dash_reach_the_hook_unchanged(self):
        token = "-Ab3_synthetic-token-value"
        command = HookCommand(Path("BIO-CE-MCP.exe"), Path("memories.sqlite3"), "conn_0123456789abcdef", token)
        arguments = command.arguments("codex", "session-start")
        self.assertIn(f"--token={token}", arguments)
        seen = []
        with patch("bio_ce.host_hooks.run_hook", side_effect=lambda request, *_: seen.append(request) or 0):
            self.assertEqual(cli.main(arguments), 0)
        self.assertEqual(seen[0].token, token)
        self.assertEqual(seen[0].connection_id, "conn_0123456789abcdef")
        self.assertIsNone(seen[0].project)

    def test_new_grant_tokens_never_start_with_a_dash(self):
        import tempfile

        from bio_ce.control_store import ControlStore

        with tempfile.TemporaryDirectory(prefix="bio-ce-token-") as scratch, \
                patch("bio_ce.control_store.secrets.token_urlsafe", side_effect=["-dash-first", "plain-second"]):
            with ControlStore(Path(scratch) / "control.sqlite3") as store:
                _grant, token = store.create_grant("codex")
        self.assertEqual(token, "plain-second")


    def test_codex_session_context_names_code_mode_tool_identifiers(self):
        import tempfile

        from bio_ce.control_store import ControlStore, control_database_for
        from bio_ce.host_hooks import HookRequest, build_context
        from bio_ce.storage.sqlite_store import SQLiteMemoryStore

        with tempfile.TemporaryDirectory(prefix="bio-ce-hint-") as scratch:
            database = Path(scratch) / "memories.sqlite3"
            SQLiteMemoryStore(database).close()
            with ControlStore(control_database_for(database)) as control:
                grant, token = control.create_grant("codex")
            codex = build_context(HookRequest("session-start", "codex", database, grant.connection_id, token), {})
            claude = build_context(HookRequest("session-start", "claude", database, grant.connection_id, token), {})
        self.assertIn("tools.mcp__bio_ce__bio_memory_search", codex)
        self.assertIn("ALL_TOOLS", codex)
        self.assertNotIn("ALL_TOOLS", claude)


if __name__ == "__main__":
    unittest.main()
