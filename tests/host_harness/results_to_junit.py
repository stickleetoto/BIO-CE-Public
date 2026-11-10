# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Convert an installer E2E ``results.jsonl`` (install_e2e.py / release_e2e.py) into JUnit XML.

Each step becomes a test case. A step whose details say "NOT RUN" (for example, a host CLI that is not
installed on the runner) is reported as skipped, not passed, so CI summaries cannot overstate coverage.

Usage: python results_to_junit.py RESULTS_JSONL JUNIT_XML [SUITE_NAME]
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from xml.etree import ElementTree


def is_not_run(step: dict) -> bool:
    return any(isinstance(value, str) and value.startswith("NOT RUN") for value in step.values())


def convert(results: Path, junit: Path, suite: str) -> dict[str, int]:
    steps = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts = {"tests": len(steps), "failures": 0, "skipped": 0}
    suite_element = ElementTree.Element("testsuite", name=suite)
    for step in steps:
        case = ElementTree.SubElement(suite_element, "testcase", classname=suite, name=str(step.get("step")))
        detail = json.dumps({k: v for k, v in step.items() if k not in ("step", "ok")}, ensure_ascii=False,
                            default=str)
        if is_not_run(step):
            counts["skipped"] += 1
            ElementTree.SubElement(case, "skipped", message="NOT RUN")
        elif not step.get("ok"):
            counts["failures"] += 1
            ElementTree.SubElement(case, "failure", message="step failed").text = detail[:4000]
        ElementTree.SubElement(case, "system-out").text = detail[:4000]
    suite_element.set("tests", str(counts["tests"]))
    suite_element.set("failures", str(counts["failures"]))
    suite_element.set("errors", "0")
    suite_element.set("skipped", str(counts["skipped"]))
    root = ElementTree.Element("testsuites")
    root.append(suite_element)
    junit.parent.mkdir(parents=True, exist_ok=True)
    ElementTree.ElementTree(root).write(junit, encoding="utf-8", xml_declaration=True)
    return counts


def main(argv: list[str]) -> int:
    results, junit = Path(argv[0]), Path(argv[1])
    suite = argv[2] if len(argv) > 2 else results.parent.name
    counts = convert(results, junit, suite)
    print(f"{suite}: {counts['tests']} steps, {counts['failures']} failed, {counts['skipped']} not run")
    return 0 if counts["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
