# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import Client, StdioServerParameters, stdio_client

from bio_ce.core.models import MemoryNotFoundError, MemoryScope, SourceProvenance
from bio_ce.demo_fixture import (
    DEMO_NAMESPACE,
    DEMO_PROJECT,
    seed_synthetic_mcp_demo,
)
from bio_ce.mcp_server import TOOL_NAMES
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


class MCPStdioIntegrationTests(unittest.TestCase):
    def test_official_sdk_client_uses_real_read_only_sqlite_server(self):
        with tempfile.TemporaryDirectory(prefix="bio-ce-mcp-") as scratch:
            database = Path(scratch) / "mcp-fixture.sqlite3"
            scope = MemoryScope(DEMO_PROJECT, DEMO_NAMESPACE)
            source = SourceProvenance("fixture", "fixture:mcp", {"synthetic": True})
            seed_synthetic_mcp_demo(database)
            with self.assertRaises(FileExistsError):
                seed_synthetic_mcp_demo(database)
            writer = SQLiteMemoryStore(database)
            active = writer.read(scope, "mem_bio_ce_demo_0001")
            withdrawn = writer.add(
                scope,
                memory_id="mem_mcp_fixture_0002",
                title="Withdrawn MCP fixture",
                content="mcpwithdrawnunique is a synthetic retracted memory.",
                source=source,
            )
            writer.retract(
                scope,
                withdrawn.memory_id,
                expected_revision_id=withdrawn.revision_id,
                source=source,
            )
            writer.close()

            parameters = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m", "bio_ce", "mcp-stdio",
                    "--db", str(database),
                    "--project", scope.project,
                    "--namespace", scope.namespace,
                ],
            )
            stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")

            async def exercise() -> None:
                async with Client(stdio_client(parameters, errlog=stderr)) as client:
                    discovered = await client.list_tools()
                    self.assertEqual(
                        {tool.name for tool in discovered.tools},
                        set(TOOL_NAMES),
                    )

                    refused = await client.call_tool(
                        "bio_memory_create",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "title": "Legacy write attempt",
                            "content": "A v0.2 style connection must stay read-only.",
                            "category": "preference",
                            "confidence": "high",
                            "evidence": "user_stated",
                        },
                    )
                    self.assertTrue(refused.is_error, "a tokenless (v0.2) server must refuse writes")

                    search = await client.call_tool(
                        "bio_memory_search",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "query": "lexical retrieval",
                        },
                    )
                    self.assertFalse(search.is_error)
                    search_data = search.structured_content
                    self.assertEqual(search_data["project"], scope.project)
                    self.assertEqual(search_data["namespace"], scope.namespace)
                    self.assertEqual(len(search_data["results"]), 1)
                    hit = search_data["results"][0]
                    self.assertEqual(hit["memory_id"], active.memory_id)
                    self.assertEqual(hit["revision_id"], active.revision_id)

                    read = await client.call_tool(
                        "bio_memory_read",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "memory_id": hit["memory_id"],
                        },
                    )
                    self.assertFalse(read.is_error)
                    read_data = read.structured_content
                    self.assertEqual(read_data["memory_id"], hit["memory_id"])
                    self.assertEqual(read_data["revision_id"], hit["revision_id"])
                    self.assertEqual(read_data["content"], active.content)

                    wrong_scope = await client.call_tool(
                        "bio_memory_search",
                        {
                            "project": "another-project",
                            "namespace": scope.namespace,
                            "query": "lexical retrieval",
                        },
                    )
                    self.assertTrue(wrong_scope.is_error)
                    self.assertIn("unavailable", wrong_scope.content[0].text)

                    wrong_namespace = await client.call_tool(
                        "bio_memory_search",
                        {
                            "project": scope.project,
                            "namespace": "another-namespace",
                            "query": "lexical retrieval",
                        },
                    )
                    self.assertTrue(wrong_namespace.is_error)
                    self.assertIn("unavailable", wrong_namespace.content[0].text)

                    missing = await client.call_tool(
                        "bio_memory_read",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "memory_id": "mem_mcp_missing_0001",
                        },
                    )
                    self.assertTrue(missing.is_error)
                    self.assertIn("unavailable", missing.content[0].text)

                    invalid_id = await client.call_tool(
                        "bio_memory_read",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "memory_id": "../invalid-secret-marker",
                        },
                    )
                    self.assertTrue(invalid_id.is_error)
                    self.assertIn("invalid", invalid_id.content[0].text)

                    retracted_read = await client.call_tool(
                        "bio_memory_read",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "memory_id": withdrawn.memory_id,
                        },
                    )
                    self.assertTrue(retracted_read.is_error)
                    self.assertIn("unavailable", retracted_read.content[0].text)

                    retracted_search = await client.call_tool(
                        "bio_memory_search",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "query": "mcpwithdrawnunique",
                        },
                    )
                    self.assertFalse(retracted_search.is_error)
                    self.assertEqual(retracted_search.structured_content["results"], [])

                    secret_marker = "ceconfidentialmarker4f381e"
                    no_match = await client.call_tool(
                        "bio_memory_search",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "query": secret_marker,
                        },
                    )
                    self.assertFalse(no_match.is_error)
                    self.assertEqual(no_match.structured_content["results"], [])

                # Exiting the SDK Client scope shuts down the first server process.
                async with Client(stdio_client(parameters, errlog=stderr)) as client:
                    reconnected = await client.call_tool(
                        "bio_memory_read",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "memory_id": active.memory_id,
                        },
                    )
                    self.assertFalse(reconnected.is_error)
                    self.assertEqual(
                        reconnected.structured_content["revision_id"], active.revision_id
                    )

            try:
                asyncio.run(exercise())
                stderr.seek(0)
                self.assertNotIn("ceconfidentialmarker4f381e", stderr.read())
            finally:
                stderr.close()

            # The same store's public API is independently protected by SQLite mode=ro.
            reader = SQLiteMemoryStore(database, read_only=True)
            try:
                self.assertEqual(reader.read(scope, active.memory_id).revision_id, active.revision_id)
                with self.assertRaises(MemoryNotFoundError):
                    reader.read(scope, withdrawn.memory_id)
            finally:
                reader.close()


if __name__ == "__main__":
    unittest.main()
