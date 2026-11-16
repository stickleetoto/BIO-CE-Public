# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Keyboard shortcuts, in one table (v0.4.4 F3): the Settings list is made from it, and a test checks that every
window-wide key in it is bound, so the list can't fall behind the keys again (inventory §13 item 12)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shortcut:
    keys: str  # as shown
    text: str  # i18n key of what it does
    sequences: tuple[str, ...] = ()  # Tk sequences bound on the window; empty for keys bound on one control


SHORTCUTS = (
    Shortcut("Ctrl+1 – Ctrl+4", "shortcut.pages", ("<Control-Key-1>", "<Control-Key-2>", "<Control-Key-3>",
                                                    "<Control-Key-4>")),
    Shortcut("Ctrl+F", "shortcut.search", ("<Control-f>",)),
    Shortcut("Ctrl+N", "shortcut.new", ("<Control-n>",)),
    Shortcut("E / Ctrl+E", "shortcut.edit", ("<KeyPress-e>", "<Control-e>")),
    Shortcut("M", "shortcut.move", ("<KeyPress-m>",)),
    Shortcut("Delete", "shortcut.delete", ("<Delete>",)),
    Shortcut("Ctrl+Z", "shortcut.undo", ("<Control-z>",)),
    Shortcut("Ctrl+S / Ctrl+Enter", "shortcut.save", ("<Control-s>",)),
    Shortcut("Enter", "shortcut.enter"),
    Shortcut("Esc", "shortcut.escape", ("<Escape>",)),
    Shortcut("Ctrl+H", "shortcut.history", ("<Control-h>",)),
    Shortcut("Ctrl+click / Space", "shortcut.select"),
    Shortcut("← ↑ → ↓", "shortcut.arrows"),
    Shortcut("Shift+F10", "shortcut.menu"),
    Shortcut("F5", "shortcut.refresh", ("<F5>",)),
    Shortcut("Tab / Shift+Tab", "shortcut.tab"),
)

__all__ = ["SHORTCUTS", "Shortcut"]
