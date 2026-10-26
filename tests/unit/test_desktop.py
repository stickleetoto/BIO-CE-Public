# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.parse import quote

from bio_ce.core.models import (
    MemoryNotFoundError,
    MemoryScope,
    RevisionConflictError,
    SourceProvenance,
)
from bio_ce.desktop import (
    AppDataPaths,
    DesktopMemoryService,
    DesktopSettingsError,
    PERSONAL_SCOPE,
    claim_single_instance,
    privacy_acknowledged,
    save_privacy_acknowledgement,
)
from bio_ce.storage.backup import BackupConflictError, BackupValidationError
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


class DesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-desktop-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def test_default_data_paths_keep_personal_and_demo_databases_separate(self):
        resolved = AppDataPaths.from_local_app_data({"LOCALAPPDATA": self.temp.name})
        self.assertEqual(resolved.user_database, Path(self.temp.name).resolve() / "BIO-CE" / "data" / "memories.sqlite3")
        self.assertEqual(resolved.demo_database, Path(self.temp.name).resolve() / "BIO-CE" / "demo" / "demo.sqlite3")
        self.assertNotEqual(resolved.user_database, resolved.demo_database)
        self.assertTrue(self.paths.user_database.is_file())
        self.assertFalse(self.paths.demo_database.exists())

    def test_privacy_acknowledgement_is_explicit_and_invalid_settings_fail_closed(self):
        self.assertFalse(privacy_acknowledged(self.paths.settings_file))
        save_privacy_acknowledgement(self.paths.settings_file)
        self.assertTrue(privacy_acknowledged(self.paths.settings_file))
        self.paths.settings_file.write_text(json.dumps({"privacy_acknowledged": True}), encoding="utf-8")
        with self.assertRaises(DesktopSettingsError):
            privacy_acknowledged(self.paths.settings_file)

    def test_desktop_explicit_add_search_read_revise_history_and_retract(self):
        first = self.service.add(
            title="Local project note",
            content="The synthetic marker desktopexplicitmarker is stored only after Save.",
            source_ref="user-input",
        )
        self.assertEqual(self.service.count(), 1)
        hits = self.service.search("desktopexplicitmarker")
        self.assertEqual([hit.memory_id for hit in hits], [first.memory_id])
        self.assertEqual(self.service.read(first.memory_id).revision_id, first.revision_id)

        revised = self.service.revise(
            first,
            title="Updated local project note",
            content="A new synthetic marker desktopexplicitmarker revision.",
            source_ref="user-edited",
        )
        self.assertEqual(revised.revision_number, 2)
        self.assertEqual(self.service.read(first.memory_id).revision_id, revised.revision_id)
        self.assertEqual([item.revision_id for item in self.service.history(first.memory_id)], [
            first.revision_id,
            revised.revision_id,
        ])

        self.service.retract(revised)
        self.assertEqual(self.service.count(), 0)
        self.assertEqual(self.service.search("desktopexplicitmarker"), ())
        with self.assertRaises(MemoryNotFoundError):
            self.service.read(first.memory_id)

    def test_desktop_list_is_exact_scope_and_hides_retracted_rows(self):
        own = self.service.add(
            title="Personal scope",
            content="Visible in the desktop list.",
            source_ref="user-input",
        )
        other_scope = MemoryScope("bio-ce-personal", "other")
        writer = SQLiteMemoryStore(self.paths.user_database)
        try:
            writer.add(
                other_scope,
                title="Other namespace",
                content="Must not appear in the desktop scope.",
                source=SourceProvenance("fixture", "fixture:scope"),
            )
            self.assertEqual([item.memory_id for item in self.service.list()], [own.memory_id])
            writer.retract(
                PERSONAL_SCOPE,
                own.memory_id,
                expected_revision_id=own.revision_id,
                source=SourceProvenance("fixture", "fixture:retraction"),
            )
            self.assertEqual(self.service.list(), ())
            self.assertEqual(self.service.count(), 0)
        finally:
            writer.close()

    def test_stale_desktop_edit_is_rejected(self):
        original = self.service.add(
            title="Revision conflict",
            content="Original content.",
            source_ref="user-input",
        )
        writer = SQLiteMemoryStore(self.paths.user_database)
        try:
            writer.revise(
                PERSONAL_SCOPE,
                original.memory_id,
                expected_revision_id=original.revision_id,
                title="Changed elsewhere",
                content="Fresh revision.",
                source=SourceProvenance("fixture", "fixture:concurrent-update"),
            )
            with self.assertRaises(RevisionConflictError):
                self.service.revise(
                    original,
                    title="Stale desktop revision",
                    content="Must not overwrite newer data.",
                    source_ref="user-edited",
                )
        finally:
            writer.close()

    def test_backup_restore_and_corrupt_backup_fail_closed(self):
        first = self.service.add(
            title="Backup snapshot one",
            content="The first synthetic backup record.",
            source_ref="user-input",
        )
        backup = Path(self.temp.name) / "backups" / "snapshot.sqlite3"
        self.service.create_backup(backup)
        with self.assertRaises(BackupConflictError):
            self.service.create_backup(backup)
        with self.assertRaises(BackupConflictError):
            self.service.create_backup(self.paths.user_database)

        second = self.service.add(
            title="Backup snapshot two",
            content="This record is newer than the selected backup.",
            source_ref="user-input",
        )
        corrupt = Path(self.temp.name) / "corrupt.sqlite3"
        corrupt.write_bytes(b"not a BIO CE SQLite database")
        with self.assertRaises(BackupValidationError):
            self.service.restore_backup(corrupt)
        self.assertEqual(self.service.count(), 2)
        self.assertEqual(self.service.read(second.memory_id).revision_id, second.revision_id)

        self.service.restore_backup(backup)
        self.assertEqual(self.service.count(), 1)
        self.assertEqual(self.service.read(first.memory_id).revision_id, first.revision_id)
        with self.assertRaises(MemoryNotFoundError):
            self.service.read(second.memory_id)
        self.assertTrue(backup.is_file())

    def test_restore_refuses_active_database_as_its_own_backup(self):
        first = self.service.add(
            title="Restore source conflict",
            content="The active database cannot replace itself.",
            source_ref="user-input",
        )
        with self.assertRaises(BackupConflictError):
            self.service.restore_backup(self.paths.user_database)
        self.assertEqual(self.service.read(first.memory_id).revision_id, first.revision_id)

    def test_restore_fails_closed_while_another_connection_holds_a_wal_snapshot(self):
        self.service.add(
            title="WAL snapshot seed",
            content="Create a stable snapshot for restore testing.",
            source_ref="user-input",
        )
        backup = Path(self.temp.name) / "before-concurrent-write.sqlite3"
        self.service.create_backup(backup)
        database_uri = f"file:{quote(self.paths.user_database.as_posix(), safe='/:')}?mode=ro"
        reader = sqlite3.connect(database_uri, uri=True, isolation_level=None)
        try:
            reader.execute("BEGIN")
            reader.execute("SELECT COUNT(*) FROM memories").fetchone()
            self.service.add(
                title="Concurrent WAL row",
                content="This write keeps WAL state newer than the reader snapshot.",
                source_ref="user-input",
            )
            with self.assertRaises(BackupConflictError):
                self.service.restore_backup(backup)
            self.assertEqual(self.service.count(), 2)
        finally:
            reader.rollback()
            reader.close()

    def test_backup_and_restore_leave_no_sqlite_sidecar_files(self):
        self.service.add(title="Sidecar check", content="Synthetic sidecar marker.", source_ref="user-input")
        folder = Path(self.temp.name) / "backups"
        backup = self.service.create_backup(folder / "clean.sqlite3")
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["clean.sqlite3"])
        # SQLite header bytes 18/19 are 1 for a rollback journal and 2 for WAL.
        self.assertEqual(backup.read_bytes()[18:20], bytes((1, 1)))
        self.service.add(title="After backup", content="Removed again by the restore.", source_ref="user-input")
        self.service.restore_backup(backup)
        self.assertEqual(self.service.count(), 1)
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["clean.sqlite3"])
        leftovers = [path.name for path in self.paths.user_database.parent.iterdir() if path.name.startswith(".bio-ce-")]
        self.assertEqual(leftovers, [])

    def test_restore_refuses_a_backup_with_pending_wal_changes(self):
        self.service.add(title="Pending WAL", content="Synthetic pending WAL marker.", source_ref="user-input")
        backup = self.service.create_backup(Path(self.temp.name) / "pending.sqlite3")
        Path(f"{backup}-wal").write_bytes(bytes(64))
        with self.assertRaises(BackupValidationError):
            self.service.restore_backup(backup)
        self.assertEqual(self.service.count(), 1)

    @unittest.skipUnless(os.name == "nt", "named mutexes are Windows-only")
    def test_second_desktop_instance_is_refused_until_the_first_exits(self):
        import ctypes

        name = f"BIO-CE-Test-SingleInstance-{os.getpid()}"
        first = claim_single_instance(name)
        self.assertTrue(first)
        self.assertIsNone(claim_single_instance(name))
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(first))
        again = claim_single_instance(name)
        self.assertTrue(again)
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(again))


if __name__ == "__main__":
    unittest.main()
