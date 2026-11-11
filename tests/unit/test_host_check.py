# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The uninstaller's read-only check: which hosts still start this installation's MCP server."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bio_ce import host_check
from bio_ce.host_check import CLAUDE_HOOKS, CLAUDE_MCP, CODEX_HOOKS, CODEX_MCP


class HostCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="bio-ce-host-check-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.app = self.root / "Programs" / "BIO CE 테스트 #1"  # Korean letters, spaces, and # in the path
        self.exe = self.app / "MCP" / "BIO-CE-MCP.exe"
        self.codex, self.claude = self.root / "codex", self.root / "claude"
        self.codex.mkdir()
        self.claude.mkdir()
        self.env = {"CODEX_HOME": str(self.codex), "CLAUDE_CONFIG_DIR": str(self.claude),
                    "USERPROFILE": str(self.root)}

    def _codex_entry(self, command: str) -> None:
        literal = command.replace("'", "")
        (self.codex / "config.toml").write_text(
            f"[mcp_servers.other]\ncommand = 'x.exe'\n\n[mcp_servers.bio-ce]\ncommand = '{literal}'\nargs = []\n",
            encoding="utf-8")

    def test_nothing_configured(self):
        self.assertEqual(host_check.references(self.app, self.env), 0)
        self.assertEqual(host_check.main(str(self.app), self.env), 0)

    def test_each_host_and_kind(self):
        self._codex_entry(str(self.exe))
        (self.codex / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": f'"{self.exe}" hook session-start --host codex'}]}]}}), encoding="utf-8")
        (self.claude / ".claude.json").write_text(json.dumps({"mcpServers": {"bio-ce": {
            "type": "stdio", "command": str(self.exe).upper(), "args": []}}}), encoding="utf-8")  # case-insensitive
        (self.claude / "settings.json").write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": str(self.exe), "args": ["hook", "user-prompt"]}]}]}}), encoding="utf-8")
        mask = host_check.references(self.app, self.env)
        self.assertEqual(mask, CODEX_MCP | CODEX_HOOKS | CLAUDE_MCP | CLAUDE_HOOKS)
        self.assertEqual(host_check.main(str(self.app), self.env), 115)
        self.assertEqual(len(host_check.describe(mask)), 4)

    def test_another_installation_or_other_servers_do_not_count(self):
        other = self.root / "Programs" / "BIO CE" / "MCP" / "BIO-CE-MCP.exe"
        self._codex_entry(str(other))
        (self.claude / ".claude.json").write_text(json.dumps({"mcpServers": {"something": {
            "command": str(self.exe)}}}), encoding="utf-8")
        (self.claude / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": f"{other} hook session-start"}]}]}}), encoding="utf-8")
        self.assertEqual(host_check.references(self.app, self.env), 0)

    def test_unreadable_files_never_raise(self):
        (self.codex / "config.toml").write_text("this is [not toml", encoding="utf-8")
        (self.claude / ".claude.json").write_text("{not json", encoding="utf-8")
        (self.codex / "hooks.json").write_bytes(b"\xff\xfe\x00")
        self.assertEqual(host_check.references(self.app, self.env), 0)

    def test_command_line_interface(self):
        self._codex_entry(str(self.exe))
        completed = subprocess.run([sys.executable, "-m", "bio_ce", "host-check", "--app-dir", str(self.app)],
                                   env={**os.environ, **self.env}, capture_output=True, timeout=60)
        self.assertEqual(completed.returncode, 100 + CODEX_MCP)


if __name__ == "__main__":
    unittest.main()
