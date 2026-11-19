# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Named test bundles (owner test rules, 2026-11-17), as pytest markers set at collection.

``data_safety``: the tests that guard against data loss and overwriting. They run before every commit together with
the tests of the changed modules, and they are never skipped before a candidate or a release::

    python -m pytest -m data_safety

- the invariant test (no action removes a row unless it is a delete),
- byte-search tests (deleted or refused text is not in the database, its log, the control file, or a backup),
- backup and restore tests,
- undo tests that must never overwrite a memory changed meanwhile,
- the test sandbox tests (no test reaches the user's real data or host settings).

A module listed with ``None`` is in the bundle whole; otherwise only its tests whose name contains one of the
words. ``tests/unit/test_test_bundles.py`` checks that every entry still matches a test, so a rename can't empty
the bundle quietly.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

DATA_SAFETY: dict[str, tuple[str, ...] | None] = {
    # Invariant
    "tests/integration/test_no_silent_deletes.py": None,
    # Byte search
    "tests/integration/test_forget_completely.py": None,
    "tests/integration/test_backup_pair_and_discard.py": None,
    "tests/integration/test_kept_originals_erase.py": None,
    "tests/integration/test_kept_still_referenced.py": None,  # rc4: forget never takes another memory's kept item
    "tests/integration/test_forget_kept_ui.py": None,  # rc4: the same through the app (Ctrl+Z, a covered Undo)
    "tests/integration/test_import.py": ("never_stored",),
    # Backup and restore
    "tests/integration/test_auto_backup_keep.py": None,
    "tests/integration/test_stabilization_paths_and_reviews.py": ("backup_and_restore",),
    "tests/unit/test_desktop.py": ("backup", "restore"),
    "tests/integration/test_mcp_server_lifetime.py": ("restore",),
    # Undo never overwrites a memory that changed meanwhile
    "tests/integration/test_inbox_move_undo.py": None,
    # Tests can't reach real user data (the sandbox and its guard)
    "tests/unit/test_test_sandbox.py": None,
}

MARKERS = {
    "data_safety": "invariant, byte-search, and backup/restore tests (never skipped before a candidate or release)",
    "ui": "tests that open Tk windows; run them one at a time (slow and unstable side by side)",
}

# ``ui``: a test module that opens Tk windows, found from its source so a new UI test is never missed. Side by side
# (pytest-xdist) these ran about five times slower each, so a full run is split (owner test rules, 2026-11-17):
#     python -m pytest -m "not ui" --numprocesses=8 --dist=load
#     python -m pytest -m ui
_UI_SOURCE = re.compile(r"^\s*(?:import tkinter|from tkinter|from tests\.tk_support|from tests\.integration\.\S+ import .*"
                        r"\bnew_root\b)|BIOCEDesktop\(", re.MULTILINE)
_ui_modules: dict[Path, bool] = {}


def opens_windows(path: str | Path) -> bool:
    path = Path(path)
    if path not in _ui_modules:
        try:
            _ui_modules[path] = bool(_UI_SOURCE.search(path.read_text(encoding="utf-8")))
        except OSError:
            _ui_modules[path] = False
    return _ui_modules[path]

_ROOT = Path(__file__).resolve().parent.parent


def _relative(path: str | Path) -> str:
    try:
        return Path(path).resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def in_data_safety(path: str | Path, test_name: str) -> bool:
    key = _relative(path)
    if key not in DATA_SAFETY:
        return False
    words = DATA_SAFETY[key]
    return words is None or any(word in test_name for word in words)


def pytest_configure(config: pytest.Config) -> None:
    for name, text in MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {text}")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if in_data_safety(item.path, item.name):
            item.add_marker(pytest.mark.data_safety)
        if opens_windows(item.path):
            item.add_marker(pytest.mark.ui)
