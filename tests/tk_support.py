# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Shared Tk test helpers."""

from __future__ import annotations

import time
import tkinter as tk

# Messages Tcl raises when it cannot read its own script library while a new
# interpreter starts. On the qualification machine these appeared intermittently
# for files that exist (for example ``auto.tcl``, ``init.tcl``, ``tk.tcl``), on two
# different CPython installations, inside ``_tkinter.create`` before any BIO CE
# code runs. They are environmental file-access failures, not application errors.
_TCL_LIBRARY_LOAD_ERRORS = (
    "couldn't read file",
    "Can't find a usable",
    "tcl_findLibrary",
    "invalid command name",
)


def new_tk_root(attempts: int = 5) -> tk.Tk:
    """Create a Tk root, retrying only Tcl script-library load failures."""
    for attempt in range(1, attempts + 1):
        try:
            return tk.Tk()
        except tk.TclError as exc:
            if attempt == attempts or not any(marker in str(exc) for marker in _TCL_LIBRARY_LOAD_ERRORS):
                raise
            time.sleep(0.2 * attempt)
    raise AssertionError("unreachable")


__all__ = ["new_tk_root"]
