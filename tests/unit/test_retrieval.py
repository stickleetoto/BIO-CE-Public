# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

import tempfile
import unittest
from pathlib import Path

from bio_ce.core.models import MemoryScope, SourceProvenance, ValidationError
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteMemoryStore(Path(self.temp.name) / "search.sqlite3")
        self.scope = MemoryScope("retrieval-project", "default")
        self.other = MemoryScope("retrieval-project", "secret")
        self.source_a = SourceProvenance("fixture", "fixture:alpha")
        self.source_b = SourceProvenance("fixture", "fixture:beta")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_search_is_repeatable_scoped_and_reports_provenance(self):
        first = self.store.add(
            self.scope, memory_id="mem_retrieval_alpha_01", title="Quartz calendar",
            content="Quartz release is scheduled for August.", source=self.source_a,
        )
        self.store.add(
            self.scope, memory_id="mem_retrieval_beta_001", title="Quartz calendar",
            content="Quartz release is scheduled for September.", source=self.source_b,
        )
        self.store.add(
            self.other, memory_id="mem_retrieval_other_01", title="Quartz secret",
            content="Quartz release is scheduled for October.", source=self.source_a,
        )
        first_run = self.store.search(self.scope, "Quartz release scheduled", limit=10)
        second_run = self.store.search(self.scope, "Quartz release scheduled", limit=10)
        self.assertEqual(first_run, second_run)
        self.assertEqual(len(first_run), 2)
        self.assertEqual([hit.rank for hit in first_run], [1, 2])
        self.assertTrue(all(hit.score >= 0 for hit in first_run))
        self.assertEqual({hit.source.source_ref for hit in first_run}, {"fixture:alpha", "fixture:beta"})
        self.assertNotIn("mem_retrieval_other_01", {hit.memory_id for hit in first_run})
        self.assertEqual(first_run[0].revision_id, first.revision_id)

    def test_valid_time_is_an_explicit_interval_filter(self):
        self.store.add(
            self.scope, memory_id="mem_valid_window_01", title="Temporary window",
            content="Orchid access is open during the spring window.", source=self.source_a,
            valid_from="2026-03-01T00:00:00Z", valid_until="2026-06-01T00:00:00Z",
        )
        self.assertEqual(len(self.store.search(self.scope, "Orchid access", valid_at="2026-04-01T00:00:00Z")), 1)
        self.assertEqual(self.store.search(self.scope, "Orchid access", valid_at="2026-06-01T00:00:00Z"), ())

    def test_bad_limits_and_naive_timestamps_fail_closed(self):
        with self.assertRaises(ValidationError):
            self.store.search(self.scope, "x", limit=0)
        with self.assertRaises(ValidationError):
            self.store.search(self.scope, "x", valid_at="2026-04-01T00:00:00")


if __name__ == "__main__":
    unittest.main()
