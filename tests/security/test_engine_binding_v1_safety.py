# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Safety tests for the proposed engine_binding_v1 extension (test-only prototype, temporary files only).

The product code is unchanged; ``ControlStore``, the MCP server, the hooks, the
memory store, and the backup validator used here are the released ones, so
"released BIO CE" below means exactly this code.
"""

from __future__ import annotations

from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from bio_ce.control_store import AccessDenied, ControlStore, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.host_hooks import HookRequest, build_context
from bio_ce.mcp_server import create_mcp_server
from bio_ce.storage.backup import validate_database
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from tests.security import engine_binding_v1_prototype as v1


REPO = Path(__file__).resolve().parents[2]
SCOPE = MemoryScope("bio-ce-personal", "default")


def run_python(code: str) -> subprocess.CompletedProcess:
    """Run ``code`` in a separate Python process (like a host-started MCP server or hook)."""
    return subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60)


class EngineBindingSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-binding-")
        self.memory = Path(self.temp.name) / "data" / "memories.sqlite3"
        store = SQLiteMemoryStore(self.memory)
        store.add(SCOPE, title="Seed", content="A synthetic seed memory for the binding tests.",
                  source=SourceProvenance("user-entered", "user-input"))
        store.close()
        self.control_path = control_database_for(self.memory)
        control = ControlStore(self.control_path)  # released code creates and upgrades it to version 2
        self.old_grant, self.old_token = control.create_grant("claude")
        control.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def migrated(self) -> Path:
        backup = v1.migrate(self.control_path)
        v1.ensure_fence(self.memory)
        return backup

    def user_version(self) -> int:
        with closing(sqlite3.connect(self.control_path)) as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    # 1. Compatibility with released BIO CE ----------------------------------------------------

    def test_released_bio_ce_opens_the_extended_database_and_keeps_existing_grants(self):
        self.migrated()
        self.assertEqual(self.user_version(), 2)
        control = ControlStore(self.control_path)
        try:
            grant = control.authenticate(self.old_grant.connection_id, self.old_token)
            self.assertEqual(grant.host, "claude")
            self.assertEqual(len(control.grants()), 1)
        finally:
            control.close()
        self.assertEqual(v1.check_binding(self.control_path, self.old_grant.connection_id, self.old_token)
                         ["binding_generation"], 0, "existing grants are Community generation 0")

    def test_released_bio_ce_can_never_use_a_core_bound_grant(self):
        self.migrated()
        connection_id, token = v1.create_bound_grant(self.control_path, "codex", "core", 0)
        control = ControlStore(self.control_path)
        try:
            with self.assertRaises(AccessDenied):
                control.authenticate(connection_id, token)
        finally:
            control.close()
        with self.assertRaises(AccessDenied):  # released MCP server
            create_mcp_server(self.memory, connection_id=connection_id, token=token)
        for event in ("session-start", "user-prompt"):  # released hooks print nothing
            self.assertEqual(build_context(HookRequest(event, "codex", self.memory, connection_id, token),
                                           {"prompt": "seed memory"}), "")
        with closing(sqlite3.connect(self.control_path)) as connection:
            stored = connection.execute("SELECT token_sha256 FROM connections WHERE connection_id = ?",
                                        (connection_id,)).fetchone()[0]
        self.assertTrue(stored.startswith(v1.CORE_HASH_PREFIX), "the prefix is why released code can't match it")

    def test_released_store_and_backup_validator_accept_the_fence_table(self):
        self.migrated()
        validate_database(self.memory)
        store = SQLiteMemoryStore(self.memory, read_only=True)
        try:
            self.assertEqual(store.count_current(SCOPE), 1)
        finally:
            store.close()
        writer = SQLiteMemoryStore(self.memory)  # the released writer reopens and keeps schema version 1
        writer.close()

    def test_migration_is_idempotent_concurrent_and_backed_up(self):
        backup = self.migrated()
        v1.migrate(self.control_path)
        code = ("from pathlib import Path; from tests.security import engine_binding_v1_prototype as v1; "
                f"v1.migrate(Path(r'{self.control_path}'))")
        processes = [subprocess.Popen([sys.executable, "-c", code], cwd=REPO, stderr=subprocess.PIPE, text=True)
                     for _ in range(4)]
        for process in processes:
            _out, err = process.communicate(timeout=60)
            self.assertEqual(process.returncode, 0, err)
        with closing(sqlite3.connect(self.control_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM control_extensions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM engine_state").fetchone()[0], 1)
            columns = [row[1] for row in connection.execute("PRAGMA table_info(connections)")]
        self.assertEqual(columns.count("engine_id"), 1)
        with closing(sqlite3.connect(backup)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("engine_state", tables, "the backup is the database as it was before")
        restored = ControlStore(backup)
        try:
            restored.authenticate(self.old_grant.connection_id, self.old_token)
        finally:
            restored.close()

    def test_migration_refuses_an_unexpected_version_without_changing_it(self):
        with closing(sqlite3.connect(self.control_path)) as connection:
            connection.execute("PRAGMA user_version = 7")
        with self.assertRaises(RuntimeError):
            v1.migrate(self.control_path)
        self.assertEqual(self.user_version(), 7)
        with closing(sqlite3.connect(self.control_path)) as connection:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(connections)")]
        self.assertNotIn("engine_id", columns)

    # 2. Generation checks in separate processes -----------------------------------------------

    def test_a_separate_process_sees_the_switch_on_its_next_call(self):
        self.migrated()
        code = ("import sys; from pathlib import Path; from tests.security import engine_binding_v1_prototype as v1\n"
                "try:\n"
                f"    v1.check_binding(Path(r'{self.control_path}'), '{self.old_grant.connection_id}', "
                f"'{self.old_token}')\n"
                "except v1.StaleBinding:\n    sys.exit(3)\n")
        self.assertEqual(run_python(code).returncode, 0)
        v1.set_phase(self.control_path, "quiesce", engine_id=None, bump=True)
        self.assertEqual(run_python(code).returncode, 3)

    def test_an_old_generation_is_refused_even_after_switching_back(self):
        self.migrated()
        v1.set_phase(self.control_path, "quiesce", engine_id=None, bump=True)        # generation 1
        v1.set_phase(self.control_path, "active", engine_id="core")
        v1.set_phase(self.control_path, "quiesce", engine_id=None, bump=True)        # generation 2
        v1.set_phase(self.control_path, "active", engine_id="community")
        with self.assertRaises(v1.StaleBinding):
            v1.check_binding(self.control_path, self.old_grant.connection_id, self.old_token)
        fresh_id, fresh_token = v1.create_bound_grant(self.control_path, "claude", "community", 2)
        v1.check_binding(self.control_path, fresh_id, fresh_token)

    # 3. Writer fence: no stale commit after the fence ----------------------------------------------

    def insert_note(self, generation: int, title: str, **options) -> None:
        v1.fenced_write(self.memory, generation, "INSERT INTO probe(title) VALUES (?)", (title,), **options)

    def probe_titles(self) -> list[str]:
        with closing(sqlite3.connect(self.memory)) as connection:
            return [row[0] for row in connection.execute("SELECT title FROM probe ORDER BY rowid")]

    def make_probe(self) -> None:
        with closing(sqlite3.connect(self.memory)) as connection:
            connection.execute("CREATE TABLE probe (title TEXT NOT NULL)")
            connection.commit()

    def test_a_stale_writer_cannot_commit_after_the_fence(self):
        self.migrated()
        self.make_probe()
        self.insert_note(0, "before switch")
        v1.raise_fence(self.memory, 1)
        with self.assertRaises(v1.Fenced):
            self.insert_note(0, "late write from the old engine binding")
        self.insert_note(1, "new generation")
        self.assertEqual(self.probe_titles(), ["before switch", "new generation"])

    def test_an_in_flight_write_is_ordered_before_the_fence(self):
        self.migrated()
        self.make_probe()
        inside, release = threading.Event(), threading.Event()
        order: list[str] = []
        errors: list[BaseException] = []

        def writer():
            try:
                self.insert_note(0, "in flight", before_commit=lambda: (inside.set(), release.wait(10)))
                order.append("writer committed")
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        def fence():
            v1.raise_fence(self.memory, 1)
            order.append("fence committed")

        writing = threading.Thread(target=writer)
        writing.start()
        self.assertTrue(inside.wait(10))
        fencing = threading.Thread(target=fence)
        fencing.start()
        time.sleep(0.3)
        self.assertEqual(order, [], "the fence waits for the in-flight writer")
        release.set()
        writing.join(10)
        fencing.join(15)
        self.assertEqual(errors, [])
        self.assertEqual(order, ["writer committed", "fence committed"])
        with self.assertRaises(v1.Fenced):
            self.insert_note(0, "after the fence")
        self.assertEqual(self.probe_titles(), ["in flight"])

    def test_a_writer_killed_before_commit_leaves_nothing_and_its_lease_expires(self):
        self.migrated()
        self.make_probe()
        code = ("import os; from datetime import timedelta; from pathlib import Path\n"
                "from tests.security import engine_binding_v1_prototype as v1\n"
                f"lease = v1.acquire_lease(Path(r'{self.control_path}'), 'conn_x', 'community', 0, "
                "ttl=timedelta(seconds=1))\n"
                f"v1.fenced_write(Path(r'{self.memory}'), 0, 'INSERT INTO probe(title) VALUES (?)', ('killed',), "
                "before_commit=lambda: os._exit(9))\n")
        self.assertEqual(run_python(code).returncode, 9)
        self.assertEqual(self.probe_titles(), [], "SQLite rolled back the killed writer")
        self.assertEqual(v1.live_leases(self.control_path, 0), 1)
        time.sleep(1.2)
        self.assertEqual(v1.live_leases(self.control_path, 0), 0, "the crashed writer's lease expired")
        v1.raise_fence(self.memory, 1)  # the lock is free again

    def test_no_new_lease_once_a_switch_started(self):
        self.migrated()
        lease = v1.acquire_lease(self.control_path, self.old_grant.connection_id, "community", 0)
        generation = v1.set_phase(self.control_path, "quiesce", engine_id=None, bump=True)
        with self.assertRaises(v1.StaleBinding):
            v1.acquire_lease(self.control_path, self.old_grant.connection_id, "community", 0)
        with self.assertRaises(v1.StaleBinding):
            v1.acquire_lease(self.control_path, self.old_grant.connection_id, "community", generation)
        self.assertEqual(v1.live_leases(self.control_path, 0), 1, "the switch waits for this writer")
        v1.release_lease(self.control_path, lease)
        self.assertEqual(v1.live_leases(self.control_path, 0), 0)

    # 4. Crash recovery ----------------------------------------------------------------------------

    def test_an_unfinished_switch_restarts_disconnected_with_a_new_generation(self):
        self.migrated()
        for phase in ("quiesce", "revoke_old", "negotiate", "bind_new", "verify"):
            with self.subTest(phase=phase):
                before = v1.set_phase(self.control_path, phase, engine_id=None)
                state = v1.recover_on_start(self.control_path)
                self.assertEqual(state["phase"], "safe_disconnected")
                self.assertIsNone(state["active_engine_id"])
                self.assertGreater(state["generation"], before)
                with self.assertRaises(v1.StaleBinding):
                    v1.check_binding(self.control_path, self.old_grant.connection_id, self.old_token)
        self.assertEqual(v1.recover_on_start(self.control_path)["phase"], "safe_disconnected",
                         "recovery is stable across restarts")


if __name__ == "__main__":
    unittest.main()
