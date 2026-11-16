# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Small pieces the unified memory screen shares: the space an action runs in, display names, times, and the window
size table of v0.4.4 §3.3."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import tkinter as tk

from bio_ce.ui.format import format_timestamp, parse_timestamp
from bio_ce.ui.i18n import t

# §3.3: window width at 100% scale → card columns and drawer width.
COLUMN_STEPS = ((2200, 4), (1600, 3), (1100, 2))
DRAWER_WIDTHS = ((2200, 680), (1600, 600), (1100, 520))
PUSH_FROM = 1600  # owner decision Q2: from this width the drawer pushes the cards aside; narrower, it overlaps them
MIN_CARD = 260  # a card is never narrower than this (100% scale); fewer columns instead
READING_WIDTH = 680  # about 72 characters (§3.3)


def columns_for(window_width: int, theme) -> int:
    for limit, columns in COLUMN_STEPS:
        if window_width >= theme.px(limit):
            return columns
    return 1


def drawer_width(window_width: int, theme) -> int:
    for limit, width in DRAWER_WIDTHS:
        if window_width >= theme.px(limit):
            return theme.px(width)
    return max(theme.px(420), int(window_width * 0.6))


def pushes(window_width: int, theme) -> bool:
    return window_width >= theme.px(PUSH_FROM)


@contextmanager
def in_space(app, space):
    """Run service and engine calls in ``space`` (memories are per space); the shown space comes back after."""
    service = app.service
    before = service.scope
    if space is not None:
        service.use_space(space.curated)
    try:
        yield
    finally:
        service.use_space(before)


def space_label(space) -> str:
    """The name shown for a space: General and Personal in the app's language (owner decision Q5), others as named."""
    if space is None:
        return t("space.general")
    if space.is_general:
        return t("space.general")
    if space.is_personal:
        return t("space.personal")
    return space.display_name


def when(value: str | None, *, now: datetime | None = None) -> str:
    """"3 days ago" in the app's language; older than a week, the date."""
    parsed = parse_timestamp(value)
    if parsed is None:
        return ""
    seconds = ((now or datetime.now(timezone.utc)) - parsed).total_seconds()
    if seconds < 0:
        return format_timestamp(value)
    if seconds < 60:
        return t("time.just_now")
    minutes = int(seconds // 60)
    if minutes < 60:
        return t("time.minutes", count=minutes)
    hours = minutes // 60
    if hours < 24:
        return t("time.hours", count=hours)
    days = hours // 24
    if days == 1:
        return t("time.yesterday")
    if days < 7:
        return t("time.days", count=days)
    return parsed.astimezone().strftime("%Y-%m-%d")


def control_of(app):
    return getattr(app.connection_manager, "control", None)


def menu_style(theme) -> dict:
    c = theme.colors
    return {"tearoff": 0, "background": c.surface_alt, "foreground": c.text, "activebackground": c.selection,
            "activeforeground": c.text, "disabledforeground": c.text_muted, "relief": "flat", "borderwidth": 1,
            "font": theme.font("body")}


class AutoText(tk.Text):
    """Read-only text whose height follows its wrapped lines, for a scrolling column (the drawer, a review card).
    Unlike a label, it can be selected and copied and can mark words (differences in a review)."""

    def __init__(self, master: tk.Misc, theme, *, font: str = "body", foreground: str | None = None,
                 max_lines: int = 4000) -> None:
        c = theme.colors
        background = str(master.cget("background"))
        super().__init__(master, font=theme.font(font), wrap="word", height=1, width=20, relief="flat",
                         borderwidth=0, highlightthickness=0, background=background,
                         foreground=foreground or c.text, selectbackground=c.selection, selectforeground=c.text,
                         inactiveselectbackground=c.selection, cursor="arrow", takefocus=0, padx=0, pady=0,
                         spacing2=theme.px(3), spacing3=theme.px(2))
        self.max_lines = max_lines
        self.configure(state="disabled")
        self.bind("<Configure>", lambda _e: self.after_idle(self.fit), add="+")

    def set(self, text: str, tag: str | None = None) -> None:
        self.configure(state="normal")
        self.delete("1.0", tk.END)
        if text:
            self.insert("1.0", text, tag) if tag else self.insert("1.0", text)
        self.configure(state="disabled")
        self.fit()

    def put(self, parts) -> None:
        """``parts``: (text, tag or None) pairs, for marked words."""
        self.configure(state="normal")
        self.delete("1.0", tk.END)
        for text, tag in parts:
            self.insert(tk.END, text, tag) if tag else self.insert(tk.END, text)
        self.configure(state="disabled")
        self.fit()

    def get_text(self) -> str:
        return self.get("1.0", "end-1c")

    def fit(self) -> None:
        try:
            lines = self.count("1.0", "end", "displaylines")
        except tk.TclError:
            return
        count = lines[0] if isinstance(lines, tuple) else (lines or 1)
        height = max(1, min(int(count or 1), self.max_lines))
        if int(self.cget("height")) != height:
            self.configure(height=height)


__all__ = ["AutoText", "COLUMN_STEPS", "DRAWER_WIDTHS", "MIN_CARD", "PUSH_FROM", "READING_WIDTH", "columns_for",
           "control_of", "drawer_width", "in_space", "menu_style", "pushes", "space_label", "when"]
