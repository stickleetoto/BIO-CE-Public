# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The Community Engine behind the engine contract, and switching between engines.

The adapter must return exactly what the desktop service returns, enforce the
same grant checks as the MCP server, and never let a request made for one
engine binding reach another engine. Engines keep separate databases; a
switch copies nothing.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bio_ce.control_store import AccessDenied, ControlStore, MODE_AUTO_MEMORY, MODE_PAUSED, control_database_for
from bio_ce.desktop import DesktopMemoryService
from bio_ce.engine.community import COMMUNITY_CAPABILITIES, COMMUNITY_ENGINE_ID, CommunityEngineAdapter
from bio_ce.engine.contract import (
    Capability,
    EngineBackend,
    EngineBinding,
    EngineUnavailable,
    HostSession,
    MemoryCandidate,
    StaleEngineBinding,
    Support,
    WriteStatus,
)
from bio_ce.engine.external import ExternalEngineAdapter
from bio_ce.engine.switching import EngineRouter, SelectionStore, SwitchError, SwitchHooks, SwitchPhase
from tests.engine_fixtures import SyntheticTransport


STATED = MemoryCandidate("Prefers tabs", "The user prefers tabs for indentation in Python files.", "preference",
                         "high", "user_stated")
INFERRED = MemoryCandidate("Maybe likes vim", "The user might like the vim editor for quick edits.", "preference",
                           "medium", "inferred")


def digest(path: Path) -> str:
    """Hash every memory and revision row; opening a store rewrites the file header, so bytes are not compared."""
    with closing(sqlite3.connect(path)) as connection:
        rows = [connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("memories", "revisions")]
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


class CommunityAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-engine-")
        self.database = Path(self.temp.name) / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.adapter = CommunityEngineAdapter(self.service)
        self.first = self.service.add(title="Lab server", content="The lab server is build-07 in room 4.",
                                      source_ref="user-input")
        self.second = self.service.add(title="Editor", content="The user edits with a light theme.",
                                       source_ref="user-input")
        self.control = ControlStore(control_database_for(self.database))
        self.grant, self.token = self.control.create_grant("claude", mode=MODE_AUTO_MEMORY)
        self.binding = EngineBinding(COMMUNITY_ENGINE_ID, 0)

    def tearDown(self) -> None:
        self.control.close()
        self.service.close()
        self.temp.cleanup()

    def session(self, guard=None) -> HostSession:
        return self.adapter.open_host_session(self.grant.connection_id, self.token, binding=self.binding,
                                              binding_guard=guard or (lambda _binding: None))

    def test_contract_shape_and_declared_capabilities(self):
        self.assertIsInstance(self.adapter, EngineBackend)
        status = self.adapter.status()
        self.assertTrue(status.ready)
        self.assertEqual(status.descriptor.engine_id, COMMUNITY_ENGINE_ID)
        for capability in Capability:
            self.assertEqual(self.adapter.support(capability), COMMUNITY_CAPABILITIES[capability])
        self.assertEqual(self.adapter.support(Capability.CONTEXT_PACK), Support.LIMITED)

    def test_reads_match_the_desktop_service_exactly(self):
        listed = self.adapter.list()
        self.assertEqual([(view.memory_id, view.revision_id, view.title, view.content) for view in listed],
                         [(r.memory_id, r.revision_id, r.title, r.content) for r in self.service.list()])
        hits = self.adapter.search("lab server room")
        self.assertEqual([(hit.memory_id, hit.revision_id, hit.score) for hit in hits],
                         [(hit.memory_id, hit.revision_id, hit.score) for hit in self.service.search("lab server room")])
        self.assertTrue(all(view.engine_id == COMMUNITY_ENGINE_ID for view in (*listed, *hits)))
        self.assertEqual(self.adapter.get(self.first.memory_id).revision_id, self.first.revision_id)

    def test_user_edits_go_through_the_existing_service_with_conflict_checks(self):
        outcome = self.adapter.revise(self.first.memory_id, expected_revision_id=self.first.revision_id,
                                      title="Lab server", content="The lab server is build-08.", source_ref="u")
        self.assertEqual(outcome.status, WriteStatus.SAVED)
        stale = self.adapter.revise(self.first.memory_id, expected_revision_id=self.first.revision_id,
                                    title="Lab server", content="Stale edit.", source_ref="u")
        self.assertEqual(stale.status, WriteStatus.CONFLICT)
        self.assertFalse(stale.persisted)
        history = self.adapter.history(self.first.memory_id)
        self.assertEqual([view.revision_number for view in history], [1, 2])
        self.assertEqual(self.adapter.retract(self.second.memory_id,
                                              expected_revision_id=self.second.revision_id).status, WriteStatus.SAVED)
        self.assertEqual(self.service.count(), 1)

    def test_host_proposals_keep_the_auto_memory_policy_and_typed_outcomes(self):
        session = self.session()
        try:
            saved = session.propose(STATED, request_id="r1")
            self.assertEqual(saved.status, WriteStatus.SAVED)
            self.assertTrue(saved.persisted)
            pending = session.propose(INFERRED, request_id="r2")
            self.assertEqual(pending.status, WriteStatus.PENDING_REVIEW)
            self.assertFalse(pending.persisted)
            self.assertIsNotNone(pending.review_id)
            self.assertEqual(session.propose(STATED, request_id="r3").status, WriteStatus.DUPLICATE)
            self.assertEqual(self.service.count(), 3, "the pending proposal must not be stored")
            self.assertEqual(self.control.pending_review_count(), 1)
        finally:
            session.close()

    def test_host_sessions_recheck_the_grant_on_every_call(self):
        with self.assertRaises(EngineUnavailable):
            self.adapter.open_host_session(self.grant.connection_id, "wrong-token", binding=self.binding,
                                           binding_guard=lambda _b: None)
        session = self.session()
        try:
            self.assertTrue(session.search("lab server"))
            self.assertIn("build-07", session.context("where is the lab server", char_budget=800).text)
            self.control.set_mode(self.grant.connection_id, MODE_PAUSED)
            with self.assertRaises(AccessDenied):
                session.search("lab server")
            with self.assertRaises(AccessDenied):
                session.propose(STATED, request_id="r1")
            self.control.set_mode(self.grant.connection_id, MODE_AUTO_MEMORY)
            self.control.revoke(self.grant.connection_id)
            with self.assertRaises(AccessDenied):
                session.get(self.first.memory_id)
        finally:
            session.close()
        self.assertEqual(self.service.count(), 2)


class EngineSwitchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-switch-")
        root = Path(self.temp.name)
        self.database = root / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.service.add(title="Community note", content="Only the Community Engine stores this note.",
                         source_ref="user-input")
        self.community = CommunityEngineAdapter(self.service)
        self.transport = SyntheticTransport()
        self.core = ExternalEngineAdapter("core", self.transport,
                                          verified={capability: Support.SUPPORTED for capability in Capability})
        self.control = ControlStore(control_database_for(self.database))
        self.grant, self.token = self.control.create_grant("claude", mode=MODE_AUTO_MEMORY)
        self.events: list[tuple[str, object]] = []
        self.fail_at: str | None = None
        self.selection_file = root / "engine-selection.json"
        self.router = self.make_router()

    def tearDown(self) -> None:
        self.control.close()
        self.service.close()
        self.temp.cleanup()

    def make_router(self) -> EngineRouter:
        def revoke_old(engine_id):
            self.events.append(("revoke", engine_id))
            if self.fail_at == "revoke":
                raise RuntimeError("synthetic revoke failure")
            if engine_id == COMMUNITY_ENGINE_ID:
                for grant in self.control.grants():
                    self.control.revoke(grant.connection_id)

        def bind_new(engine_id, generation):
            self.events.append(("bind", (engine_id, generation)))
            if self.fail_at == "bind":
                raise RuntimeError("synthetic bind failure")

        def verify(backend):
            self.events.append(("verify", backend.descriptor.engine_id))
            if self.fail_at == "verify":
                raise RuntimeError("synthetic verify failure")
            backend.status()

        return EngineRouter({"community": self.community, "core": self.core}, SelectionStore(self.selection_file),
                            SwitchHooks(revoke_old, bind_new, verify))

    def test_community_is_the_default_without_any_selection_file(self):
        self.assertFalse(self.selection_file.exists())
        self.assertEqual(self.router.current_binding(), EngineBinding(COMMUNITY_ENGINE_ID, 0))
        self.assertIs(self.router.active_backend(), self.community)

    def test_switch_revokes_old_grants_first_and_copies_no_data(self):
        before = self.service.count()
        old_binding = self.router.current_binding()
        session = self.community.open_host_session(self.grant.connection_id, self.token, binding=old_binding,
                                                   binding_guard=self.router.guard)
        try:
            selection = self.router.switch_to("core")
            self.assertEqual(selection.phase, SwitchPhase.ACTIVE)
            self.assertEqual(self.router.current_binding(), EngineBinding("core", 1))
            self.assertEqual([event for event, _ in self.events], ["revoke", "bind", "verify"])
            # A request made under the old binding is refused and reaches no engine.
            sent = len(self.transport.requests)
            with self.assertRaises(StaleEngineBinding):
                session.propose(STATED, request_id="late-write")
            with self.assertRaises(StaleEngineBinding):
                self.router.backend_for(old_binding)
            self.assertEqual(len(self.transport.requests), sent)
            self.assertTrue(self.control.grant(self.grant.connection_id).revoked_at)
        finally:
            session.close()
        self.assertEqual(self.service.count(), before, "switching must not copy or change Community memories")
        self.assertNotIn("session.propose", [op for op, _ in self.transport.requests])

    def test_switching_back_keeps_community_memories_unchanged(self):
        self.service.close()
        fingerprint = digest(self.database)
        self.service = DesktopMemoryService(self.database)
        self.community._service = self.service
        self.router.switch_to("core")
        self.router.switch_to("community")
        self.assertEqual(self.router.current_binding(), EngineBinding(COMMUNITY_ENGINE_ID, 2))
        self.assertEqual([view.title for view in self.community.list()], ["Community note"])
        self.service.close()
        self.assertEqual(digest(self.database), fingerprint)
        self.service = DesktopMemoryService(self.database)
        self.community._service = self.service

    def test_every_failed_phase_ends_disconnected_without_fallback(self):
        for phase in ("revoke", "bind", "verify"):
            with self.subTest(phase=phase):
                self.selection_file.unlink(missing_ok=True)
                self.fail_at = phase
                router = self.make_router()
                with self.assertRaises(SwitchError):
                    router.switch_to("core")
                self.assertEqual(router.selection.phase, SwitchPhase.SAFE_DISCONNECTED)
                self.assertIsNone(router.current_binding())
                self.assertIsNone(router.active_backend())
                with self.assertRaises(StaleEngineBinding):
                    router.backend_for(EngineBinding(COMMUNITY_ENGINE_ID, 0))
        self.fail_at = None
        recovered = self.make_router()
        self.assertEqual(recovered.selection.phase, SwitchPhase.SAFE_DISCONNECTED, "the failure survives a restart")
        recovered.switch_to("community")
        self.assertEqual(recovered.selection.phase, SwitchPhase.ACTIVE)

    def test_an_unready_engine_is_refused_at_negotiation(self):
        self.transport.running = False
        with self.assertRaises(SwitchError) as raised:
            self.router.switch_to("core")
        self.assertEqual(raised.exception.phase, SwitchPhase.NEGOTIATE)
        self.assertNotIn("bind", [event for event, _ in self.events])
        self.assertIsNone(self.router.current_binding())

    def test_a_crash_mid_switch_restarts_disconnected(self):
        store = SelectionStore(self.selection_file)
        from bio_ce.engine.switching import EngineSelection

        store.save(EngineSelection(SwitchPhase.BIND_NEW, None, 4, "core"))  # what a crash during bind leaves
        router = self.make_router()
        self.assertEqual(router.selection.phase, SwitchPhase.SAFE_DISCONNECTED)
        self.assertIsNone(router.current_binding())
        self.assertGreater(router.selection.generation, 4, "old bindings stay invalid after recovery")
        self.selection_file.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.make_router().selection.phase, SwitchPhase.SAFE_DISCONNECTED)


if __name__ == "__main__":
    unittest.main()
