# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Long text in a Treeview column (v0.4.4 K3): shortened with "…" to the column's width, whole in a row tooltip.

A Treeview cuts a cell at the column edge with no sign that there is more. ``ElidedColumn`` keeps each row's full
text and shows as much as fits, ending in "…"; it fits again whenever the column gets another width.
``RowTooltip`` shows the full text of the row under the pointer.
"""

from __future__ import annotations

from typing import Callable
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from bio_ce.ui.theme import Theme
from bio_ce.ui.widgets import Tooltip, style_padding_x

ELLIPSIS = "…"


def elide(text: str, measure: Callable[[str], int], width: int) -> str:
    """``text`` if it is at most ``width`` px wide, otherwise its longest start that fits with "…" after it."""
    if measure(text) <= width:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle].rstrip() + ELLIPSIS) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + ELLIPSIS


def _tree_font(tree: ttk.Treeview, theme: Theme) -> tkfont.Font:
    style = str(tree.cget("style")) or tree.winfo_class()
    try:
        return tkfont.nametofont(str(ttk.Style(tree).lookup(style, "font")))
    except (tk.TclError, ValueError):
        return theme.font("body")


class ElidedColumn:
    """One column of ``tree`` whose cells end in "…" when their text is wider than the column."""

    def __init__(self, tree: ttk.Treeview, theme: Theme, column: str) -> None:
        self.tree = tree
        self.theme = theme
        self.column = column
        self.full: dict[str, str] = {}
        self._width: int | None = None
        # Bound after fit_tree_columns, so this runs once the column has its new width.
        tree.bind("<Configure>", lambda _event: self.fit(), add="+")

    def text(self, iid: str) -> str:
        return self.full.get(iid, "")

    def set(self, iid: str, text: str) -> None:
        self.full[iid] = " ".join(text.split())
        self._width = None

    def clear(self) -> None:
        self.full.clear()
        self._width = None

    def fit(self) -> None:
        try:
            pad = style_padding_x(self.tree, ".Item") or self.theme.px(20)
            width = int(self.tree.column(self.column, "width")) - pad - 2
        except tk.TclError:
            return  # the window is closing
        if width == self._width:
            return
        self._width = width
        measure = _tree_font(self.tree, self.theme).measure
        for iid, text in self.full.items():
            if not self.tree.exists(iid):
                continue
            shown = elide(text, measure, max(width, 1))
            if str(self.tree.set(iid, self.column)) != shown:
                self.tree.set(iid, self.column, shown)


class RowTooltip(Tooltip):
    """A tooltip with the text ``text_for(row)`` of the Treeview row under the pointer, wrapped to a readable width."""

    def __init__(self, tree: ttk.Treeview, theme: Theme, text_for: Callable[[str], str]) -> None:
        super().__init__(tree, theme, "")
        self.tree = tree
        self.text_for = text_for
        self.row = ""
        tree.bind("<Motion>", self._moved, add="+")
        tree.bind("<Leave>", lambda _event: self._forget_row(), add="+")

    def _forget_row(self) -> None:
        self.row = ""
        self.text = ""

    def _moved(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row == self.row:
            return
        self._hide()
        self.row = row
        self.text = self.text_for(row) if row else ""
        self._schedule()

    def _show(self) -> None:
        self._after = None
        if self._window is not None or not self.text or not self.tree.winfo_ismapped():
            return
        c, theme = self.theme.colors, self.theme
        window = tk.Toplevel(self.tree)
        window.wm_overrideredirect(True)
        window.configure(background=c.border_strong)
        tk.Label(window, text=self.text, background=c.surface_alt, foreground=c.text, font=theme.font("caption"),
                 justify="left", anchor="w", wraplength=theme.px(480), padx=theme.px(8), pady=theme.px(4)).pack(
            padx=1, pady=1)
        box = self.tree.bbox(self.row) if self.row and self.tree.exists(self.row) else ""
        x = self.tree.winfo_pointerx() + theme.px(12)
        y = self.tree.winfo_rooty() + (box[1] + box[3] if box else self.tree.winfo_height()) + theme.px(4)
        window.wm_geometry(f"+{x}+{y}")
        self._window = window
