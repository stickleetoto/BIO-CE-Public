# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The BIO CE memory skill: its text agrees with the server policy, and installs never clobber user edits."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from bio_ce import display_version, memory_skill
from bio_ce.connections import MCPConnectionConsentRequired, MCPConnectionError, MCPConnectionManager
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.mcp_server import TOOL_NAMES
from bio_ce.memory_policy import CATEGORIES, CHANGE_TYPES, EVIDENCE, TRUSTED_EVIDENCE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore

# The v1 text as shipped. Changing SKILL_TEMPLATE needs SKILL_VERSION 2 and a new SHIPPED_DIGESTS entry.
V1_DIGEST = "40b5e90a6794dc620ed146a45513a7feda8e53d9031f86aaab8eeb80a3aaf2a5"
WAS_LINE = re.compile(r"\nWas: (?P<previous>[^\n]+)\Z")


class SkillTextTests(unittest.TestCase):
    text = memory_skill.render()

    def test_the_shipped_text_is_pinned(self):
        self.assertEqual(memory_skill.SKILL_VERSION, 1)
        self.assertEqual(memory_skill.SHIPPED_DIGESTS[1], V1_DIGEST,
                         "the skill text changed: bump SKILL_VERSION and add a SHIPPED_DIGESTS entry")

    def test_frontmatter_and_version(self):
        frontmatter = self.text.split("---\n")[1]
        self.assertIn("name: bio-ce-memory\n", frontmatter)
        description = re.search(r"^description: (.+)$", frontmatter, re.M).group(1)
        self.assertLess(len(description), 1024)
        for trigger in ("지난번", "저번에", "전에 말한", "아까", "기억나?", "우리가 정한", "이전 결정", "왜 이렇게 했더라",
                        "이어서", "규칙", "컨벤션", "before recommending or making", "Once per session"):
            self.assertIn(trigger, description)
        self.assertIn(f"<!-- BIO CE memory skill v1 · for BIO CE {display_version()} · ", self.text)
        self.assertEqual(memory_skill.installed_version(self.text), f"v1 · {display_version()}")

    def test_names_match_the_server(self):
        for name in re.findall(r"`(bio_memory_\w+)`", self.text):
            self.assertIn(name, TOOL_NAMES)
        categories = set(re.findall(r"\| `(\w+)` \|", self.text)) - {"category"}  # minus the table header
        self.assertTrue(categories)
        for category in categories:
            self.assertIn(category, CATEGORIES)
        for evidence in re.findall(r'"(user_\w+)"', self.text):
            self.assertIn(evidence, EVIDENCE)
            self.assertIn(evidence, TRUSTED_EVIDENCE, "the skill must only ask for trusted evidence")
        for change in re.findall(r'`change_type` "(\w+)"', self.text):
            self.assertIn(change, CHANGE_TYPES)

    def test_required_rules_are_present(self):
        for rule in (
            "Always search before you create a memory",
            "update it with\n`bio_memory_update` instead of creating a new one",
            "Do not store these even if the user asks you to",
            "Memories → Add memory",
            "You have not already done this check in this session",
            "put all such candidates in one short question in one message",
            "Never more than 3 items",
            "`Decision changed: `",
            "`Was: <the previous decision, in one line>`",
            "Progress status",
            "Guesses",
        ):
            self.assertIn(rule, self.text)
        good = self.text.split("Good memories")[1].split("Bad memories")[0]
        bad = self.text.split("Bad memories")[1].split("## When a decision changes")[0]
        self.assertTrue(2 <= good.count('\n- "') <= 3)
        self.assertTrue(2 <= bad.count('\n- "') <= 3)

    def test_the_was_line_format_is_machine_readable(self):
        content = "Use SQLite FTS5 for search: no server needed.\nWas: Use Postgres full-text search."
        self.assertEqual(WAS_LINE.search(content).group("previous"), "Use Postgres full-text search.")
        self.assertIsNone(WAS_LINE.search("Was: one\nnew text"), "the Was line must be the last line")


class SkillStateTests(unittest.TestCase):
    def test_states(self):
        self.assertEqual(memory_skill.text_state(None), memory_skill.ABSENT)
        self.assertEqual(memory_skill.text_state(memory_skill.render()), memory_skill.CURRENT)
        self.assertEqual(memory_skill.text_state(memory_skill.render().replace("\n", "\r\n")), memory_skill.CURRENT)
        self.assertEqual(memory_skill.text_state(memory_skill.render("0.3.9")), memory_skill.OUTDATED)
        self.assertEqual(memory_skill.text_state(memory_skill.render() + "\nMy own rule.\n"), memory_skill.MODIFIED)

    def test_agents_block_keeps_the_users_file(self):
        mine = "# My instructions\r\n\r\nAlways answer in Korean.\r\n"
        added = memory_skill.with_agents_block(mine)
        self.assertTrue(added.startswith(mine))
        self.assertIn(memory_skill.AGENTS_BEGIN, added)
        self.assertNotIn("name: bio-ce-memory", added, "AGENTS.md gets the body without frontmatter")
        self.assertEqual(memory_skill.without_agents_block(added), mine)
        self.assertEqual(memory_skill.with_agents_block(added), added, "adding twice changes nothing")
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "AGENTS.md"
            path.write_text(added, encoding="utf-8", newline="")
            self.assertEqual(memory_skill.agents_state(path), memory_skill.CURRENT)
            path.write_text(added.replace("Never more than 3 items", "Never more than 5 items"), encoding="utf-8")
            self.assertEqual(memory_skill.agents_state(path), memory_skill.MODIFIED)
            path.write_text(mine, encoding="utf-8")
            self.assertEqual(memory_skill.agents_state(path), memory_skill.ABSENT)
        self.assertEqual(memory_skill.without_agents_block(memory_skill.with_agents_block("")), "")


class FakeHosts(MCPConnectionManager):
    def _find_cli(self, host: str) -> Path | None:
        return Path(f"{host}.exe")

    def _run_cli(self, host, args):
        if tuple(args) == ("--version",):
            return subprocess.CompletedProcess(args, 0, "codex-cli 0.166.0\n", "")
        if tuple(args)[:2] == ("mcp", "remove"):
            path = self._config_path(host)
            if host == "claude":
                data = json.loads(path.read_text(encoding="utf-8"))
                data["mcpServers"].pop("bio-ce", None)
                path.write_text(json.dumps(data), encoding="utf-8")
            else:
                path.write_text('model = "example"\n', encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")


class ManagerSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="bio-ce-skill-")
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        database = root / "personal.sqlite3"
        store = SQLiteMemoryStore(database)
        store.add(MemoryScope("bio-ce-personal", "default"), title="Synthetic", content="synthetic skill test",
                  source=SourceProvenance("fixture", "fixture:skill"))
        store.close()
        self.codex_home, self.claude_dir = root / "codex", root / "claude"
        self.codex_home.mkdir()
        self.claude_dir.mkdir()
        env = dict(os.environ, CODEX_HOME=str(self.codex_home), CLAUDE_CONFIG_DIR=str(self.claude_dir),
                   USERPROFILE=str(root), HOME=str(root))
        self.manager = FakeHosts(database, root / "appdata", env=env)
        self.addCleanup(self.manager.close)
        for host in ("codex", "claude"):
            grant, token = self.manager.control.create_grant(host, project="bio-ce-personal", namespace="default")
            command, args = self.manager._mcp_server_command(grant.connection_id)
            if host == "codex":
                (self.codex_home / "config.toml").write_text(
                    f"[mcp_servers.bio-ce]\ncommand = {json.dumps(command)}\nargs = {json.dumps(list(args))}\n\n"
                    f'[mcp_servers.bio-ce.env]\nBIO_CE_CONNECTION_TOKEN = "{token}"\n', encoding="utf-8")
            else:
                (self.claude_dir / ".claude.json").write_text(json.dumps({"mcpServers": {"bio-ce": {
                    "type": "stdio", "command": command, "args": list(args),
                    "env": {"BIO_CE_CONNECTION_TOKEN": token}}}}), encoding="utf-8")

    def test_paths_follow_the_host_settings_folder(self):
        self.assertEqual(self.manager.memory_skill_path("claude"),
                         (self.claude_dir / "skills" / "bio-ce-memory" / "SKILL.md").resolve())
        self.assertEqual(self.manager.memory_skill_path("codex"),
                         (self.codex_home / "skills" / "bio-ce-memory" / "SKILL.md").resolve())
        self.assertEqual(memory_skill.agents_path(self.manager.env), (self.codex_home / "AGENTS.md").resolve())

    def test_install_update_and_remove(self):
        with self.assertRaises(MCPConnectionConsentRequired):
            self.manager.install_memory_skill("claude")
        skill, agents = self.manager.install_memory_skill("claude", approved=True)
        self.assertEqual((skill.state, agents), ("installed", None))
        self.assertEqual(skill.path.read_text(encoding="utf-8"), memory_skill.render())
        self.assertEqual(self.manager.status("claude").skill, memory_skill.CURRENT)
        self.assertEqual(self.manager.install_memory_skill("claude", approved=True)[0].state, "unchanged")
        skill.path.write_text(memory_skill.render("0.4.0"), encoding="utf-8")  # from an earlier BIO CE
        updated = self.manager.install_memory_skill("claude", approved=True)[0]
        self.assertEqual(updated.state, "updated")
        self.assertEqual(updated.backup_file.read_text(encoding="utf-8"), memory_skill.render("0.4.0"))
        removed = self.manager.remove_memory_skill("claude", approved=True)[0]
        self.assertEqual(removed.state, "removed")
        self.assertFalse(skill.path.exists())
        self.assertFalse(skill.path.parent.exists(), "the empty skill folder is removed too")

    def test_a_file_the_user_edited_is_kept_unless_they_choose_otherwise(self):
        skill = self.manager.install_memory_skill("codex", approved=True)[0]
        edited = memory_skill.render() + "\nAlso remember my favourite editor.\n"
        skill.path.write_text(edited, encoding="utf-8")
        (skill.path.parent / "notes.txt").write_text("mine", encoding="utf-8")
        self.assertEqual(self.manager.status("codex").skill, memory_skill.MODIFIED)
        self.assertEqual(self.manager.install_memory_skill("codex", approved=True)[0].state, "kept_modified")
        self.assertEqual(self.manager.remove_memory_skill("codex", approved=True)[0].state, "kept_modified")
        self.assertEqual(skill.path.read_text(encoding="utf-8"), edited)
        replaced = self.manager.install_memory_skill("codex", approved=True, replace_modified=True)[0]
        self.assertEqual(replaced.state, "updated")
        self.assertEqual(replaced.backup_file.read_text(encoding="utf-8"), edited)
        self.manager.remove_memory_skill("codex", approved=True)
        self.assertTrue((skill.path.parent / "notes.txt").is_file(), "other files in the folder are kept")

    def test_codex_agents_block_only_when_asked(self):
        agents_file = self.codex_home / "AGENTS.md"
        agents_file.write_text("# Mine\n", encoding="utf-8")
        _skill, agents = self.manager.install_memory_skill("codex", approved=True)
        self.assertIsNone(agents)
        self.assertEqual(agents_file.read_text(encoding="utf-8"), "# Mine\n")
        _skill, agents = self.manager.install_memory_skill("codex", approved=True, agents_md=True)
        self.assertEqual(agents.state, "installed")
        self.assertEqual(self.manager.status("codex").agents_block, memory_skill.CURRENT)
        self.manager.remove_memory_skill("codex", approved=True)
        self.assertEqual(agents_file.read_text(encoding="utf-8"), "# Mine\n")

    def test_disconnect_removes_the_skill_only_when_asked(self):
        self.manager.install_memory_skill("claude", approved=True)
        path = self.manager.memory_skill_path("claude")
        self.manager.disconnect("claude", approved=True)
        self.assertTrue(path.is_file(), "kept unless the user chose to remove it")
        self.assertEqual(self.manager.remove_memory_skill("claude", approved=True)[0].state, "removed")
        self.manager.install_memory_skill("codex", approved=True)
        self.manager.disconnect("codex", approved=True, remove_skill=True)
        self.assertFalse(self.manager.memory_skill_path("codex").exists())

    def test_install_needs_a_connection(self):
        (self.claude_dir / ".claude.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(MCPConnectionError):
            self.manager.install_memory_skill("claude", approved=True)


if __name__ == "__main__":
    unittest.main()
