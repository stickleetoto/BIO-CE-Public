# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4: "Forget completely" removes a curated memory from BIO CE's files, as far as the app can.

Retracting only hides a memory; its earlier revisions stay in the file. Forgetting deletes the memory, every
revision, its search rows, the inbox items kept for it, and the text the control file kept about it (audit titles
and details, suggestion drafts, the review items that targeted it), the way a discard deletes (v0.4.2). A byte
search of the database, its log, the control file, and a backup made afterwards must not find its text. A
positive control retracts the same setup instead and finds the text still there.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from bio_ce.control_store import (
    CURATION_CLEANUP_PENDING,
    CURATION_DISCARDED,
    REVIEW_FAILED,
    REVIEW_PENDING,
    ControlStore,
    control_database_for,
)
from bio_ce.core.models import MemoryNotFoundError, MemoryScope, SourceProvenance
from bio_ce.desktop import DesktopMemoryService
from bio_ce.inbox import finish_pending_cleanups, inbox_scope, kept_scope
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.storage.backup import pair_path
from tests.integration.test_backup_pair_and_discard import file_bytes

GENERAL = MemoryScope("bio-ce-personal", "default")
INBOX = inbox_scope(GENERAL)
HOST = SourceProvenance("ai-host-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})
WHERE = {"project": GENERAL.project, "namespace": GENERAL.namespace}


def mark() -> str:
    # Short: a long random string reads as a secret token and dilutes a merge comparison.
    return f"km{uuid.uuid4().hex[:10]}"


class ForgetCompletelyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-forget-")
        self.root = Path(self.temp.name)
        self.database = self.root / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.control = ControlStore(control_database_for(self.database))

    def tearDown(self) -> None:
        self.service.close()
        self.control.close()
        self.temp.cleanup()

    @property
    def spaces(self):
        return (*self.control.spaces(), PERSONAL_SPACE)

    def curation(self):
        return self.service.curation(self.control, self.spaces)

    def host_saves(self, title: str, content: str, recorded: str = "2026-11-10T10:00:00Z") -> str:
        revision = self.service._store.add(INBOX, title=title, content=content, source=HOST, recorded_at=recorded)
        self.control.inbox_seen(revision.memory_id)
        return revision.memory_id

    def kept(self) -> list[str]:
        return [r.memory_id for r in self.service._store.list_current(kept_scope(INBOX), limit=100)]

    def files(self) -> list[Path]:
        backup = self.service.create_backup(self.root / f"after-{uuid.uuid4().hex[:6]}.sqlite3")
        return [self.database, control_database_for(self.database), backup, pair_path(backup)]

    def assert_gone(self, *needles: str) -> None:
        for path in self.files():
            data = file_bytes(path)
            for needle in needles:
                self.assertNotIn(needle.encode("utf-8"), data, f"{needle} is still in {path.name}")

    def build(self) -> tuple:
        """A memory whose text (``said``) is in two revisions, kept inbox items (an approved suggestion and a move),
        the suggestion's draft, a pending review that targets it, and an audit title. ``moved`` is only in the inbox
        item that was moved into it."""
        said, moved, other = mark(), mark(), mark()
        self.host_saves("Tabs", f"The user prefers tabs over spaces in Go code. {said}", "2026-11-01T10:00:00Z")
        self.host_saves("Tabs", f"The user prefers tabs over spaces in Go code. {said}")
        self.curation().find()
        (keep,) = self.curation().suggestions()
        memory = self.curation().approve(keep.proposal_id, content=f"The user prefers tabs in Go code. {said}")
        item = self.host_saves("Tabs in C", f"The user also prefers tabs in C code. {moved}")
        memory = self.service.move_inbox(self.control, item, title="Tabs",
                                         content=f"The user prefers tabs in Go and C code. {said}", update=memory)
        self.assertEqual(len(self.kept()), 3)
        target = self.control.enqueue_review(
            host="codex", connection_id=None, kind="update", title=f"Tabs {said}",
            content=f"The user prefers tabs everywhere. {said}", review_reason="test", memory_id=memory.memory_id,
            expected_revision_id=memory.revision_id, metadata={"evidence": f"the user said {said}", **WHERE})
        untouched = self.control.enqueue_review(
            host="codex", connection_id=None, kind="create", title="Coffee",
            content=f"The user drinks coffee. {other}", review_reason="test", metadata=WHERE)
        self.control.record(host="codex", connection_id=None, action="update", outcome="queued",
                            memory_id=memory.memory_id, title=f"Tabs {said}", detail={"review_id": target})
        return memory, said, moved, other, target, untouched

    def test_forgetting_leaves_no_text_in_the_files_or_a_later_backup(self):
        memory, said, moved, other, target, untouched = self.build()
        self.assertIn(said.encode(), file_bytes(control_database_for(self.database)))  # positive control
        result = self.service.forget(self.service.read(memory.memory_id), control=self.control)
        self.assertTrue(result.completed)
        self.assertEqual((result.deleted, result.kept, result.reviews), (1, 3, 1))
        self.assertEqual(self.kept(), [])
        self.assertNotIn(memory.memory_id, [row[0] for row in self.service._store.inventory()])
        with self.assertRaises(MemoryNotFoundError):
            self.service.read(memory.memory_id)
        self.assertEqual(Path(f"{self.database}-wal").stat().st_size, 0)
        self.assert_gone(said, moved)
        self.assertIn(other.encode(), file_bytes(control_database_for(self.database)))  # another review stays
        entry = self.control.recent_activity(limit=1)[0]
        self.assertEqual((entry.action, entry.outcome, entry.title, entry.memory_id),
                         ("forget", "forgotten", None, None))
        self.assertEqual((entry.detail["count"], entry.detail["kept"], entry.detail["reviews"]), (1, 3, 1))
        self.assertEqual(self.control.curation_items(statuses=(CURATION_DISCARDED,))[-1]["memory_ids"],
                         [memory.memory_id])

    def test_control_case_retracting_the_same_memory_leaves_its_text(self):
        """Positive control: retraction hides the memory, and the byte search still finds its earlier revisions."""
        memory, said, moved, _other, _target, _untouched = self.build()
        self.service.retract(self.service.read(memory.memory_id), control=self.control)
        self.service._store.checkpoint()
        self.assertIn(said.encode(), file_bytes(self.database))
        self.assertIn(said.encode(), file_bytes(control_database_for(self.database)))  # the review still has it

    def test_a_retracted_memory_can_be_forgotten_and_leaves_no_text(self):
        """Owner decision 2026-11-16: a memory retracted earlier is forgotten the same way, from its listing."""
        memory, said, moved, other, target, _untouched = self.build()
        self.service.retract(self.service.read(memory.memory_id), control=self.control)
        self.service._store.checkpoint()
        self.assertIn(said.encode(), file_bytes(self.database))  # positive control: retraction kept the text
        (listed,) = self.service.retracted()
        self.assertEqual(listed.last.memory_id, memory.memory_id)
        self.assertIn(said, listed.last.content)
        self.assertEqual(self.service.retracted_count(), 1)
        result = self.service.forget(listed.last, control=self.control)
        self.assertTrue(result.completed)
        self.assertEqual((result.deleted, result.kept, result.reviews), (1, 0, 1))  # the retraction took the kept
        self.assertEqual((self.service.retracted(), self.service.retracted_count()), ((), 0))
        self.assertNotIn(memory.memory_id, [row[0] for row in self.service._store.inventory()])
        self.assertEqual(self.control.review(target).status, REVIEW_FAILED)
        self.assert_gone(said, moved)
        self.assertIn(other.encode(), file_bytes(control_database_for(self.database)))  # another review stays

    def test_a_memory_retracted_outside_the_app_takes_its_kept_originals_with_it(self):
        """A retraction that left the kept originals (an earlier build's, or a direct store write, as here):
        forgetting the retracted memory finds them from its last revision before the retraction."""
        memory, said, moved, _other, _target, _untouched = self.build()
        current = self.service.read(memory.memory_id)
        self.service._store.retract(GENERAL, memory.memory_id, expected_revision_id=current.revision_id,
                                    source=SourceProvenance("ai-host-retraction", "codex:test"))
        self.assertEqual(len(self.kept()), 3)
        self.service._store.checkpoint()
        self.assertIn(moved.encode(), file_bytes(self.database))  # positive control: the kept item has it
        (listed,) = self.service.retracted()
        result = self.service.forget(listed.last, control=self.control)
        self.assertEqual((result.deleted, result.kept, result.completed), (1, 3, True))
        self.assertEqual(self.kept(), [])
        self.assert_gone(said, moved)

    def test_retracted_memories_are_listed_only_for_forgetting(self):
        live = self.service.add(title="Shell", content="The user uses PowerShell.", source_ref="test")
        hidden = self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        self.service.retract(hidden, control=self.control)
        store = self.service._store
        self.assertEqual([r.last.memory_id for r in self.service.retracted()], [hidden.memory_id])
        self.assertEqual(self.service.retracted()[0].last.content, "The user edits in helix.")
        self.assertEqual([r.memory_id for r in store.list_current(GENERAL)], [live.memory_id])
        self.assertEqual([hit.memory_id for hit in store.search(GENERAL, "helix")], [])  # still hidden from search
        with self.assertRaises(MemoryNotFoundError):
            store.retracted_history(GENERAL, live.memory_id)  # only retracted memories
        self.assertEqual([r.kind.value for r in store.retracted_history(GENERAL, hidden.memory_id)],
                         ["assertion", "retraction"])
        before = store.inventory()
        with self.assertRaises(MemoryNotFoundError):
            self.service.forget(replace(live, memory_id=f"mem_{uuid.uuid4().hex}"), control=self.control)
        self.assertEqual(store.inventory(), before)  # a missing memory changes nothing
        self.assertEqual(store.count_retracted(inbox_scope(GENERAL)), 0)

    def test_reviews_that_target_the_memory_fail_with_blank_text_and_others_stay(self):
        memory, said, _moved, other, target, untouched = self.build()
        self.service.forget(self.service.read(memory.memory_id), control=self.control)
        closed = self.control.review(target)
        self.assertEqual((closed.status, closed.title, closed.content), (REVIEW_FAILED, "", None))
        self.assertEqual(closed.resolution, "the memory was forgotten")
        self.assertNotIn(said, str(dict(closed.metadata)))
        self.assertEqual(dict(closed.metadata), WHERE)  # the space stays, for the record
        kept = self.control.review(untouched)
        self.assertEqual((kept.status, kept.title, kept.content), (REVIEW_PENDING, "Coffee",
                                                                   f"The user drinks coffee. {other}"))

    def test_a_memory_made_from_an_approved_review_takes_that_review_text_with_it(self):
        said = mark()
        review_id = self.control.enqueue_review(
            host="codex", connection_id=None, kind="create", title=f"Editor {said}",
            content=f"The user edits in helix. {said}", review_reason="test", metadata=WHERE)
        self.control.record(host="codex", connection_id=None, action="create", outcome="queued",
                            title=f"Editor {said}", detail={"review_id": review_id, "reason": f"said {said}"})
        memory = self.service.approve_review(self.control, review_id)
        self.assertIn(said.encode(), file_bytes(control_database_for(self.database)))  # positive control
        result = self.service.forget(memory, control=self.control)
        self.assertEqual(result.reviews, 1)
        approved = self.control.review(review_id)
        self.assertEqual((approved.status, approved.title, approved.content), ("approved", "", None))
        self.assert_gone(said)

    def test_a_reader_holding_a_snapshot_delays_completion_until_it_lets_go(self):
        said = mark()
        memory = self.service.add(title=f"Editor {said}", content=f"The user edits in helix. {said}",
                                  source_ref="test")
        memory = self.service.revise(memory, title="Editor", content=f"The user edits in helix, dark. {said}",
                                     source_ref="test")
        reader = sqlite3.connect(self.database, isolation_level=None)
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM memories").fetchone()
        try:
            result = self.service.forget(memory, control=self.control)
            self.assertFalse(result.completed)
            self.assertEqual(len(self.control.curation_items(statuses=(CURATION_CLEANUP_PENDING,))), 1)
            self.assertEqual(self.control.recent_activity(limit=1)[0].outcome, "cleanup-pending")
            self.assertEqual(finish_pending_cleanups(self.service._store, self.control), 0)
        finally:
            reader.execute("COMMIT")
            reader.close()
        self.assertEqual(finish_pending_cleanups(self.service._store, self.control), 1)
        self.assertEqual(self.control.curation_items(statuses=(CURATION_CLEANUP_PENDING,)), ())
        self.service.close()
        self.control.close()
        self.assertNotIn(said.encode(), file_bytes(self.database))
        self.assertNotIn(said.encode(), file_bytes(control_database_for(self.database)))
        self.service = DesktopMemoryService(self.database)
        self.control = ControlStore(control_database_for(self.database))

    def test_an_interrupted_forget_is_carried_out_on_retry(self):
        said = mark()
        memory = self.service.add(title="Editor", content=f"The user edits in helix. {said}", source_ref="test")
        stays = self.service.add(title="Shell", content="The user uses PowerShell.", source_ref="test")
        self.control.open_discard([memory.memory_id])  # the app stopped before the erase ran
        self.assertEqual(finish_pending_cleanups(self.service._store, self.control), 1)
        self.assertEqual([row[0] for row in self.service._store.inventory()], [stays.memory_id])
        self.service.close()
        self.assertNotIn(said.encode(), file_bytes(self.database))
        self.service = DesktopMemoryService(self.database)

    def test_the_store_keeps_its_two_delete_paths_apart(self):
        """purge() still refuses curated memories; erase() is the curated path and refuses inbox items."""
        memory = self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        item = self.host_saves("Ramen", "The user likes miso ramen.")
        store = self.service._store
        with self.assertRaises(PermissionError):
            store.purge(GENERAL, [memory.memory_id])
        with self.assertRaises(PermissionError):
            store.erase(INBOX, [item])
        with self.assertRaises(PermissionError):
            store.erase(kept_scope(INBOX), [item])
        self.assertEqual(store.erase(GENERAL, [item]).deleted, 0)  # a curated scope can't reach an inbox item
        result = store.erase(GENERAL, [memory.memory_id])
        self.assertEqual((result.deleted, result.checkpointed), (1, True))

    def test_no_text_is_needed_in_the_audit_entry(self):
        """The forget entry keeps counts only, and the earlier entries about the memory lose their titles."""
        said = mark()
        memory = self.service.add(title=f"Editor {said}", content="The user edits in helix.", source_ref="test")
        self.control.record(host="bio-ce-desktop", connection_id=None, action="add", outcome="created",
                            memory_id=memory.memory_id, title=f"Editor {said}", detail={"note": said})
        self.service.forget(memory, control=self.control)
        for entry in self.control.recent_activity(limit=10):
            self.assertNotIn(said, f"{entry.title} {dict(entry.detail)}")
        with closing(sqlite3.connect(control_database_for(self.database))) as raw:
            self.assertEqual(raw.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'forget'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
