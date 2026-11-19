# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""rc4 (owner decision 2026-11-19): a kept inbox original that a memory staying in BIO CE still names is never
discarded with another memory.

Found by the night random-operation run (2026-11-19, seed 11): an Undo of "To memories" retracts memory M1 and
gives item A back, but M1's last revision still lists A as kept. A is then used again for memory M2. Forget
completely on the retracted M1 erased A, so the Undo of the second move gave M2 its earlier text back and A's
text was gone. Every path that discards kept items (forget, delete, a discarded inbox item, an approved delete
request, undoing an import) now leaves an item another memory still keeps; each test below also checks that the
item still goes once nothing names it (positive control).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import uuid

from bio_ce.control_store import ControlStore, control_database_for
from bio_ce.core.models import MemoryNotFoundError, SourceProvenance
from bio_ce.desktop import DesktopMemoryService
from bio_ce.importer import parse_text
from bio_ce.inbox import inbox_scope, kept_scope, still_kept_for_others
from bio_ce.spaces import PERSONAL_SPACE
from tests.integration.test_backup_pair_and_discard import file_bytes

HOST = SourceProvenance("ai-host-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})


def mark() -> str:
    return f"kr{uuid.uuid4().hex[:10]}"


class KeptStillReferencedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-kept-ref-")
        self.database = Path(self.temp.name) / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.store = self.service._store
        self.control = ControlStore(control_database_for(self.database))
        self.general = self.control.spaces()[0]
        self.service.use_space(self.general.curated)

    def tearDown(self) -> None:
        self.service.close()
        self.control.close()
        self.temp.cleanup()

    @property
    def aside(self):
        return kept_scope(self.general.inbox)

    def host_saves(self, title: str, content: str) -> str:
        revision = self.store.add(self.general.inbox, title=title, content=content, source=HOST)
        self.control.inbox_seen(revision.memory_id)
        return revision.memory_id

    def reused_item(self, said: str):
        """A made into M1, the move undone (M1 retracted, still listing A), then A used to update M2."""
        item = self.host_saves("Ramen", f"The user likes miso ramen with extra corn. {said}")
        first = self.service.move_inbox(self.control, item, title="Ramen",
                                        content=f"The user likes miso ramen with extra corn. {said}")
        self.service.undo_move_inbox(self.control, item, first)
        other = self.service.add(title="Food", content="The user likes noodles.", source_ref="test")
        second = self.service.move_inbox(self.control, item, title="Food",
                                         content=f"The user likes miso ramen with extra corn. {said}", update=other)
        (retracted,) = [r.last for r in self.service.retracted() if r.last.memory_id == first.memory_id]
        return item, retracted, second

    def test_forgetting_a_retracted_memory_keeps_what_another_memory_kept(self):
        said = mark()
        item, retracted, second = self.reused_item(said)
        self.assertEqual(self.service.kept_count(second.memory_id), 1)  # M2 keeps A
        result = self.service.forget(retracted, control=self.control)
        self.assertEqual(result.kept, 0, "A is kept for M2, so it does not go with M1")
        self.assertTrue(result.completed)
        with self.assertRaises(MemoryNotFoundError):
            self.store.read(self.general.curated, retracted.memory_id)  # M1 itself is forgotten
        self.assertEqual(self.store.read(self.aside, item).content,
                         f"The user likes miso ramen with extra corn. {said}")
        # The Undo of the second move gives M2 its earlier text and A back to the inbox, unchanged.
        undone = self.service.undo_move_inbox(self.control, item, second)
        self.assertEqual(undone.content, "The user likes noodles.")
        self.assertEqual(self.service.read_inbox(item).content, f"The user likes miso ramen with extra corn. {said}")

    def test_the_kept_item_goes_when_the_memory_still_keeping_it_is_forgotten(self):
        """Positive control: once M2 goes too, nothing names A, and A is erased with M2 (byte search)."""
        said = mark()
        item, retracted, second = self.reused_item(said)
        self.service.forget(retracted, control=self.control)
        self.assertTrue(said.encode() in file_bytes(self.database), "positive control: the text is there")
        result = self.service.forget(self.service.read(second.memory_id), control=self.control)
        self.assertEqual(result.kept, 1)
        with self.assertRaises(MemoryNotFoundError):
            self.store.read(self.aside, item)
        for path in (self.database, control_database_for(self.database)):
            self.assertFalse(said.encode() in file_bytes(path), f"{said} is still in {path.name}")

    def test_deleting_the_memory_that_keeps_it_still_discards_it(self):
        """Positive control for the delete path: M2 deleted (retracted) takes A with it even though M1 named it."""
        said = mark()
        item, _retracted, second = self.reused_item(said)
        self.service.retract(self.service.read(second.memory_id), control=self.control)
        with self.assertRaises(MemoryNotFoundError):  # its text stays only in the retracted memories' History
            self.store.read(self.aside, item)

    def test_undoing_an_import_keeps_an_item_a_memory_still_keeps(self):
        said = mark()
        spaces = (*self.control.spaces(), PERSONAL_SPACE)
        planner = self.service.import_planner(spaces, size_limit=2000)
        preview = planner.preview(parse_text(f"[2025-02-01] - The team deploys on Fridays. {said}"),
                                  source="chatgpt", destination="general")
        imports = self.service.import_service(self.control, spaces)
        batch = imports.commit(preview)
        (item,) = [revision.memory_id for revision in self.service.inbox()]
        other = self.service.add(title="Deploys", content="The team deploys weekly.", source_ref="test")
        moved = self.service.move_inbox(self.control, item, title="Deploys",
                                        content=f"The team deploys on Fridays. {said}", update=other)
        imports.undo(batch.batch_id)
        # The memory is "already sorted" and stays; the item it keeps stays with it, so its Undo still works.
        self.assertEqual(self.store.read(self.aside, item).content, f"The team deploys on Fridays. {said}")
        self.service.undo_move_inbox(self.control, item, moved)
        self.assertEqual(self.service.read(other.memory_id).content, "The team deploys weekly.")
        self.assertEqual(self.service.read_inbox(item).content, f"The team deploys on Fridays. {said}")

    def test_an_import_undo_still_removes_kept_items_nothing_names(self):
        """Positive control: an imported item merged into another imported item goes with the import's undo."""
        first, second = mark(), mark()
        spaces = (*self.control.spaces(), PERSONAL_SPACE)
        planner = self.service.import_planner(spaces, size_limit=2000)
        preview = planner.preview(parse_text(f"[2025-02-01] - The team deploys on Fridays. {first}\n"
                                             f"[2025-02-02] - The team deploys on Fridays always. {second}"),
                                  source="chatgpt", destination="general")
        imports = self.service.import_service(self.control, spaces)
        batch = imports.commit(preview)
        curation = self.service.curation(self.control, spaces)
        curation.find()
        (merge,) = curation.suggestions()
        curation.approve(merge.proposal_id)
        self.assertEqual(len(self.store.list_current(self.aside, limit=10)), 1)
        imports.undo(batch.batch_id)
        self.assertEqual(self.store.list_current(self.aside, limit=10), ())
        self.assertFalse(first.encode() in file_bytes(self.database), f"{first} is still in the database")

    def test_a_chain_of_kept_items_is_protected_through_the_memory_that_keeps_it(self):
        """M keeps B (a merged item), and B was made from A: both stay while M stays, both go with M."""
        aside = self.aside
        a = self.store.add(aside, title="A", content="first", source=HOST)
        b = self.store.add(aside, title="B", content="second",
                           source=SourceProvenance("ai-host-auto-memory", "codex:test",
                                                   {"stage": "inbox", "kept": [a.memory_id]}))
        m = self.store.add(self.general.curated, title="M", content="third",
                           source=SourceProvenance("user-entered", "bio-ce-inbox", {"kept": [b.memory_id]}))
        ids = [a.memory_id, b.memory_id]
        self.assertEqual(still_kept_for_others(self.store, ids), set(ids))
        self.assertEqual(still_kept_for_others(self.store, ids, leaving=[m.memory_id]), set())
        self.assertEqual(self.service.kept_count(m.memory_id), 2)
        self.service.retract(self.service.read(m.memory_id), control=self.control)
        self.assertEqual(self.store.list_current(aside, limit=10), ())

    def test_a_retracted_memory_names_nothing(self):
        """Only memories that stay count: a retracted one's old kept list protects nothing."""
        aside = self.aside
        a = self.store.add(aside, title="A", content="first", source=HOST)
        m = self.store.add(self.general.curated, title="M", content="third",
                           source=SourceProvenance("user-entered", "bio-ce-inbox", {"kept": [a.memory_id]}))
        self.assertEqual(still_kept_for_others(self.store, [a.memory_id]), {a.memory_id})
        self.store.retract(self.general.curated, m.memory_id, expected_revision_id=m.revision_id,
                           source=SourceProvenance("user-requested-retraction", "test"))
        self.assertEqual(still_kept_for_others(self.store, [a.memory_id]), set())


if __name__ == "__main__":
    unittest.main()
