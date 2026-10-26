# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Connections page controls for Auto memory, against a real control database."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bio_ce.connections import ConnectionResult, HostStatus
from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, MODE_PAUSED, control_database_for
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.ui.dialogs import ReviewEditDialog
from tests.integration.test_desktop_ui_redesign import new_root


class FakeManagedConnections:
    """Real grants and review queue; no host CLI or settings file is touched."""

    def __init__(self, database: Path) -> None:
        self.control = ControlStore(control_database_for(database))
        self.grant, _token = self.control.create_grant("codex")
        self.hooks = False
        self.calls: list[tuple[str, str]] = []

    def status(self, host: str) -> HostStatus:
        if host == "claude":
            return HostStatus("claude", True, True, legacy=True, mode="read_only")
        grant = self.control.grant(self.grant.connection_id)
        return HostStatus("codex", True, grant.active, mode=grant.mode, connection_id=grant.connection_id,
                          hooks_installed=self.hooks)

    def set_mode(self, host: str, mode: str):
        self.calls.append(("set_mode", mode))
        return self.control.set_mode(self.grant.connection_id, mode)

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

    def disconnect(self, host: str, *, approved: bool = False) -> ConnectionResult:
        return ConnectionResult(host, False, False, None)

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


if __name__ == "__main__":
    unittest.main()
