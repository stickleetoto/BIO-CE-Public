# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Layout audit for the desktop app: what is cut off or pushed out of view. Test helper only.

A widget the user should see is a problem when it is

- cut: given less width (or height) than it asks for — a cut-off Button ignores clicks, a cut-off label hides text;
- off view: its right or bottom edge is outside the window, or, inside a scrolling area, outside the area's width
  (scrolling areas scroll vertically, so only their width counts);
- a table whose columns are wider than the table (the right columns are off the edge);
- squeezed out: laid out (pack/grid/place) inside a visible parent but given no room at all, so Tk hides it.
  Without this check such a widget would just be skipped as "not visible".

Checked: Buttons, labels (WrapLabel only for being off view: it wraps by design; ElideLabel for its shown text
fitting after shortening), badges (Pill), check and radio buttons, combo boxes, and tables. Entry fields and text areas are not: they scroll their own text.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from bio_ce.ui.widgets import Button, ElideLabel, Pill, WrapLabel
from bio_ce.ui.widgets import style_padding_x as _style_padding_x

TOLERANCE = 1
HEADING_DIVIDER = 2  # the line between headings; the padding itself is read from the style (style_padding_x)


#: Left plus right padding of a Treeview style element, read from the style as ttk draws it. A guessed constant
#: (8, then 16) let "DESTINATION" pass here while it showed cut at about 960 px (2026-11-16).
style_padding_x = _style_padding_x


def _walk(widget: tk.Misc):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _inside_button(widget: tk.Misc) -> bool:
    parent = widget.master
    while parent is not None:
        if isinstance(parent, Button):
            return True
        parent = parent.master
    return False


def _scroll_area(widget: tk.Misc) -> tk.Canvas | None:
    """The nearest canvas this widget is embedded in (a ScrollFrame body), if any."""
    parent = widget.master
    while parent is not None:
        if isinstance(parent, tk.Canvas):
            return parent
        parent = parent.master
    return None


def _kind(widget: tk.Misc) -> str | None:
    if isinstance(widget, Button):
        return "button"
    if _inside_button(widget):
        return None  # the Button itself is checked
    if isinstance(widget, ElideLabel):
        return "elide" if str(widget.cget("text")).strip() else None
    if isinstance(widget, WrapLabel):
        return "wrap" if str(widget.cget("text")).strip() else None
    if isinstance(widget, Pill):
        return "badge" if str(widget.cget("text")).strip() else None
    if isinstance(widget, (tk.Checkbutton, tk.Radiobutton, ttk.Checkbutton, ttk.Radiobutton)):
        return "choice"
    if isinstance(widget, ttk.Combobox):
        return "combo"
    if isinstance(widget, ttk.Treeview):
        return "table"
    if isinstance(widget, (tk.Label, ttk.Label)):
        try:
            text = str(widget.cget("text")).strip()
        except tk.TclError:
            return None
        return "label" if text else None
    return None


def _has_content(widget: tk.Misc) -> bool:
    return any(_kind(part) is not None for part in _walk(widget))


def _squeezed_out(widget: tk.Misc) -> bool:
    try:
        if widget.winfo_ismapped() or widget.winfo_manager() not in ("pack", "grid", "place"):
            return False
        master = widget.master
        return master is not None and bool(master.winfo_viewable()) and _has_content(widget)
    except tk.TclError:
        return False


def describe(widget: tk.Misc) -> str:
    try:
        text = str(widget.cget("text"))
    except tk.TclError:
        text = ""
    if isinstance(widget, Button):
        text = widget.text
    text = " ".join(text.split())[:40]
    return f"{widget.winfo_class()} '{text}' ({widget})"


def audit(top: tk.Misc, where: str, *, vertical: bool = True) -> list[str]:
    """Problems in the viewable widgets under ``top`` (a page, a dialog, or the whole window).

    ``vertical=False`` leaves out running out of height (cut in height, below the window, squeezed out): for a
    screen too small for the app's minimum window, where that is a known limitation. Width is always checked.
    """
    top.update_idletasks()
    window = top.winfo_toplevel()
    win_left, win_top = window.winfo_rootx(), window.winfo_rooty()
    win_right, win_bottom = win_left + window.winfo_width(), win_top + window.winfo_height()
    problems: list[str] = []
    for widget in _walk(top):
        try:
            if not widget.winfo_viewable():
                if vertical and _squeezed_out(widget):
                    problems.append(f"{where}: squeezed out (no room left, so hidden): {describe(widget)}")
                continue
        except tk.TclError:
            continue
        kind = _kind(widget)
        if kind is None:
            continue
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        width, height = widget.winfo_width(), widget.winfo_height()
        area = _scroll_area(widget)
        if area is not None:
            left, right = area.winfo_rootx(), area.winfo_rootx() + area.winfo_width()
            if x < left - TOLERANCE or x + width > right + TOLERANCE:
                problems.append(f"{where}: {kind} off view (outside the scrolling area's width): {describe(widget)} "
                                f"x={x - left}..{x + width - left} area={area.winfo_width()}")
        else:
            if x < win_left - TOLERANCE or x + width > win_right + TOLERANCE:
                problems.append(f"{where}: {kind} off view (right edge outside the window): {describe(widget)} "
                                f"x={x - win_left}..{x + width - win_left} window={window.winfo_width()}")
            if vertical and y + height > win_bottom + TOLERANCE:
                problems.append(f"{where}: {kind} off view (below the window): {describe(widget)} "
                                f"y={y - win_top}..{y + height - win_top} window={window.winfo_height()}")
        if kind in ("button", "label", "badge", "choice", "combo"):
            need_w, need_h = widget.winfo_reqwidth(), widget.winfo_reqheight()
            if width < need_w - TOLERANCE or (vertical and height < need_h - TOLERANCE):
                problems.append(f"{where}: {kind} cut: {describe(widget)} size={width}x{height} "
                                f"needs={need_w}x{need_h}")
        if kind == "elide" and width > 1:
            shown = tkfont.Font(font=widget.cget("font")).measure(str(widget.cget("text")))
            if shown > width + TOLERANCE:
                problems.append(f"{where}: label cut (not shortened to fit): {describe(widget)} text={shown} "
                                f"width={width}")
        if kind == "table":
            columns = widget.cget("columns")
            show = str(widget.cget("show"))
            total = sum(int(widget.column(column, "width")) for column in columns)
            if "tree" in show:
                total += int(widget.column("#0", "width"))
            if total > width + 2:
                problems.append(f"{where}: table columns off the edge: {describe(widget)} columns={total} "
                                f"table={width}")
            try:
                style = str(widget.cget("style")) or "Treeview"
                heading_font = tkfont.nametofont(str(ttk.Style(widget).lookup(style + ".Heading", "font")))
            except (tk.TclError, ValueError):
                heading_font = tkfont.nametofont("TkHeadingFont")
            padding = style_padding_x(widget, ".Heading")
            for column in columns:
                heading = str(widget.heading(column, "text"))
                need = heading_font.measure(heading) + padding + HEADING_DIVIDER if heading else 0
                if need > int(widget.column(column, "width")) + TOLERANCE:
                    problems.append(f"{where}: table heading cut: '{heading}' in {describe(widget)} "
                                    f"width={widget.column(column, 'width')} needs={need}")
    return problems


__all__ = ["audit", "describe"]
