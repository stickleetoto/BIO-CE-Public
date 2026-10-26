# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Scope binding over the real stdio MCP server and the official MCP SDK client.

A server serves exactly one project/namespace. Managed connections take it from
the authenticated grant, tools accept an omitted scope, and any other scope is
refused, so memories in other projects stay unreachable.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from mcp import Client, StdioServerParameters, stdio_client

from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.host_hooks import HookRequest, build_context
from bio_ce.mcp_server import TOKEN_ENVIRONMENT_VARIABLE, TOOL_NAMES
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


PERSONAL = MemoryScope("bio-ce-personal", "default")
OTHER = MemoryScope("team-atlas", "default")
SOURCE = SourceProvenance("user-entered", "user-input")


class MCPScopeBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-scope-")
        self.database = Path(self.temp.name) / "data" / "memories.sqlite3"
        store = SQLiteMemoryStore(self.database)
        self.mine = store.add(PERSONAL, title="Personal scope note",
                              content="Synthetic personalscopemarker text.", source=SOURCE)
        self.theirs = store.add(OTHER, title="Other project note",
                                content="Synthetic otherscopemarker text that must stay hidden.", source=SOURCE)
        store.close()
        self.control = ControlStore(control_database_for(self.database))
        self.grant, self.token = self.control.create_grant("codex", project=PERSONAL.project,
                                                           namespace=PERSONAL.namespace)
        self.control.set_mode(self.grant.connection_id, MODE_AUTO_MEMORY)

    def tearDown(self) -> None:
        self.control.close()
        self.temp.cleanup()

    def server_args(self, *, connection: str | None, project: str | None = None,
                    namespace: str | None = None) -> list[str]:
        args = ["-m", "bio_ce", "mcp-stdio", "--db", str(self.database)]
        if project is not None:
            args += ["--project", project]
        if namespace is not None:
            args += ["--namespace", namespace]
        if connection is not None:
            args += ["--connection", connection]
        return args

    @asynccontextmanager
    async def client(self, *, connection: str | None = "default", token: str | None = None, **scope):
        if connection == "default":
            connection, token = self.grant.connection_id, self.token
        env = {TOKEN_ENVIRONMENT_VARIABLE: token or ""} if connection else None
        params = StdioServerParameters(command=sys.executable, args=self.server_args(connection=connection, **scope),
                                       env=env)
        errlog = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        try:
            async with Client(stdio_client(params, errlog=errlog)) as client:
                yield client
        finally:
            errlog.close()

    def run_async(self, coroutine):
        return asyncio.run(asyncio.wait_for(coroutine, timeout=90))

    def read_store(self, scope: MemoryScope, memory_id: str):
        store = SQLiteMemoryStore(self.database, read_only=True)
        try:
            return store.read(scope, memory_id)
        finally:
            store.close()

    # Contract ------------------------------------------------------------------

    def test_scope_arguments_are_optional_in_every_tool_schema(self):
        async def scenario():
            async with self.client() as client:
                return (await client.list_tools()).tools

        tools = {tool.name: tool for tool in self.run_async(scenario())}
        self.assertEqual(set(tools), set(TOOL_NAMES))
        for name, tool in tools.items():
            with self.subTest(tool=name):
                schema = tool.input_schema
                self.assertIn("project", schema["properties"])
                self.assertIn("namespace", schema["properties"])
                self.assertNotIn("project", schema.get("required", []))
                self.assertNotIn("namespace", schema.get("required", []))

    def test_omitted_or_exact_scope_works_and_any_other_scope_is_refused(self):
        async def scenario():
            outcomes = {}
            async with self.client() as client:
                omitted = await client.call_tool("bio_memory_search", {"query": "personalscopemarker"})
                exact = await client.call_tool("bio_memory_search", {"query": "personalscopemarker",
                                                                     "project": PERSONAL.project,
                                                                     "namespace": PERSONAL.namespace})
                outcomes["omitted"] = omitted
                outcomes["exact"] = exact
                for label, scope in (("other_project", {"project": OTHER.project}),
                                     ("other_namespace", {"namespace": "elsewhere"}),
                                     ("guessed_default", {"project": "default", "namespace": "default"})):
                    outcomes[label] = await client.call_tool("bio_memory_search", {"query": "marker", **scope})
                outcomes["read_omitted"] = await client.call_tool("bio_memory_read", {"memory_id": self.mine.memory_id})
                outcomes["history_omitted"] = await client.call_tool("bio_memory_history",
                                                                     {"memory_id": self.mine.memory_id})
                outcomes["create_omitted"] = await client.call_tool("bio_memory_create", {
                    "title": "Prefers dark editor themes", "content": "The user prefers dark editor themes.",
                    "category": "preference", "confidence": "high", "evidence": "user_stated"})
                outcomes["create_other"] = await client.call_tool("bio_memory_create", {
                    "project": OTHER.project, "title": "Should not land", "content": "The user likes tea.",
                    "category": "preference", "confidence": "high", "evidence": "user_stated"})
            return outcomes

        outcomes = self.run_async(scenario())
        for label in ("omitted", "exact"):
            with self.subTest(label=label):
                result = outcomes[label]
                self.assertFalse(result.is_error, result)
                self.assertEqual(result.structured_content["project"], PERSONAL.project)
                self.assertEqual([hit["memory_id"] for hit in result.structured_content["results"]],
                                 [self.mine.memory_id])
        for label in ("other_project", "other_namespace", "guessed_default", "create_other"):
            with self.subTest(label=label):
                result = outcomes[label]
                self.assertTrue(result.is_error, result)
                message = result.content[0].text
                self.assertIn("'bio-ce-personal'", message)
                self.assertIn("Omit project and namespace", message)
        self.assertFalse(outcomes["read_omitted"].is_error)
        self.assertEqual(outcomes["read_omitted"].structured_content["revision_id"], self.mine.revision_id)
        self.assertFalse(outcomes["history_omitted"].is_error)
        self.assertEqual(outcomes["create_omitted"].structured_content["status"], "created")
        store = SQLiteMemoryStore(self.database, read_only=True)
        try:
            self.assertEqual(store.count_current(OTHER), 1)
            self.assertEqual(store.count_current(PERSONAL), 2)
        finally:
            store.close()

    def test_memories_in_other_scopes_cannot_be_found_read_changed_or_retracted(self):
        theirs = self.theirs

        async def scenario():
            async with self.client() as client:
                return {
                    "search": await client.call_tool("bio_memory_search", {"query": "otherscopemarker"}),
                    "read": await client.call_tool("bio_memory_read", {"memory_id": theirs.memory_id}),
                    "history": await client.call_tool("bio_memory_history", {"memory_id": theirs.memory_id}),
                    "update": await client.call_tool("bio_memory_update", {
                        "memory_id": theirs.memory_id, "expected_revision_id": theirs.revision_id,
                        "title": "Hijacked", "content": "Overwritten by another project.",
                        "change_type": "correction", "confidence": "high", "evidence": "user_stated"}),
                    "retract": await client.call_tool("bio_memory_retract", {
                        "memory_id": theirs.memory_id, "expected_revision_id": theirs.revision_id}),
                }

        outcomes = self.run_async(scenario())
        self.assertFalse(outcomes["search"].is_error)
        self.assertEqual(outcomes["search"].structured_content["results"], [])
        for label in ("read", "history", "update", "retract"):
            with self.subTest(label=label):
                self.assertTrue(outcomes[label].is_error, outcomes[label])
        self.assertEqual(self.read_store(OTHER, theirs.memory_id).revision_id, theirs.revision_id)
        self.assertEqual(self.control.reviews(), ())

    def test_server_scope_comes_from_the_grant_not_from_arguments(self):
        team, team_token = self.control.create_grant("claude", project=OTHER.project, namespace=OTHER.namespace)

        async def scenario():
            async with self.client(connection=team.connection_id, token=team_token) as client:
                return (await client.call_tool("bio_memory_search",
                                               {"query": "otherscopemarker personalscopemarker"}),
                        await client.call_tool("bio_memory_read", {"memory_id": self.mine.memory_id}))

        search, read = self.run_async(scenario())
        self.assertEqual(search.structured_content["project"], OTHER.project)
        self.assertEqual([hit["memory_id"] for hit in search.structured_content["results"]], [self.theirs.memory_id])
        self.assertTrue(read.is_error)

        for scope in ({"project": OTHER.project}, {"project": PERSONAL.project, "namespace": "elsewhere"}):
            with self.subTest(scope=scope):
                completed = subprocess.run(
                    [sys.executable, *self.server_args(connection=self.grant.connection_id, **scope)],
                    env={**os.environ, TOKEN_ENVIRONMENT_VARIABLE: self.token},
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(completed.returncode, 3, completed.stderr)
                self.assertEqual(completed.stdout, "")

    def test_legacy_read_only_server_still_needs_and_enforces_its_scope(self):
        completed = subprocess.run([sys.executable, *self.server_args(connection=None)],
                                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--project and --namespace", completed.stderr)

        async def scenario():
            async with self.client(connection=None, project=PERSONAL.project, namespace=PERSONAL.namespace) as client:
                return (await client.call_tool("bio_memory_search", {"query": "personalscopemarker"}),
                        await client.call_tool("bio_memory_search", {"query": "marker", "project": OTHER.project}),
                        await client.call_tool("bio_memory_create", {
                            "title": "Legacy write", "content": "The user likes tea.", "category": "preference",
                            "confidence": "high", "evidence": "user_stated"}))

        omitted, other, write = self.run_async(scenario())
        self.assertFalse(omitted.is_error)
        self.assertEqual(len(omitted.structured_content["results"]), 1)
        self.assertTrue(other.is_error)
        self.assertTrue(write.is_error)

    # Hooks and control database -------------------------------------------------

    def test_hooks_use_the_grant_scope_and_ignore_mismatched_arguments(self):
        payload = {"prompt": "personalscopemarker otherscopemarker"}
        bound = build_context(HookRequest("user-prompt", "codex", self.database, self.grant.connection_id,
                                          self.token), payload)
        self.assertIn("Personal scope note", bound)
        self.assertNotIn("Other project note", bound)
        mismatched = build_context(HookRequest("user-prompt", "codex", self.database, self.grant.connection_id,
                                               self.token, OTHER.project, OTHER.namespace), payload)
        self.assertEqual(mismatched, "")

    def test_v1_control_database_is_migrated_with_personal_scope(self):
        legacy = Path(self.temp.name) / "legacy" / "control.sqlite3"
        legacy.parent.mkdir()
        connection = sqlite3.connect(legacy)
        connection.executescript(
            "CREATE TABLE connections (connection_id TEXT PRIMARY KEY, host TEXT NOT NULL, "
            "token_sha256 TEXT NOT NULL, mode TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "revoked_at TEXT); PRAGMA user_version = 1;"
        )
        from bio_ce.control_store import hash_token

        connection.execute("INSERT INTO connections VALUES ('conn_legacy', 'codex', ?, 'auto_memory', 't', 't', NULL)",
                           (hash_token("legacy-token"),))
        connection.commit()
        connection.close()
        with ControlStore(legacy) as store:
            grant = store.authenticate("conn_legacy", "legacy-token")
            self.assertEqual((grant.project, grant.namespace), (PERSONAL.project, PERSONAL.namespace))
            self.assertEqual(grant.mode, MODE_AUTO_MEMORY)
        with ControlStore(legacy) as store:  # second open is a no-op migration
            self.assertEqual(store.grant("conn_legacy").project, PERSONAL.project)
        check = sqlite3.connect(legacy)
        try:
            self.assertEqual(check.execute("PRAGMA user_version").fetchone()[0], 2)
        finally:
            check.close()


if __name__ == "__main__":
    unittest.main()
