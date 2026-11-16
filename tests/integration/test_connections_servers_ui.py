# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 §9.2 (M1) in the app: the Connections page shows the running BIO CE MCP servers and can end idle ones.

The records are written to a temporary data folder for child processes this test starts, the way
``test_server_registry`` does; no other process is ever ended.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from bio_ce import server_registry
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.server_registry import ServerRecord, folder, running
from bio_ce.ui.pages import connections as connections_page
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root


def sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


class ServersOnConnectionsPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-servers-ui-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.data = self.paths.user_database.parent
        self.children: list[subprocess.Popen] = []
        self.root = new_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.update()
        self.page = self.app.pages["connections"]

    def tearDown(self) -> None:
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(10)
        self.app.tasks.wait(10)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def server(self, connection_id: str | None, *, idle: timedelta = timedelta(minutes=1)) -> subprocess.Popen:
        """A real child process with a server record, as a BIO CE MCP server would write it."""
        child = sleeper()
        self.children.append(child)
        stamp = (datetime.now(timezone.utc) - idle).isoformat(timespec="seconds").replace("+00:00", "Z")
        record = ServerRecord(child.pid, None, "codex.exe", connection_id, server_registry.process_image(child.pid),
                              stamp, stamp)
        folder(self.data).mkdir(parents=True, exist_ok=True)
        (folder(self.data) / f"{child.pid}.json").write_text(json.dumps(asdict(record)), encoding="utf-8")
        return child

    def show(self) -> None:
        self.app.show_page("connections")
        for _ in range(3):
            self.root.update()

    def test_each_card_counts_its_servers_and_the_page_counts_them_all(self):
        codex = self.connections.grant.connection_id
        self.server(codex)
        self.server(codex)
        self.server("another-connection")
        self.show()
        card = self.page.cards["codex"]
        self.assertTrue(card.servers_row.winfo_manager())
        self.assertIn("2", str(card.servers_label.cget("text")))
        self.assertEqual(self.page.server_counts(), ({codex: 2, "another-connection": 1}, 3))
        self.assertIn("3", str(self.page.servers_total.cget("text")))
        self.assertFalse(self.page.cards["claude"].servers_row.winfo_manager())  # legacy: no connection ID

    def test_the_count_is_refreshed_whenever_the_page_is_shown(self):
        codex = self.connections.grant.connection_id
        self.server(codex)
        self.show()
        self.assertEqual(self.page.server_counts()[1], 1)
        self.assertIn("1", str(self.page.cards["codex"].servers_label.cget("text")))
        self.app.show_page("dashboard")
        self.server(codex)
        self.assertFalse(self.page.stale)  # positive control: a plain show would not reload the page
        with patch.object(self.app, "host_statuses", wraps=self.app.host_statuses) as hosts:
            self.show()
        self.assertIn("2", str(self.page.cards["codex"].servers_label.cget("text")))
        self.assertIn("2", str(self.page.servers_total.cget("text")))
        hosts.assert_not_called()  # counting servers doesn't ask the hosts again

    def test_end_idle_servers_asks_then_ends_only_those_idle_for_12_hours(self):
        self.assertEqual(connections_page.IDLE_SERVER_SECONDS, 12 * 3600)
        codex = self.connections.grant.connection_id
        old = self.server(codex, idle=timedelta(hours=13))
        recent = self.server(codex, idle=timedelta(hours=11, minutes=50))
        self.show()
        with patch.object(self.app, "confirm", return_value=False) as asked:
            self.assertEqual(self.page.end_idle_servers(), [])
        message = " ".join([asked.call_args.kwargs["title"], asked.call_args.kwargs.get("message", ""),
                            *asked.call_args.kwargs.get("points", ())])
        self.assertIn("1", asked.call_args.kwargs["title"])
        self.assertIn("next memory call", message)
        time.sleep(0.2)
        self.assertIsNone(old.poll())  # cancelled: nothing ended
        with patch.object(self.app, "confirm", return_value=True):
            self.assertEqual(self.page.end_idle_servers(), [old.pid])
        old.wait(10)
        self.assertIsNone(recent.poll())  # under 12 hours: still running
        self.assertEqual([r.pid for r in running(self.data)], [recent.pid])
        self.assertIn("1", str(self.page.servers_total.cget("text")))

    def test_with_no_idle_server_nothing_is_asked_or_ended(self):
        recent = self.server(self.connections.grant.connection_id, idle=timedelta(minutes=5))
        self.show()
        with patch.object(self.app, "confirm") as asked, patch.object(self.app, "notify") as notice:
            self.assertEqual(self.page.end_idle_servers(), [])
        asked.assert_not_called()
        notice.assert_called_once()
        self.assertIsNone(recent.poll())

    def test_nothing_ends_a_server_on_its_own(self):
        """No automatic ending in v0.4.4: whether a host starts a new server after one is ended (spike S-MCP) is not
        known yet."""
        old = self.server(self.connections.grant.connection_id, idle=timedelta(days=3))
        with patch.object(connections_page, "end_idle", side_effect=AssertionError("ended on its own")):
            self.show()
            self.page.refresh()
            self.app.show_page("dashboard")
            self.show()
        time.sleep(0.2)
        self.assertIsNone(old.poll())
        self.assertEqual(self.page.server_counts()[1], 1)


if __name__ == "__main__":
    unittest.main()
