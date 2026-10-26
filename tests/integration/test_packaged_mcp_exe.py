# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import Client, StdioServerParameters, stdio_client

from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.mcp_server import TOOL_NAMES
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "packaging"))
import bio_ce  # noqa: E402
import build_assets  # noqa: E402

PACKAGED_MCP = (REPOSITORY / "build" / build_assets.display_version(bio_ce.__version__) / "mcp-dist" / "BIO-CE-MCP"
                / "BIO-CE-MCP.exe")


class PackagedMCPExecutableTests(unittest.TestCase):
    def test_onedir_mcp_exe_runs_official_sdk_search_read_retraction_and_reconnect(self):
        if not PACKAGED_MCP.is_file():
            self.skipTest("Run packaging/build_windows.ps1 before the bundled EXE smoke test")
        with tempfile.TemporaryDirectory(prefix="bio-ce-packaged-mcp-") as scratch:
            database = Path(scratch) / "synthetic.sqlite3"
            scope = MemoryScope("bio-ce-personal", "default")
            writer = SQLiteMemoryStore(database)
            first = writer.add(
                scope,
                memory_id="mem_packaged_test_0001",
                title="Packaged executable synthetic memory",
                content="The marker packagedmcpverification is synthetic test data.",
                source=SourceProvenance("fixture", "fixture:packaged-mcp"),
            )
            writer.close()
            parameters = StdioServerParameters(
                command=str(PACKAGED_MCP),
                args=[
                    "mcp-stdio",
                    "--db",
                    str(database),
                    "--project",
                    scope.project,
                    "--namespace",
                    scope.namespace,
                ],
            )

            async def exercise() -> None:
                async with Client(stdio_client(parameters)) as client:
                    tools = await client.list_tools()
                    self.assertEqual(
                        {tool.name for tool in tools.tools},
                        set(TOOL_NAMES),
                    )
                    search = await client.call_tool(
                        "bio_memory_search",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "query": "packagedmcpverification",
                            "limit": 5,
                        },
                    )
                    self.assertFalse(search.is_error)
                    hit = search.structured_content["results"][0]
                    self.assertEqual(hit["memory_id"], first.memory_id)
                    self.assertEqual(hit["revision_id"], first.revision_id)
                    read = await client.call_tool(
                        "bio_memory_read",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "memory_id": hit["memory_id"],
                        },
                    )
                    self.assertFalse(read.is_error)
                    self.assertEqual(read.structured_content["revision_id"], hit["revision_id"])

                update_store = SQLiteMemoryStore(database)
                update_store.retract(
                    scope,
                    first.memory_id,
                    expected_revision_id=first.revision_id,
                    source=SourceProvenance("fixture", "fixture:packaged-retract"),
                )
                update_store.close()
                async with Client(stdio_client(parameters)) as client:
                    denied = await client.call_tool(
                        "bio_memory_read",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "memory_id": first.memory_id,
                        },
                    )
                    self.assertTrue(denied.is_error)

            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
