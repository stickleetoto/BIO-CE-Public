# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.demo import run_demo


class DemoIntegrationTests(unittest.TestCase):
    def test_full_demo_runs_with_expected_evidence_boundaries(self):
        output = io.StringIO()
        self.assertEqual(run_demo(output=output), 0)
        text = output.getvalue()
        self.assertIn("1. Fact search", text)
        self.assertIn("2. Revision history", text)
        self.assertIn("3. Retraction", text)
        self.assertIn("read after retraction: BLOCKED", text)
        self.assertIn("4. Source comparison", text)
        self.assertIn("5. Uncertain query", text)
        self.assertIn("ABSTAIN:", text)
        self.assertIn("not a global completeness claim", text)

    def test_sqlite_memory_survives_a_process_restart(self):
        scope = MemoryScope("restart-project", "synthetic")
        source = SourceProvenance("fixture", "fixture:restart", {"synthetic": True})
        with tempfile.TemporaryDirectory(prefix="bio-ce-restart-") as scratch:
            database = str(Path(scratch) / "restart.sqlite3")
            create_code = (
                "from bio_ce.core.models import MemoryScope, SourceProvenance; "
                "from bio_ce.storage.sqlite_store import SQLiteMemoryStore; "
                f"s=SQLiteMemoryStore({database!r}); "
                f"r=s.add(MemoryScope({scope.project!r}, {scope.namespace!r}), "
                "memory_id='mem_process_restart_01', title='Restart', "
                "content='Synthetic row survived process exit.', "
                f"source=SourceProvenance({source.source_type!r}, {source.source_ref!r}, "
                f"{dict(source.metadata)!r})); print(r.revision_id); s.close()"
            )
            created = subprocess.run(
                [sys.executable, "-c", create_code], check=True, capture_output=True,
                text=True, encoding="utf-8", env=os.environ.copy(),
            ).stdout.strip()
            read_code = (
                "import json; from bio_ce.core.models import MemoryScope; "
                "from bio_ce.storage.sqlite_store import SQLiteMemoryStore; "
                f"s=SQLiteMemoryStore({database!r}); "
                f"r=s.read(MemoryScope({scope.project!r}, {scope.namespace!r}), "
                "'mem_process_restart_01'); "
                "print(json.dumps({'revision_id': r.revision_id, 'content': r.content}, "
                "sort_keys=True)); s.close()"
            )
            recovered = subprocess.run(
                [sys.executable, "-c", read_code], check=True, capture_output=True,
                text=True, encoding="utf-8", env=os.environ.copy(),
            ).stdout.strip()
        payload = json.loads(recovered)
        self.assertEqual(payload["revision_id"], created)
        self.assertEqual(payload["content"], "Synthetic row survived process exit.")


if __name__ == "__main__":
    unittest.main()
