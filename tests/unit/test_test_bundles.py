# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The data-safety bundle (tests/bundles.py) can't go empty quietly: every entry still names tests that exist."""

from __future__ import annotations

from pathlib import Path
import re
import unittest

from tests.bundles import DATA_SAFETY, in_data_safety

ROOT = Path(__file__).resolve().parents[2]


class DataSafetyBundleTests(unittest.TestCase):
    def test_every_entry_matches_at_least_one_test(self):
        for relative, words in DATA_SAFETY.items():
            with self.subTest(relative):
                path = ROOT / relative
                self.assertTrue(path.is_file(), f"{relative} is gone; update tests/bundles.py")
                names = re.findall(r"^\s+def (test_\w+)", path.read_text(encoding="utf-8"), re.MULTILINE)
                matched = [name for name in names if in_data_safety(path, name)]
                self.assertTrue(matched, f"no test in {relative} matches {words}")
                if words is not None:
                    self.assertLess(len(matched), len(names), f"{relative}: list it whole (None) instead")

    def test_only_listed_tests_are_in_the_bundle(self):
        self.assertTrue(in_data_safety(ROOT / "tests/unit/test_desktop.py", "test_backup_and_restore_x"))
        self.assertFalse(in_data_safety(ROOT / "tests/unit/test_desktop.py", "test_stale_desktop_edit_is_rejected"))
        self.assertFalse(in_data_safety(ROOT / "tests/unit/test_store.py", "test_anything"))


if __name__ == "__main__":
    unittest.main()
