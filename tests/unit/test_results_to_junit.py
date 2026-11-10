# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The installer E2E JUnit converter reports NOT RUN steps as skipped and failed steps as failures."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host_harness"))
import results_to_junit  # noqa: E402


class ResultsToJunitTests(unittest.TestCase):
    def test_pass_fail_and_not_run_are_kept_apart(self):
        with tempfile.TemporaryDirectory(prefix="bio-ce-junit-") as scratch:
            results = Path(scratch) / "results.jsonl"
            results.write_text("\n".join(json.dumps(step, ensure_ascii=False) for step in (
                {"step": "install", "ok": True, "version": "0.4.0-rc1"},
                {"step": "codex-registration", "ok": True, "result": "NOT RUN: CLI not installed"},
                {"step": "upgrade-preserves-data", "ok": False, "detail": "한글 detail"},
            )) + "\n", encoding="utf-8")
            junit = Path(scratch) / "out" / "junit.xml"
            counts = results_to_junit.convert(results, junit, "release-e2e")
            self.assertEqual(counts, {"tests": 3, "failures": 1, "skipped": 1})
            suite = ElementTree.parse(junit).getroot().find("testsuite")
            self.assertEqual((suite.get("tests"), suite.get("failures"), suite.get("skipped")), ("3", "1", "1"))
            cases = {case.get("name"): case for case in suite.iter("testcase")}
            self.assertIsNone(cases["install"].find("failure"))
            self.assertIsNotNone(cases["codex-registration"].find("skipped"))
            self.assertIn("한글 detail", cases["upgrade-preserves-data"].find("failure").text)
            self.assertEqual(results_to_junit.main([str(results), str(junit)]), 1)


if __name__ == "__main__":
    unittest.main()
