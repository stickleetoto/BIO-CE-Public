# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The desktop UI reaches memories only through the engine contract.

The only direct desktop-service calls allowed in ``bio_ce.ui`` are the
Community-only operations that the contract never routes to another engine
(backup, restore, review decisions) and closing the service. Each of them is
gated by a capability in the UI.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


UI = Path(__file__).resolve().parents[2] / "src" / "bio_ce" / "ui"
ALLOWED_SERVICE_CALLS = {"create_backup", "restore_backup", "approve_review", "reject_review", "close"}


class EngineBoundaryTests(unittest.TestCase):
    def test_the_ui_never_opens_a_memory_store_or_sqlite_directly(self):
        for path in UI.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("SQLiteMemoryStore", text)
                self.assertNotIn("._store", text)
                self.assertIsNone(re.search(r"^\s*import sqlite3|^\s*from sqlite3", text, re.MULTILINE))

    def test_direct_service_calls_are_only_the_community_only_operations(self):
        used: set[str] = set()
        for path in UI.rglob("*.py"):
            used |= set(re.findall(r"\.service\.(\w+)\(", path.read_text(encoding="utf-8")))
        self.assertTrue(used <= ALLOWED_SERVICE_CALLS, used - ALLOWED_SERVICE_CALLS)


if __name__ == "__main__":
    unittest.main()
