# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The per-test time limit ends a hung run quickly and leaves normal runs alone."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[2]


def run(body: str, limit: str) -> tuple[int, float, str]:
    with tempfile.TemporaryDirectory(prefix="bio-ce-time-limit-") as folder:
        test = Path(folder) / "test_probe.py"
        test.write_text(body, encoding="utf-8")
        log = Path(folder) / "timeout.log"
        env = {**os.environ, "BIO_CE_TEST_TIMEOUT": limit, "PYTHONPATH": str(REPO),
               "BIO_CE_TEST_TIMEOUT_LOG": str(log)}
        # The child's own ini and root keep its collection inside this folder: with the repository as its root it
        # walked the shared temporary folder, where another worker's sandbox can vanish mid-walk (seen 2026-11-17).
        ini = Path(folder) / "pytest.ini"
        ini.write_text("[pytest]\n", encoding="utf-8")
        started = time.monotonic()
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p",
                               "tests.time_limit", "-c", str(ini), "--rootdir", folder, str(test)], cwd=folder,
                              env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=120)  # UTF-8, not the console code page
        seconds = time.monotonic() - started
        trace = log.read_text(encoding="utf-8") if log.exists() else ""
        return done.returncode, seconds, done.stdout + done.stderr + trace


class TimeLimitTests(unittest.TestCase):
    def test_a_hung_test_ends_the_run_and_shows_where_it_waited(self):
        code, seconds, output = run("import time\n\ndef test_hangs():\n    time.sleep(60)\n", "2")
        self.assertNotEqual(code, 0)
        self.assertLess(seconds, 40)
        self.assertIn("time limit (2 s) reached in", output)
        self.assertIn("test_hangs", output)
        self.assertIn("Timeout", output)  # faulthandler's own header with every thread's stack

    def test_ui_modules_get_the_shorter_limit(self):
        from tests.time_limit import limit_seconds
        self.assertEqual(limit_seconds(r"C:\repo\tests\integration\test_export_ui.py"), 120)
        self.assertEqual(limit_seconds(r"C:\repo\tests\integration\test_import.py"), 600)

    def test_a_quick_test_passes_under_the_limit(self):
        code, _seconds, output = run("def test_quick():\n    assert 1 + 1 == 2\n", "30")
        self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()
