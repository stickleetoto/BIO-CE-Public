# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Codex's code-mode option: written exactly once, checked, and restored when Codex rejects it."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

from bio_ce import codex_options
from bio_ce.codex_options import CodeModeOptionError, add_option, option_state, parse_codex_version
from bio_ce.connections import MCPConnectionConsentRequired, MCPConnectionManager
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.storage.sqlite_store import SQLiteMemoryStore

ENTRY = """model = "example"

[mcp_servers.other]
command = "other.exe"

[mcp_servers.bio-ce]
command = 'C:\\\\Program Files\\\\BIO CE\\\\MCP\\\\BIO-CE-MCP.exe'
args = ["mcp-stdio"]

[mcp_servers.bio-ce.env]
BIO_CE_CONNECTION_TOKEN = "x"

[features]
hooks = true
"""


class OptionTextTests(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(parse_codex_version("codex-cli 0.166.0"), (0, 166, 0))
        self.assertEqual(parse_codex_version("codex-cli 0.167.0-alpha.3.2"), (0, 167, 0))
        self.assertIsNone(parse_codex_version("not codex"))
        self.assertTrue(codex_options.version_supported((0, 166, 0)))
        self.assertTrue(codex_options.version_supported((1, 0, 0)))
        self.assertFalse(codex_options.version_supported((0, 165, 9)))
        self.assertFalse(codex_options.version_supported(None))

    def test_the_option_goes_directly_under_the_bio_ce_header_and_nothing_else_changes(self):
        updated = add_option(ENTRY)
        config = tomllib.loads(updated)
        self.assertEqual(config["mcp_servers"]["bio-ce"]["omit_tools_from"], ["code_mode"])
        self.assertNotIn("omit_tools_from", config["mcp_servers"]["other"])
        self.assertEqual(config["features"], {"hooks": True})
        self.assertIn("[mcp_servers.bio-ce]\n" + codex_options.MARKER + "\n" + codex_options.OPTION_LINE + "\n",
                      updated)
        self.assertEqual(option_state(updated), codex_options.APPLIED)
        self.assertEqual(updated.replace(codex_options.MARKER + "\n" + codex_options.OPTION_LINE + "\n", ""), ENTRY)

    def test_header_variants(self):
        for header in ('[mcp_servers."bio-ce"]', "[ mcp_servers . bio-ce ]", "[mcp_servers.bio-ce]  # BIO CE"):
            with self.subTest(header=header):
                raw = ENTRY.replace("[mcp_servers.bio-ce]\n", header + "\n")
                self.assertEqual(option_state(add_option(raw)), codex_options.APPLIED)
        crlf = ENTRY.replace("\n", "\r\n")
        updated = add_option(crlf)
        self.assertIn(codex_options.OPTION_LINE + "\r\n", updated)
        self.assertNotIn("\r\r", updated)
        at_end = 'x = 1\n[mcp_servers.bio-ce]'  # an empty table at the very end, no final newline
        self.assertEqual(tomllib.loads(add_option(at_end))["mcp_servers"]["bio-ce"]["omit_tools_from"], ["code_mode"])

    def test_states_that_are_left_alone(self):
        self.assertEqual(option_state('[mcp_servers.other]\ncommand = "x"\n'), codex_options.NOT_REGISTERED)
        user = ENTRY.replace("[mcp_servers.bio-ce]\n", '[mcp_servers.bio-ce]\nomit_tools_from = ["deferred"]\n')
        self.assertEqual(option_state(user), codex_options.USER_SET)
        both = ENTRY.replace("[mcp_servers.bio-ce]\n", '[mcp_servers.bio-ce]\nomit_tools_from = ["direct", "code_mode"]\n')
        self.assertEqual(option_state(both), codex_options.APPLIED)
        for raw in (user, both):
            with self.assertRaises(CodeModeOptionError):
                add_option(raw)
        inline = 'mcp_servers = { bio-ce = { command = "x" } }\n'
        with self.assertRaises(CodeModeOptionError):
            add_option(inline)

    def test_orphan_marker_is_removed_only_when_the_entry_is_gone(self):
        updated = add_option(ENTRY)
        self.assertEqual(codex_options.remove_orphan_marker(updated), updated)
        without_entry = (updated.replace("[mcp_servers.bio-ce]\n", "").replace("[mcp_servers.bio-ce.env]\n", "")
                         .replace("command = 'C:\\\\Program Files\\\\BIO CE\\\\MCP\\\\BIO-CE-MCP.exe'\n", "")
                         .replace('args = ["mcp-stdio"]\n', "").replace('BIO_CE_CONNECTION_TOKEN = "x"\n', ""))
        cleaned = codex_options.remove_orphan_marker(without_entry)
        self.assertNotIn(codex_options.MARKER, cleaned)
        self.assertNotIn("omit_tools_from", cleaned)


class FakeCodexManager(MCPConnectionManager):
    """A manager whose Codex CLI is simulated: --version, and mcp get validating like Codex 0.166."""

    version_text = "codex-cli 0.166.0"
    reject_option = False
    on_backup = None

    def _find_cli(self, host: str) -> Path | None:
        return Path("codex.exe")

    def _run_cli(self, host, args):
        args = tuple(args)
        if args == ("--version",):
            return subprocess.CompletedProcess(args, 0, self.version_text + "\n", "")
        if args[:2] == ("mcp", "get"):
            try:
                config = tomllib.loads(self._config_path("codex").read_text(encoding="utf-8"))
                values = config["mcp_servers"]["bio-ce"].get("omit_tools_from", [])
                valid = all(value in ("direct", "deferred", "code_mode") for value in values)
            except (OSError, ValueError, KeyError):
                valid = False
            return subprocess.CompletedProcess(args, 0 if valid and not self.reject_option else 1, "", "")
        raise AssertionError(f"unexpected CLI call {args}")

    def _backup_config(self, host, config_path):
        backup = super()._backup_config(host, config_path)
        if self.on_backup is not None:
            hook, self.on_backup = self.on_backup, None
            hook(config_path)
        return backup


class ManagerCodeModeTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="bio-ce-code-mode-")
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        database = root / "personal.sqlite3"
        store = SQLiteMemoryStore(database)
        store.add(MemoryScope("bio-ce-personal", "default"), title="Synthetic", content="synthetic code mode test",
                  source=SourceProvenance("fixture", "fixture:code-mode"))
        store.close()
        codex_home = root / "codex"
        codex_home.mkdir()
        env = dict(os.environ, CODEX_HOME=str(codex_home), USERPROFILE=str(root), HOME=str(root))
        self.manager = FakeCodexManager(database, root / "appdata", env=env)
        self.addCleanup(self.manager.close)
        grant, token = self.manager.control.create_grant("codex", project="bio-ce-personal", namespace="default")
        command, args = self.manager._mcp_server_command(grant.connection_id)
        self.config = codex_home / "config.toml"
        self.original = (
            'model = "example"\r\n\r\n'
            f"[mcp_servers.bio-ce]\r\ncommand = {json.dumps(command)}\r\nargs = {json.dumps(list(args))}\r\n\r\n"
            f'[mcp_servers.bio-ce.env]\r\nBIO_CE_CONNECTION_TOKEN = "{token}"\r\n'
        ).encode("utf-8")
        self.config.write_bytes(self.original)

    def test_consent_is_required(self):
        with self.assertRaises(MCPConnectionConsentRequired):
            self.manager.apply_codex_code_mode()
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_applied_with_a_backup_and_shown_in_status(self):
        self.assertEqual(self.manager.status("codex").code_mode, codex_options.MISSING)
        result = self.manager.apply_codex_code_mode(approved=True)
        self.assertEqual(result.state, "applied")
        self.assertEqual(result.codex_version, "codex-cli 0.166.0")
        self.assertEqual(result.backup_file.read_bytes(), self.original)
        self.assertEqual(self.manager.status("codex").code_mode, codex_options.APPLIED)
        self.assertTrue(self.manager.status("codex").connected, "the connection still authenticates")
        again = self.manager.apply_codex_code_mode(approved=True)
        self.assertEqual(again.state, "already_applied")

    def test_older_or_unknown_codex_is_left_unchanged(self):
        for text in ("codex-cli 0.165.2", "something else"):
            with self.subTest(text=text):
                self.manager.version_text = text
                result = self.manager.apply_codex_code_mode(approved=True)
                self.assertEqual(result.state, "unsupported")
                self.assertIn("0.166.0 or later", result.detail)
                self.assertEqual(self.config.read_bytes(), self.original)

    def test_a_value_the_user_set_is_left_alone(self):
        user = self.original.replace(b"[mcp_servers.bio-ce]\r\n", b'[mcp_servers.bio-ce]\r\nomit_tools_from = ["deferred"]\r\n')
        self.config.write_bytes(user)
        self.assertEqual(self.manager.apply_codex_code_mode(approved=True).state, "user_set")
        self.assertEqual(self.config.read_bytes(), user)

    def test_rejected_by_codex_restores_the_previous_file(self):
        self.manager.reject_option = True
        with self.assertRaises(Exception) as caught:
            self.manager.apply_codex_code_mode(approved=True)
        # mcp get keeps failing in this simulation, so even the restore cannot be confirmed: BIO CE says so.
        self.assertIn("could not confirm", str(caught.exception))
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_rejected_option_restored_when_codex_reads_the_old_file(self):
        calls = {"get": 0}
        run = self.manager._run_cli

        def flaky(host, args):
            if tuple(args)[:2] == ("mcp", "get"):
                calls["get"] += 1
                if calls["get"] == 1:  # the check after writing fails, the check after restoring passes
                    return subprocess.CompletedProcess(args, 1, "", "")
            return run(host, args)

        self.manager._run_cli = flaky
        result = self.manager.apply_codex_code_mode(approved=True)
        self.assertEqual(result.state, "restored")
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(result.backup_file.read_bytes(), self.original)

    def test_a_concurrent_rewrite_is_retried_once(self):
        def rewrite(path: Path) -> None:
            path.write_bytes(path.read_bytes() + b"\r\n# written by another app\r\n")

        self.manager.on_backup = rewrite
        result = self.manager.apply_codex_code_mode(approved=True)
        self.assertEqual(result.state, "applied")
        text = self.config.read_text(encoding="utf-8")
        self.assertIn("# written by another app", text, "the other app's change is kept")
        self.assertEqual(option_state(text), codex_options.APPLIED)


if __name__ == "__main__":
    unittest.main()
