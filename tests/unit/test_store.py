# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

from pathlib import Path
import tempfile
import threading
import unittest

from bio_ce.core.models import (
    MemoryNotFoundError,
    MemoryScope,
    RevisionConflictError,
    RevisionKind,
    SnapshotChangedError,
    SourceProvenance,
    ValidationError,
)
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "memories.sqlite3"
        self.scope = MemoryScope("project-a", "namespace-a")
        self.source = SourceProvenance("fixture", "fixture:test", {"synthetic": True})
        self.store = SQLiteMemoryStore(self.db)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_revision_chain_and_stale_write_check(self):
        first = self.store.add(
            self.scope, memory_id="mem_test_revision_01", title="Launch date",
            content="Launch is planned for May.", source=self.source,
            recorded_at="2026-01-01T00:00:00Z",
        )
        second = self.store.revise(
            self.scope, first.memory_id, expected_revision_id=first.revision_id,
            title="Launch date", content="Launch is planned for June.", source=self.source,
            recorded_at="2026-01-02T00:00:00Z",
        )
        self.assertEqual(second.revision_number, 2)
        self.assertEqual(second.previous_revision_id, first.revision_id)
        self.assertEqual(self.store.read(self.scope, first.memory_id, revision_id=first.revision_id).content,
                         "Launch is planned for May.")
        self.assertEqual([r.revision_number for r in self.store.history(self.scope, first.memory_id)], [1, 2])
        with self.assertRaises(RevisionConflictError):
            self.store.revise(
                self.scope, first.memory_id, expected_revision_id=first.revision_id,
                title="Stale", content="Must not win.", source=self.source,
            )

    def test_scope_is_exact(self):
        created = self.store.add(
            self.scope, memory_id="mem_test_scope_0001", title="Private to scope",
            content="A scoped synthetic fact.", source=self.source,
        )
        with self.assertRaises(MemoryNotFoundError):
            self.store.read(MemoryScope("project-a", "other-namespace"), created.memory_id)
        with self.assertRaises(MemoryNotFoundError):
            self.store.read(MemoryScope("other-project", "namespace-a"), created.memory_id)
        self.assertEqual(
            self.store.search(MemoryScope("project-a", "other-namespace"), "scoped synthetic"),
            (),
        )
        with self.assertRaises(ValidationError):
            self.store.read(self.scope, "not-a-memory-id")

    def test_retraction_blocks_current_and_historical_reads(self):
        created = self.store.add(
            self.scope, memory_id="mem_test_retract_001", title="Retired",
            content="This synthetic fact is withdrawn.", source=self.source,
        )
        retracted = self.store.retract(
            self.scope, created.memory_id, expected_revision_id=created.revision_id, source=self.source,
        )
        self.assertEqual(retracted.kind, RevisionKind.RETRACTION)
        self.assertIsNone(retracted.content)
        self.assertEqual(self.store.search(self.scope, "synthetic fact withdrawn"), ())
        with self.assertRaises(MemoryNotFoundError):
            self.store.read(self.scope, created.memory_id)
        with self.assertRaises(MemoryNotFoundError):
            self.store.read(self.scope, created.memory_id, revision_id=created.revision_id)
        with self.assertRaises(MemoryNotFoundError):
            self.store.history(self.scope, created.memory_id)

    def test_read_only_connection_rejects_store_writes(self):
        created = self.store.add(
            self.scope, memory_id="mem_test_readonly_01", title="Read only",
            content="A read-only connection can inspect this.", source=self.source,
        )
        reader = SQLiteMemoryStore(self.db, read_only=True)
        try:
            self.assertEqual(reader.read(self.scope, created.memory_id).revision_id, created.revision_id)
            with self.assertRaises(PermissionError):
                reader.add(
                    self.scope, memory_id="mem_test_readonly_02", title="Denied",
                    content="This write must fail.", source=self.source,
                )
        finally:
            reader.close()

    def test_batch_read_fails_closed_when_retraction_commits_after_snapshot(self):
        first = self.store.add(
            self.scope, memory_id="mem_test_batchrev_01", title="First snapshot row",
            content="Synthetic row selected before retraction.", source=self.source,
        )
        second = self.store.add(
            self.scope, memory_id="mem_test_batchrev_02", title="Second snapshot row",
            content="Second synthetic row in the batch.", source=self.source,
        )
        selected = threading.Event()
        resume = threading.Event()

        class PausingReadStore(SQLiteMemoryStore):
            def _current_row(inner_self, scope, memory_id):
                row = super(PausingReadStore, inner_self)._current_row(scope, memory_id)
                if memory_id == first.memory_id and not selected.is_set():
                    selected.set()
                    if not resume.wait(5):
                        raise TimeoutError("test synchronization timed out")
                return row

        reader = PausingReadStore(self.db, read_only=True)
        result = []
        failure = []

        def run_batch():
            try:
                result.extend(reader.read_many(self.scope, [first.memory_id, second.memory_id]))
            except Exception as exc:  # surfaced in the test thread
                failure.append(exc)

        thread = threading.Thread(target=run_batch)
        thread.start()
        try:
            self.assertTrue(selected.wait(5), "batch did not reach its first SELECT")
            retracted = self.store.retract(
                self.scope, first.memory_id, expected_revision_id=first.revision_id,
                source=self.source,
            )
            self.assertEqual(retracted.kind, RevisionKind.RETRACTION)
        finally:
            resume.set()
            thread.join(5)
            reader.close()

        self.assertFalse(thread.is_alive(), "batch reader did not finish")
        self.assertEqual(result, [])
        self.assertEqual(len(failure), 1)
        self.assertIsInstance(failure[0], SnapshotChangedError)
        with self.assertRaises(MemoryNotFoundError):
            self.store.read(self.scope, first.memory_id)
        with self.assertRaises(MemoryNotFoundError):
            self.store.read_many(self.scope, [first.memory_id])

    def test_current_read_fails_closed_when_revision_changes_after_snapshot(self):
        created = self.store.add(
            self.scope, memory_id="mem_test_readrace_01", title="Concurrent revision",
            content="The old synthetic revision must not escape after a concurrent update.",
            source=self.source,
        )
        selected = threading.Event()
        resume = threading.Event()

        class PausingReadStore(SQLiteMemoryStore):
            def _current_row(inner_self, scope, memory_id):
                row = super(PausingReadStore, inner_self)._current_row(scope, memory_id)
                if memory_id == created.memory_id and not selected.is_set():
                    selected.set()
                    if not resume.wait(5):
                        raise TimeoutError("test synchronization timed out")
                return row

        reader = PausingReadStore(self.db, read_only=True)
        result = []
        failure = []

        def run_read():
            try:
                result.append(reader.read(self.scope, created.memory_id))
            except Exception as exc:
                failure.append(exc)

        thread = threading.Thread(target=run_read)
        thread.start()
        try:
            self.assertTrue(selected.wait(5), "read did not reach its snapshot SELECT")
            revised = self.store.revise(
                self.scope,
                created.memory_id,
                expected_revision_id=created.revision_id,
                title="Concurrent revision",
                content="The new synthetic revision is current.",
                source=self.source,
            )
        finally:
            resume.set()
            thread.join(5)
            reader.close()

        self.assertFalse(thread.is_alive(), "reader did not finish")
        self.assertEqual(result, [])
        self.assertEqual(len(failure), 1)
        self.assertIsInstance(failure[0], SnapshotChangedError)
        self.assertEqual(self.store.read(self.scope, created.memory_id).revision_id, revised.revision_id)

    def test_read_linearized_before_retraction_may_finish_after_commit(self):
        created = self.store.add(
            self.scope, memory_id="mem_test_inflight_retract_01", title="In-flight read",
            content="Synthetic content selected before the later retraction.", source=self.source,
        )
        validated = threading.Event()
        resume = threading.Event()

        class PausingValidationStore(SQLiteMemoryStore):
            def _verify_active_snapshot(inner_self, scope, expected_revisions):
                super(PausingValidationStore, inner_self)._verify_active_snapshot(
                    scope, expected_revisions
                )
                validated.set()
                if not resume.wait(5):
                    raise TimeoutError("test synchronization timed out")

        reader = PausingValidationStore(self.db, read_only=True)
        result = []
        failure = []

        def run_read():
            try:
                result.append(reader.read(self.scope, created.memory_id))
            except Exception as exc:
                failure.append(exc)

        thread = threading.Thread(target=run_read)
        thread.start()
        try:
            self.assertTrue(validated.wait(5), "read did not pass final freshness validation")
            retracted = self.store.retract(
                self.scope, created.memory_id, expected_revision_id=created.revision_id,
                source=self.source,
            )
        finally:
            resume.set()
            thread.join(5)
            reader.close()

        self.assertFalse(thread.is_alive(), "reader did not finish")
        self.assertEqual(failure, [])
        self.assertEqual(retracted.kind, RevisionKind.RETRACTION)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content, created.content)
        with self.assertRaises(MemoryNotFoundError):
            self.store.read(self.scope, created.memory_id)

    def test_search_fails_closed_when_retraction_commits_before_final_validation(self):
        created = self.store.add(
            self.scope, memory_id="mem_test_searchrace_01", title="Search snapshot",
            content="searchwithdrawalanchor appears in this synthetic content.", source=self.source,
        )
        selected = threading.Event()
        resume = threading.Event()

        class PausingValidationStore(SQLiteMemoryStore):
            def _verify_active_snapshot(inner_self, scope, expected_revisions):
                selected.set()
                if not resume.wait(5):
                    raise TimeoutError("test synchronization timed out")
                return super(PausingValidationStore, inner_self)._verify_active_snapshot(
                    scope, expected_revisions
                )

        reader = PausingValidationStore(self.db, read_only=True)
        result = []
        failure = []

        # Search through the pausing store so the barrier is exactly between
        # its FTS snapshot and the final freshness validation.
        def run_paused_search():
            try:
                result.extend(reader.search(self.scope, "searchwithdrawalanchor"))
            except Exception as exc:
                failure.append(exc)

        thread = threading.Thread(target=run_paused_search)
        thread.start()
        try:
            self.assertTrue(selected.wait(5), "search did not reach final validation")
            self.store.retract(
                self.scope, created.memory_id, expected_revision_id=created.revision_id,
                source=self.source,
            )
        finally:
            resume.set()
            thread.join(5)
            reader.close()

        self.assertFalse(thread.is_alive(), "search reader did not finish")
        self.assertEqual(result, [])
        self.assertEqual(len(failure), 1)
        self.assertIsInstance(failure[0], SnapshotChangedError)

    def test_history_fails_closed_when_retraction_commits_before_final_validation(self):
        created = self.store.add(
            self.scope, memory_id="mem_test_historyrace_01", title="History snapshot",
            content="historywithdrawalanchor is synthetic historical content.", source=self.source,
        )
        selected = threading.Event()
        resume = threading.Event()

        class PausingValidationStore(SQLiteMemoryStore):
            def _verify_active_snapshot(inner_self, scope, expected_revisions):
                selected.set()
                if not resume.wait(5):
                    raise TimeoutError("test synchronization timed out")
                return super(PausingValidationStore, inner_self)._verify_active_snapshot(
                    scope, expected_revisions
                )

        reader = PausingValidationStore(self.db, read_only=True)
        result = []
        failure = []

        def run_history():
            try:
                result.extend(reader.history(self.scope, created.memory_id))
            except Exception as exc:
                failure.append(exc)

        thread = threading.Thread(target=run_history)
        thread.start()
        try:
            self.assertTrue(selected.wait(5), "history did not reach final validation")
            self.store.retract(
                self.scope, created.memory_id, expected_revision_id=created.revision_id,
                source=self.source,
            )
        finally:
            resume.set()
            thread.join(5)
            reader.close()

        self.assertFalse(thread.is_alive(), "history reader did not finish")
        self.assertEqual(result, [])
        self.assertEqual(len(failure), 1)
        self.assertIsInstance(failure[0], SnapshotChangedError)

    def test_source_metadata_must_be_finite_json(self):
        with self.assertRaises(ValidationError):
            SourceProvenance("fixture", "fixture:bad", {"not-finite": float("nan")})

    def test_restart_reopens_persisted_synthetic_memory(self):
        created = self.store.add(
            self.scope, memory_id="mem_test_restart_01", title="Restart check",
            content="Recovered from the local SQLite file.", source=self.source,
        )
        self.store.close()
        self.store = SQLiteMemoryStore(self.db)
        recovered = self.store.read(self.scope, created.memory_id)
        self.assertEqual(recovered.revision_id, created.revision_id)
        self.assertEqual(recovered.content, "Recovered from the local SQLite file.")

    def test_retraction_remains_blocked_after_store_restart(self):
        created = self.store.add(
            self.scope, memory_id="mem_test_restart_retract_01", title="Restart retraction",
            content="restartretractedanchor must remain unavailable.", source=self.source,
        )
        self.store.retract(
            self.scope, created.memory_id, expected_revision_id=created.revision_id,
            source=self.source,
        )
        self.store.close()
        self.store = SQLiteMemoryStore(self.db)

        with self.assertRaises(MemoryNotFoundError):
            self.store.read(self.scope, created.memory_id)
        self.assertEqual(self.store.search(self.scope, "restartretractedanchor"), ())


if __name__ == "__main__":
    unittest.main()
