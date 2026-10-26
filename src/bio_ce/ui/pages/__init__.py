# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Top-level screens of the desktop app."""

from __future__ import annotations

from typing import TYPE_CHECKING
import tkinter as tk

if TYPE_CHECKING:
    from bio_ce.ui.app import BIOCEDesktop


class Page(tk.Frame):
    """Base screen. The shell shows ``title``/``subtitle`` and the ``actions`` frame in its header."""

    key = ""
    nav_key = ""
    title = ""
    subtitle = ""

    def __init__(self, app: "BIOCEDesktop", master: tk.Misc) -> None:
        super().__init__(master, background=app.theme.colors.bg)
        self.app = app
        self.theme = app.theme
        self.colors = app.theme.colors
        self.actions = tk.Frame(app.header_actions, background=app.theme.colors.bg)
        self.stale = True

    def heading(self) -> tuple[str, str]:
        return self.title, self.subtitle

    def refresh(self) -> None:
        """Reload data from the store or host configuration."""
        self.stale = False

    def on_show(self) -> None:
        if self.stale:
            self.refresh()

    def focus_default(self) -> None:
        self.focus_set()


__all__ = ["Page"]
