# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Pins what MCP tools and hooks return today, before they are routed through the engine contract.

Hosts and their models depend on these field names. Routing MCP and hooks
through ``HostSession`` must keep every field below; if a field cannot be
produced by the engine-neutral views, that gap is listed explicitly here.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.engine.community import memory_view, search_view
from bio_ce.engine.contract import MemoryView, SearchResultView
from bio_ce.host_hooks import HookRequest, run_hook
from bio_ce.mcp_server import TOOL_NAMES, _revision_dict, _search_hit_dict
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


SCOPE = MemoryScope("bio-ce-personal", "default")
REVISION_FIELDS = {"memory_id", "revision_id", "revision_number", "kind", "project", "namespace", "title", "content",
                   "source", "recorded_at", "valid_from", "valid_until", "previous_revision_id"}
SEARCH_FIELDS = {"memory_id", "revision_id", "rank", "score", "title", "preview", "source", "recorded_at",
                 "valid_from", "valid_until"}
SOURCE_FIELDS = {"source_type", "source_ref", "metadata"}
# MCP fields the engine-neutral views do not carry yet (the routing step must add them or map around them).
REVISION_GAPS = {"project", "namespace", "previous_revision_id", "source.metadata"}
SEARCH_GAPS = {"valid_from", "valid_until", "source.source_ref", "source.metadata"}


def view_fields(view_type) -> set[str]:
    fields = set(view_type.__dataclass_fields__) - {"engine_id"}
    renamed = {"source_type": "source.source_type", "source_ref": "source.source_ref"}
    return {renamed.get(name, name) for name in fields}


def flatten(keys: set[str], source_keys: set[str]) -> set[str]:
    return (keys - {"source"}) | {f"source.{key}" for key in source_keys}


class ContractSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-snapshot-")
        self.database = Path(self.temp.name) / "memories.sqlite3"
        self.store = SQLiteMemoryStore(self.database)
        first = self.store.add(SCOPE, title="Snapshot editor", content="The user edits snapshot files in vim.",
                               source=SourceProvenance("user-entered", "user-input", {"k": "v"}))
        self.revision = self.store.revise(SCOPE, first.memory_id, expected_revision_id=first.revision_id,
                                          title="Snapshot editor", content="The user edits snapshot files in helix.",
                                          source=SourceProvenance("user-entered", "user-input"))

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_mcp_tool_names_are_unchanged(self):
        self.assertEqual(TOOL_NAMES, ("bio_memory_search", "bio_memory_read", "bio_memory_history",
                                      "bio_memory_create", "bio_memory_update", "bio_memory_retract"))

    def test_read_and_history_fields_are_pinned(self):
        payload = _revision_dict(self.revision)
        self.assertEqual(set(payload), REVISION_FIELDS)
        self.assertEqual(set(payload["source"]), SOURCE_FIELDS)
        self.assertEqual(payload["previous_revision_id"], self.revision.previous_revision_id)

    def test_search_fields_are_pinned(self):
        hit = self.store.search(SCOPE, "snapshot helix", limit=5)[0]
        payload = _search_hit_dict(hit)
        self.assertEqual(set(payload), SEARCH_FIELDS)
        self.assertEqual(set(payload["source"]), SOURCE_FIELDS)

    def test_the_view_gaps_are_exactly_the_listed_ones(self):
        revision_view = flatten(REVISION_FIELDS, SOURCE_FIELDS) - view_fields(MemoryView)
        self.assertEqual(revision_view, REVISION_GAPS)
        search_view_gaps = flatten(SEARCH_FIELDS, SOURCE_FIELDS) - view_fields(SearchResultView)
        self.assertEqual(search_view_gaps, SEARCH_GAPS)
        # Fields both sides carry hold the same values for the Community Engine.
        view = memory_view(self.revision)
        payload = _revision_dict(self.revision)
        for name in ("memory_id", "revision_id", "revision_number", "kind", "title", "content", "recorded_at"):
            self.assertEqual(getattr(view, name), payload[name], name)
        hit = self.store.search(SCOPE, "snapshot helix", limit=5)[0]
        self.assertEqual((search_view(hit).score, search_view(hit).preview),
                         (_search_hit_dict(hit)["score"], _search_hit_dict(hit)["preview"]))

    def test_hook_output_shape_is_pinned(self):
        control = ControlStore(control_database_for(self.database))
        grant, token = control.create_grant("claude", mode=MODE_AUTO_MEMORY)
        control.close()
        for event, name in (("session-start", "SessionStart"), ("user-prompt", "UserPromptSubmit")):
            with self.subTest(event=event):
                out = io.StringIO()
                code = run_hook(HookRequest(event, "claude", self.database, grant.connection_id, token),
                                io.StringIO(json.dumps({"prompt": "which snapshot editor", "cwd": "C:/work/snapshot"})),
                                out)
                self.assertEqual(code, 0)
                document = json.loads(out.getvalue())
                self.assertEqual(set(document), {"hookSpecificOutput"})
                self.assertEqual(set(document["hookSpecificOutput"]), {"hookEventName", "additionalContext"})
                self.assertEqual(document["hookSpecificOutput"]["hookEventName"], name)
                self.assertIn("helix", document["hookSpecificOutput"]["additionalContext"])
        out = io.StringIO()
        self.assertEqual(run_hook(HookRequest("user-prompt", "claude", self.database, grant.connection_id, "bad"),
                                  io.StringIO("{}"), out), 0)
        self.assertEqual(out.getvalue(), "", "a hook that cannot authenticate prints nothing")


if __name__ == "__main__":
    unittest.main()
