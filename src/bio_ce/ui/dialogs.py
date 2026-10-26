# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Themed dialogs: confirmations, revision history, text viewer, first-run notice."""

from __future__ import annotations

import time
from typing import Sequence
import tkinter as tk

from bio_ce.core.models import MemoryRevision
from bio_ce.ui.format import format_timestamp, revision_kind_label
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XL, SPACE_XS, Theme, apply_window_chrome
from bio_ce.ui.widgets import Button, Field, ScrollFrame, TextArea, WrapLabel


class Dialog(tk.Toplevel):
    """Base dialog: content area, footer with right-aligned buttons, Esc closes.

    Buttons ignore activation for a short moment after the dialog appears so a
    click or key press meant for the window underneath can't confirm it.
    """

    ARM_DELAY = 0.4

    def __init__(self, parent: tk.Misc, theme: Theme, title: str, *, resizable: bool = False) -> None:
        super().__init__(parent)
        self.withdraw()
        self.theme = theme
        c = theme.colors
        self.parent_window = parent.winfo_toplevel()
        self.title(title)
        self.configure(background=c.surface)
        self.transient(self.parent_window)
        self.resizable(resizable, resizable)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda _event: self.cancel())
        self.result: object = None
        self._armed_at = float("inf")
        self.footer = tk.Frame(self, background=c.bg)
        self.footer.pack(side="bottom", fill="x")
        tk.Frame(self, height=1, background=c.border).pack(side="bottom", fill="x")
        self.buttons = tk.Frame(self.footer, background=c.bg)
        self.buttons.pack(side="right", padx=theme.px(SPACE_XL - 2), pady=theme.px(SPACE_L - 2))
        self.content = tk.Frame(self, background=c.surface)
        self.content.pack(side="top", fill="both", expand=True,
                          padx=theme.px(SPACE_XL), pady=(theme.px(SPACE_XL), theme.px(SPACE_L)))

    def add_button(self, text: str, command, *, variant: str = "secondary") -> Button:
        button = Button(self.buttons, self.theme, text, command=lambda: command() if self.armed else None,
                        variant=variant)
        button.pack(side="left", padx=(self.theme.px(SPACE_S), 0))
        return button

    def present(self, *, focus: tk.Misc | None = None, modal: bool = True, size: tuple[int, int] | None = None) -> None:
        self.update_idletasks()
        width, height = size or (self.winfo_reqwidth(), self.winfo_reqheight())
        parent = self.parent_window
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}" if size else f"+{x}+{y}")
        self._armed_at = time.monotonic() + self.ARM_DELAY
        self.deiconify()
        apply_window_chrome(self, self.theme.colors)
        self.lift()
        (focus or self).focus_set()
        if modal:
            self.grab_set()
            self.wait_window()

    @property
    def armed(self) -> bool:
        return time.monotonic() >= self._armed_at

    def finish(self, result: object) -> None:
        self.result = result
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def cancel(self) -> None:
        self.finish(None)


class ConfirmDialog(Dialog):
    """Ask before a consequential action. Buttons name the action explicitly."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        title: str,
        message: str,
        confirm_text: str,
        cancel_text: str = "Cancel",
        danger: bool = False,
        points: Sequence[str] = (),
        quote: str | None = None,
    ) -> None:
        super().__init__(parent, theme, title)
        c = theme.colors
        wrap = theme.px(420)
        header = tk.Frame(self.content, background=c.surface)
        header.pack(fill="x")
        glyph = theme.icon("warning" if danger else "info")
        if glyph:
            tk.Label(header, text=glyph, font=theme.icon_font("large"), background=c.surface,
                     foreground=c.warning if danger else c.info).pack(side="left", anchor="n",
                                                                     padx=(0, theme.px(SPACE_M)))
        column = tk.Frame(header, background=c.surface)
        column.pack(side="left", fill="x", expand=True)
        tk.Label(column, text=title, font=theme.font("title"), background=c.surface, foreground=c.text,
                 anchor="w", justify="left", wraplength=wrap).pack(fill="x")
        tk.Label(column, text=message, font=theme.font("body"), background=c.surface, foreground=c.text_secondary,
                 anchor="w", justify="left", wraplength=wrap).pack(fill="x", pady=(theme.px(SPACE_S), 0))
        if quote:
            box = tk.Frame(column, background=c.surface_alt, highlightthickness=1, highlightbackground=c.border)
            box.pack(fill="x", pady=(theme.px(SPACE_M), 0))
            tk.Label(box, text=quote, font=theme.font("body_strong"), background=c.surface_alt, foreground=c.text,
                     anchor="w", justify="left", wraplength=wrap - theme.px(24)).pack(
                fill="x", padx=theme.px(SPACE_M), pady=theme.px(SPACE_S))
        for point in points:
            row = tk.Frame(column, background=c.surface)
            row.pack(fill="x", pady=(theme.px(SPACE_S), 0))
            tk.Label(row, text="•", font=theme.font("body"), background=c.surface,
                     foreground=c.text_muted).pack(side="left", anchor="n", padx=(0, theme.px(SPACE_S)))
            tk.Label(row, text=point, font=theme.font("body"), background=c.surface, foreground=c.text_secondary,
                     anchor="w", justify="left", wraplength=wrap - theme.px(16)).pack(side="left", fill="x")
        confirm = self.add_button(confirm_text, lambda: self.finish(True), variant="danger" if danger else "primary")
        cancel = self.add_button(cancel_text, self.cancel)
        self.result = False
        self._default_focus = cancel if danger else confirm

    def cancel(self) -> None:
        self.finish(False)

    def ask(self) -> bool:
        self.present(focus=self._default_focus)
        return bool(self.result)


class HistoryDialog(Dialog):
    """Read-only, newest-first view of every revision of one memory."""

    def __init__(self, parent: tk.Misc, theme: Theme, revisions: Sequence[MemoryRevision]) -> None:
        super().__init__(parent, theme, "Revision history", resizable=True)
        c = theme.colors
        latest = revisions[-1] if revisions else None
        tk.Label(self.content, text="Revision history", font=theme.font("title"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        subtitle = (f"{latest.title} · {len(revisions)} revision{'s' if len(revisions) != 1 else ''}"
                    if latest else "No revisions")
        tk.Label(self.content, text=subtitle, font=theme.font("body"), background=c.surface,
                 foreground=c.text_secondary, anchor="w", justify="left", wraplength=theme.px(640)).pack(
            fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_M)))
        self.view = TextArea(self.content, theme, readonly=True, font="body", height=18)
        self.view.configure(highlightthickness=1, highlightbackground=c.border)
        self.view.text.configure(padx=theme.px(SPACE_L), pady=theme.px(SPACE_M))
        self.view.pack(fill="both", expand=True)
        text = self.view.text
        text.tag_configure("heading", font=theme.font("body_strong"), foreground=c.text, spacing1=theme.px(SPACE_S))
        text.tag_configure("current", font=theme.font("caption_strong"), foreground=c.success)
        text.tag_configure("meta", font=theme.font("caption"), foreground=c.text_muted, spacing3=theme.px(SPACE_S))
        text.tag_configure("title", font=theme.font("section"), foreground=c.text, spacing3=theme.px(SPACE_XS))
        text.tag_configure("body", font=theme.font("body"), foreground=c.text_secondary, spacing3=theme.px(SPACE_XS))
        text.tag_configure("empty", font=theme.font("body"), foreground=c.text_muted)
        text.tag_configure("rule", font=theme.font("caption"), foreground=c.border_strong, spacing1=theme.px(SPACE_S),
                           spacing3=theme.px(SPACE_S))
        text.configure(state="normal")
        for index, revision in enumerate(reversed(revisions)):
            if index:
                text.insert(tk.END, "─" * 40 + "\n", "rule")
            text.insert(tk.END, f"Revision {revision.revision_number} · {revision_kind_label(revision.kind)}", "heading")
            if index == 0:
                text.insert(tk.END, "   CURRENT", "current")
            text.insert(tk.END, "\n")
            text.insert(
                tk.END,
                f"{format_timestamp(revision.recorded_at)} · Source: {revision.source.source_ref}\n",
                "meta",
            )
            text.insert(tk.END, f"{revision.title}\n", "title")
            if revision.content:
                body = revision.content if len(revision.content) <= 4000 else revision.content[:4000] + "…"
                text.insert(tk.END, body.rstrip() + "\n", "body")
            else:
                text.insert(tk.END, "No memory text\n", "empty")
        text.configure(state="disabled")
        self.close_button = self.add_button("Close", self.cancel, variant="primary")

    def show(self) -> "HistoryDialog":
        self.present(focus=self.close_button, modal=False, size=(self.theme.px(720), self.theme.px(560)))
        self.minsize(self.theme.px(420), self.theme.px(320))
        return self


class TextViewerDialog(Dialog):
    """Read-only viewer for license and notice files."""

    def __init__(self, parent: tk.Misc, theme: Theme, title: str, body: str) -> None:
        super().__init__(parent, theme, title, resizable=True)
        c = theme.colors
        tk.Label(self.content, text=title, font=theme.font("title"), background=c.surface, foreground=c.text,
                 anchor="w").pack(fill="x", pady=(0, theme.px(SPACE_M)))
        self.view = TextArea(self.content, theme, readonly=True, font="mono", height=20)
        self.view.configure(highlightthickness=1, highlightbackground=c.border)
        self.view.text.configure(padx=theme.px(SPACE_M), pady=theme.px(SPACE_S), spacing3=0, spacing2=0)
        self.view.set(body)
        self.view.pack(fill="both", expand=True)
        self.close_button = self.add_button("Close", self.cancel, variant="primary")

    def show(self) -> "TextViewerDialog":
        self.present(focus=self.close_button, modal=False, size=(self.theme.px(760), self.theme.px(580)))
        return self


WELCOME_POINTS = (
    ("shield", "Stays on this PC",
     "Memories you save are stored in a local SQLite file in your Windows user profile. Nothing is uploaded."),
    ("edit", "Only what you allow",
     "BIO CE never records conversations. A memory is stored when you select Save, or when you turn on Auto "
     "memory for an AI host and it saves a lasting fact under BIO CE's rules."),
    ("lock", "AI access is read only by default",
     "A connected AI host can search and read your memories. It can save or update them only after you turn on "
     "Auto memory for it, and it can never retract one without you. Memories a host reads or saves become part "
     "of that conversation and may be sent to the host's AI model provider."),
    ("backup", "Connection backups stay local",
     "Connecting a host first backs up its MCP settings. Those backups can contain settings or environment values "
     "for other servers and are stored without encryption."),
    ("warning", "Know the limits",
     "The database is not encrypted. Retraction hides a memory but does not securely erase earlier revisions."),
)


class ReviewEditDialog(Dialog):
    """Let the user correct an AI-suggested memory before approving it."""

    def __init__(self, parent: tk.Misc, theme: Theme, *, title: str, content: str, reason: str) -> None:
        super().__init__(parent, theme, "Edit before saving", resizable=True)
        c = theme.colors
        tk.Label(self.content, text="Edit before saving", font=theme.font("title"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        WrapLabel(self.content, f"Suggested by an AI host: {reason}", font=theme.font("caption"),
                  foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_M)))
        tk.Label(self.content, text="Title", font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        self.title_value = tk.StringVar(master=self, value=title)
        self.title_field = Field(self.content, theme, textvariable=self.title_value)
        self.title_field.pack(fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_M)))
        tk.Label(self.content, text="Memory", font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        self.body = TextArea(self.content, theme, height=8)
        self.body.set(content)
        self.body.pack(fill="both", expand=True, pady=(theme.px(SPACE_XS), 0))
        self.add_button("Save memory", self._save, variant="primary")
        self.add_button("Cancel", self.cancel)

    def _save(self) -> None:
        title, content = self.title_value.get().strip(), self.body.get().strip()
        if not title:
            self.title_field.set_error(True)
            return
        self.finish((title, content))

    def ask(self) -> tuple[str, str] | None:
        self.present(focus=self.title_field, size=(self.theme.px(560), self.theme.px(440)))
        return self.result  # type: ignore[return-value]


def ask_privacy_consent(root: tk.Tk, theme: Theme) -> bool:
    """Show the first-run data notice inside the main window; True to continue."""
    c = theme.colors
    decision = tk.StringVar(master=root, value="")
    page = tk.Frame(root, background=c.surface)
    page.pack(fill="both", expand=True)
    footer = tk.Frame(page, background=c.bg)
    footer.pack(side="bottom", fill="x")
    tk.Frame(page, height=1, background=c.border).pack(side="bottom", fill="x")
    scroll = ScrollFrame(page, theme, max_width=620, center=True)
    scroll.pack(fill="both", expand=True)
    body = tk.Frame(scroll.body, background=c.surface)
    body.pack(fill="x", padx=theme.px(36), pady=(theme.px(32), theme.px(SPACE_XL)))
    tk.Label(body, text="BIO COMMUNITY EDITION", font=theme.font("caption_strong"), background=c.surface,
             foreground=c.accent_text, anchor="w").pack(fill="x")
    tk.Label(body, text="Welcome to BIO CE", font=theme.font("display"), background=c.surface, foreground=c.text,
             anchor="w").pack(fill="x", pady=(theme.px(SPACE_XS), 0))
    WrapLabel(body, "A private memory manager for your AI tools. Before you start, here is how your data is handled.",
              font=theme.font("body"), foreground=c.text_secondary).pack(
        fill="x", pady=(theme.px(SPACE_S), theme.px(SPACE_L)))
    for icon, heading, text in WELCOME_POINTS:
        row = tk.Frame(body, background=c.surface)
        row.pack(fill="x", pady=theme.px(7))
        tk.Label(row, text=theme.icon(icon), font=theme.icon_font("normal"), background=c.surface,
                 foreground=c.warning if icon == "warning" else c.accent_text, width=2).pack(
            side="left", anchor="n", padx=(0, theme.px(SPACE_M)), pady=(theme.px(2), 0))
        column = tk.Frame(row, background=c.surface)
        column.pack(side="left", fill="x", expand=True)
        tk.Label(column, text=heading, font=theme.font("body_strong"), background=c.surface, foreground=c.text,
                 anchor="w").pack(fill="x")
        WrapLabel(column, text, font=theme.font("body"), foreground=c.text_secondary).pack(fill="x")
    tk.Label(body, text="Select Continue to create your local BIO CE data folder.", font=theme.font("caption"),
             background=c.surface, foreground=c.text_muted, anchor="w").pack(fill="x", pady=(theme.px(SPACE_L), 0))
    buttons = tk.Frame(footer, background=c.bg)
    buttons.pack(side="right", padx=theme.px(SPACE_XL), pady=theme.px(SPACE_L))
    proceed = Button(buttons, theme, "Continue", variant="primary", command=lambda: decision.set("accept"))
    proceed.pack(side="left")
    Button(buttons, theme, "Quit", command=lambda: decision.set("decline")).pack(side="left", padx=(theme.px(SPACE_S), 0))
    root.protocol("WM_DELETE_WINDOW", lambda: decision.set("decline"))
    root.bind("<Escape>", lambda _e: decision.set("decline"))
    root.deiconify()
    apply_window_chrome(root, c)
    proceed.focus_set()
    root.wait_variable(decision)
    root.unbind("<Escape>")
    page.destroy()
    return decision.get() == "accept"


__all__ = [
    "ConfirmDialog",
    "Dialog",
    "HistoryDialog",
    "ReviewEditDialog",
    "TextViewerDialog",
    "WELCOME_POINTS",
    "ask_privacy_consent",
]
