# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The test sandbox (tests/sandbox.py) keeps every test away from the user's real data and host settings, also
when pytest is started directly without the sandboxed runner (owner, 2026-11-17).

Positive control: the same probe run without the conftest resolves BIO CE's data folder to the real one. The probe
only computes paths; nothing here opens or changes a real location (the guard tests use paths that don't exist, so
even a broken guard could not create anything).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import uuid

import pytest

from bio_ce import host_hooks
from bio_ce.desktop import AppDataPaths
from tests import sandbox

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "tests" / "unit" / "probe_sandbox.py"


def under(path, root) -> bool:
    path, root = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    return path == root or path.startswith(root + os.sep)


class SandboxInPlaceTests(unittest.TestCase):
    def test_the_users_folders_point_into_this_runs_sandbox(self):
        self.assertIsNotNone(sandbox.ROOT)
        for key in sandbox.REDIRECTED:
            with self.subTest(key):
                self.assertTrue(under(os.environ[key], sandbox.ROOT), os.environ[key])
                self.assertFalse(sandbox.is_protected(os.environ[key]))
        self.assertTrue(under(tempfile.gettempdir(), sandbox.ROOT))
        self.assertTrue(under(Path.home(), sandbox.ROOT))

    def test_bio_ce_data_and_host_settings_resolve_into_the_sandbox(self):
        for path in (AppDataPaths.from_local_app_data().root, host_hooks.claude_settings_path(os.environ),
                     host_hooks.codex_hooks_path(os.environ)):
            with self.subTest(str(path)):
                self.assertTrue(under(path, sandbox.ROOT))

    @unittest.skipUnless(sys.platform == "win32", "the real folders come from Windows")
    def test_the_real_locations_do_not_follow_a_changed_environment(self):
        """Found 2026-11-17: SHGetKnownFolderPath expands %USERPROFILE% from the process environment, so under the
        sandboxed runner it named the runner's folder. The token and Shell Folders lookups don't."""
        fake = {key: str(sandbox.ROOT / "fake" / key) for key in ("USERPROFILE", "LOCALAPPDATA", "APPDATA")}
        with unittest.mock.patch.dict(os.environ, fake):
            found = sandbox.real_locations()
        for key, value in found.items():
            with self.subTest(key):
                self.assertFalse(under(value, sandbox.ROOT), value)
                self.assertTrue(Path(value).is_dir(), value)
        self.assertEqual(found, sandbox.REAL)

    def test_the_real_locations_are_protected_and_nothing_else(self):
        for root in sandbox.protected_roots():
            self.assertTrue(sandbox.is_protected(root), root)
            self.assertTrue(sandbox.is_protected(root / "data" / "memories.sqlite3"), root)
        self.assertTrue(sandbox.is_protected("file:E:/BIO-CE/data/memories.sqlite3?mode=ro"))
        self.assertFalse(sandbox.is_protected("E:/BIO-CE-Public/tests"))  # a name that only starts the same
        self.assertFalse(sandbox.is_protected(sandbox.ROOT / "l" / "BIO-CE" / "data" / "memories.sqlite3"))
        self.assertFalse(sandbox.is_protected(":memory:"))
        if "LOCALAPPDATA" in sandbox.REAL:
            self.assertTrue(sandbox.is_protected(sandbox.REAL["LOCALAPPDATA"] / "BIO-CE" / "data"))

    @unittest.skipUnless("LOCALAPPDATA" in sandbox.REAL, "no real LOCALAPPDATA on this system")
    def test_the_guard_stops_the_run_before_a_real_path_is_touched(self):
        missing = sandbox.REAL["LOCALAPPDATA"] / "BIO-CE" / f"guard-probe-{uuid.uuid4().hex}"  # never exists
        mine = Path(tempfile.gettempdir()) / "mine.txt"
        mine.write_text("x", encoding="utf-8")
        for name, call in (
                ("sqlite3.connect", lambda: sqlite3.connect(f"file:{missing.as_posix()}/m.sqlite3?mode=ro", uri=True)),
                ("open for writing", lambda: open(missing / "x.txt", "w", encoding="utf-8")),
                ("open for reading", lambda: open(missing / "x.txt", encoding="utf-8")),
                ("Path.write_text", lambda: (missing / "x.txt").write_text("x", encoding="utf-8")),
                ("os.replace onto it", lambda: os.replace(mine, missing / "y.txt")),
                ("os.remove", lambda: os.remove(missing / "x.txt")),
                ("Path.mkdir", lambda: missing.mkdir(parents=True))):
            with self.subTest(name), self.assertRaises(pytest.exit.Exception):
                call()
        self.assertFalse(os.path.exists(missing))
        self.assertTrue(mine.exists())  # the replace never ran


def probe(*extra: str) -> dict:
    """Run the probe in a new pytest the way a developer would, in a real user's environment."""
    env = dict(os.environ)
    for key, value in (("LOCALAPPDATA", sandbox.REAL.get("LOCALAPPDATA")), ("APPDATA", sandbox.REAL.get("APPDATA")),
                       ("USERPROFILE", sandbox.REAL.get("USERPROFILE")), ("HOME", sandbox.REAL.get("USERPROFILE"))):
        if value is not None:
            env[key] = str(value)
    if "LOCALAPPDATA" in sandbox.REAL:
        env["TEMP"] = env["TMP"] = str(sandbox.REAL["LOCALAPPDATA"] / "Temp")
    for key in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "PYTEST_XDIST_WORKER", "PYTEST_CURRENT_TEST"):
        env.pop(key, None)
    out = Path(tempfile.gettempdir()) / f"probe-{uuid.uuid4().hex}.json"
    env["BIO_CE_PROBE_OUT"] = str(out)
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist",
                                *extra, str(PROBE)], cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
    if completed.returncode != 0:
        raise AssertionError(completed.stdout[-2000:] + completed.stderr[-2000:])
    return json.loads(out.read_text(encoding="utf-8"))


@unittest.skipUnless(sys.platform == "win32", "the real folders come from Windows")
class DirectPytestTests(unittest.TestCase):
    def test_pytest_run_directly_still_resolves_into_a_sandbox_that_is_removed_afterwards(self):
        found = probe()
        self.assertFalse(sandbox.is_protected(found["bio_ce_root"]), found)
        self.assertTrue(Path(found["localappdata"]).parent.name.startswith(sandbox.SANDBOX_PREFIX), found)
        self.assertNotEqual(os.path.normcase(found["bio_ce_root"]),
                            os.path.normcase(str(sandbox.REAL["LOCALAPPDATA"] / "BIO-CE")))
        self.assertFalse(Path(found["localappdata"]).parent.exists())  # its sandbox folder is gone

    def test_positive_control_without_the_conftest_it_would_be_the_real_data_folder(self):
        found = probe("--noconftest")  # the guard and the sandbox off: only paths are computed
        self.assertEqual(os.path.normcase(found["bio_ce_root"]),
                         os.path.normcase(str((sandbox.REAL["LOCALAPPDATA"] / "BIO-CE").resolve())))
        self.assertTrue(sandbox.is_protected(found["bio_ce_root"]))


if __name__ == "__main__":
    unittest.main()
