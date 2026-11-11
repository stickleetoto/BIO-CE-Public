# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""A stdio MCP server must not outlive its host.

Reproduces the v0.4.0 accumulation: a long-lived host (the Codex desktop app's app-server) keeps one
server per thread with stdin open and never exits, so servers piled up. Each server now leaves when
stdin closes, when the process that started it ends, or after a period without requests.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from mcp import Client, StdioServerParameters, stdio_client

from bio_ce.control_store import MODE_AUTO_MEMORY, ControlStore, control_database_for
from bio_ce.demo_fixture import DEMO_NAMESPACE, DEMO_PROJECT, seed_synthetic_mcp_demo
from bio_ce.desktop import BackupConflictError, DesktopMemoryService
from bio_ce.server_lifetime import IDLE_ENVIRONMENT_VARIABLE, RELEASE_ENVIRONMENT_VARIABLE, process_alive

_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# A virtual environment's python.exe is a stub that starts the real interpreter as its child, so killing
# it would leave the server running and add a process between host and server. The packaged
# BIO-CE-MCP.exe has no such stub: run the base interpreter directly with this environment's packages.
PYTHON = getattr(sys, "_base_executable", sys.executable)
PYTHONPATH = os.pathsep.join(entry for entry in sys.path if entry)


def _server_command(database: Path) -> list[str]:
    return [PYTHON, "-m", "bio_ce", "mcp-stdio", "--db", str(database),
            "--project", DEMO_PROJECT, "--namespace", DEMO_NAMESPACE]


def _wait_until(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return predicate()


class ServerLifetimeTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="bio-ce-lifetime-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.database = self.root / "lifetime.sqlite3"
        seed_synthetic_mcp_demo(self.database)

    def _start(self, idle: str | None) -> subprocess.Popen:
        env = dict(os.environ, PYTHONPATH=PYTHONPATH)
        env.pop(IDLE_ENVIRONMENT_VARIABLE, None)
        if idle is not None:
            env[IDLE_ENVIRONMENT_VARIABLE] = idle
        process = subprocess.Popen(_server_command(self.database), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env, creationflags=_FLAGS)
        self.addCleanup(self._stop, process)
        return process

    @staticmethod
    def _stop(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def test_server_exits_when_stdin_closes(self):
        process = self._start(idle="0")
        time.sleep(1.5)
        self.assertIsNone(process.poll(), "the server should be running while its host keeps stdin open")
        process.stdin.close()
        self.assertTrue(_wait_until(lambda: process.poll() is not None, 15), "server ignored stdin EOF")
        self.assertEqual(process.returncode, 0)

    def test_idle_servers_from_a_long_lived_host_do_not_accumulate(self):
        # Without a time limit, servers of a host that never closes stdin stay forever (the v0.4.0 behaviour).
        unlimited = [self._start(idle="0") for _ in range(2)]
        limited = [self._start(idle="2") for _ in range(3)]
        self.assertTrue(_wait_until(lambda: all(p.poll() is not None for p in limited), 30),
                        "idle servers kept running after the idle limit")
        self.assertTrue(all(p.returncode == 0 for p in limited))
        self.assertTrue(all(p.poll() is None for p in unlimited), "idle limit 0 must turn the limit off")

    def test_a_request_resets_the_idle_timer(self):
        environment = dict(os.environ, PYTHONPATH=PYTHONPATH, **{IDLE_ENVIRONMENT_VARIABLE: "3"})
        parameters = StdioServerParameters(command=PYTHON, args=_server_command(self.database)[1:],
                                           env=environment)
        stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        self.addCleanup(stderr.close)

        async def exercise() -> None:
            async with Client(stdio_client(parameters, errlog=stderr)) as client:
                for _ in range(3):  # 3 x 2 s of steady use outlasts one idle period
                    await asyncio.sleep(2)
                    result = await client.call_tool("bio_memory_search", {"query": "synthetic", "limit": 1})
                    self.assertFalse(result.is_error)

        asyncio.run(asyncio.wait_for(exercise(), timeout=60))

    def _restore_while_a_server_is_connected(self, release: str) -> tuple[bool, bool]:
        """Restore a backup in the desktop app while a managed MCP server is connected but idle.

        Returns (restore succeeded, the server still answers afterwards and sees the restored data)."""
        database = self.root / f"personal-{release}.sqlite3"
        service = DesktopMemoryService(database)
        self.addCleanup(service.close)
        service.add(title="Before backup", content="synthetic backup restore marker before", source_ref="user-input")
        backup = service.create_backup(self.root / f"backup-{release}.sqlite3")
        service.add(title="After backup", content="synthetic restore marker after", source_ref="user-input")
        with ControlStore(control_database_for(database)) as control:
            grant, token = control.create_grant("codex", project="bio-ce-personal", namespace="default")
            control.set_mode(grant.connection_id, MODE_AUTO_MEMORY)
        environment = dict(os.environ, PYTHONPATH=PYTHONPATH, BIO_CE_CONNECTION_TOKEN=token,
                           **{RELEASE_ENVIRONMENT_VARIABLE: release})
        parameters = StdioServerParameters(command=PYTHON, args=[
            "-m", "bio_ce", "mcp-stdio", "--db", str(database), "--connection", grant.connection_id], env=environment)
        stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        self.addCleanup(stderr.close)
        outcome: dict[str, bool] = {}

        async def exercise() -> None:
            async with Client(stdio_client(parameters, errlog=stderr)) as client:
                first = await client.call_tool("bio_memory_search", {"query": "marker", "limit": 5})
                self.assertFalse(first.is_error)
                await asyncio.sleep(4)  # longer than the release time (2 s) when it is on
                try:
                    service.restore_backup(backup)
                    outcome["restored"] = True
                except BackupConflictError:
                    outcome["restored"] = False
                after = await client.call_tool("bio_memory_search", {"query": "marker", "limit": 5})
                titles = {hit["title"] for hit in after.structured_content["results"]} if not after.is_error else set()
                outcome["answers"] = not after.is_error and (
                    titles == {"Before backup"} if outcome["restored"] else bool(titles))

        asyncio.run(asyncio.wait_for(exercise(), timeout=90))
        return outcome["restored"], outcome["answers"]

    def test_an_idle_server_releases_the_database_so_a_restore_works(self):
        restored, answers = self._restore_while_a_server_is_connected("2")
        self.assertTrue(restored, "the restore was blocked although the connected server was idle")
        self.assertTrue(answers, "the server did not reopen the database and see the restored memories")
        # Control: with releasing turned off, the connected server keeps the database open and blocks it.
        restored, answers = self._restore_while_a_server_is_connected("0")
        self.assertFalse(restored)
        self.assertTrue(answers)

    def test_server_exits_when_the_process_that_started_it_ends(self):
        # The launcher keeps a copy of the server's stdin in a holder process, so stdin never reaches EOF:
        # only the parent watch can end the server.
        python, command, path = PYTHON, _server_command(self.database), PYTHONPATH
        launcher = self.root / "launcher.py"
        launcher.write_text(textwrap.dedent(f"""
            import msvcrt, os, subprocess, sys, time
            env = dict(os.environ)
            env[{IDLE_ENVIRONMENT_VARIABLE!r}] = "0"
            env["PYTHONPATH"] = {path!r}
            server = subprocess.Popen({command!r}, stdin=subprocess.PIPE,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            os.set_handle_inheritable(msvcrt.get_osfhandle(server.stdin.fileno()), True)
            holder = subprocess.Popen([{python!r}, "-c", "import time; time.sleep(120)"], close_fds=False)
            print(server.pid, holder.pid, flush=True)
            time.sleep(120)
        """), encoding="utf-8")
        if sys.platform != "win32":
            self.skipTest("the launcher uses Windows handle inheritance")
        launched = subprocess.Popen([python, str(launcher)], stdout=subprocess.PIPE, text=True,
                                    creationflags=_FLAGS, env=dict(os.environ, PYTHONPATH=path))
        self.addCleanup(self._stop, launched)
        server_pid, holder_pid = (int(value) for value in launched.stdout.readline().split())
        self.addCleanup(lambda: subprocess.run(["taskkill", "/F", "/PID", str(holder_pid)],
                                               capture_output=True, creationflags=_FLAGS))
        self.addCleanup(lambda: subprocess.run(["taskkill", "/F", "/PID", str(server_pid)],
                                               capture_output=True, creationflags=_FLAGS))
        time.sleep(2)
        self.assertTrue(process_alive(server_pid), "the server should run while its parent runs")
        launched.kill()
        launched.wait(timeout=10)
        self.assertTrue(process_alive(holder_pid), "the holder keeps stdin open, so EOF cannot end the server")
        self.assertTrue(_wait_until(lambda: not process_alive(server_pid), 20),
                        "the server kept running after its parent ended")


if __name__ == "__main__":
    unittest.main()
