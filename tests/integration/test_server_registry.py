# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 §9.2: running BIO CE MCP servers keep a record, and the user can end the long-idle ones."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from bio_ce import server_registry
from bio_ce.server_registry import ServerRecord, ServerRegistration, end_idle, folder, running
from tests.integration.test_mcp_scope_binding import MCPScopeBindingTests


def sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-registry-")
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        self.children: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for child in self.children:
            child.kill()
            child.wait(10)
        self.temp.cleanup()

    def record_for(self, child: subprocess.Popen, *, idle: timedelta, executable: str | None = None) -> None:
        stamp = (datetime.now(timezone.utc) - idle).isoformat(timespec="seconds").replace("+00:00", "Z")
        record = ServerRecord(child.pid, None, "", "conn", executable or server_registry.process_image(child.pid),
                              stamp, stamp)
        folder(self.data).mkdir(parents=True, exist_ok=True)
        (folder(self.data) / f"{child.pid}.json").write_text(json.dumps(asdict(record)), encoding="utf-8")

    def test_this_server_writes_touches_and_removes_its_record(self):
        clock = [0.0]
        registration = ServerRegistration(self.data, connection_id="conn", parent_pid=None, clock=lambda: clock[0])
        (record,) = running(self.data)
        self.assertEqual((record.connection_id, record.pid), ("conn", registration._record.pid))
        first = record.last_request_at
        clock[0] = 30.0
        registration._record = ServerRecord(**{**asdict(registration._record), "last_request_at": "2000-01-01T00:00:00Z"})
        registration.touch()  # within a minute: not written
        self.assertEqual(running(self.data)[0].last_request_at, first)
        clock[0] = 61.0
        registration.touch()
        self.assertNotEqual(running(self.data)[0].last_request_at, "2000-01-01T00:00:00Z")
        registration.remove()
        self.assertEqual(running(self.data), [])

    def test_a_record_whose_process_ended_is_removed_when_read(self):
        child = sleeper()
        self.record_for(child, idle=timedelta(0))
        self.assertEqual([r.pid for r in running(self.data)], [child.pid])  # positive control: alive is listed
        child.kill()
        child.wait(10)
        self.assertEqual(running(self.data), [])
        self.assertEqual(list(folder(self.data).glob("*.json")), [])

    def test_only_servers_idle_long_enough_are_ended(self):
        old, recent = sleeper(), sleeper()
        self.children += [old, recent]
        self.record_for(old, idle=timedelta(hours=13))
        self.record_for(recent, idle=timedelta(minutes=5))
        self.assertEqual(end_idle(self.data, 12 * 3600), [old.pid])
        old.wait(10)  # it really ended
        self.assertIsNone(recent.poll())  # the recent one is still running
        self.assertEqual([r.pid for r in running(self.data)], [recent.pid])

    def test_a_process_that_is_not_the_recorded_program_is_never_ended(self):
        child = sleeper()
        self.children.append(child)
        self.record_for(child, idle=timedelta(days=2), executable=r"C:\Somewhere\Else\BIO-CE-MCP.exe")
        self.assertEqual(end_idle(self.data, 60), [])
        time.sleep(0.2)
        self.assertIsNone(child.poll())  # still running
        self.assertEqual(running(self.data), [])  # and its stale record is gone


class ServerKeepsARecordTests(MCPScopeBindingTests):
    """A real stdio server: its record exists while it runs and is gone after the host closes stdin."""

    def test_a_running_server_has_a_record_until_it_ends(self):
        data = self.database.parent

        async def scenario():
            async with self.client() as client:
                await client.list_tools()
                return running(data)

        during = self.run_async(scenario())
        self.assertEqual(len(during), 1)
        self.assertEqual(during[0].connection_id, self.grant.connection_id)
        deadline = time.monotonic() + 10
        while running(data) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(running(data), [])

    # Only the test above in this class; the inherited scope tests run in their own file.
    test_scope_arguments_are_optional_in_every_tool_schema = None
    test_omitted_or_exact_scope_works_and_any_other_scope_is_refused = None


if __name__ == "__main__":
    unittest.main()
