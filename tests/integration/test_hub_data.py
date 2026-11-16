# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 §2.2: what the unified memory screen lists — four states, one space or all, search, hidden deletes."""

from __future__ import annotations

import tempfile
import unittest

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.core.models import SourceProvenance
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from bio_ce.ui.hub.data import ALL_SPACES, INBOX, MEMORIES, REVIEWS, SUGGESTIONS, HubData
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root

HOST = SourceProvenance("ai-host-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})


class HubDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-hub-data-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.control.set_personal_enabled(True)
        self.general = self.control.space("general")
        self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        self.service.use_space(PERSONAL_SPACE.curated)
        self.service.add(title="Running", content="The user runs every morning.", source_ref="test")
        self.service.use_space(self.general.curated)
        store = SQLiteMemoryStore(self.paths.user_database)
        for text in ("The team deploys on Fridays.", "The team deploys on Fridays. Releases need a tag."):
            item = store.add(self.general.inbox, title="Deploys", content=text, source=HOST)
            self.control.inbox_seen(item.memory_id)
        store.close()
        self.service.curation(self.control, (*self.control.spaces(), PERSONAL_SPACE)).find()
        self.control.enqueue_review(host="codex", connection_id=None, kind="create", title="Tea",
                                    content="The user drinks green tea.", review_reason="test",
                                    metadata={"project": PERSONAL_SPACE.curated.project,
                                              "namespace": PERSONAL_SPACE.curated.namespace})
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.data = HubData(self.app)

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def test_every_state_from_all_spaces_and_from_one(self):
        self.assertEqual(self.data.counts(ALL_SPACES), {MEMORIES: 2, INBOX: 2, SUGGESTIONS: 1, REVIEWS: 1})
        self.assertEqual(self.data.counts("personal"), {MEMORIES: 1, INBOX: 0, SUGGESTIONS: 0, REVIEWS: 1})
        self.assertEqual(self.data.counts("general"), {MEMORIES: 1, INBOX: 2, SUGGESTIONS: 1, REVIEWS: 0})
        titles = {item.title: item.space.space_id for item in self.data.items(MEMORIES, ALL_SPACES)}
        self.assertEqual(titles, {"Editor": "general", "Running": "personal"})
        self.assertEqual(self.app.service.scope, self.general.curated)  # the shown space is restored

    def test_search_narrows_within_the_state(self):
        self.assertEqual([i.title for i in self.data.items(MEMORIES, ALL_SPACES, "helix")], ["Editor"])
        self.assertEqual(self.data.items(MEMORIES, ALL_SPACES, "nothing like this"), [])
        self.assertEqual(len(self.data.items(INBOX, ALL_SPACES, "fridays")), 2)

    def test_items_waiting_for_their_delete_are_left_out(self):
        editor = next(i for i in self.data.items(MEMORIES, ALL_SPACES) if i.title == "Editor")
        self.app.pending.defer([editor.item_id], lambda: None, message="deleted", title="Deleted")
        self.assertEqual([i.title for i in self.data.items(MEMORIES, ALL_SPACES)], ["Running"])
        self.app.pending.undo()
        self.assertEqual(len(self.data.items(MEMORIES, ALL_SPACES)), 2)  # positive control: back after Undo


if __name__ == "__main__":
    unittest.main()
