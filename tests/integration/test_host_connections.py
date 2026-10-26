# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest

from bio_ce import host_hooks
from bio_ce.connections import (
    MCPConnectionError,
    MCPConnectionManager,
    MCPConnectionConsentRequired,
)
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


class HostConnectionIntegrationTests(unittest.TestCase):
    def _make_manager(self, host: str, root: Path, *, sdk_verifier=None) -> MCPConnectionManager:
        database = root / "personal.sqlite3"
        store = SQLiteMemoryStore(database)
        try:
            store.add(
                MemoryScope("bio-ce-personal", "default"),
                title="Synthetic host verification memory",
                content="synthetichostconnectionmarker is a test-only value.",
                source=SourceProvenance("fixture", "fixture:host-connection"),
            )
        finally:
            store.close()

        env = dict(os.environ)
        codex_home = root / "codex-profile"
        claude_home = root / "claude-profile"
        claude_config = claude_home / ".claude"
        for directory in (codex_home, claude_home, claude_config):
            directory.mkdir(parents=True, exist_ok=True)
        env.update(
            {
                "CODEX_HOME": str(codex_home),
                "USERPROFILE": str(claude_home),
                "HOME": str(claude_home),
                "CLAUDE_CONFIG_DIR": str(claude_config),
            }
        )
        return MCPConnectionManager(
            database,
            root / "appdata",
            env=env,
            sdk_verifier=sdk_verifier,
        )

    def _add_other_server(self, manager: MCPConnectionManager, host: str) -> None:
        args = ("mcp", "add", "bio-ce-test-other", "--", "cmd.exe", "/c", "exit", "0")
        if host == "claude":
            args = (
                "mcp",
                "add",
                "--transport",
                "stdio",
                "--scope",
                "user",
                "bio-ce-test-other",
                "--",
                "cmd.exe",
                "/c",
                "exit",
                "0",
            )
        completed = manager._run_cli(host, args)
        self.assertEqual(completed.returncode, 0)

    def _configured_names(self, manager: MCPConnectionManager, host: str) -> set[str]:
        path = manager._config_path(host)
        raw = path.read_text(encoding="utf-8")
        if host == "codex":
            values = tomllib.loads(raw).get("mcp_servers", {})
        else:
            values = json.loads(raw).get("mcpServers", {})
        return set(values)

    def _exercise_host(self, host: str, *, fail_sdk_verification: bool = False) -> None:
        if shutil.which(host) is None:
            self.skipTest(f"{host} CLI is not installed")
        with tempfile.TemporaryDirectory(prefix=f"bio-ce-{host}-profile-") as scratch:
            root = Path(scratch).resolve()
            manager = self._make_manager(
                host,
                root,
                sdk_verifier=(lambda *_args: (_ for _ in ()).throw(RuntimeError("test rejection")))
                if fail_sdk_verification
                else None,
            )
            try:
                self._run_host_flow(manager, host, fail_sdk_verification)
            finally:
                manager.close()

    def _run_host_flow(self, manager: MCPConnectionManager, host: str, fail_sdk_verification: bool) -> None:
        with self.assertRaises(MCPConnectionConsentRequired):
            manager.connect(host)

        self._add_other_server(manager, host)
        if fail_sdk_verification:
            with self.assertRaises(MCPConnectionError):
                manager.connect(host, approved=True)
            self.assertNotIn("bio-ce", self._configured_names(manager, host))
            self.assertIn("bio-ce-test-other", self._configured_names(manager, host))
            self.assertEqual(manager.control.grants(), ())
            return

        result = manager.connect(host, approved=True)
        self.assertTrue(result.connected)
        self.assertFalse(result.already_configured)
        self.assertIsNotNone(result.backup_file)
        self.assertTrue(result.backup_file.is_file())
        self.assertIn("bio-ce", self._configured_names(manager, host))
        self.assertIn("bio-ce-test-other", self._configured_names(manager, host))
        status = manager.status(host)
        self.assertTrue(status.connected)
        self.assertEqual(status.mode, "read_only", "Auto memory must be off by default")
        self.assertFalse(status.legacy)

        approvals = host_hooks.tool_approval_path(host, manager.env)
        self.assertFalse(host_hooks.tool_approval_enabled(host, approvals), "nothing is pre-approved by default")
        manager.set_mode(host, "auto_memory")
        self.assertEqual(manager.status(host).mode, "auto_memory")
        self.assertTrue(host_hooks.tool_approval_enabled(host, approvals))
        self.assertIn("bio-ce-test-other", self._configured_names(manager, host), "other entries survive")
        manager.set_mode(host, "read_only")
        self.assertFalse(host_hooks.tool_approval_enabled(host, approvals))
        manager.set_mode(host, "auto_memory")
        manager.install_hooks(host, approved=True)
        self.assertTrue(manager.status(host).hooks_installed)
        connection_id = status.connection_id

        removed = manager.disconnect(host, approved=True)
        self.assertFalse(removed.connected)
        self.assertIsNotNone(removed.backup_file)
        self.assertNotIn("bio-ce", self._configured_names(manager, host))
        self.assertIn("bio-ce-test-other", self._configured_names(manager, host))
        self.assertFalse(manager.status(host).connected)
        self.assertFalse(manager.control.grant(connection_id).active)
        self.assertFalse(manager.status(host).hooks_installed)
        self.assertFalse(host_hooks.tool_approval_enabled(host, approvals))

    def test_codex_user_scope_registration_sdk_verification_and_removal(self):
        self._exercise_host("codex")

    def test_claude_user_scope_registration_sdk_verification_and_removal(self):
        self._exercise_host("claude")

    def test_registration_failure_rolls_back_only_bio_ce_entry(self):
        for host in ("codex", "claude"):
            if shutil.which(host) is not None:
                with self.subTest(host=host):
                    self._exercise_host(host, fail_sdk_verification=True)


if __name__ == "__main__":
    unittest.main()
