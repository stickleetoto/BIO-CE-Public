# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""UI test windows stay out of the user's way (owner test rules, 2026-11-17). A pytest plugin, tests only.

Every Tk window a test opens (the app's main window, dialogs, tooltips):

- opens and stays off the screen: a position the app asks for on the screen is moved by ``OFFSET`` on both axes, so
  where a window sits *relative* to another (a dialog over its parent, a tooltip under its widget) is unchanged, and
  sizes are untouched, so the cut-off checks still measure real, mapped widgets;
- is a tool window, so it never appears on the taskbar;
- never takes the foreground from the user: on Windows, while the tests run, this process locks
  SetForegroundWindow (LockSetForegroundWindow). A test run started from the app the user is in inherits the right
  to come to the front, and Tk uses it when a window is mapped or focused; WS_EX_NOACTIVATE did not stop that
  (probe 2026-11-17: 60 of 60 checks in the foreground without the lock, 0 of 60 with it). The user's own click or
  Alt key always ends the lock, and it is released when the tests end;
- ``focus_force`` is never called: it becomes ``focus_set`` (keyboard focus inside the test window only).

``BIO_CE_TEST_ONSCREEN=1`` turns this off to watch a test. The app code is not changed.
"""

from __future__ import annotations

import os
import re
import sys
import tkinter as tk

OFFSET = -30000  # well past any monitor arrangement, inside the 16-bit range Windows keeps window positions in
_ON_SCREEN_LIMIT = OFFSET // 2  # a position left of / above this was already moved (or placed relative to one)
_POSITION = re.compile(r"^(?P<size>\d+x\d+)?(?P<x>[+-]-?\d+)(?P<y>[+-]-?\d+)$")
_originals: dict[str, object] = {}


def enabled() -> bool:
    return os.environ.get("BIO_CE_TEST_ONSCREEN", "") != "1"


def moved(geometry: str) -> str:
    """``geometry`` with an on-screen ``+x+y`` moved off the screen; a size alone, or ``-x`` forms, as they are."""
    match = _POSITION.match(geometry)
    if match is None or not match["x"].startswith("+") or not match["y"].startswith("+"):
        return geometry
    x, y = int(match["x"][1:]), int(match["y"][1:])
    if x > _ON_SCREEN_LIMIT:
        x += OFFSET
    if y > _ON_SCREEN_LIMIT:
        y += OFFSET
    return f"{match['size'] or ''}+{x}+{y}"


def _lock_foreground(lock: bool) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.WinDLL("user32").LockSetForegroundWindow(1 if lock else 2)  # LSFW_LOCK / LSFW_UNLOCK


def _prepare(window: tk.Wm) -> None:
    """Before the window is first shown: off the screen and no taskbar button."""
    _originals["wm_geometry"](window, f"+{OFFSET}+{OFFSET}")
    if sys.platform == "win32":
        try:
            window.wm_attributes("-toolwindow", True)
        except tk.TclError:
            pass


def install() -> None:
    if _originals or not enabled():
        return
    _lock_foreground(True)
    _originals.update(wm_geometry=tk.Wm.wm_geometry, tk_init=tk.Tk.__init__, top_init=tk.Toplevel.__init__,
                      focus_force=tk.Misc.focus_force)

    def wm_geometry(self, newGeometry=None):
        if newGeometry is None:
            return _originals["wm_geometry"](self)
        return _originals["wm_geometry"](self, moved(str(newGeometry)))

    def tk_init(self, *args, **kwargs):
        _originals["tk_init"](self, *args, **kwargs)
        _prepare(self)

    def top_init(self, *args, **kwargs):
        _originals["top_init"](self, *args, **kwargs)
        _prepare(self)

    def focus_force(self):  # never take the foreground from the user's own work
        return self.focus_set()

    tk.Wm.wm_geometry = tk.Wm.geometry = wm_geometry
    tk.Tk.__init__ = tk_init
    tk.Toplevel.__init__ = top_init
    tk.Misc.focus_force = tk.Misc.focus = focus_force


def uninstall() -> None:
    if not _originals:
        return
    tk.Wm.wm_geometry = tk.Wm.geometry = _originals["wm_geometry"]
    tk.Tk.__init__ = _originals["tk_init"]
    tk.Toplevel.__init__ = _originals["top_init"]
    tk.Misc.focus_force = _originals["focus_force"]
    tk.Misc.focus = tk.Misc.focus_set
    _originals.clear()
    _lock_foreground(False)


def pytest_configure(config) -> None:
    install()


def pytest_unconfigure(config) -> None:
    uninstall()
