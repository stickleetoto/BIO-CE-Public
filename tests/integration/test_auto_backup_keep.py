# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 §7.2: BIO CE keeps only the latest N of the backups it makes by itself.

Automatic backups ("auto-<reason>-<time>.sqlite3" and their ".control.sqlite3" pair, made before a move or a
restore) are pruned right after a new one is made, whatever their reason, newest N pairs kept. A pair is removed as
a pair, each file overwritten with zeros before it is deleted. Backups the user made are never touched. Every
database here is synthetic and lives in a temporary folder.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from bio_ce.control_store import ControlStore, control_database_for
from bio_ce.desktop import DesktopMemoryService
from bio_ce.storage import backup as backup_module
from bio_ce.storage.backup import pair_path


class AutoBackupKeepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-auto-keep-")
        self.root = Path(self.temp.name)
        self.database = self.root / "data" / "memories.sqlite3"
        self.folder = self.database.parent / "backups"
        self.service = DesktopMemoryService(self.database)
        self.control = ControlStore(control_database_for(self.database))
        self.service.add(title="Backed up note", content="A synthetic memory in every backup.", source_ref="test")

    def tearDown(self) -> None:
        self.service.close()
        self.control.close()
        self.temp.cleanup()

    def automatic(self) -> list[str]:
        return sorted(p.name for p in self.folder.glob("auto-*.sqlite3") if not p.name.endswith(".control.sqlite3"))

    def make(self, count: int, reasons=("before-move", "before-restore")) -> list[Path]:
        return [self.service.automatic_backup(reasons[i % len(reasons)]) for i in range(count)]

    def test_the_setting_defaults_to_ten_and_takes_one_to_a_hundred(self):
        self.assertEqual(self.control.auto_backup_keep(), 10)
        for good in (1, 100, 25):
            self.control.set_auto_backup_keep(good)
            self.assertEqual(self.control.auto_backup_keep(), good)
        for bad in (0, 101, -3, "5", 2.5, True, None):
            with self.assertRaises(ValueError):
                self.control.set_auto_backup_keep(bad)
        self.assertEqual(self.control.auto_backup_keep(), 25)
        with closing(sqlite3.connect(self.control.path)) as raw:
            raw.execute("UPDATE app_settings SET value = 'many' WHERE key = 'auto_backup_keep'")
            raw.commit()
        self.assertEqual(self.control.auto_backup_keep(), 10)  # a damaged value falls back to the default

    def test_only_the_newest_n_pairs_remain_and_user_backups_stay(self):
        self.control.set_auto_backup_keep(3)
        mine = self.service.create_backup(self.folder / "my backup.sqlite3")
        named_like = self.service.create_backup(self.folder / "auto-mine.sqlite3")  # the user's name, not ours
        made = self.make(3 + 3)
        self.assertEqual(self.automatic(), sorted(["auto-mine.sqlite3", *(p.name for p in made[-3:])]))
        for path in made[-3:]:
            self.assertTrue(pair_path(path).is_file(), f"{path.name} lost its pair")
        for path in made[:-3]:
            self.assertFalse(path.exists())
            self.assertFalse(pair_path(path).exists(), f"{pair_path(path).name} was left alone")
        for path in (mine, named_like):  # positive control: the user's backups are still there, both files
            self.assertTrue(path.is_file() and pair_path(path).is_file(), path.name)
        leftovers = [p.name for p in self.folder.iterdir() if p.name.startswith(".bio-ce-")]
        self.assertEqual(leftovers, [])

    def test_a_changed_setting_applies_on_the_next_automatic_backup(self):
        self.control.set_auto_backup_keep(5)
        made = self.make(5)
        self.assertEqual(len(self.automatic()), 5)
        self.control.set_auto_backup_keep(2)
        self.assertEqual(len(self.automatic()), 5)  # nothing is removed until the next automatic backup
        newest = self.service.automatic_backup("before-move")
        self.assertEqual(self.automatic(), sorted([made[-1].name, newest.name]))

    def test_removed_files_are_overwritten_with_zeros_before_they_are_deleted(self):
        self.control.set_auto_backup_keep(1)
        (old,) = self.make(1)
        sizes = {old: old.stat().st_size, pair_path(old): pair_path(old).stat().st_size}
        seen: dict[Path, bytes] = {}
        real = backup_module._unlink

        def spy(path: Path) -> None:
            seen[Path(path)] = Path(path).read_bytes()
            real(path)

        with mock.patch.object(backup_module, "_unlink", side_effect=spy):
            self.make(1)
        self.assertEqual(set(seen), set(sizes))
        for path, data in seen.items():
            self.assertEqual(len(data), sizes[path])
            self.assertGreater(len(data), 0)
            self.assertEqual(data.count(0), len(data), f"{path.name} still had content when it was deleted")
        self.assertFalse(old.exists() or pair_path(old).exists())

    def test_a_file_that_cannot_be_removed_does_not_fail_the_backup(self):
        self.control.set_auto_backup_keep(1)
        (old,) = self.make(1)
        with mock.patch.object(backup_module, "_unlink", side_effect=PermissionError("in use")):
            newest = self.service.automatic_backup("before-move")
        self.assertTrue(newest.is_file() and pair_path(newest).is_file())
        self.assertTrue(old.is_file(), "the memory file stays when its pair could not be removed")
        entry = self.control.recent_activity(limit=1)[0]
        self.assertEqual((entry.action, entry.outcome, entry.title), ("backup-prune", "failed", None))
        self.assertEqual(dict(entry.detail), {"failed": 1, "removed": 0})
        self.make(1)  # once it can be removed, the next automatic backup does it
        self.assertEqual(len(self.automatic()), 1)

    def test_restoring_the_oldest_automatic_backup_is_not_pruned_away_by_its_own_safety_backup(self):
        """The safety backup a restore makes first must not remove the backup being restored (or its pair)."""
        self.control.set_auto_backup_keep(2)
        oldest, _newer = self.make(2)
        added = self.service.add(title="Made later", content="Not in the oldest backup.", source_ref="test")
        report = self.service.restore_backup(oldest, control=self.control)
        self.assertEqual(report["pair"], "matched")
        self.assertEqual([m.memory_id for m in self.service.list()].count(added.memory_id), 0)
        self.assertTrue(oldest.is_file() and pair_path(oldest).is_file())
        self.make(1)  # no longer in use: the next automatic backup prunes it
        self.assertFalse(oldest.exists() or pair_path(oldest).exists())
        self.assertEqual(len(self.automatic()), 2)

    def test_without_a_control_file_the_default_applies_and_no_control_file_is_made(self):
        other = self.root / "solo" / "memories.sqlite3"
        service = DesktopMemoryService(other)
        try:
            service.add(title="Solo", content="A memory without a control file.", source_ref="test")
            made = [service.automatic_backup("before-move") for _ in range(12)]
        finally:
            service.close()
        kept = sorted(p.name for p in (other.parent / "backups").glob("auto-*.sqlite3"))
        self.assertEqual(kept, sorted(p.name for p in made[-10:]))
        self.assertFalse(control_database_for(other).exists())


if __name__ == "__main__":
    unittest.main()
