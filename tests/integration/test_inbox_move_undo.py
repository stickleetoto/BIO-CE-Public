# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 move table: "To memories" can be undone, and "Add as a new memory" for a proposed change is recorded as
an approval (the memory screen's Reviews tab).

Undo puts the inbox item back in the inbox (it was only kept aside) and takes the memory back: a memory the move
made is retracted, a memory it updated gets its earlier text back as a new revision. Nothing is deleted, and a
memory that changed after the move is never overwritten.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bio_ce.control_store import REVIEW_APPROVED, ControlStore, control_database_for
from bio_ce.core.models import MemoryNotFoundError, MemoryScope, RevisionConflictError, SourceProvenance
from bio_ce.desktop import DesktopMemoryService
from bio_ce.inbox import inbox_scope, kept_originals, kept_scope
from tests.integration.test_no_silent_deletes import rows

GENERAL = MemoryScope("bio-ce-personal", "default")
INBOX = inbox_scope(GENERAL)
HOST = SourceProvenance("ai-host-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})
WHERE = {"project": GENERAL.project, "namespace": GENERAL.namespace}


class InboxMoveUndoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-move-undo-")
        self.database = Path(self.temp.name) / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.control = ControlStore(control_database_for(self.database))
        self.store = self.service._store

    def tearDown(self) -> None:
        self.service.close()
        self.control.close()
        self.temp.cleanup()

    def host_saves(self, title: str, content: str) -> str:
        revision = self.store.add(INBOX, title=title, content=content, source=HOST)
        self.control.inbox_seen(revision.memory_id)
        return revision.memory_id

    def inbox_ids(self) -> list[str]:
        return [revision.memory_id for revision in self.service.inbox()]

    def test_undoing_a_move_that_made_a_memory_retracts_it_and_returns_the_item(self):
        item = self.host_saves("Ramen", "The user likes miso ramen.")
        made = self.service.move_inbox(self.control, item, title="Ramen", content="The user likes miso ramen.")
        self.assertEqual(self.inbox_ids(), [])
        before = rows(self.database)
        self.service.undo_move_inbox(self.control, item, made)
        self.assertEqual(self.inbox_ids(), [item])  # back in the inbox, same item, same text
        self.assertEqual(self.service.read_inbox(item).content, "The user likes miso ramen.")
        with self.assertRaises(MemoryNotFoundError):
            self.service.read(made.memory_id)  # the memory the move made is retracted
        self.assertTrue(before["memories"] <= rows(self.database)["memories"])  # nothing deleted
        self.assertTrue(before["revisions"] <= rows(self.database)["revisions"])
        self.assertEqual(self.store.list_current(kept_scope(GENERAL)), ())
        entry = self.control.recent_activity(limit=1)[0]
        self.assertEqual((entry.action, entry.outcome), ("inbox-move", "undone"))

    def test_undoing_a_move_that_updated_a_memory_gives_its_earlier_text_back(self):
        older = self.host_saves("Tabs", "The user prefers tabs in Go.")
        memory = self.service.move_inbox(self.control, older, title="Tabs", content="The user prefers tabs in Go.")
        item = self.host_saves("Tabs in C", "The user also prefers tabs in C.")
        updated = self.service.move_inbox(self.control, item, title="Tabs",
                                          content="The user prefers tabs in Go and C.", update=memory)
        self.assertEqual(sorted(kept_originals(self.store, GENERAL, [memory.memory_id])), sorted([older, item]))
        self.service.undo_move_inbox(self.control, item, updated)
        current = self.service.read(memory.memory_id)
        self.assertEqual((current.title, current.content), ("Tabs", "The user prefers tabs in Go."))
        self.assertEqual(current.revision_number, 3)  # a new revision: History keeps the undone one
        self.assertEqual(self.inbox_ids(), [item])
        self.assertEqual(kept_originals(self.store, GENERAL, [memory.memory_id]), [older])  # still kept for it

    def test_a_memory_that_changed_after_the_move_is_not_overwritten(self):
        item = self.host_saves("Ramen", "The user likes miso ramen.")
        made = self.service.move_inbox(self.control, item, title="Ramen", content="The user likes miso ramen.")
        self.service.revise(made, title="Ramen", content="The user likes shoyu ramen now.", source_ref="test")
        with self.assertRaises(RevisionConflictError):
            self.service.undo_move_inbox(self.control, item, made)
        self.assertEqual(self.service.read(made.memory_id).content, "The user likes shoyu ramen now.")
        self.assertEqual(self.inbox_ids(), [])  # nothing changed: the item stays kept for the memory
        self.assertEqual(kept_originals(self.store, GENERAL, [made.memory_id]), [item])


class ApproveAsNewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-as-new-")
        self.database = Path(self.temp.name) / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.control = ControlStore(control_database_for(self.database))

    def tearDown(self) -> None:
        self.service.close()
        self.control.close()
        self.temp.cleanup()

    def proposal(self, content: str) -> tuple:
        memory = self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        review_id = self.control.enqueue_review(
            host="codex", connection_id=None, kind="update", title="Shell", content=content,
            review_reason="test", memory_id=memory.memory_id, expected_revision_id=memory.revision_id,
            metadata=WHERE)
        return memory, review_id

    def test_a_proposed_change_added_as_a_new_memory_is_an_approval_and_leaves_the_old_one(self):
        memory, review_id = self.proposal("The user uses PowerShell 7.")
        added = self.service.approve_review_as_new(self.control, review_id, title="Shell",
                                                   content="The user uses PowerShell 7.")
        self.assertNotEqual(added.memory_id, memory.memory_id)
        self.assertEqual(self.service.read(memory.memory_id).content, "The user edits in helix.")  # untouched
        self.assertEqual((added.title, added.content, added.revision_number), ("Shell", "The user uses PowerShell 7.", 1))
        self.assertEqual(added.source.metadata["review_id"], review_id)  # forgetting it takes the review text too
        self.assertEqual(self.control.review(review_id).status, REVIEW_APPROVED)
        entry = self.control.recent_activity(limit=1)[0]
        self.assertEqual((entry.action, entry.outcome, entry.memory_id), ("review-update", "approved-as-new",
                                                                          added.memory_id))

    def test_a_secret_is_refused_and_nothing_is_stored(self):
        memory, review_id = self.proposal("The token is ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8")
        count = len(self.service.list())
        with self.assertRaises(ValueError):
            self.service.approve_review_as_new(self.control, review_id)
        self.assertEqual(len(self.service.list()), count)


if __name__ == "__main__":
    unittest.main()
