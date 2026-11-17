# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Connections: summary first, details on request (POLISH §3.1, v0.4.4 rc2).

Each AI tool card shows its name, status, access, and one settings line; the rest is under "Details ▸", closed by
default and never remembered (R5). Whatever the user must act on stays in the summary as one "Needs attention" line
that opens the details (R2). That line is decided only from status values the card already had: a settings
conflict, a legacy connection, limited Auto memory, Codex's code-mode option off, an outdated or edited skill, failed
diagnostics. Positive control: a healthy connection shows no such line.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bio_ce.connections import DiagnosticCheck, HostStatus
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


class StatusConnections(FakeManagedConnections):
    """FakeManagedConnections whose host statuses a test can set."""

    def __init__(self, database: Path) -> None:
        super().__init__(database)
        self.statuses: dict[str, HostStatus] = {}

    def status(self, host: str) -> HostStatus:
        return self.statuses.get(host) or super().status(host)

    def healthy_claude(self, **changes) -> HostStatus:
        values = dict(mode="read_only", connection_id=self.grant.connection_id, hooks_installed=True, skill="current")
        values.update(changes)
        return HostStatus("claude", True, True, **values)


def shown(widget) -> bool:
    return bool(widget.winfo_viewable())


class ConnectionsSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-conn-summary-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = StatusConnections(self.paths.user_database)
        self.root = new_root()
        self.root.geometry("1200x900+0+0")
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.page = self.app.pages["connections"]

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def show(self) -> None:
        self.app.show_page("connections")
        self.page.refresh()
        for _ in range(4):
            self.root.update()

    def card(self, host: str):
        return self.page.cards[host]

    # Summary by default ---------------------------------------------------

    def test_a_card_shows_its_summary_and_keeps_the_details_closed(self):
        self.connections.statuses["claude"] = self.connections.healthy_claude()
        self.show()
        card = self.card("claude")
        self.assertFalse(card.details.opened, "details are closed by default")
        self.assertTrue(shown(card.pill))
        self.assertTrue(shown(card.mode_buttons["read_only"]), "the access segment is part of the summary")
        self.assertTrue(shown(card.settings_line), "spaces, Personal, and saving are one summary line")
        line = card.settings_line.cget("text")
        self.assertIn("General and all project spaces", line)
        self.assertIn("Curated", line)
        self.assertTrue(shown(card.details.toggle))
        for hidden in (card.message, card.support_pill, card.support_detail, card.spaces_label, card.saving_label,
                       card.hooks_label, card.skill_label, card.disconnect_button, card.diagnose_button):
            self.assertFalse(shown(hidden), f"{hidden} is a detail")
        self.assertFalse(shown(card.desc_line), "a connected tool's description is a detail")
        self.assertFalse(shown(card.connect_button), "Connect is not offered for a connected tool")

    def test_personal_appears_in_the_settings_line_when_personal_is_on(self):
        self.connections.control.set_personal_enabled(True)
        self.show()
        line = self.card("codex").settings_line.cget("text")
        self.assertIn("Personal", line)
        self.assertIn("Off", line)

    def test_opening_the_details_shows_the_rows_disconnect_and_diagnose(self):
        self.connections.statuses["claude"] = self.connections.healthy_claude()
        self.show()
        card = self.card("claude")
        card.details.toggle.invoke()
        for _ in range(3):
            self.root.update()
        self.assertTrue(card.details.opened)
        for visible in (card.message, card.support_pill, card.support_detail, card.spaces_label, card.spaces_button,
                        card.saving_label, card.saving_button, card.hooks_label, card.skill_label,
                        card.disconnect_button, card.diagnose_button):
            self.assertTrue(shown(visible), f"{visible} is shown in the details")
        self.assertEqual(card.primary.text, "Disconnect")
        self.page.refresh()
        self.root.update()
        self.assertTrue(card.details.opened, "a refresh keeps the details open while the screen is shown")

    def test_a_tool_that_is_not_connected_shows_one_line_and_connect(self):
        self.show()
        card = self.card("claude_desktop")  # installed, not connected
        self.assertTrue(shown(card.desc_line), "a tool that is not connected says in one line what it is")
        self.assertEqual(card.desc_line.max_lines, 1)
        self.assertTrue(shown(card.connect_button))
        self.assertEqual(card.connect_button.text, "Connect")
        self.assertFalse(shown(card.diagnose_button))
        self.assertFalse(shown(card.attention))

    # Needs attention (R2) -----------------------------------------------

    def attention(self, host: str) -> str:
        card = self.card(host)
        return card.attention_label.cget("text") if shown(card.attention) else ""

    def test_positive_control_a_healthy_connection_needs_no_attention(self):
        self.connections.statuses["claude"] = self.connections.healthy_claude()
        self.show()
        self.assertEqual(self.attention("claude"), "")
        self.assertEqual(self.card("claude").attention_reasons(), [])

    def test_each_state_to_act_on_shows_its_line_in_the_summary(self):
        healthy = self.connections.healthy_claude
        cases = {
            "settings conflict": ("claude", HostStatus("claude", True, False, configuration_conflict=True)),
            "connected the old way": ("claude", HostStatus("claude", True, True, legacy=True, mode="read_only")),
            "memory skill has an update": ("claude", healthy(skill="outdated")),
            "memory skill was edited": ("claude", healthy(skill="modified")),
            "code mode option is off": ("codex", None),
            "Auto memory is limited": ("codex", None),
        }
        for reason, (host, status) in cases.items():
            with self.subTest(reason=reason):
                self.connections.statuses.pop("claude", None)
                if status is not None:
                    self.connections.statuses[host] = status
                self.show()
                text = self.attention(host)
                self.assertIn("Needs attention", text)
                self.assertIn(reason, text)
                self.assertFalse(self.card(host).details.opened, "the line is in the summary; details stay closed")

    def test_limited_auto_memory_shows_alone_once_code_mode_is_on(self):
        self.connections.code_mode = "applied"
        self.connections.skill = "current"
        self.show()
        text = self.attention("codex")
        self.assertIn("Auto memory is limited", text)
        self.assertNotIn("code mode", text)

    def test_failed_diagnostics_show_a_count_and_leave_the_details_open(self):
        self.connections.statuses["claude"] = self.connections.healthy_claude()
        self.show()
        checks = (DiagnosticCheck("Host command", "pass", "ok"), DiagnosticCheck("BIO CE entry", "fail", "missing"),
                  DiagnosticCheck("Read-only tools", "fail", "missing"))
        self.page._diagnosed("claude", checks)
        self.root.update()
        card = self.card("claude")
        self.assertIn("2 diagnostic checks failed", card.attention_label.cget("text"))
        self.assertTrue(card.details.opened, "Diagnose leaves the details open on its results")
        self.assertTrue(shown(card.results))
        self.page._diagnosed("claude", (DiagnosticCheck("Host command", "pass", "ok"),))
        self.root.update()
        self.assertEqual(self.attention("claude"), "", "passing diagnostics clear the line")

    def test_selecting_the_attention_line_opens_the_details(self):
        self.show()
        card = self.card("codex")
        self.assertTrue(shown(card.attention))
        self.assertFalse(card.details.opened)
        card.attention_label.event_generate("<ButtonRelease-1>", x=2, y=2)
        self.root.update()
        self.assertTrue(card.details.opened)
        self.assertTrue(shown(card.code_mode_label))

    def test_legacy_connection_offers_reconnect_in_the_summary(self):
        self.show()
        card = self.card("claude")  # the fake's Claude Code entry is a v0.2 (legacy) one
        self.assertTrue(shown(card.connect_button))
        self.assertEqual(card.connect_button.text, "Reconnect")
        self.assertIs(card.primary, card.connect_button)

    # The page -------------------------------------------------------------

    def test_the_callout_is_one_line_and_starts_open_only_when_no_tool_is_connected(self):
        self.show()  # Codex and Claude Code are connected
        more = self.page.callout_more
        self.assertTrue(shown(self.page.callout_title))
        self.assertTrue(shown(more.toggle))
        self.assertFalse(more.opened)
        self.assertFalse(shown(self.page.callout_body))
        more.flip()
        self.root.update()
        self.assertTrue(shown(self.page.callout_body))

    def test_with_no_tool_connected_the_callout_starts_open(self):
        self.connections.statuses.update({
            "codex": HostStatus("codex", True, False), "claude": HostStatus("claude", True, False)})
        self.show()
        self.assertTrue(self.page.callout_more.opened, "with nothing connected the explanation starts open")
        self.assertTrue(shown(self.page.callout_body))
        self.page.callout_more.flip()
        self.page.refresh()
        self.root.update()
        self.assertFalse(self.page.callout_more.opened, "closing it sticks while the screen is shown")

    def test_servers_and_backups_are_under_advanced(self):
        self.show()
        advanced = self.page.advanced
        self.assertFalse(advanced.opened)
        self.assertTrue(shown(advanced.toggle))
        self.assertIn("Settings backups", advanced.hint_label.cget("text"))
        self.assertIn("No BIO CE server running", advanced.hint_label.cget("text"))
        self.assertFalse(shown(self.page.end_idle_button))
        self.assertFalse(shown(self.page.servers_total))
        self.assertFalse(shown(self.page.backups_button))
        advanced.flip()
        self.root.update()
        for widget in (self.page.end_idle_button, self.page.servers_total, self.page.backups_button):
            self.assertTrue(shown(widget))

    def test_recent_activity_shows_five_lines_and_all_on_request(self):
        control = self.connections.control
        for number in range(8):
            control.record(host="codex", connection_id=self.connections.grant.connection_id, action="create",
                           outcome="queued", title=f"Note {number}")
        self.show()
        rows = [child for child in self.page.activity_list.winfo_children() if shown(child)]
        self.assertEqual(len(rows), 5)
        self.assertTrue(shown(self.page.activity_more))
        self.page.activity_more.invoke()
        self.root.update()
        rows = [child for child in self.page.activity_list.winfo_children() if shown(child)]
        self.assertEqual(len(rows), 8)


if __name__ == "__main__":
    unittest.main()
