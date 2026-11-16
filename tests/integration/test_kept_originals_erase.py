# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Kept originals go with the memory they were kept for (owner request, 2026-11-16).

Approving a suggestion, or moving an inbox item to the memories, keeps the inbox items it used aside so it can be
undone. When the user deletes the result (Discard for an inbox item, Retract for a memory) or undoes the import
the items came from, those kept items are deleted the way a discard deletes (v0.4.2): secure_delete, the search
index merged, the log folded and emptied. A byte search of the database, its log, the control file, and a backup
made afterwards must not find their text. Each test first finds the text there (positive control).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import uuid

from bio_ce.control_store import ControlStore, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.desktop import DesktopMemoryService
from bio_ce.importer import parse_text
from bio_ce.inbox import inbox_scope, kept_scope
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.storage.backup import pair_path
from tests.integration.test_backup_pair_and_discard import file_bytes

GENERAL = MemoryScope("bio-ce-personal", "default")
INBOX = inbox_scope(GENERAL)
HOST = SourceProvenance("ai-host-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})


def mark() -> str:
    # Short: a long random string reads as a secret token (an import blocks it) and dilutes a merge comparison.
    return f"km{uuid.uuid4().hex[:10]}"


class KeptOriginalsEraseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-kept-erase-")
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

    def assert_found(self, needle: str) -> None:
        self.assertIn(needle.encode("utf-8"), file_bytes(self.database), "positive control: the text is there")

    def assert_gone(self, *needles: str) -> None:
        for path in self.files():
            data = file_bytes(path)
            for needle in needles:
                self.assertNotIn(needle.encode("utf-8"), data, f"{needle} is still in {path.name}")

    def test_discarding_a_merged_item_deletes_the_items_kept_for_it(self):
        older, newer = mark(), mark()
        self.host_saves("Deploys", f"The team deploys on Fridays. Releases need a tag. {older}",
                        "2026-11-09T10:00:00Z")
        self.host_saves("Deploys", f"The team deploys on Fridays. {newer}")
        self.curation().find()
        (merge,) = self.curation().suggestions()
        merged = self.curation().approve(merge.proposal_id, content=f"The team deploys on Fridays. {newer}")
        self.assertEqual(len(self.kept()), 1)
        self.assert_found(older)
        self.service.discard_inbox(self.control, [merged.memory_id])
        self.assertEqual(self.kept(), [])
        self.assert_gone(older, newer)

    def test_retracting_a_kept_memory_deletes_the_items_kept_for_it(self):
        said = mark()
        self.host_saves("Tabs", f"The user prefers tabs over spaces in Go code. {said}", "2026-11-01T10:00:00Z")
        self.host_saves("Tabs", f"The user prefers tabs over spaces in Go code. {said}")
        self.curation().find()
        (keep,) = self.curation().suggestions()
        memory = self.curation().approve(keep.proposal_id, content="The user prefers tabs in Go code.")
        self.assertEqual(len(self.kept()), 2)
        self.assert_found(said)
        self.service.retract(self.service.read(memory.memory_id))
        self.assertEqual(self.kept(), [])
        self.assert_gone(said)

    def test_retracting_a_moved_inbox_item_deletes_the_kept_inbox_copy(self):
        said = mark()
        item = self.host_saves("Ramen", f"The user likes miso ramen. {said}")
        memory = self.service.move_inbox(self.control, item, title="Ramen", content="The user likes miso ramen.")
        self.assertEqual(self.kept(), [item])  # the inbox copy is kept, not deleted
        self.assert_found(said)
        self.service.retract(self.service.read(memory.memory_id))
        self.assertEqual(self.kept(), [])
        self.assert_gone(said)

    def test_undoing_an_import_deletes_its_items_that_were_kept_aside(self):
        first, second = mark(), mark()
        planner = self.service.import_planner(self.spaces, size_limit=2000)
        preview = planner.preview(parse_text(f"[2025-02-01] - The team deploys on Fridays. {first}\n"
                                             f"[2025-02-02] - The team deploys on Fridays always. {second}"),
                                  source="chatgpt", destination="general")
        batch = self.service.import_service(self.control, self.spaces).commit(preview)
        self.curation().find()
        (merge,) = self.curation().suggestions()
        self.curation().approve(merge.proposal_id)
        self.assertEqual(len(self.kept()), 1)
        self.service.import_service(self.control, self.spaces).undo(batch.batch_id)
        self.assertEqual(self.kept(), [])
        self.assertEqual(self.service.inbox(), ())
        self.assert_gone(first, second)

    def test_a_discarded_item_leaves_no_text_in_the_suggestions_that_used_it(self):
        """Found 2026-11-16: a suggestion's draft (control file) kept the text of items discarded later."""
        first, second = mark(), mark()
        a = self.host_saves("Deploys", f"The team deploys on Fridays. Releases need a tag. {first}",
                            "2026-11-09T10:00:00Z")
        b = self.host_saves("Deploys", f"The team deploys on Fridays. {second}")
        self.curation().find()
        self.assertEqual(len(self.curation().suggestions()), 1)
        self.assertIn(first.encode(), file_bytes(control_database_for(self.database)))  # positive control
        self.service.discard_inbox(self.control, [a, b])
        self.assert_gone(first, second)

    def test_a_retraction_without_kept_items_changes_nothing_else(self):
        """Positive control for the link: retracting an ordinary memory doesn't touch kept items of another."""
        said = mark()
        item = self.host_saves("Ramen", f"The user likes miso ramen. {said}")
        self.service.move_inbox(self.control, item, title="Ramen", content="The user likes miso ramen.")
        other = self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        self.service.retract(other)
        self.assertEqual(self.kept(), [item])
        self.assert_found(said)


if __name__ == "__main__":
    unittest.main()
