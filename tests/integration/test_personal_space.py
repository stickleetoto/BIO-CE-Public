# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 A: the built-in Personal space and its safety rules, over the real stdio server and hooks (synthetic data).

Every "never" below has a positive control next to it, so a test that sees nothing also proves it could have.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from bio_ce.control_store import MODE_AUTO_MEMORY, MODE_READ_ONLY, ControlStore, ControlStoreError
from bio_ce.core.models import MemoryScope, SourceProvenance, ValidationError
from bio_ce.desktop import DesktopMemoryService
from bio_ce.spaces import PERSONAL_SPACE, Space, is_personal_request, resolve_space, space_for_scope
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from tests.integration.test_spaces_mcp_and_hooks import GENERAL, USER, _SpaceFixture


PERSONAL = PERSONAL_SPACE.curated
PERSONAL_INBOX = PERSONAL_SPACE.inbox


def titles(result) -> list[str]:
    return [hit["title"] for hit in result.structured_content["results"]]


class PersonalSpaceTests(_SpaceFixture):
    def setUp(self) -> None:
        super().setUp()
        store = SQLiteMemoryStore(self.database)
        store.add(PERSONAL, title="Blood type", content="The user's blood type is O; the user cycles to the clinic.",
                  source=USER)
        store.add(PERSONAL_INBOX, title="Personal inbox note", content="The user cycles along the river.",
                  source=USER)
        store.add(GENERAL, title="Cycling", content="The user cycles to work on weekdays.", source=USER)
        store.close()

    def hook(self, event: str, cwd, prompt: str = "") -> str:
        from bio_ce.host_hooks import HookRequest, build_context
        return build_context(HookRequest(event, "claude", self.database, self.grant.connection_id, self.token),
                             {"cwd": str(cwd), "prompt": prompt})

    def allow(self, *, read=True, write=False) -> None:
        self.control.set_personal_enabled(True)
        self.control.set_personal_access(self.grant.connection_id, can_read=read, can_write=write)

    def test_personal_is_off_by_default_and_asking_for_it_never_falls_back_to_general(self):
        self.assertFalse(self.control.personal_enabled())
        asked, by_namespace, general = self.calls(
            ("bio_memory_search", {"query": "cycles", "space": "Personal"}),
            ("bio_memory_search", {"query": "cycles", "namespace": "personal"}),
            ("bio_memory_search", {"query": "cycles"}),
        )
        for result in (asked, by_namespace):
            self.assertTrue(result.is_error, result)
            self.assertIn("Personal is turned off", result.content[0].text)
            self.assertIn("did not use General", result.content[0].text)
        self.assertEqual(titles(general), ["Cycling"])  # positive control: the same query works in General

    def test_personal_needs_an_explicit_row_and_all_project_spaces_does_not_open_it(self):
        self.control.set_personal_enabled(True)
        self.assertTrue(self.control.connection_settings(self.grant.connection_id)["all_projects"])
        self.assertEqual(self.control.space_access(self.grant.connection_id, PERSONAL_SPACE), (False, False))
        read, write = self.calls(
            ("bio_memory_search", {"query": "cycles", "space": "personal"}),
            ("bio_memory_create", self.fact(space="Personal", title="Shoe size", content="The user wears size 270.",
                                            category="preference")),
        )
        self.assertTrue(read.is_error)
        self.assertIn("no read access to Personal", read.content[0].text)
        self.assertTrue(write.is_error)
        self.assertIn("no write access to Personal", write.content[0].text)
        store = SQLiteMemoryStore(self.database, read_only=True)
        try:
            general_titles = {r.title for r in store.list_current(GENERAL, limit=20)}
        finally:
            store.close()
        self.assertNotIn("Shoe size", general_titles)  # the refused write did not land in General either

    def test_allowed_reads_are_marked_personal_and_default_search_stays_general(self):
        self.allow(read=True)
        personal, default, with_inbox, read = self.calls(
            ("bio_memory_search", {"query": "cycles", "space": "Personal"}),
            ("bio_memory_search", {"query": "cycles"}),
            ("bio_memory_search", {"query": "cycles", "space": "Personal", "include_inbox": True}),
            ("bio_memory_search", {"query": "blood"}),
        )
        self.assertEqual(titles(personal), ["Blood type"])
        self.assertTrue(personal.structured_content["personal"])
        self.assertEqual(personal.structured_content["space"], {"id": "personal", "name": "Personal"})
        self.assertTrue(all(hit["personal"] for hit in personal.structured_content["results"]))
        self.assertEqual(titles(default), ["Cycling"])
        self.assertNotIn("personal", default.structured_content)
        self.assertEqual(titles(with_inbox), ["Blood type", "Personal inbox note"])
        self.assertEqual(titles(read), [])  # a Personal-only word is not found without space="Personal"
        memory_id = personal.structured_content["results"][0]["memory_id"]
        (opened,) = self.calls(("bio_memory_read", {"memory_id": memory_id, "space": "Personal"}))
        self.assertTrue(opened.structured_content["personal"])
        (elsewhere,) = self.calls(("bio_memory_read", {"memory_id": memory_id}))
        self.assertTrue(elsewhere.is_error)  # a Personal id is not readable through General

    def test_writes_need_write_access_and_the_connection_mode_stays_the_outer_switch(self):
        self.allow(read=True, write=True)
        (created,) = self.calls(("bio_memory_create", self.fact(space="Personal", title="Shoe size",
                                                                content="The user wears size 270 shoes.",
                                                                category="preference")))
        self.assertEqual(created.structured_content["status"], "created", created)
        self.assertTrue(created.structured_content["personal"])
        store = SQLiteMemoryStore(self.database, read_only=True)
        try:
            self.assertIn("Shoe size", {r.title for r in store.list_current(PERSONAL, limit=20)})
        finally:
            store.close()
        self.control.set_mode(self.grant.connection_id, MODE_READ_ONLY)
        (refused,) = self.calls(("bio_memory_create", self.fact(space="Personal", title="Hat size",
                                                                content="The user wears size 58 hats.",
                                                                category="preference")))
        self.assertTrue(refused.is_error)
        self.assertIn("Auto memory is off", refused.content[0].text)

    def test_unknown_or_ambiguous_names_fall_back_to_general_never_to_personal(self):
        self.allow(read=True, write=True)
        (fallback,) = self.calls(("bio_memory_create", self.fact(space="Persnal", title="Cycling route",
                                                                 content="The user cycles along the harbour.",
                                                                 category="preference")))
        self.assertEqual(fallback.structured_content["space"]["name"], "General")
        self.assertEqual(fallback.structured_content["space_resolution"], "fallback_general")
        self.assertNotIn("personal", fallback.structured_content)
        spaces = self.control.spaces()
        self.assertNotIn("personal", {space.space_id for space in spaces})
        self.assertEqual(resolve_space(spaces, "zzz").space.space_id, "general")
        self.assertTrue(is_personal_request(" PERSONAL "))
        self.assertFalse(is_personal_request("personal stuff"))

    def test_hooks_never_use_personal_even_when_the_host_may_read_it(self):
        self.allow(read=True, write=True)
        words = ("Blood type", "Personal inbox note")
        contexts = [self.hook("session-start", self.root / "elsewhere"),
                    self.hook("user-prompt", self.root / "elsewhere", prompt="what is my blood type, the user cycles"),
                    self.hook("session-start", self.project_folder),
                    self.hook("user-prompt", self.project_folder, prompt="blood type cycles clinic")]
        for text in contexts:
            for word in words:
                self.assertNotIn(word, text)
        self.assertIn("Cycling", contexts[0])  # positive control: General memories do reach the hook

    def test_a_path_goes_to_the_personal_inbox_only_with_personal_write_access(self):
        path_fact = self.fact(title="Notes folder", content=r"The user keeps notes in D:\Notes\Diary.",
                              category="preference")
        (queued,) = self.calls(("bio_memory_create", path_fact))
        self.assertEqual(queued.structured_content["status"], "queued_for_review", queued)
        self.allow(read=True, write=True)
        (moved,) = self.calls(("bio_memory_create", dict(path_fact, title="Diary folder")))
        self.assertEqual(moved.structured_content["status"], "created", moved)
        self.assertEqual(moved.structured_content["stage"], "inbox")
        self.assertEqual(moved.structured_content["space"]["name"], "Personal")
        store = SQLiteMemoryStore(self.database, read_only=True)
        try:
            self.assertIn("Diary folder", {r.title for r in store.list_current(PERSONAL_INBOX, limit=20)})
            self.assertNotIn("Diary folder", {r.title for r in store.list_current(GENERAL, limit=20)})
            self.assertNotIn("Diary folder", {r.title for r in store.list_current(
                MemoryScope(GENERAL.project, "default.inbox"), limit=20)})
        finally:
            store.close()

    def test_turning_personal_off_keeps_its_memories_and_removes_every_access_row(self):
        self.allow(read=True, write=True)
        self.control.set_personal_enabled(False)
        with closing(sqlite3.connect(self.control.path)) as raw:
            rows = raw.execute("SELECT COUNT(*) FROM connection_spaces WHERE space_id = 'personal'").fetchone()[0]
        self.assertEqual(rows, 0)
        store = SQLiteMemoryStore(self.database, read_only=True)
        try:
            self.assertEqual([r.title for r in store.list_current(PERSONAL, limit=20)], ["Blood type"])
        finally:
            store.close()
        with self.assertRaises(ControlStoreError):
            self.control.set_personal_access(self.grant.connection_id, can_read=True, can_write=False)
        self.control.set_personal_enabled(True)
        self.assertEqual(self.control.space_access(self.grant.connection_id, PERSONAL_SPACE), (False, False))

    def test_project_spaces_cannot_be_named_personal(self):
        for name in ("Personal", " personal ", "ＰＥＲＳＯＮＡＬ"):
            with self.subTest(name=name), self.assertRaises(ControlStoreError):
                self.control.create_space(name)
        with self.assertRaises(ControlStoreError):
            self.control.rename_space(self.alpha.space_id, "Personal")
        self.assertEqual(self.control.create_space("Personal finance").display_name, "Personal finance")


class PersonalMoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-personal-move-")
        self.database = Path(self.temp.name) / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.control = ControlStore(self.database.with_name("control.sqlite3"))

    def tearDown(self) -> None:
        self.service.close()
        self.control.close()
        self.temp.cleanup()

    def test_move_keeps_ids_and_history_updates_search_and_backs_up_first(self):
        first = self.service.add(title="Allergy", content="The user is allergic to peanuts.", source_ref="test")
        second = self.service.revise(first, title="Allergy", content="The user is allergic to peanuts and shellfish.",
                                     source_ref="test")
        stay = self.service.add(title="Editor", content="The user edits in helix.", source_ref="test")
        result = self.service.move_memories(self.control, [first.memory_id], PERSONAL)
        self.assertEqual(result["moved"], 1)
        backup = result["backup"]
        self.assertTrue(backup.is_file())
        self.assertTrue(backup.with_name(backup.stem + ".control.sqlite3").is_file())
        with closing(sqlite3.connect(backup)) as raw:  # the backup holds the state before the move
            self.assertEqual(raw.execute("SELECT namespace FROM memories WHERE memory_id = ?",
                                         (first.memory_id,)).fetchone()[0], "default")
        self.assertEqual([hit.title for hit in self.service.search("allergic")], [])
        self.assertEqual([hit.title for hit in self.service.search("helix")], ["Editor"])  # positive control
        self.service.use_space(PERSONAL)
        self.assertEqual([hit.memory_id for hit in self.service.search("shellfish")], [first.memory_id])
        self.assertEqual([r.revision_id for r in self.service.history(first.memory_id)],
                         [first.revision_id, second.revision_id])
        self.assertEqual(self.service.read(first.memory_id).revision_id, second.revision_id)
        with closing(sqlite3.connect(self.database)) as raw:
            fts = raw.execute("SELECT DISTINCT project, namespace FROM memory_fts WHERE memory_id = ?",
                              (first.memory_id,)).fetchall()
        self.assertEqual(fts, [("bio-ce-personal", "personal")])
        entry = [e for e in self.control.recent_activity() if e.action == "space-move"][0]
        self.assertEqual(entry.detail["count"], 1)
        self.assertIsNone(entry.title)
        self.assertNotEqual(stay.memory_id, first.memory_id)

    def test_inbox_items_move_to_the_other_inbox_and_stages_never_mix(self):
        store = SQLiteMemoryStore(self.database)
        item = store.add(MemoryScope(GENERAL.project, "default.inbox"), title="Clinic", content="Dentist on Monday.",
                         source=USER)
        with self.assertRaises(ValidationError):
            store.move(GENERAL, PERSONAL_INBOX, [item.memory_id])
        store.close()
        result = self.service.move_memories(self.control, [item.memory_id], PERSONAL, inbox=True)
        self.assertEqual(result["moved"], 1)
        self.service.use_space(PERSONAL)
        self.assertEqual([r.memory_id for r in self.service.inbox()], [item.memory_id])

    def test_space_for_scope_knows_personal_and_its_inbox(self):
        self.assertEqual(space_for_scope(self.control.spaces(), PERSONAL_INBOX), PERSONAL_SPACE)
        self.assertEqual(space_for_scope(self.control.spaces(), GENERAL).space_id, "general")
        self.assertIsNone(space_for_scope(self.control.spaces(), MemoryScope("team-atlas", "notes")))
        self.assertIsInstance(PERSONAL_SPACE, Space)


if __name__ == "__main__":
    unittest.main()
