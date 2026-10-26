# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Reusable widgets built on plain Tk so every state can follow the theme.

All interactive widgets are keyboard accessible: they take focus with Tab,
show a visible focus ring, and activate with Enter or Space.
"""

from __future__ import annotations

from typing import Callable
import tkinter as tk
from tkinter import ttk

from bio_ce.ui.theme import READING_MAX_WIDTH, SPACE_L, SPACE_M, SPACE_XS, Theme


Command = Callable[[], object] | None


def pointer_inside(widget: tk.Misc) -> bool:
    try:
        x, y = widget.winfo_pointerxy()
        current = widget.winfo_containing(x, y)
    except (KeyError, tk.TclError):
        return False
    while current is not None:
        if current is widget:
            return True
        current = current.master
    return False


def surface_of(widget: tk.Misc) -> str:
    try:
        return str(widget.cget("background"))
    except tk.TclError:
        return "#000000"


def copy_to_clipboard(widget: tk.Misc, text: str) -> None:
    widget.clipboard_clear()
    widget.clipboard_append(text)


class Tooltip:
    """Small delayed hint shown when the pointer rests on a widget."""

    def __init__(self, widget: tk.Misc, theme: Theme, text: str) -> None:
        self.widget = widget
        self.theme = theme
        self.text = text
        self._after: str | None = None
        self._window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        if self.text:
            self._after = self.widget.after(550, self._show)

    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self) -> None:
        self._after = None
        if self._window is not None or not self.widget.winfo_ismapped():
            return
        c = self.theme.colors
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.configure(background=c.border_strong)
        tk.Label(
            window,
            text=self.text,
            background=c.surface_alt,
            foreground=c.text,
            font=self.theme.font("caption"),
            padx=self.theme.px(8),
            pady=self.theme.px(4),
        ).pack(padx=1, pady=1)
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.theme.px(4)
        window.wm_geometry(f"+{x}+{y}")
        self._window = window

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None


class Button(tk.Frame):
    """Flat button with hover, pressed, disabled, and keyboard focus states.

    Variants: ``primary``, ``secondary``, ``subtle``, ``danger``,
    ``danger_subtle``, and ``link``.
    """

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        text: str = "",
        *,
        command: Command = None,
        icon: str | None = None,
        variant: str = "secondary",
        tooltip: str | None = None,
        padx: int = 14,
        pady: int = 6,
        font: str = "body",
        anchor: str = "center",
    ) -> None:
        self.theme = theme
        self._surface = surface_of(master)
        super().__init__(
            master,
            background=self._surface,
            highlightthickness=theme.px(2),
            highlightbackground=self._surface,
            highlightcolor=theme.colors.focus,
            takefocus=1,
            cursor="hand2" if variant == "link" else "",
        )
        self.command = command
        self.variant = variant
        self._state = "normal"
        self._hover = False
        self._pressed = False
        self.body = tk.Frame(self, background=self._surface)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        inner = tk.Frame(self.body, background=self._surface)
        inner.pack(expand=True, anchor=anchor, padx=theme.px(padx if variant != "link" else 2), pady=theme.px(pady))
        self._inner = inner
        self.icon_label: tk.Label | None = None
        glyph = theme.icon(icon) if icon else ""
        if glyph:
            self.icon_label = tk.Label(inner, text=glyph, font=theme.icon_font("small"), borderwidth=0)
            self.icon_label.pack(side="left", padx=(0, theme.px(8) if text else 0))
        self.label = tk.Label(inner, text=text, font=theme.font(font), borderwidth=0)
        if text:
            self.label.pack(side="left")
        parts = [self, self.body, inner, self.label] + ([self.icon_label] if self.icon_label else [])
        for part in parts:
            part.bind("<Enter>", self._on_enter, add="+")
            part.bind("<Leave>", self._on_leave, add="+")
            part.bind("<ButtonPress-1>", self._on_press, add="+")
            part.bind("<ButtonRelease-1>", self._on_release, add="+")
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, self._on_key)
        if tooltip:
            Tooltip(self, theme, tooltip)
        self._paint()

    @property
    def text(self) -> str:
        return str(self.label.cget("text"))

    def set_text(self, text: str) -> None:
        self.label.configure(text=text)
        if text and not self.label.winfo_manager():
            self.label.pack(side="left")

    def set_command(self, command: Command) -> None:
        self.command = command

    def set_variant(self, variant: str) -> None:
        self.variant = variant
        self._paint()

    def set_enabled(self, enabled: bool) -> None:
        self._state = "normal" if enabled else "disabled"
        self.configure(takefocus=1 if enabled else 0)
        self._hover = self._hover and enabled
        self._paint()

    @property
    def enabled(self) -> bool:
        return self._state == "normal"

    def invoke(self) -> object:
        if self._state != "normal" or self.command is None:
            return None
        return self.command()

    def _palette(self) -> tuple[str, str, str]:
        """Return (fill, foreground, border) for the current state."""
        c = self.theme.colors
        surface = self._surface
        if self._state == "disabled":
            if self.variant in {"subtle", "link"}:
                return surface, c.text_disabled, surface
            return c.surface_alt, c.text_disabled, c.border
        hot = self._pressed or self._hover
        if self.variant == "primary":
            fill = c.accent_pressed if self._pressed else c.accent_hover if self._hover else c.accent
            return fill, c.on_accent, fill
        if self.variant == "danger":
            fill = c.danger_solid_pressed if self._pressed else c.danger_solid_hover if self._hover else c.danger_solid
            return fill, c.on_accent, fill
        if self.variant == "danger_subtle":
            fill = c.danger_bg if hot else c.surface_alt
            return fill, c.danger, c.danger if hot else c.border_strong
        if self.variant == "subtle":
            fill = c.surface_active if self._pressed else c.surface_hover if self._hover else surface
            return fill, c.text, fill
        if self.variant == "link":
            return surface, c.text if hot else c.accent_text, surface
        fill = c.surface_active if self._pressed else c.surface_hover if self._hover else c.surface_alt
        return fill, c.text, c.border_strong

    def _paint(self) -> None:
        fill, foreground, border = self._palette()
        self.body.configure(background=fill)
        self._inner.configure(background=fill)
        self.configure(background=border)
        self.label.configure(background=fill, foreground=foreground)
        if self.icon_label is not None:
            self.icon_label.configure(background=fill, foreground=foreground)

    def _on_enter(self, _event=None) -> None:
        if self._state == "normal" and not self._hover:
            self._hover = True
            self._paint()

    def _on_leave(self, _event=None) -> None:
        if self._hover and not pointer_inside(self):
            self._hover = False
            self._pressed = False
            self._paint()

    def _on_press(self, _event=None) -> None:
        if self._state == "normal":
            self._pressed = True
            self._paint()

    def _on_release(self, _event=None) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._paint()
        if was_pressed and pointer_inside(self):
            self.invoke()

    def _on_key(self, _event=None) -> str:
        self.invoke()
        return "break"


class IconButton(Button):
    """Square, icon-only subtle button; always carries a tooltip label."""

    def __init__(self, master: tk.Misc, theme: Theme, icon: str, tooltip: str, *, command: Command = None) -> None:
        super().__init__(master, theme, "" if theme.has_icons else tooltip, icon=icon, variant="subtle",
                         command=command, tooltip=tooltip, padx=7, pady=5)


class NavItem(tk.Frame):
    """Sidebar navigation entry with a selection indicator."""

    def __init__(self, master: tk.Misc, theme: Theme, text: str, icon: str, command: Command, *, shortcut: str = "") -> None:
        c = theme.colors
        self.theme = theme
        self._surface = surface_of(master)
        super().__init__(master, background=self._surface, highlightthickness=theme.px(2),
                         highlightbackground=self._surface, highlightcolor=c.focus, takefocus=1)
        self.text = text
        self.command = command
        self.selected = False
        self._hover = False
        self.row = tk.Frame(self, background=self._surface)
        self.row.pack(fill="x")
        self.indicator = tk.Frame(self.row, width=theme.px(3), background=self._surface)
        self.indicator.pack(side="left", fill="y", pady=theme.px(8))
        self.icon_label = tk.Label(self.row, text=theme.icon(icon), font=theme.icon_font("normal"),
                                   width=2, borderwidth=0)
        self.icon_label.pack(side="left", padx=(theme.px(9), theme.px(4)), pady=theme.px(8))
        self.label = tk.Label(self.row, text=text, font=theme.font("body"), anchor="w", borderwidth=0)
        self.label.pack(side="left", fill="x", expand=True, padx=(theme.px(6), theme.px(8)))
        Tooltip(self, theme, f"{text} ({shortcut})" if shortcut else text)
        for part in (self, self.row, self.indicator, self.icon_label, self.label):
            part.bind("<Enter>", self._on_enter, add="+")
            part.bind("<Leave>", self._on_leave, add="+")
            part.bind("<ButtonRelease-1>", self._on_click, add="+")
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, self._on_key)
        self._paint()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._paint()

    def set_compact(self, compact: bool) -> None:
        if compact:
            self.label.pack_forget()
        elif not self.label.winfo_manager():
            self.label.pack(side="left", fill="x", expand=True, padx=(self.theme.px(6), self.theme.px(8)))

    def _paint(self) -> None:
        c = self.theme.colors
        fill = c.surface_active if self.selected else c.surface_hover if self._hover else self._surface
        for part in (self.row, self.icon_label, self.label):
            part.configure(background=fill)
        self.indicator.configure(background=c.accent_text if self.selected else fill)
        self.icon_label.configure(foreground=c.text if self.selected else c.text_secondary)
        self.label.configure(
            foreground=c.text if self.selected else c.text_secondary,
            font=self.theme.font("body_strong" if self.selected else "body"),
        )

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._paint()

    def _on_leave(self, _event=None) -> None:
        if not pointer_inside(self):
            self._hover = False
            self._paint()

    def _on_click(self, _event=None) -> None:
        if pointer_inside(self) and self.command is not None:
            self.command()

    def _on_key(self, _event=None) -> str:
        if self.command is not None:
            self.command()
        return "break"


class RowButton(tk.Frame):
    """Focusable list row; place labels in ``row.body`` and call ``track(widget)``."""

    def __init__(self, master: tk.Misc, theme: Theme, command: Command) -> None:
        self.theme = theme
        self._surface = surface_of(master)
        super().__init__(master, background=self._surface, highlightthickness=theme.px(2),
                         highlightbackground=self._surface, highlightcolor=theme.colors.focus, takefocus=1)
        self.command = command
        self._hover = False
        self.body = tk.Frame(self, background=self._surface)
        self.body.pack(fill="both", expand=True)
        self._parts: list[tk.Misc] = []
        self.track(self)
        self.track(self.body)
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, self._on_key)

    def track(self, widget: tk.Misc, *, paint: bool = True) -> tk.Misc:
        """Forward hover/click from ``widget``; ``paint`` also gives it the hover fill."""
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonRelease-1>", self._on_click, add="+")
        if widget is not self and paint:
            self._parts.append(widget)
        return widget

    def _paint(self) -> None:
        fill = self.theme.colors.surface_hover if self._hover else self._surface
        for part in self._parts:
            try:
                part.configure(background=fill)
            except tk.TclError:
                pass

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._paint()

    def _on_leave(self, _event=None) -> None:
        if not pointer_inside(self):
            self._hover = False
            self._paint()

    def _on_click(self, _event=None) -> None:
        if pointer_inside(self) and self.command is not None:
            self.command()

    def _on_key(self, _event=None) -> str:
        if self.command is not None:
            self.command()
        return "break"


class Card(tk.Frame):
    """Raised surface with a 1px border. Put content in ``card.body``."""

    def __init__(self, master: tk.Misc, theme: Theme, *, padding: int = 20, background: str | None = None) -> None:
        c = theme.colors
        fill = background or c.surface
        super().__init__(master, background=fill, highlightthickness=1,
                         highlightbackground=c.border, highlightcolor=c.border)
        self.body = tk.Frame(self, background=fill)
        self.body.pack(fill="both", expand=True, padx=theme.px(padding), pady=theme.px(padding))


class Pill(tk.Label):
    """Compact status label, e.g. ``Connected`` or ``Not installed``."""

    KINDS = ("success", "warning", "danger", "info", "neutral")

    def __init__(self, master: tk.Misc, theme: Theme, text: str = "", kind: str = "neutral") -> None:
        self.theme = theme
        super().__init__(master, font=theme.font("caption_strong"), padx=theme.px(8), pady=theme.px(2), borderwidth=0)
        self.kind = kind
        self.set(text, kind)

    def set(self, text: str, kind: str = "neutral") -> None:
        c = self.theme.colors
        foreground, background = {
            "success": (c.success, c.success_bg),
            "warning": (c.warning, c.warning_bg),
            "danger": (c.danger, c.danger_bg),
            "info": (c.info, c.info_bg),
        }.get(kind, (c.text_secondary, c.surface_alt))
        self.kind = kind
        self.configure(text=f"• {text}" if kind != "neutral" else text, foreground=foreground, background=background)


class WrapLabel(tk.Label):
    """Label whose wrap length follows its allocated width."""

    def __init__(self, master: tk.Misc, text: str = "", *, max_width: int | None = None, **options) -> None:
        options.setdefault("justify", "left")
        options.setdefault("anchor", "w")
        options.setdefault("borderwidth", 0)
        options.setdefault("background", surface_of(master))
        super().__init__(master, text=text, wraplength=options.pop("wraplength", 320), **options)
        self._max_width = max_width
        self.bind("<Configure>", self._rewrap, add="+")

    def _rewrap(self, event) -> None:
        width = max(40, int(event.width) - 4)
        if self._max_width:
            width = min(width, self._max_width)
        if abs(int(self.cget("wraplength")) - width) > 2:
            self.configure(wraplength=width)


class AutoScrollbar(ttk.Scrollbar):
    """Scrollbar that hides itself while all content fits (grid only)."""

    def set(self, first, last) -> None:  # noqa: A003 - Tk protocol name
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        super().set(first, last)


class Field(tk.Frame):
    """Bordered single-line text box with focus and error states."""

    def __init__(
        self,
        master: tk.Misc,
        theme: Theme,
        *,
        textvariable: tk.StringVar | None = None,
        font: str = "body",
        readonly: bool = False,
        width: int = 24,
    ) -> None:
        c = theme.colors
        self.theme = theme
        self._fill = c.surface if readonly else c.surface_alt
        super().__init__(master, background=self._fill, highlightthickness=1,
                         highlightbackground=c.border_strong, highlightcolor=c.border_strong)
        self._error = False
        self.content = tk.Frame(self, background=self._fill)
        self.content.pack(fill="both", expand=True)
        self.entry = tk.Entry(
            self.content,
            textvariable=textvariable,
            font=theme.font(font),
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            background=self._fill,
            foreground=c.text,
            disabledbackground=self._fill,
            disabledforeground=c.text_disabled,
            readonlybackground=self._fill,
            insertbackground=c.text,
            selectbackground=c.selection,
            selectforeground=c.text,
            width=width,
        )
        if readonly:
            self.entry.configure(state="readonly", foreground=c.text_secondary)
        self.entry.pack(side="left", fill="x", expand=True, padx=theme.px(10), pady=theme.px(7))
        self.entry.bind("<FocusIn>", lambda _e: self._paint(True), add="+")
        self.entry.bind("<FocusOut>", lambda _e: self._paint(False), add="+")
        for part in (self, self.content):
            part.bind("<Button-1>", lambda _e: self.entry.focus_set(), add="+")

    def set_error(self, error: bool) -> None:
        self._error = error
        self._paint(self.focus_get() is self.entry)

    def focus_set(self) -> None:  # type: ignore[override]
        self.entry.focus_set()

    def _paint(self, focused: bool) -> None:
        c = self.theme.colors
        color = c.danger if self._error else c.focus if focused else c.border_strong
        self.configure(highlightbackground=color, highlightcolor=color)


class SearchBox(Field):
    """Search field with icon, placeholder text, and a clear button."""

    def __init__(self, master: tk.Misc, theme: Theme, variable: tk.StringVar, placeholder: str,
                 *, on_clear: Command = None) -> None:
        super().__init__(master, theme, textvariable=variable)
        c = theme.colors
        self.variable = variable
        self.entry.pack_configure(padx=(theme.px(4), theme.px(4)))
        glyph = theme.icon("search")
        if glyph:
            icon = tk.Label(self.content, text=glyph, font=theme.icon_font("small"), background=self._fill,
                            foreground=c.text_muted)
            icon.pack(side="left", padx=(theme.px(10), theme.px(2)), before=self.entry)
            icon.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.placeholder = tk.Label(self.content, text=placeholder, font=theme.font("body"), background=self._fill,
                                    foreground=c.text_muted, borderwidth=0)
        self.placeholder.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.clear_button = IconButton(self.content, theme, "close", "Clear search", command=self.clear)
        self._on_clear = on_clear
        variable.trace_add("write", lambda *_: self._sync())
        self.entry.bind("<Escape>", lambda _e: self.clear() if self.variable.get() else None, add="+")
        self._sync()

    def clear(self) -> None:
        self.variable.set("")
        self.entry.focus_set()
        if self._on_clear is not None:
            self._on_clear()

    def _sync(self) -> None:
        if self.variable.get():
            self.placeholder.place_forget()
            if not self.clear_button.winfo_manager():
                self.clear_button.pack(side="right", padx=(0, self.theme.px(2)))
        else:
            self.placeholder.place(in_=self.entry, x=1, rely=0.5, anchor="w")
            if self.clear_button.winfo_manager():
                self.clear_button.pack_forget()


class TextArea(tk.Frame):
    """Multi-line text box with an auto-hiding scrollbar."""

    def __init__(self, master: tk.Misc, theme: Theme, *, font: str = "body", readonly: bool = False,
                 height: int = 10, bordered: bool = True) -> None:
        c = theme.colors
        self.theme = theme
        fill = c.surface if readonly else c.surface_alt
        super().__init__(master, background=fill, highlightthickness=1 if bordered else 0,
                         highlightbackground=c.border_strong, highlightcolor=c.border_strong)
        self._error = False
        self.text = tk.Text(
            self,
            font=theme.font(font),
            wrap="word",
            undo=not readonly,
            height=height,
            width=40,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            background=fill,
            foreground=c.text,
            insertbackground=c.text,
            selectbackground=c.selection,
            selectforeground=c.text,
            inactiveselectbackground=c.selection,
            padx=theme.px(12) if bordered else 0,
            pady=theme.px(10) if bordered else theme.px(2),
            spacing1=theme.px(1),
            spacing2=theme.px(3),
            spacing3=theme.px(6) if readonly else theme.px(2),
            tabs=(theme.px(32),),
        )
        self.scrollbar = AutoScrollbar(self, orient="vertical", command=self.text.yview,
                                       style=theme.scrollbar_style(fill))
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, theme.px(2)), pady=theme.px(2))
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.readonly = readonly
        if readonly:
            self.text.configure(state="disabled", cursor="arrow", takefocus=1)
        else:
            self.text.bind("<FocusIn>", lambda _e: self._paint(True), add="+")
            self.text.bind("<FocusOut>", lambda _e: self._paint(False), add="+")
            # Tab moves focus instead of inserting a tab character; Ctrl+Tab inserts one.
            self.text.bind("<Tab>", self._focus_next)
            self.text.bind("<Shift-Tab>", self._focus_prev)
            self.text.bind("<Control-Tab>", lambda _e: (self.text.insert("insert", "\t"), "break")[1])

    def focus_set(self) -> None:  # type: ignore[override]
        self.text.focus_set()

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        state = str(self.text.cget("state"))
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", value)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.text.configure(state=state)
        self.text.yview_moveto(0)

    def set_error(self, error: bool) -> None:
        self._error = error
        self._paint(self.focus_get() is self.text)

    def _paint(self, focused: bool) -> None:
        c = self.theme.colors
        color = c.danger if self._error else c.focus if focused else c.border_strong
        self.configure(highlightbackground=color, highlightcolor=color)

    def _focus_next(self, _event=None) -> str:
        self.text.tk_focusNext().focus_set()
        return "break"

    def _focus_prev(self, _event=None) -> str:
        self.text.tk_focusPrev().focus_set()
        return "break"


class ScrollFrame(tk.Frame):
    """Vertically scrolling container; place children in ``self.body``."""

    def __init__(self, master: tk.Misc, theme: Theme, *, max_width: int | None = None, center: bool = False) -> None:
        fill = surface_of(master)
        super().__init__(master, background=fill)
        self.theme = theme
        self._max_width = theme.px(max_width) if max_width else None
        self._center = center
        self.canvas = tk.Canvas(self, background=fill, highlightthickness=0, borderwidth=0, takefocus=0)
        self.scrollbar = AutoScrollbar(self, orient="vertical", command=self.canvas.yview,
                                       style=theme.scrollbar_style(fill))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.body = tk.Frame(self.canvas, background=fill)
        self._window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def scroll(self, units: int) -> None:
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return
        self.canvas.yview_scroll(units, "units")

    def scroll_to_widget(self, widget: tk.Misc) -> None:
        self.update_idletasks()
        top = widget.winfo_rooty() - self.body.winfo_rooty()
        height = max(1, self.body.winfo_height())
        view_top, view_bottom = self.canvas.yview()
        visible = (view_bottom - view_top) * height
        if top < view_top * height or top + widget.winfo_height() > view_top * height + visible:
            self.canvas.yview_moveto(max(0.0, (top - self.theme.px(SPACE_L)) / height))

    def _on_body_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=(0, 0, self.body.winfo_reqwidth(), self.body.winfo_reqheight()))

    def _on_canvas_configure(self, event) -> None:
        width = int(event.width)
        if self._max_width:
            width = min(width, self._max_width)
        self.canvas.itemconfigure(self._window, width=width)
        if self._center:
            self.canvas.coords(self._window, max(0, (int(event.width) - width) // 2), 0)


def install_mousewheel(root: tk.Misc) -> None:
    """Route wheel events to the nearest ScrollFrame unless a scrollable widget is under the pointer."""

    def on_wheel(event) -> None:
        try:
            widget = root.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        while widget is not None:
            if isinstance(widget, (tk.Text, ttk.Treeview, tk.Listbox)):
                first, last = widget.yview()
                if not (first <= 0.0 and last >= 1.0):
                    return
            if isinstance(widget, ScrollFrame):
                widget.scroll(-1 * int(event.delta / 120) * 3 if event.delta else 0)
                return
            widget = widget.master

    root.bind_all("<MouseWheel>", on_wheel, add="+")
    for widget_class in ("Text", "Treeview", "Listbox"):
        # Hand wheel events back to the page once a list or text has nothing left to scroll.
        root.bind_class(widget_class, "<MouseWheel>", lambda e: _scroll_own(e), add="")


def _scroll_own(event) -> str | None:
    widget = event.widget
    try:
        first, last = widget.yview()
    except (AttributeError, tk.TclError):
        return None
    if first <= 0.0 and last >= 1.0:
        return None
    widget.yview_scroll(-1 * int(event.delta / 120) * 3 if event.delta else 0, "units")
    return "break"


class EmptyState(tk.Frame):
    """Centered icon, heading, explanation, and optional actions."""

    def __init__(self, master: tk.Misc, theme: Theme, *, icon: str, title: str, message: str,
                 actions: tuple[tuple[str, Command, str], ...] = ()) -> None:
        fill = surface_of(master)
        super().__init__(master, background=fill)
        c = theme.colors
        self.theme = theme
        column = tk.Frame(self, background=fill)
        column.place(relx=0.5, rely=0.42, anchor="center")
        self.column = column
        glyph = theme.icon(icon)
        if glyph:
            tk.Label(column, text=glyph, font=theme.icon_font("hero"), background=fill,
                     foreground=c.text_muted).pack(pady=(0, theme.px(SPACE_M)))
        self.title_label = tk.Label(column, text=title, font=theme.font("section"), background=fill, foreground=c.text)
        self.title_label.pack()
        self.message_label = tk.Label(column, text=message, font=theme.font("body"), background=fill,
                                      foreground=c.text_secondary, justify="center",
                                      wraplength=theme.px(420))
        self.message_label.pack(pady=(theme.px(SPACE_XS), 0))
        self.buttons: list[Button] = []
        if actions:
            row = tk.Frame(column, background=fill)
            row.pack(pady=(theme.px(SPACE_L), 0))
            for text, command, variant in actions:
                button = Button(row, theme, text, command=command, variant=variant)
                button.pack(side="left", padx=theme.px(SPACE_XS))
                self.buttons.append(button)
        self.bind("<Configure>", self._fit, add="+")

    def set_text(self, title: str | None = None, message: str | None = None) -> None:
        if title is not None:
            self.title_label.configure(text=title)
        if message is not None:
            self.message_label.configure(text=message)

    def _fit(self, event) -> None:
        self.message_label.configure(wraplength=max(self.theme.px(160), min(self.theme.px(420), event.width - self.theme.px(48))))
        needed = self.column.winfo_reqheight() + self.theme.px(24)
        self.configure(height=max(needed, 1))


class InfoBar(tk.Frame):
    """Inline notification for success, info, warning, and error messages."""

    TIMEOUTS = {"success": 6000, "info": 8000}

    def __init__(self, master: tk.Misc, theme: Theme, *, pack_options: dict, before: tk.Misc | None = None) -> None:
        c = theme.colors
        super().__init__(master, background=c.border, highlightthickness=0)
        self.theme = theme
        self._pack_options = pack_options
        self._before = before
        self._after: str | None = None
        self.kind: str | None = None
        self.title: str = ""
        self.message: str = ""
        self.stripe = tk.Frame(self, width=theme.px(3))
        self.stripe.pack(side="left", fill="y")
        self.inner = tk.Frame(self)
        self.inner.pack(side="left", fill="both", expand=True)
        self.icon_label = tk.Label(self.inner, font=theme.icon_font("normal"), borderwidth=0)
        self.icon_label.pack(side="left", anchor="n", padx=(theme.px(12), theme.px(10)), pady=theme.px(11))
        text_column = tk.Frame(self.inner)
        text_column.pack(side="left", fill="both", expand=True, pady=theme.px(9))
        self.text_column = text_column
        self.title_label = tk.Label(text_column, font=theme.font("body_strong"), anchor="w", borderwidth=0)
        self.message_label = WrapLabel(text_column, font=theme.font("body"))
        self.message_label.pack(fill="x")
        self.close_button = IconButton(self.inner, theme, "close", "Dismiss", command=self.hide)
        self.close_button.pack(side="right", anchor="n", padx=theme.px(6), pady=theme.px(5))
        self.action_button: Button | None = None

    def show(self, kind: str, message: str, *, title: str = "",
             action: tuple[str, Callable[[], object]] | None = None) -> None:
        c = self.theme.colors
        accent, fill = {
            "success": (c.success, c.success_bg),
            "warning": (c.warning, c.warning_bg),
            "error": (c.danger, c.danger_bg),
        }.get(kind, (c.info, c.info_bg))
        self.kind, self.title, self.message = kind, title, message
        for part in (self.inner, self.text_column, self.title_label, self.message_label, self.icon_label):
            part.configure(background=fill)
        self.stripe.configure(background=accent)
        glyph = kind if kind in {"success", "warning", "error", "info"} else "info"
        self.icon_label.configure(text=self.theme.icon(glyph), foreground=accent)
        self.title_label.configure(text=title, foreground=c.text)
        if title:
            self.title_label.pack(fill="x", before=self.message_label)
        else:
            self.title_label.pack_forget()
        self.message_label.configure(text=message, foreground=c.text)
        if self.action_button is not None:
            self.action_button.destroy()
            self.action_button = None
        self.close_button.destroy()
        self.close_button = IconButton(self.inner, self.theme, "close", "Dismiss", command=self.hide)
        self.close_button.pack(side="right", anchor="n", padx=self.theme.px(6), pady=self.theme.px(5))
        if action is not None:
            label, callback = action
            self.action_button = Button(self.inner, self.theme, label, variant="secondary",
                                        command=lambda: (self.hide(), callback()))
            self.action_button.pack(side="right", anchor="n", pady=self.theme.px(7))
        if not self.winfo_manager():
            options = dict(self._pack_options)
            if self._before is not None:
                options["before"] = self._before
            self.pack(**options)
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        timeout = self.TIMEOUTS.get(kind)
        if timeout and action is None:
            self._after = self.after(timeout, self.hide)

    def hide(self) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        if self.winfo_manager():
            self.pack_forget()
        self.kind = None

    @property
    def visible(self) -> bool:
        return bool(self.winfo_manager())


def section_label(master: tk.Misc, theme: Theme, text: str, *, font: str = "section") -> tk.Label:
    return tk.Label(master, text=text, font=theme.font(font), background=surface_of(master),
                    foreground=theme.colors.text, anchor="w", borderwidth=0)


def caption_label(master: tk.Misc, theme: Theme, text: str, *, muted: bool = False) -> WrapLabel:
    color = theme.colors.text_muted if muted else theme.colors.text_secondary
    return WrapLabel(master, text, font=theme.font("caption"), foreground=color)


def divider(master: tk.Misc, theme: Theme) -> tk.Frame:
    return tk.Frame(master, height=1, background=theme.colors.border)


def reading_padding(theme: Theme, width: int) -> int:
    """Extra right padding that caps a reading column near the comfortable measure."""
    return max(0, width - theme.px(READING_MAX_WIDTH))


__all__ = [
    "AutoScrollbar",
    "Button",
    "Card",
    "EmptyState",
    "Field",
    "IconButton",
    "InfoBar",
    "NavItem",
    "Pill",
    "RowButton",
    "ScrollFrame",
    "SearchBox",
    "TextArea",
    "Tooltip",
    "WrapLabel",
    "caption_label",
    "copy_to_clipboard",
    "divider",
    "install_mousewheel",
    "pointer_inside",
    "reading_padding",
    "section_label",
    "surface_of",
]
