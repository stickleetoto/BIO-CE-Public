# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.2: inbox items are deleted from the files as far as the app can, and backups are two files.

Every database here is synthetic and lives in a temporary folder.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid

from bio_ce.control_store import (
    CURATION_CLEANUP_PENDING,
    CURATION_DISCARDED,
    CURATION_PENDING,
    GENERAL_SPACE_ID,
    MODE_AUTO_MEMORY,
    MODE_READ_ONLY,
    PRE_UPGRADE_SNAPSHOT,
    ControlStore,
    control_database_for,
)
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.desktop import DesktopMemoryService
from bio_ce.inbox import discard_inbox_items, finish_pending_cleanups, inbox_scope
from bio_ce.storage import backup as backup_module
from bio_ce.storage.backup import (
    PAIR_MATCHED,
    PAIR_MISMATCH,
    PAIR_MISSING,
    BackupConflictError,
    BackupError,
    check_pair,
    create_backup,
    file_sha256,
    pair_path,
    validate_database,
)
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


CURATED = MemoryScope("bio-ce-personal", "default")
INBOX = inbox_scope(CURATED)
USER = SourceProvenance("user-entered", "test")
REPO = Path(__file__).resolve().parents[2]


def marker() -> str:
    return f"PURGEMARK{uuid.uuid4().hex}"


def file_bytes(path: Path) -> bytes:
    data = b""
    for candidate in (path, Path(f"{path}-wal")):
        if candidate.is_file():
            data += candidate.read_bytes()
    return data


class DiscardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-discard-")
        self.root = Path(self.temp.name)
        self.database = self.root / "data" / "memories.sqlite3"
        self.store = SQLiteMemoryStore(self.database)
        self.control = ControlStore(control_database_for(self.database))
        self.kept = self.store.add(CURATED, title="Kept curated note", content="The user prefers metric units.",
                                   source=USER)

    def tearDown(self) -> None:
        self.store.close()
        self.control.close()
        self.temp.cleanup()

    def add_inbox(self, mark: str, korean: str = "") -> str:
        first = self.store.add(INBOX, title=f"Inbox {mark}", content=f"Collected text {mark} {korean}".strip(),
                               source=USER)
        # A second revision: the first revision's text must not survive either.
        self.store.revise(INBOX, first.memory_id, expected_revision_id=first.revision_id,
                          title=f"Inbox {mark} v2", content=f"Revised text {mark}v2 {korean}".strip(), source=USER)
        self.control.record(host="codex", connection_id=None, action="create", outcome="created",
                            memory_id=first.memory_id, title=f"Inbox {mark}", detail={"reason": f"user said {mark}"})
        with closing(sqlite3.connect(self.control.path)) as raw:
            raw.execute("INSERT INTO inbox_usage (memory_id, first_seen, hit_count) VALUES (?, '2026-11-01', 1)",
                        (first.memory_id,))
            raw.commit()
        return first.memory_id

    def assert_absent(self, path: Path, *needles: str) -> None:
        data = file_bytes(path)
        for needle in needles:
            self.assertNotIn(needle.encode("utf-8"), data, f"{needle!r} is still in {path.name}")

    def test_discarded_item_is_gone_from_both_files_their_logs_and_a_later_backup(self):
        mark, korean = marker(), "삭제표식" + uuid.uuid4().hex[:8]
        memory_id = self.add_inbox(mark, korean)
        result = discard_inbox_items(self.store, self.control, INBOX, [memory_id])
        self.assertEqual((result.deleted, result.completed), (1, True))
        self.assertEqual(self.control.curation_items(statuses=(CURATION_DISCARDED,))[0]["memory_ids"], [memory_id])
        self.assertEqual(self.store.read(CURATED, self.kept.memory_id).title, "Kept curated note")
        self.assertEqual(self.store.inventory(), [(self.kept.memory_id, CURATED.project, CURATED.namespace)])
        self.assertEqual(Path(f"{self.database}-wal").stat().st_size, 0)
        later = DesktopMemoryService(self.database)
        try:
            backup = later.create_backup(self.root / "after-discard.sqlite3")
        finally:
            later.close()
        self.store.close()
        self.control.close()
        for path in (self.database, control_database_for(self.database), backup, pair_path(backup)):
            self.assert_absent(path, mark, korean)
        self.store = SQLiteMemoryStore(self.database)
        self.control = ControlStore(control_database_for(self.database))
        discard_entry = self.control.recent_activity(limit=1)[0]
        self.assertEqual((discard_entry.action, discard_entry.outcome, discard_entry.title), ("discard", "discarded", None))
        self.assertEqual(discard_entry.detail["count"], 1)

    def test_control_case_a_plain_delete_leaves_the_text_in_the_file(self):
        # Shows that the byte search can see leftovers: without secure_delete and optimize, the text stays.
        mark = marker()
        memory_id = self.add_inbox(mark)
        self.store.close()
        with closing(sqlite3.connect(self.database)) as raw:
            raw.execute("PRAGMA secure_delete = OFF")
            raw.execute("DELETE FROM revisions WHERE memory_id = ?", (memory_id,))
            raw.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            raw.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
            raw.commit()
            raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.assertIn(mark.encode("utf-8"), file_bytes(self.database))
        self.store = SQLiteMemoryStore(self.database)

    def test_a_reader_holding_a_snapshot_delays_completion_until_it_lets_go(self):
        mark = marker()
        memory_id = self.add_inbox(mark)
        reader = sqlite3.connect(self.database, isolation_level=None)
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM memories").fetchone()
        try:
            result = discard_inbox_items(self.store, self.control, INBOX, [memory_id])
            self.assertFalse(result.completed)
            self.assertEqual(len(self.control.curation_items(statuses=(CURATION_CLEANUP_PENDING,))), 1)
            self.assertEqual(self.control.recent_activity(limit=1)[0].outcome, "cleanup-pending")
            self.assertEqual(finish_pending_cleanups(self.store, self.control), 0)
        finally:
            reader.execute("COMMIT")
            reader.close()
        self.assertEqual(finish_pending_cleanups(self.store, self.control), 1)
        self.assertEqual(self.control.curation_items(statuses=(CURATION_CLEANUP_PENDING,)), ())
        self.store.close()
        self.control.close()
        self.assert_absent(self.database, mark)
        self.assert_absent(control_database_for(self.database), mark)
        self.store = SQLiteMemoryStore(self.database)
        self.control = ControlStore(control_database_for(self.database))

    def test_an_interrupted_discard_is_carried_out_on_retry(self):
        mark = marker()
        memory_id = self.add_inbox(mark)
        self.control.open_discard([memory_id])  # the app stopped before the delete ran
        self.assertEqual(finish_pending_cleanups(self.store, self.control), 1)
        self.assertEqual(self.store.inventory(), [(self.kept.memory_id, CURATED.project, CURATED.namespace)])
        self.store.close()
        self.control.close()
        self.assert_absent(self.database, mark)
        self.store = SQLiteMemoryStore(self.database)
        self.control = ControlStore(control_database_for(self.database))

    def test_curated_memories_are_never_physically_deleted(self):
        with self.assertRaises(PermissionError):
            self.store.purge(CURATED, [self.kept.memory_id])
        # An inbox scope cannot reach a curated memory either.
        self.assertEqual(self.store.purge(INBOX, [self.kept.memory_id]).deleted, 0)
        self.assertEqual(self.store.read(CURATED, self.kept.memory_id).title, "Kept curated note")


class BackupPairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-pair-")
        self.root = Path(self.temp.name)
        self.database = self.root / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.control = ControlStore(control_database_for(self.database))
        self.memory = self.service.add(title="Backed up note", content="A synthetic memory in the backup.",
                                       source_ref="test")

    def tearDown(self) -> None:
        self.service.close()
        self.control.close()
        self.temp.cleanup()

    def raw_control(self) -> sqlite3.Connection:
        return closing(sqlite3.connect(self.control.path))

    def test_backup_writes_two_files_that_belong_together(self):
        backup = self.service.create_backup(self.root / "out" / "bio ce 백업.sqlite3")
        pair = pair_path(backup)
        self.assertEqual(pair.name, "bio ce 백업.control.sqlite3")
        validate_database(backup, standalone=True)
        self.assertEqual(check_pair(backup), (PAIR_MATCHED, pair))
        with closing(sqlite3.connect(f"file:{pair.as_posix()}?mode=ro&immutable=1", uri=True)) as raw:
            info = raw.execute("SELECT format, memory_sha256, app_version FROM backup_info").fetchone()
        self.assertEqual(info[:2], (1, file_sha256(backup)))
        self.assertTrue(info[2])
        self.assertEqual(sorted(p.name for p in backup.parent.iterdir()), sorted([backup.name, pair.name]))

    def test_neither_file_is_overwritten_and_a_failed_pair_leaves_nothing(self):
        backup = self.service.create_backup(self.root / "one.sqlite3")
        with self.assertRaises(BackupConflictError):
            self.service.create_backup(backup)
        pair_path(self.root / "two.sqlite3").write_bytes(b"someone else's file")
        with self.assertRaises(BackupConflictError):
            self.service.create_backup(self.root / "two.sqlite3")
        self.assertFalse((self.root / "two.sqlite3").exists())
        with mock.patch.object(backup_module, "_copy_control_snapshot", side_effect=BackupError("synthetic")):
            with self.assertRaises(BackupError):
                self.service.create_backup(self.root / "three.sqlite3")
        self.assertFalse((self.root / "three.sqlite3").exists())
        self.assertFalse(pair_path(self.root / "three.sqlite3").exists())
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".bio-ce-")], [])

    def test_pair_check_missing_and_mismatched(self):
        first = self.service.create_backup(self.root / "first.sqlite3")
        self.service.add(title="Second note", content="Only in the second backup.", source_ref="test")
        second = self.service.create_backup(self.root / "second.sqlite3")
        pair_path(first).unlink()
        self.assertEqual(check_pair(first), (PAIR_MISSING, None))
        shutil.copyfile(pair_path(second), pair_path(first))
        self.assertEqual(check_pair(first), (PAIR_MISMATCH, None))
        pair_path(first).write_bytes(b"not a database")
        self.assertEqual(check_pair(first), (PAIR_MISMATCH, None))

    def test_restore_never_brings_back_a_revoked_connection_or_a_wider_permission(self):
        revoked, _token = self.control.create_grant("codex")
        self.control.set_mode(revoked.connection_id, MODE_AUTO_MEMORY)
        narrowed, _token = self.control.create_grant("claude-code")
        self.control.set_mode(narrowed.connection_id, MODE_AUTO_MEMORY)
        self.control.set_connection_settings(narrowed.connection_id, save_mode="collect")
        with self.raw_control() as raw:
            # New connections get General access by default.
            self.assertEqual(raw.execute("SELECT can_read, can_write FROM connection_spaces WHERE connection_id = ?",
                                         (narrowed.connection_id,)).fetchall(), [(1, 1)])
        backup = self.service.create_backup(self.root / "before.sqlite3")
        self.control.revoke(revoked.connection_id)
        self.control.set_mode(narrowed.connection_id, MODE_READ_ONLY)
        with self.raw_control() as raw:
            raw.execute("UPDATE connection_spaces SET can_write = 0")
            raw.execute("UPDATE connection_settings SET save_mode = 'curated'")
            raw.commit()
        audit_before = len(self.control.recent_activity(limit=1000))
        report = self.service.restore_backup(backup, control=self.control)
        self.assertEqual(report["pair"], PAIR_MATCHED)
        self.assertFalse(self.control.grant(revoked.connection_id).active)
        self.assertEqual(self.control.grant(narrowed.connection_id).mode, MODE_READ_ONLY)
        with self.raw_control() as raw:
            self.assertEqual(raw.execute("SELECT DISTINCT can_write FROM connection_spaces").fetchall(), [(0,)])
            self.assertEqual(raw.execute("SELECT DISTINCT save_mode FROM connection_settings").fetchall(),
                             [("curated",)])
        activity = self.control.recent_activity(limit=1000)
        self.assertEqual(len(activity), audit_before + 1)
        self.assertEqual((activity[0].action, activity[0].outcome), ("restore", "restored"))

    def test_spaces_and_folders_merge_and_current_rows_win(self):
        with self.raw_control() as raw:
            raw.execute("INSERT INTO spaces VALUES ('p1', 'project', 'project:alpha', 'Alpha', 'then', NULL)")
            raw.execute("INSERT INTO spaces VALUES ('p3', 'project', 'project:gamma', 'Gamma (old)', 'then', NULL)")
            raw.execute("INSERT INTO space_folders VALUES ('p1', 'hash-alpha', 'alpha', 'then')")
            raw.commit()
        backup = self.service.create_backup(self.root / "spaces.sqlite3")
        with self.raw_control() as raw:
            raw.execute("DELETE FROM space_folders")
            raw.execute("DELETE FROM spaces WHERE space_id = 'p1'")
            raw.execute("UPDATE spaces SET display_name = 'Gamma' WHERE space_id = 'p3'")
            raw.execute("INSERT INTO spaces VALUES ('p2', 'project', 'project:beta', 'Beta', 'now', NULL)")
            raw.commit()
        report = self.service.restore_backup(backup, control=self.control)
        with self.raw_control() as raw:
            names = dict(raw.execute("SELECT space_id, display_name FROM spaces").fetchall())
            folders = raw.execute("SELECT space_id, folder_key FROM space_folders").fetchall()
        self.assertEqual(names, {GENERAL_SPACE_ID: "General", "p1": "Alpha", "p2": "Beta", "p3": "Gamma"})
        self.assertEqual(folders, [("p1", "hash-alpha")])
        self.assertEqual(report["restored_spaces"], ["project:alpha"])

    def test_memory_only_restore_names_unknown_project_spaces_and_older_backups_still_restore(self):
        store = SQLiteMemoryStore(self.database)
        try:
            store.add(MemoryScope("project:alpha", "default"), title="Alpha note", content="Project memory.",
                      source=USER)
        finally:
            store.close()
        older = create_backup(self.database, self.root / "made-like-0.4.1.sqlite3")  # no pair file
        report = self.service.restore_backup(older, control=self.control)
        self.assertEqual(report["pair"], PAIR_MISSING)
        with self.raw_control() as raw:
            row = raw.execute("SELECT kind, display_name FROM spaces WHERE project = 'project:alpha'").fetchone()
        self.assertEqual(row, ("project", "Restored: alpha"))
        self.assertEqual(self.service.read(self.memory.memory_id).title, "Backed up note")

    def test_pending_discards_come_back_with_a_fresh_wait_and_orphaned_reviews_fail(self):
        store = SQLiteMemoryStore(self.database)
        try:
            item = store.add(INBOX, title="Collected", content="An inbox item kept in the backup.", source=USER)
        finally:
            store.close()
        self.control.open_discard([item.memory_id], status=CURATION_PENDING, due_at="2026-01-01T00:00:00Z")
        backup = self.service.create_backup(self.root / "with-inbox.sqlite3")
        for pending in self.control.curation_items():
            self.control.set_curation_status(pending["item_id"], CURATION_DISCARDED)
        later = self.service.add(title="Made after the backup", content="Not in the backup file.", source_ref="t")
        review_id = self.control.enqueue_review(host="codex", connection_id=None, kind="update", title="Edit",
                                                content="Change it.", review_reason="test", memory_id=later.memory_id,
                                                expected_revision_id=later.revision_id)
        report = self.service.restore_backup(backup, control=self.control)
        self.assertEqual((report["discards_restored"], report["reviews_failed"]), (1, 1))
        restored = self.control.curation_items()
        self.assertEqual(restored[0]["memory_ids"], [item.memory_id])
        due = datetime.fromisoformat(restored[0]["due_at"].replace("Z", "+00:00"))
        self.assertGreater(due, datetime.now(timezone.utc) + timedelta(days=6, hours=23))
        self.assertEqual(self.control.review(review_id).status, "failed")


class ControlUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-upgrade-")
        self.path = Path(self.temp.name) / "control.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def released_module(self, name: str):
        """control_store.py exactly as released in v0.4.1-rc1, loaded under another name.

        The copy lives in tests/fixtures because CI checkouts have no tags. SHA-256 of
        `git show v0.4.1-rc1:src/bio_ce/control_store.py`: ab538556...a63a66a.
        """
        source = (REPO / "tests" / "fixtures" / "released_v041" / f"{name}.py").read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),
                         "ab538556962c7209eee47158a6bc2f63f89f7ee203861076186b36191a63a66a")
        target = Path(self.temp.name) / f"released_{name}.py"
        target.write_bytes(source)
        spec = importlib.util.spec_from_file_location(f"released_{name}", target)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_upgrade_snapshots_the_old_file_once_and_adds_tables_without_a_version_change(self):
        released = self.released_module("control_store")
        old = released.ControlStore(self.path)
        grant, token = old.create_grant("codex")
        old.close()
        upgraded = ControlStore(self.path)
        upgraded.close()
        snapshot = self.path.with_name(PRE_UPGRADE_SNAPSHOT)
        with closing(sqlite3.connect(snapshot)) as raw:
            tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertEqual(raw.execute("SELECT connection_id FROM connections").fetchall(), [(grant.connection_id,)])
        self.assertNotIn("spaces", tables)
        stamp = snapshot.stat().st_mtime_ns
        ControlStore(self.path).close()
        self.assertEqual(snapshot.stat().st_mtime_ns, stamp)
        with closing(sqlite3.connect(self.path)) as raw:
            self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(raw.execute("SELECT space_id, project FROM spaces").fetchall(),
                             [(GENERAL_SPACE_ID, "bio-ce-personal")])
        # Rollback: the released v0.4.1 code still opens the file and authenticates the same connection.
        rolled_back = released.ControlStore(self.path)
        try:
            self.assertEqual(rolled_back.authenticate(grant.connection_id, token).host, "codex")
        finally:
            rolled_back.close()

    def test_a_new_file_needs_no_snapshot(self):
        ControlStore(self.path).close()
        self.assertFalse(self.path.with_name(PRE_UPGRADE_SNAPSHOT).exists())


if __name__ == "__main__":
    unittest.main()
