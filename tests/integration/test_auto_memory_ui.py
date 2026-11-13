# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Connections page controls for Auto memory, against a real control database."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bio_ce.connections import CodeModeResult, ConnectionResult, HostStatus, SkillResult
from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, MODE_PAUSED, control_database_for
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.ui.dialogs import ReviewEditDialog
from tests.integration.test_desktop_ui_redesign import new_root


def _all_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _all_widgets(child)


class FakeManagedConnections:
    """Real grants and review queue; no host CLI or settings file is touched."""

    def __init__(self, database: Path) -> None:
        self.control = ControlStore(control_database_for(database))
        self.grant, _token = self.control.create_grant("codex")
        self.hooks = False
        self.skill = "absent"
        self.code_mode = "missing"
        self.calls: list[tuple] = []

    def status(self, host: str) -> HostStatus:
        if host == "claude":
            return HostStatus("claude", True, True, legacy=True, mode="read_only")
        grant = self.control.grant(self.grant.connection_id)
        return HostStatus("codex", True, grant.active, mode=grant.mode, connection_id=grant.connection_id,
                          hooks_installed=self.hooks, code_mode=self.code_mode, skill=self.skill)

    def set_mode(self, host: str, mode: str):
        self.calls.append(("set_mode", mode))
        return self.control.set_mode(self.grant.connection_id, mode)

    def connection_settings(self, host: str):
        return self.control.connection_settings(self.grant.connection_id)

    def set_connection_settings(self, host: str, **values):
        self.calls.append(("set_connection_settings", values))
        return self.control.set_connection_settings(self.grant.connection_id, **values)

    def install_hooks(self, host: str, *, approved: bool = False):
        assert approved is True
        self.calls.append(("install_hooks", host))
        self.hooks = True

    def remove_hooks(self, host: str, *, approved: bool = False):
        assert approved is True
        self.calls.append(("remove_hooks", host))
        self.hooks = False

    def connect(self, host: str, *, approved: bool = False) -> ConnectionResult:
        self.calls.append(("connect", host))
        return ConnectionResult(host, True, False, None)

    def disconnect(self, host: str, *, approved: bool = False, remove_skill: bool = False,
                   remove_modified_skill: bool = False) -> ConnectionResult:
        self.calls.append(("disconnect", host, remove_skill))
        return ConnectionResult(host, False, False, None)

    def memory_skill_path(self, host: str) -> Path:
        return Path(f"C:/fake/{host}/skills/bio-ce-memory/SKILL.md")

    def install_memory_skill(self, host: str, *, approved: bool = False, replace_modified: bool = False,
                             agents_md: bool = False):
        assert approved is True
        self.calls.append(("install_skill", host, agents_md, replace_modified))
        self.skill = "current"
        return SkillResult("installed", self.memory_skill_path(host)), None

    def remove_memory_skill(self, host: str, *, approved: bool = False, remove_modified: bool = False):
        assert approved is True
        self.calls.append(("remove_skill", host))
        self.skill = "absent"
        return SkillResult("removed", self.memory_skill_path(host)), None

    def apply_codex_code_mode(self, *, approved: bool = False):
        assert approved is True
        self.calls.append(("apply_code_mode", "codex"))
        self.code_mode = "applied"
        return CodeModeResult("applied", "BIO CE's tools and instructions are now shown in Codex code mode.")

    def diagnose(self, host: str, *, run_server_check: bool = True):
        return ()

    def close(self) -> None:
        self.control.close()


class AutoMemoryConnectionsPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-auto-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.update()

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def test_mode_controls_hooks_and_legacy_reconnect(self):
        app = self.app
        app.show_page("connections")
        codex, claude = app.connections.cards["codex"], app.connections.cards["claude"]
        self.assertTrue(codex.access.winfo_manager(), "managed connections show access controls")
        self.assertEqual(codex.mode_buttons["read_only"].variant, "primary")
        self.assertFalse(claude.access.winfo_manager(), "v0.2 entries have no permission controls")
        self.assertEqual(claude.primary.text, "Reconnect")

        with patch.object(app, "confirm", return_value=False) as declined:
            app.connections.set_mode("codex", MODE_AUTO_MEMORY)
        self.assertIn("Auto memory", declined.call_args.kwargs["title"])
        self.assertIn("may not use Auto memory", declined.call_args.kwargs["points"][0])
        self.assertEqual(self.connections.grant.mode, "read_only")
        self.assertEqual(self.connections.status("codex").mode, "read_only")
        with patch.object(app, "confirm", return_value=True):
            app.connections.set_mode("codex", MODE_AUTO_MEMORY)
        self.root.update()
        self.assertEqual(self.connections.status("codex").mode, MODE_AUTO_MEMORY)
        self.assertEqual(codex.mode_buttons[MODE_AUTO_MEMORY].variant, "primary")
        self.assertIn("Auto memory", codex.pill.cget("text"))
        # Connected is not the same as "the host's model can use Auto memory": Codex is shown as limited.
        self.assertIn("limited", codex.pill.cget("text"))
        self.assertEqual(codex.support_pill.kind, "warning")
        self.assertIn("code mode", codex.support_detail.cget("text"))
        self.assertEqual(claude.support_pill.kind, "success")
        with patch.object(app, "confirm", return_value=False) as warned:
            app.connections.set_mode("claude", MODE_AUTO_MEMORY)
        self.assertFalse(any("may not use Auto memory" in point for point in warned.call_args.kwargs.get("points", ())))

        with patch.object(app, "confirm", return_value=True) as asked:
            app.connections.toggle_hooks("codex")
        self.assertIn("/hooks", " ".join(asked.call_args.kwargs["points"]), "Codex users are told to trust hooks")
        app.tasks.wait(10)
        self.root.update()
        self.assertTrue(self.connections.hooks)
        self.assertEqual(codex.hooks_button.text, "Remove")

        with patch.object(app, "confirm", return_value=True):
            app.connections.pause_all()
        self.assertEqual(self.connections.status("codex").mode, MODE_PAUSED)

    def test_code_mode_skill_rows_and_notes(self):
        app = self.app
        app.show_page("connections")
        page = app.connections
        codex, claude = page.cards["codex"], page.cards["claude"]
        self.root.update()
        texts = " ".join(str(w.cget("text")) for w in _all_widgets(page) if "text" in w.keys())
        self.assertIn("You can close the BIO CE app: connected AI tools keep using your memories.", texts)
        self.assertIn("The Claude desktop chat app is not supported.", texts)
        self.assertIn("Codex (CLI · desktop app)", texts)
        self.assertNotIn("0.164", codex.support_detail.cget("text"))

        self.assertEqual(codex.code_mode_label.cget("text"), "Off")
        self.assertTrue(codex.code_mode_button.winfo_manager(), "Apply is offered while the option is missing")
        self.assertIsNone(claude.code_mode_label, "only Codex has a code mode row")
        with patch.object(app, "confirm", return_value=True) as asked:
            page.apply_code_mode("codex")
        self.assertIn("0.166 or later", " ".join(asked.call_args.kwargs["points"]))
        app.tasks.wait(10)
        self.root.update()
        self.assertIn(("apply_code_mode", "codex"), self.connections.calls)
        self.assertTrue(codex.code_mode_label.cget("text").startswith("On"))
        self.assertFalse(codex.code_mode_button.winfo_manager())
        self.assertIn("verified with Codex 0.166", codex.support_detail.cget("text"))
        self.assertTrue(codex.support_pill.cget("text").endswith("Limited"), "Codex stays Limited (decision F1)")

        self.assertEqual(codex.skill_label.cget("text"), "Not installed")
        self.assertEqual(codex.skill_button.text, "Install")
        with patch.object(app, "confirm", return_value=True) as asked:
            page.toggle_skill("codex")
        self.assertTrue(asked.call_args.kwargs["links"], "the skill can be previewed before installing")
        app.tasks.wait(10)
        self.root.update()
        self.assertIn(("install_skill", "codex", False, False), self.connections.calls)
        self.assertEqual(codex.skill_label.cget("text"), "Installed")
        self.assertEqual(codex.skill_button.text, "Remove")

        with patch.object(app, "confirm", return_value=False) as asked:
            page.disconnect_host("codex")
        options = {key: default for key, _label, default in asked.call_args.kwargs["options"]}
        self.assertEqual(options, {"remove_skill": True}, "an unedited skill is removed with the connection by default")
        self.connections.skill = "modified"
        app.hosts_changed()
        self.root.update()
        with patch.object(app, "confirm", return_value=False) as asked:
            page.disconnect_host("codex")
        options = {key: default for key, _label, default in asked.call_args.kwargs["options"]}
        self.assertEqual(options, {"remove_skill": False}, "a skill the user edited is kept by default")

    def test_pending_reviews_show_on_dashboard_and_sidebar_and_host_status_is_not_clipped(self):
        app, control = self.app, self.connections.control
        app.show_page("dashboard")
        self.root.update()
        self.assertEqual(app.dashboard.review_value.cget("text"), "0")
        self.assertFalse(app.nav["connections"].badge.winfo_manager(), "no badge while nothing waits")
        for index in range(3):
            control.enqueue_review(host="codex", connection_id=self.connections.grant.connection_id, kind="create",
                                   title=f"Synthetic review {index}", content="synthetic", review_reason="test")
        app.show_page("memories")
        app.show_page("dashboard")
        self.root.update()
        self.assertEqual(app.dashboard.review_value.cget("text"), "3")
        self.assertEqual(app.nav["connections"].badge.cget("text"), "3")
        self.assertTrue(app.nav["connections"].badge.winfo_manager())
        # The status pill sits on its own line under the host name, inside the card.
        control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        app.hosts_changed()
        self.root.update()
        pill = app.dashboard.host_rows["codex"]
        card = app.dashboard.connections_card
        self.assertLessEqual(pill.winfo_rootx() + pill.winfo_reqwidth(), card.winfo_rootx() + card.winfo_width())
        self.assertGreaterEqual(pill.winfo_rootx(), card.winfo_rootx())

    def test_review_queue_approve_edit_retract_and_reject(self):
        app = self.app
        control = self.connections.control
        existing = self.service.add(title="Lab server", content="The lab server is build-07.", source_ref="user-input")
        common = dict(host="codex", connection_id=self.connections.grant.connection_id)
        first = control.enqueue_review(kind="create", title="Prefers short answers",
                                       content="The user prefers short answers.", review_reason="inferred", **common)
        second = control.enqueue_review(kind="create", title="Uses a standing desk",
                                        content="The user might use a standing desk.", review_reason="medium",
                                        **common)
        control.enqueue_review(kind="retract", title=existing.title, content=None, memory_id=existing.memory_id,
                               expected_revision_id=existing.revision_id,
                               review_reason="retraction always needs the user's approval", **common)
        control.enqueue_review(kind="create", title="Rejected idea", content="Synthetic idea to reject.",
                               review_reason="medium", **common)
        app.show_page("connections")
        page = app.connections
        self.assertEqual(page.review_pill.cget("text").strip("• "), "4")

        items = {item.review_id: item for item in control.reviews()}
        page.approve_review(items[first])
        self.assertEqual(self.service.count(), 2)

        with patch.object(ReviewEditDialog, "ask", return_value=("Uses a standing desk", "The user uses a "
                                                                  "standing desk every afternoon.")):
            page.approve_review(items[second], edit=True)
        titles = {revision.title: revision for revision in self.service.list()}
        self.assertIn("every afternoon", titles["Uses a standing desk"].content)
        self.assertTrue(titles["Uses a standing desk"].source.metadata["edited"])

        retract = next(item for item in control.reviews() if item.kind == "retract")
        with patch.object(app, "confirm", return_value=True):
            page.approve_review(retract)
        self.assertNotIn("Lab server", {revision.title for revision in self.service.list()})

        page.reject_review(control.reviews()[0])
        self.assertEqual(control.pending_review_count(), 0)
        self.assertEqual(page.review_pill.cget("text").strip("• "), "0")
        self.assertTrue(page.activity_list.winfo_children())

    def test_a_stale_review_card_cannot_apply_or_reject_a_handled_item(self):
        # U1-D1/D2: a card shown before the item was handled must not save it and must not raise.
        app = self.app
        control = self.connections.control
        review_id = control.enqueue_review(kind="create", title="Prefers tea", content="The user prefers green tea.",
                                           review_reason="inferred", host="codex",
                                           connection_id=self.connections.grant.connection_id)
        app.show_page("connections")
        page = app.connections
        stale = control.review(review_id)
        page.reject_review(stale)
        with patch.object(app, "notify") as notified:
            page.approve_review(stale)
        self.assertEqual(self.service.count(), 0, "a rejected suggestion was saved")
        self.assertEqual(notified.call_args.args[0], "warning")
        with patch.object(app, "notify") as notified:
            page.reject_review(stale)  # used to raise ControlStoreError out of the Tk callback
        self.assertEqual(notified.call_args.args[0], "warning")
        self.assertIn("already handled", notified.call_args.args[1])
        self.assertEqual(control.pending_review_count(), 0)


if __name__ == "__main__":
    unittest.main()
