# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U5 (design §6.3): Korean text reaches a file or a pipe as UTF-8, also without Python's UTF-8 mode, the way
the CLI runs from a host or a script on a Korean Windows (console code page 949). The MCP server's stderr and the
hooks' output are checked in their own tests (test_claude_desktop, test_memory_policy_and_hooks)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

KOREAN = "BIO CE 앱을 먼저 실행하세요 · 기억 ✓"


def run(code_or_args: list[str]) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items()
           if key not in ("PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO")}
    return subprocess.run([sys.executable, "-X", "utf8=0", *code_or_args], capture_output=True, env=env, timeout=60)


class Utf8OutputTests(unittest.TestCase):
    def test_redirected_output_is_utf8_without_utf8_mode(self):
        done = run(["-c", f"from bio_ce.cli import utf8_output; utf8_output(); print({KOREAN!r}); "
                          f"import sys; print({KOREAN!r}, file=sys.stderr)"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.decode("utf-8").strip(), KOREAN)
        self.assertEqual(done.stderr.decode("utf-8").strip(), KOREAN)

    @unittest.skipUnless(sys.platform == "win32", "the console code page is a Windows matter")
    def test_positive_control_without_it_the_code_page_breaks_the_text(self):
        done = run(["-c", f"print({KOREAN!r})"])
        broken = done.returncode != 0
        if not broken:
            try:
                broken = done.stdout.decode("utf-8").strip() != KOREAN
            except UnicodeDecodeError:
                broken = True
        self.assertTrue(broken, "without utf8_output the code page should not give UTF-8 here")

    def test_the_cli_command_writes_utf8(self):
        with tempfile.TemporaryDirectory(prefix="bio-ce-utf8-") as folder:
            done = run(["-m", "bio_ce", "seed-synthetic-mcp-demo", "--db", str(Path(folder) / "기억 데모.sqlite3")])
            self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
            self.assertIn("Seeded", done.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
