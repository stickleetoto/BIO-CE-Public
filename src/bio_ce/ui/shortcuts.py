# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Keyboard shortcuts, in one table (v0.4.4 F3): the Settings list is made from it, and a test checks that every
window-wide key in it is bound, so the list can't fall behind the keys again (inventory §13 item 12)."""

from __future__ import annotations

from dataclasses import dataclass

from bio_ce.ui.i18n import t


@dataclass(frozen=True)
class Shortcut:
    keys: str  # key names as written on keyboards (Ctrl, Shift, Space) and the word "click"
    text: str  # i18n key of what it does
    sequences: tuple[str, ...] = ()  # Tk sequences bound on the window; empty for keys bound on one control

    @property
    def shown(self) -> str:
        """The keys as the list shows them: key names stay as on the keyboard, "click" is in the app's language
        ("Ctrl+click" stayed English in the Korean list in rc1)."""
        return self.keys.replace("click", t("shortcut.click"))


SHORTCUTS = (
    Shortcut("Ctrl+1 – Ctrl+4", "shortcut.pages", ("<Control-Key-1>", "<Control-Key-2>", "<Control-Key-3>",
                                                    "<Control-Key-4>")),
    Shortcut("Ctrl+F / /", "shortcut.search", ("<Control-f>", "<slash>")),
    Shortcut("?", "shortcut.list", ("<question>",)),
    Shortcut("Ctrl+N", "shortcut.new", ("<Control-n>",)),
    Shortcut("E / Ctrl+E", "shortcut.edit", ("<KeyPress-e>", "<Control-e>")),
    Shortcut("M", "shortcut.move", ("<KeyPress-m>",)),
    Shortcut("Delete", "shortcut.delete", ("<Delete>",)),
    Shortcut("Ctrl+Z", "shortcut.undo", ("<Control-z>",)),
    Shortcut("Ctrl+S / Ctrl+Enter", "shortcut.save", ("<Control-s>",)),
    Shortcut("Enter", "shortcut.enter"),
    Shortcut("Esc", "shortcut.escape", ("<Escape>",)),
    Shortcut("Ctrl+H", "shortcut.history", ("<Control-h>",)),
    Shortcut("Ctrl+click / Shift+click / Space", "shortcut.select"),
    Shortcut("← ↑ → ↓", "shortcut.arrows"),
    Shortcut("Shift+F10", "shortcut.menu"),
    Shortcut("F5", "shortcut.refresh", ("<F5>",)),
    Shortcut("Tab / Shift+Tab", "shortcut.tab"),
)

__all__ = ["SHORTCUTS", "Shortcut"]
