# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""A time limit for every test (pytest plugin, standard library only).

A UI test that waits on a window or dialog that never closes would otherwise hang the whole run. After the limit
(BIO_CE_TEST_TIMEOUT seconds; default 600, because the installer build tests are the slowest) every thread's stack
is written to a log file and the test process ends with exit code 1: a hard failure that says where it was stuck,
instead of a run that never finishes.

pytest captures stderr at the file-descriptor level, so the stacks go to BIO_CE_TEST_TIMEOUT_LOG (default
``%TEMP%\\bio-ce-test-timeout.log``), which survives the process ending.
"""

from __future__ import annotations

import faulthandler
import os
from pathlib import Path
import tempfile

import pytest

_log = None


def limit_seconds(path: str = "") -> int:
    """UI test modules (``*_ui*.py``) get BIO_CE_UI_TEST_TIMEOUT (default 120 s); others BIO_CE_TEST_TIMEOUT."""
    name, default = ("BIO_CE_UI_TEST_TIMEOUT", 120) if "_ui" in Path(path).name else ("BIO_CE_TEST_TIMEOUT", 600)
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def log_path() -> Path:
    return Path(os.environ.get("BIO_CE_TEST_TIMEOUT_LOG") or Path(tempfile.gettempdir()) / "bio-ce-test-timeout.log")


def _open_log():
    global _log
    if _log is None:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _log = open(path, "w", encoding="utf-8")  # noqa: SIM115 - kept open for faulthandler
    return _log


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """Covers setup, the test, and teardown (closing the app window can hang too)."""
    seconds = limit_seconds(str(item.fspath))
    log = _open_log()
    log.seek(0)
    log.truncate()
    log.write(f"BIO CE test time limit ({seconds} s) reached in {item.nodeid}\n")
    log.flush()
    faulthandler.dump_traceback_later(seconds, exit=True, file=log)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()
