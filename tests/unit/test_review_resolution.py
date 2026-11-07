# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""A review item is applied at most once, and only while it is still pending.

Regression for U1-D1: ``ReviewService.approve`` used to write to the memory
database before noticing that the item was already approved, rejected, or
failed. A rejected suggestion was then saved anyway and a second approval
created a duplicate memory, while the user was only told "already handled".
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bio_ce.auto_memory import ReviewService
from bio_ce.control_store import (
    ControlStore,
    ControlStoreError,
    REVIEW_APPROVED,
    REVIEW_FAILED,
    REVIEW_REJECTED,
    control_database_for,
)
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


SCOPE = MemoryScope("bio-ce-personal", "default")
FAKE_KEY = "sk-proj-" + "Zx7Qw2Er9Ty4Ui8Op3As6Df1Gh5Jk0Lz"  # synthetic, not a real credential


class ReviewResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-review-")
        database = Path(self.temp.name) / "data" / "memories.sqlite3"
        self.store = SQLiteMemoryStore(database)
        self.control = ControlStore(control_database_for(database))
        self.service = ReviewService(self.store, self.control, SCOPE)

    def tearDown(self) -> None:
        self.store.close()
        self.control.close()
        self.temp.cleanup()

    def enqueue(self, **values) -> int:
        fields = dict(host="claude", connection_id="conn_synthetic", kind="create",
                      title="Prefers dark theme", content="The user prefers a dark editor theme.",
                      review_reason="inferred")
        fields.update(values)
        return self.control.enqueue_review(**fields)

    def test_a_rejected_suggestion_is_never_saved_by_a_later_approval(self):
        review_id = self.enqueue()
        self.service.reject(review_id)
        with self.assertRaises(ControlStoreError):
            self.service.approve(review_id)
        self.assertEqual(self.store.count_current(SCOPE), 0)
        self.assertEqual(self.control.review(review_id).status, REVIEW_REJECTED)

    def test_approving_twice_creates_one_memory(self):
        review_id = self.enqueue()
        self.service.approve(review_id)
        with self.assertRaises(ControlStoreError):
            self.service.approve(review_id)
        self.assertEqual(self.store.count_current(SCOPE), 1)
        self.assertEqual(self.control.review(review_id).status, REVIEW_APPROVED)

    def test_a_failed_item_stays_failed_and_writes_nothing(self):
        review_id = self.enqueue(content=f"The deploy key is {FAKE_KEY} for staging.")
        with self.assertRaises(ValueError):
            self.service.approve(review_id)
        self.assertEqual(self.control.review(review_id).status, REVIEW_FAILED)
        with self.assertRaises(ControlStoreError):
            self.service.approve(review_id, content="The user deploys staging on Fridays.")
        self.assertEqual(self.store.count_current(SCOPE), 0)

    def test_a_handled_retraction_is_not_applied_again(self):
        memory = self.store.add(SCOPE, title="Lab server", content="The lab server is build-07.",
                                source=SourceProvenance("user-entered", "user-input"))
        review_id = self.enqueue(kind="retract", title=memory.title, content=None, memory_id=memory.memory_id,
                                 expected_revision_id=memory.revision_id)
        self.service.reject(review_id)
        with self.assertRaises(ControlStoreError):
            self.service.approve(review_id)
        self.assertEqual(self.store.read(SCOPE, memory.memory_id).revision_id, memory.revision_id)

    def test_rejecting_a_handled_item_changes_nothing_and_logs_nothing(self):
        review_id = self.enqueue()
        self.service.approve(review_id)
        before = len(self.control.recent_activity())
        with self.assertRaises(ControlStoreError):
            self.service.reject(review_id)
        self.assertEqual(self.control.review(review_id).status, REVIEW_APPROVED)
        self.assertEqual(len(self.control.recent_activity()), before)


if __name__ == "__main__":
    unittest.main()
