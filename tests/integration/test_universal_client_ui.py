# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Real Tk tests: the desktop app as a universal client over the engine contract.

The Community Engine is the default and must behave exactly as before. Other
engines are synthetic stand-ins (``tests.engine_fixtures``); no real external
engine is contacted and engine switching stays disabled in this version.
"""

from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from bio_ce.control_store import ControlStore, control_database_for
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.engine.community import CommunityEngineAdapter
from bio_ce.engine.contract import Capability, EngineState, Support, WriteOutcome, WriteStatus
from bio_ce.engine.external import ExternalEngineAdapter
from bio_ce.engine.switching import EngineSelection, SwitchPhase
from tests.engine_fixtures import SyntheticTransport
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import FakeConnections
from tests.tk_support import new_tk_root


READS = {capability: Support.SUPPORTED for capability in (
    Capability.MEMORY_SEARCH, Capability.MEMORY_GET, Capability.MEMORY_LIST, Capability.MEMORY_HISTORY)}
CORE_ACTIVE = EngineSelection(SwitchPhase.ACTIVE, "core", 1)
EDIT_ACTIONS = ("create", "edit", "retract")


class PendingCommunity(CommunityEngineAdapter):
    """A Community adapter whose direct edits come back as proposals (exercises the pending path)."""

    def create(self, *, title, content, source_ref):
        return WriteOutcome(self.engine_id, WriteStatus.PENDING_REVIEW, review_id="7",
                            reasons=("synthetic pending",))


class UniversalClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-universal-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.community_note = self.service.add(title="Community only note",
                                               content="Stored only in the Community Engine database.",
                                               source_ref="user-input")
        self.root: tk.Tk | None = None
        self.app: BIOCEDesktop | None = None

    def tearDown(self) -> None:
        if self.app is not None:
            try:
                self.app.tasks.wait(10)
                self.app.editor.load(None)
                self.app.close()
            except tk.TclError:
                self.service.close()
        else:
            self.service.close()
        self.temp.cleanup()

    def open(self, connections=None, **options) -> BIOCEDesktop:
        self.root = new_tk_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, connections or FakeConnections(), **options)
        self.root.update()
        return self.app

    def core(self, **transport) -> ExternalEngineAdapter:
        return ExternalEngineAdapter("core", SyntheticTransport(**transport), verified=READS)

    # Community default ------------------------------------------------------------

    def test_community_is_the_default_engine_and_core_is_not_claimed(self):
        app = self.open()
        self.assertIsInstance(app.engine, CommunityEngineAdapter)
        self.assertEqual(app.engine_banner().title, "Using Community Engine")
        self.assertIn("Community Engine", app.engine_label.cget("text"))
        self.assertTrue(all(app.allowed(action).enabled for action in
                            ("browse", "search", "create", "edit", "retract", "review", "backup", "restore")))
        app.show_page("settings")
        rows = app.settings.engine_rows
        self.assertEqual(list(rows), ["community", "core"])
        self.assertEqual(rows["community"].pill.cget("text").strip("• "), "Connected")
        self.assertEqual(rows["core"].pill.cget("text").strip("• "), "Not installed")
        self.assertFalse(rows["core"].button.enabled, "a missing engine can't be chosen")
        self.assertIn("each memory engine keeps its own memories", app.settings.engine_note.cget("text").lower())
        status = {s.engine_id: s for s in app.engine_statuses()}["core"]
        self.assertEqual(status.state, EngineState.NOT_INSTALLED)

    def test_gui_memory_operations_go_through_the_engine(self):
        app = self.open()
        engine = app.engine
        with patch.object(engine, "create", wraps=engine.create) as create, \
                patch.object(engine, "revise", wraps=engine.revise) as revise, \
                patch.object(engine, "retract", wraps=engine.retract) as retract, \
                patch.object(engine, "list", wraps=engine.list) as listing, \
                patch.object(engine, "get", wraps=engine.get) as get, \
                patch.object(engine, "history", wraps=engine.history) as history:
            app.start_new_memory()
            app.title_value.set("Engine routed")
            app.content_value.insert("1.0", "Saved through the engine contract.")
            saved = app.save_memory()
            self.assertIsNotNone(saved)
            self.assertEqual(saved.engine_id, "community")
            app.start_edit_memory()
            app.content_value.delete("1.0", tk.END)
            app.content_value.insert("1.0", "Revised through the engine contract.")
            app.save_memory()
            self.assertIsNotNone(app.show_history())
            with patch.object(app, "confirm", return_value=True):
                app.retract_selected()
        self.assertEqual((create.call_count, revise.call_count, retract.call_count), (1, 1, 1))
        self.assertTrue(listing.called and get.called and history.called)
        self.assertEqual([r.title for r in self.service.list()], ["Community only note"])

    def test_list_and_detail_match_the_desktop_service(self):
        for index in range(3):
            self.service.add(title=f"Parity note {index}", content=f"Parity body {index}.", source_ref=f"src-{index}")
        app = self.open()
        app.show_page("memories")
        shown = list(app.memories.tree.get_children())
        self.assertEqual(shown, [r.memory_id for r in self.service.list()])
        app.memories.select(shown[0])
        expected = self.service.read(shown[0])
        self.assertEqual((app.selected.revision_id, app.selected.title, app.selected.content,
                          app.selected.source_ref), (expected.revision_id, expected.title, expected.content,
                                                     expected.source.source_ref))
        self.assertIn(expected.source.source_ref, app.memories.meta_label.cget("text"))
        app.query.set("Parity body 1")
        app.memories.refresh()
        self.assertEqual(list(app.memories.tree.get_children()),
                         [hit.memory_id for hit in self.service.search("Parity body 1")])

    # Capability gating with another engine ---------------------------------------------

    def test_a_read_only_engine_disables_edits_review_and_backup(self):
        core = self.core()
        app = self.open(engine=core, engine_selection=CORE_ACTIVE)
        self.assertEqual(app.engine_banner().title, "Using Synthetic engine")
        app.show_page("memories")
        titles = {app.memories.records[iid].title for iid in app.memories.tree.get_children()}
        self.assertIn("Synthetic engine note 0", titles)
        self.assertNotIn("Community only note", titles, "Community memories must not appear under another engine")
        for action in EDIT_ACTIONS + ("review", "backup", "restore"):
            self.assertFalse(app.allowed(action).enabled, action)
        self.assertFalse(app.memories.add_button.enabled)
        app.memories.select(app.memories.tree.get_children()[0])
        self.assertFalse(app.memories.edit_button.enabled)
        self.assertFalse(app.memories.retract_button.enabled)
        self.assertTrue(app.memories.history_button.enabled)
        app.show_page("settings")
        self.assertFalse(app.settings.backup_button.enabled)
        self.assertFalse(app.settings.restore_button.enabled)
        with patch.object(app, "notify") as notified:
            app.start_new_memory()  # Ctrl+N path
        self.assertIsNot(app.current, app.editor)
        self.assertEqual(notified.call_args.args[0], "warning")
        self.assertIn("does not offer", notified.call_args.args[1])

    def test_an_unverified_engine_offers_nothing(self):
        core = ExternalEngineAdapter("core", SyntheticTransport())  # claims everything, verified nothing
        app = self.open(engine=core, engine_selection=CORE_ACTIVE)
        states = {action: app.allowed(action) for action in ("browse", "search", "create", "backup")}
        self.assertFalse(any(state.enabled for state in states.values()))
        self.assertIn("Not yet verified", states["browse"].note)

    def test_review_cards_are_gated_and_say_nothing_is_stored_yet(self):
        control = ControlStore(control_database_for(self.paths.user_database))
        try:
            control.enqueue_review(host="codex", connection_id="conn_synthetic", kind="create", title="Prefers tea",
                                   content="The user prefers green tea.", review_reason="inferred")
        finally:
            control.close()
        app = self.open(FakeManagedConnections(self.paths.user_database))
        app.show_page("connections")
        self.assertIn("Not saved yet", app.connections.review_cards[0].status_text)
        self.assertTrue(all(button.enabled for button in app.connections.review_cards[0].buttons))
        app.close()
        self.service = DesktopMemoryService(self.paths.user_database)
        app = self.open(FakeManagedConnections(self.paths.user_database), engine=self.core(),
                        engine_selection=CORE_ACTIVE)
        app.show_page("connections")
        self.assertFalse(any(button.enabled for button in app.connections.review_cards[0].buttons))

    # Failures and disconnected states ---------------------------------------------------

    def test_an_unavailable_engine_shows_an_error_and_never_falls_back(self):
        app = self.open(engine=self.core(running=False), engine_selection=CORE_ACTIVE)
        banner = app.engine_banner()
        self.assertFalse(banner.connected)
        self.assertIn("not running", banner.title)
        self.assertIn("not running", app.engine_label.cget("text").lower())
        with patch.object(app, "notify") as notified:
            app.show_page("memories")
            app.memories.refresh()
        self.assertEqual(app.memories.tree.get_children(), ())
        self.assertEqual(notified.call_args.args[0], "error")
        self.assertIn("engine", notified.call_args.args[1].lower())
        self.assertFalse(any(app.allowed(action).enabled for action in ("browse", "create", "backup")))

    def test_an_authentication_error_is_shown_as_access_refused(self):
        transport = SyntheticTransport()
        transport.request = lambda operation, payload: {"error": {"code": "unauthorized"}}
        app = self.open(engine=ExternalEngineAdapter("core", transport, verified=READS),
                        engine_selection=CORE_ACTIVE)
        self.assertEqual(app.engine_status.state, EngineState.UNAUTHORIZED)
        app.show_page("settings")
        self.assertEqual(app.settings.engine_rows["core"].pill.cget("text").strip("• "), "Access refused")

    def test_safe_disconnected_shows_no_engine_and_no_memories(self):
        selection = EngineSelection(SwitchPhase.SAFE_DISCONNECTED, None, 2, "core", "A previous switch did not finish.")
        app = self.open(engine_selection=selection)
        self.assertEqual(app.engine_banner().title, "No memory engine connected")
        self.assertIn("no engine", app.engine_label.cget("text").lower())
        app.show_page("memories")
        self.assertEqual(app.memories.tree.get_children(), ())
        self.assertFalse(app.memories.add_button.enabled)
        app.show_page("settings")
        self.assertFalse(app.settings.engine_rows["community"].active)

    def test_engine_errors_during_reads_and_saves_are_reported(self):
        app = self.open()
        from bio_ce.engine.contract import EngineUnavailable

        with patch.object(app.engine, "list", side_effect=EngineUnavailable("down")), \
                patch.object(app, "notify") as notified:
            app.show_page("memories")
            app.memories.refresh()
        self.assertEqual(notified.call_args.kwargs.get("title"), "Memory engine unavailable")
        app.start_new_memory()
        app.title_value.set("Will fail")
        app.content_value.insert("1.0", "Engine goes away during save.")
        with patch.object(app.engine, "create", side_effect=EngineUnavailable("down")), \
                patch.object(app, "notify") as notified:
            self.assertIsNone(app.save_memory())
        self.assertEqual(notified.call_args.args[0], "error")
        self.assertIs(app.current, app.editor, "the user's text stays in the editor")
        self.assertEqual(self.service.count(), 1)

    # Pending vs saved ----------------------------------------------------------------

    def test_a_pending_outcome_is_not_shown_as_saved(self):
        app = self.open(engine=PendingCommunity(self.service))
        app.start_new_memory()
        app.title_value.set("Needs review")
        app.content_value.insert("1.0", "This comes back as a proposal.")
        with patch.object(app, "notify") as notified:
            result = app.save_memory()
        self.assertIsNone(result)
        self.assertEqual(notified.call_args.kwargs["title"], "Waiting for your review")
        self.assertNotIn("saved", notified.call_args.kwargs["title"].lower())
        self.assertEqual(self.service.count(), 1, "nothing was stored")

    # Restart ------------------------------------------------------------------------

    def test_close_and_restart_keep_memories_and_the_community_default(self):
        app = self.open()
        app.start_new_memory()
        app.title_value.set("Survives restart")
        app.content_value.insert("1.0", "Written before the app was closed.")
        self.assertIsNotNone(app.save_memory())
        app.close()
        self.app = None
        self.service = DesktopMemoryService(self.paths.user_database)
        app = self.open()
        app.show_page("memories")
        titles = {app.memories.records[iid].title for iid in app.memories.tree.get_children()}
        self.assertEqual(titles, {"Community only note", "Survives restart"})
        self.assertEqual(app.engine_banner().title, "Using Community Engine")
        self.assertFalse((self.paths.root / "engine-selection.json").exists(), "no selection file is created")


if __name__ == "__main__":
    unittest.main()
