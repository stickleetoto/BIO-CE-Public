# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""General and Project spaces over the real stdio MCP server and the session hooks (synthetic data only)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import Client, StdioServerParameters, stdio_client

from bio_ce.auto_memory import ReviewService
from bio_ce.control_store import MODE_AUTO_MEMORY, MODE_READ_ONLY, ControlStore, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.host_hooks import HookRequest, build_context
from bio_ce.mcp_server import TOKEN_ENVIRONMENT_VARIABLE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


GENERAL = MemoryScope("bio-ce-personal", "default")
USER = SourceProvenance("user-entered", "test")


class _SpaceFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-spaces-")
        self.root = Path(self.temp.name)
        self.database = self.root / "data" / "memories.sqlite3"
        self.control = ControlStore(control_database_for(self.database))
        self.alpha = self.control.create_space("Alpha App")
        self.beta = self.control.create_space("Beta")
        self.project_folder = self.root / "work" / "alpha-app"
        self.project_folder.mkdir(parents=True)
        self.control.link_folder(self.alpha.space_id, self.project_folder)
        store = SQLiteMemoryStore(self.database)
        store.add(GENERAL, title="Units", content="The user prefers metric units.", source=USER)
        store.add(self.alpha.curated, title="Alpha build", content="Alpha App builds with the release script.",
                  source=USER)
        store.close()
        self.grant, self.token = self.control.create_grant("codex")
        self.control.set_mode(self.grant.connection_id, MODE_AUTO_MEMORY)

    def tearDown(self) -> None:
        self.control.close()
        self.temp.cleanup()

    @asynccontextmanager
    async def client(self):
        args = ["-m", "bio_ce", "mcp-stdio", "--db", str(self.database), "--connection", self.grant.connection_id]
        params = StdioServerParameters(command=sys.executable, args=args,
                                       env={TOKEN_ENVIRONMENT_VARIABLE: self.token})
        errlog = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        try:
            async with Client(stdio_client(params, errlog=errlog)) as client:
                yield client
        finally:
            errlog.close()

    def run_async(self, coroutine):
        return asyncio.run(asyncio.wait_for(coroutine, timeout=60))

    def calls(self, *steps):
        async def scenario():
            async with self.client() as client:
                results = []
                for tool, arguments in steps:
                    results.append(await client.call_tool(tool, arguments))
                return results
        return self.run_async(scenario())

    @staticmethod
    def fact(**extra):
        return {"title": "Alpha deploys", "content": "The user deploys Alpha App every Friday afternoon.",
                "category": "work_context", "confidence": "high", "evidence": "user_stated", **extra}


class SpaceTests(_SpaceFixture):
    def test_space_argument_resolution_and_result_fields(self):
        exact, by_slug, omitted, unknown = self.calls(
            ("bio_memory_search", {"query": "release script", "space": "alpha app"}),
            ("bio_memory_search", {"query": "release script", "space": "alpha-app"}),
            ("bio_memory_search", {"query": "metric"}),
            ("bio_memory_search", {"query": "metric", "space": "Gamma"}),
        )
        self.assertEqual(exact.structured_content["space"], {"id": self.alpha.space_id, "name": "Alpha App"})
        self.assertEqual(exact.structured_content["space_resolution"], "exact")
        self.assertEqual([hit["title"] for hit in exact.structured_content["results"]], ["Alpha build"])
        self.assertEqual(by_slug.structured_content["space"]["id"], self.alpha.space_id)
        self.assertEqual(omitted.structured_content["space"]["name"], "General")
        self.assertEqual(omitted.structured_content["space_resolution"], "default")
        self.assertEqual(omitted.structured_content["stage"], "curated")
        self.assertEqual(unknown.structured_content["space_resolution"], "fallback_general")
        self.assertEqual(unknown.structured_content["space_resolution_reason"], "unknown")
        self.assertEqual([hit["title"] for hit in unknown.structured_content["results"]], ["Units"])

    def test_write_goes_to_the_named_space_and_unknown_names_write_to_general(self):
        named, fallback = self.calls(
            ("bio_memory_create", self.fact(space="Alpha App")),
            ("bio_memory_create", self.fact(space="No Such Space", title="Cycling",
                                            content="The user cycles to work on weekdays.",
                                            category="preference")),
        )
        self.assertEqual(named.structured_content["status"], "created", named)
        self.assertEqual(fallback.structured_content["space_resolution"], "fallback_general")
        store = SQLiteMemoryStore(self.database, read_only=True)
        try:
            self.assertIn("Alpha deploys", {r.title for r in store.list_current(self.alpha.curated, limit=10)})
            self.assertIn("Cycling", {r.title for r in store.list_current(GENERAL, limit=10)})
        finally:
            store.close()

    def test_a_denied_space_is_refused_and_never_redirected_to_general(self):
        self.control.set_connection_settings(self.grant.connection_id, all_projects=False)
        write, read = self.calls(
            ("bio_memory_create", self.fact(space="Alpha App")),
            ("bio_memory_search", {"query": "release", "space": "Alpha App"}),
        )
        self.assertTrue(write.is_error)
        self.assertIn("no write access", str(write.content))
        self.assertTrue(read.is_error)
        store = SQLiteMemoryStore(self.database, read_only=True)
        try:
            self.assertNotIn("Alpha deploys", {r.title for r in store.list_current(GENERAL, limit=10)})
        finally:
            store.close()

    def test_read_only_mode_still_says_auto_memory_is_off(self):
        self.control.set_mode(self.grant.connection_id, MODE_READ_ONLY)
        (write,) = self.calls(("bio_memory_create", self.fact(space="Alpha App")))
        self.assertTrue(write.is_error)
        self.assertIn("Auto memory is off", str(write.content))

    def test_project_namespace_arguments_map_to_spaces_and_inbox_scopes_are_refused(self):
        by_project, conflicting, inbox, other = self.calls(
            ("bio_memory_search", {"query": "release", "project": self.alpha.project, "namespace": "default"}),
            ("bio_memory_search", {"query": "release", "project": self.alpha.project, "space": "Beta"}),
            ("bio_memory_search", {"query": "release", "project": "bio-ce-personal", "namespace": "default.inbox"}),
            ("bio_memory_search", {"query": "release", "project": "someone-else", "namespace": "default"}),
        )
        self.assertEqual(by_project.structured_content["space"]["name"], "Alpha App")
        self.assertTrue(conflicting.is_error)
        self.assertTrue(inbox.is_error)
        self.assertTrue(other.is_error)

    def test_archived_spaces_are_not_available(self):
        self.control.archive_space(self.beta.space_id)
        (result,) = self.calls(("bio_memory_search", {"query": "x", "space": "Beta"}))
        self.assertEqual(result.structured_content["space_resolution"], "fallback_general")

    def hook(self, event: str, cwd: Path | str, prompt: str = "") -> str:
        return build_context(HookRequest(event, "claude", self.database, self.grant.connection_id, self.token),
                             {"cwd": str(cwd), "prompt": prompt})

    def test_hooks_use_the_deepest_linked_folder(self):
        inside = self.hook("session-start", self.project_folder / "src" / "ui")
        self.assertIn("BIO CE space for this folder: 'Alpha App'", inside)
        self.assertIn("Alpha build", inside)
        self.assertIn("Units", inside)  # General stays in view after the project's own memories
        self.assertLess(inside.index("Alpha build"), inside.index("Units"))
        outside = self.hook("session-start", self.root / "elsewhere")
        self.assertIn("isn't linked to a BIO CE project space", outside)
        self.assertNotIn("Alpha build", outside)
        prompt = self.hook("user-prompt", self.project_folder, prompt="how does the release script work")
        self.assertIn("Alpha build", prompt)

    def test_hooks_fall_back_to_general_when_a_folder_is_ambiguous_or_not_allowed(self):
        self.control.link_folder(self.beta.space_id, self.project_folder)
        ambiguous = self.hook("session-start", self.project_folder)
        self.assertIn("couldn't decide which space", ambiguous)
        self.assertNotIn("Alpha build", ambiguous)
        self.control.unlink_folder(self.beta.space_id, self.control.folder_links()[0][1]
                                   if self.control.folder_links()[0][0] == self.beta.space_id
                                   else self.control.folder_links()[1][1])
        self.control.set_connection_settings(self.grant.connection_id, all_projects=False)
        limited = self.hook("session-start", self.project_folder)
        self.assertIn("uses BIO CE's General space", limited)
        self.assertNotIn("Alpha build", limited)


class SpaceReviewAndBindingTests(_SpaceFixture):
    def test_a_queued_project_item_is_approved_into_its_own_space(self):
        (queued,) = self.calls(("bio_memory_create", self.fact(space="Alpha App", evidence="inferred",
                                                              confidence="medium")))
        self.assertEqual(queued.structured_content["status"], "queued_for_review")
        item = self.control.reviews()[0]
        self.assertEqual((item.metadata["project"], item.metadata["namespace"]), (self.alpha.project, "default"))
        store = SQLiteMemoryStore(self.database)
        try:
            revision = ReviewService(store, self.control, GENERAL).approve(item.review_id)
            self.assertEqual(revision.scope, self.alpha.curated)
        finally:
            store.close()

    def test_a_grant_bound_to_another_scope_gets_no_spaces(self):
        team, token = self.control.create_grant("claude", project="team-atlas", namespace="notes")
        self.assertEqual(self.control.space_access(team.connection_id, self.alpha), (False, False))
        context = build_context(HookRequest("session-start", "claude", self.database, team.connection_id, token),
                                {"cwd": str(self.project_folder)})
        self.assertNotIn("Alpha", context)
        self.assertNotIn("General", context)


class SpaceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-space-store-")
        self.control = ControlStore(Path(self.temp.name) / "control.sqlite3")

    def tearDown(self) -> None:
        self.control.close()
        self.temp.cleanup()

    def test_create_rename_archive_and_general_rules(self):
        alpha = self.control.create_space("Alpha")
        self.assertEqual(alpha.project, "project:alpha")
        with self.assertRaisesRegex(Exception, "already exists"):
            self.control.create_space("ALPHA")
        renamed = self.control.rename_space(alpha.space_id, "Alpha Two")
        self.assertEqual((renamed.display_name, renamed.project), ("Alpha Two", "project:alpha"))
        self.control.archive_space(alpha.space_id)
        again = self.control.create_space("Alpha")
        self.assertEqual(again.project, "project:alpha-2")  # the archived slug stays taken
        for action in (lambda: self.control.rename_space("general", "Mine"),
                       lambda: self.control.archive_space("general")):
            with self.assertRaises(Exception):
                action()
        self.assertEqual([space.display_name for space in self.control.spaces()], ["General", "Alpha"])

    def test_folders_store_only_a_hash_and_the_folder_name(self):
        alpha = self.control.create_space("Alpha")
        key = self.control.link_folder(alpha.space_id, r"C:\Users\Someone\work\alpha")
        self.assertEqual(self.control.folder_links(), ((alpha.space_id, key, "alpha"),))
        raw = Path(self.control.path).read_bytes() + Path(f"{self.control.path}-wal").read_bytes()
        self.assertNotIn(b"Someone", raw)


if __name__ == "__main__":
    unittest.main()
