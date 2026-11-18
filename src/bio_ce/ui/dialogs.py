# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Themed dialogs: confirmations, revision history, text viewer, first-run notice."""

from __future__ import annotations

import time
from typing import Callable, Sequence
import tkinter as tk

from bio_ce.engine.contract import MemoryView
from bio_ce.ui.format import format_timestamp, revision_kind_label
from bio_ce.ui.hub.common import space_label
from bio_ce.ui.hub.filters import source_text
from bio_ce.ui.i18n import t
from bio_ce.ui.theme import (
    SPACE_L,
    SPACE_M,
    SPACE_S,
    SPACE_XL,
    SPACE_XS,
    SPACE_XXL,
    SPACE_XXS,
    Theme,
    apply_window_chrome,
)
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
        self.buttons.pack(side="right", padx=theme.px(SPACE_XL), pady=theme.px(SPACE_L))
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
        cancel_text: str | None = None,
        danger: bool = False,
        points: Sequence[str] = (),
        quote: str | None = None,
        options: Sequence[tuple[str, str, bool]] = (),
        choices: dict[str, bool] | None = None,
        links: Sequence[tuple[str, Callable[[tk.Misc], None]]] = (),
    ) -> None:
        """``options`` are (key, label, default) check boxes; when the user confirms, their values are
        written into ``choices``. ``links`` are (label, action) buttons; the action gets this dialog."""
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
                     anchor="w", justify="left", wraplength=wrap - theme.px(SPACE_XL)).pack(
                fill="x", padx=theme.px(SPACE_M), pady=theme.px(SPACE_S))
        for point in points:
            row = tk.Frame(column, background=c.surface)
            row.pack(fill="x", pady=(theme.px(SPACE_S), 0))
            tk.Label(row, text="•", font=theme.font("body"), background=c.surface,
                     foreground=c.text_muted).pack(side="left", anchor="n", padx=(0, theme.px(SPACE_S)))
            tk.Label(row, text=point, font=theme.font("body"), background=c.surface, foreground=c.text_secondary,
                     anchor="w", justify="left", wraplength=wrap - theme.px(SPACE_L)).pack(side="left", fill="x")
        self.option_vars: dict[str, tk.BooleanVar] = {}
        for key, label, default in options:
            variable = tk.BooleanVar(self, value=default)
            self.option_vars[key] = variable
            tk.Checkbutton(column, text=label, variable=variable, font=theme.font("body"), background=c.surface,
                           foreground=c.text, activebackground=c.surface, activeforeground=c.text,
                           selectcolor=c.surface_alt, anchor="w", justify="left", wraplength=wrap - theme.px(SPACE_XL),
                           highlightthickness=0, borderwidth=0).pack(fill="x", pady=(theme.px(SPACE_S), 0))
        for label, action in links:
            Button(column, theme, label, variant="link", command=lambda act=action: self._open_link(act)).pack(
                anchor="w", pady=(theme.px(SPACE_XS), 0))
        self._choices = choices

        def confirmed() -> None:
            if self._choices is not None:
                self._choices.update({key: bool(variable.get()) for key, variable in self.option_vars.items()})
            self.finish(True)

        confirm = self.add_button(confirm_text, confirmed, variant="danger" if danger else "primary")
        cancel = self.add_button(t("common.cancel") if cancel_text is None else cancel_text, self.cancel)
        self.result = False
        self._default_focus = cancel if danger else confirm

    def cancel(self) -> None:
        self.finish(False)

    def _open_link(self, action: Callable[[tk.Misc], None]) -> None:
        action(self)
        if self.winfo_exists():
            self.grab_set()  # a nested dialog took the grab; take it back

    def ask(self) -> bool:
        self.present(focus=self._default_focus)
        return bool(self.result)


class HistoryDialog(Dialog):
    """Read-only, newest-first view of every revision of one memory."""

    def __init__(self, parent: tk.Misc, theme: Theme, revisions: Sequence[MemoryView], *,
                 undo: Callable[[], object] | None = None) -> None:
        """``undo``: when the current revision came from an approved suggestion, a button that undoes it."""
        super().__init__(parent, theme, t("dialog.history.title"), resizable=True)
        self._undo = undo
        c = theme.colors
        latest = revisions[-1] if revisions else None
        tk.Label(self.content, text=t("dialog.history.title"), font=theme.font("title"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        subtitle = (t("dialog.history.subtitle", title=latest.title, count=len(revisions))
                    if latest else t("dialog.history.none"))
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
            text.insert(tk.END, t("dialog.history.revision", number=revision.revision_number,
                                  kind=revision_kind_label(revision.kind)), "heading")
            if index == 0:
                text.insert(tk.END, "   " + t("dialog.history.current"), "current")
            text.insert(tk.END, "\n")
            text.insert(
                tk.END,
                t("dialog.history.meta", time=format_timestamp(revision.recorded_at), source=source_text(revision))
                + "\n",
                "meta",
            )
            text.insert(tk.END, f"{revision.title}\n", "title")
            if revision.content:
                body = revision.content if len(revision.content) <= 4000 else revision.content[:4000] + "…"
                text.insert(tk.END, body.rstrip() + "\n", "body")
            else:
                text.insert(tk.END, t("dialog.history.no_text") + "\n", "empty")
        text.configure(state="disabled")
        self.undo_button = None
        if undo is not None:
            self.undo_button = self.add_button(t("dialog.history.undo"), self._undo_clicked, variant="secondary")
        self.close_button = self.add_button(t("common.close"), self.cancel, variant="primary")

    def _undo_clicked(self) -> None:
        if self._undo is not None and self._undo():
            self.cancel()

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
        self.close_button = self.add_button(t("common.close"), self.cancel, variant="primary")

    def show(self, *, modal: bool = False) -> "TextViewerDialog":
        """Non-modal by default; modal when opened from another modal dialog, which holds the input grab."""
        self.present(focus=self.close_button, modal=modal, size=(self.theme.px(760), self.theme.px(580)))
        return self


class ShortcutsDialog(Dialog):
    """The keyboard shortcuts (v0.4.4 F3, the ? key), from the same table as the Settings list."""

    def __init__(self, parent: tk.Misc, theme: Theme) -> None:
        from bio_ce.ui.shortcuts import SHORTCUTS

        super().__init__(parent, theme, t("shortcut.dialog_title"))
        c = theme.colors
        tk.Label(self.content, text=t("shortcut.dialog_title"), font=theme.font("title"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x", pady=(0, theme.px(SPACE_M)))
        # The list scrolls: Korean lines wrap taller and ran past the fixed height (self-check 2026-11-17).
        self.scroll = ScrollFrame(self.content, theme)
        self.scroll.pack(fill="both", expand=True)
        grid = tk.Frame(self.scroll.body, background=c.surface)
        grid.pack(fill="both", expand=True)
        self.rows = []
        for index, shortcut in enumerate(SHORTCUTS):
            tk.Label(grid, text=shortcut.shown, font=theme.font("mono"), background=c.surface_alt, foreground=c.text,
                     padx=theme.px(SPACE_S), pady=theme.px(1)).grid(row=index, column=0, sticky="w", pady=theme.px(SPACE_XS))
            label = WrapLabel(grid, t(shortcut.text), font=theme.font("body"), foreground=c.text_secondary)
            label.grid(row=index, column=1, sticky="we", padx=(theme.px(SPACE_M), 0))
            self.rows.append(label)
        grid.columnconfigure(1, weight=1)
        self.close_button = self.add_button(t("common.close"), self.cancel, variant="primary")

    def show(self) -> ShortcutsDialog:
        self.present(focus=self.close_button, modal=False, size=(self.theme.px(560), self.theme.px(620)))
        return self


#: (icon, heading key, text key) of the first-run notice; looked up when the notice is shown.
WELCOME_POINTS = (
    ("shield", "dialog.welcome.local", "dialog.welcome.local_text"),
    ("edit", "dialog.welcome.allow", "dialog.welcome.allow_text"),
    ("lock", "dialog.welcome.read_only", "dialog.welcome.read_only_text"),
    ("backup", "dialog.welcome.backups", "dialog.welcome.backups_text"),
    ("warning", "dialog.welcome.limits", "dialog.welcome.limits_text"),
)


class ReviewEditDialog(Dialog):
    """Let the user correct an AI-suggested memory before approving it."""

    def __init__(self, parent: tk.Misc, theme: Theme, *, title: str, content: str, reason: str) -> None:
        super().__init__(parent, theme, t("dialog.review_edit.title"), resizable=True)
        c = theme.colors
        tk.Label(self.content, text=t("dialog.review_edit.title"), font=theme.font("title"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        WrapLabel(self.content, t("dialog.review_edit.reason", reason=reason), font=theme.font("caption"),
                  foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_M)))
        tk.Label(self.content, text=t("dialog.review_edit.title_label"), font=theme.font("body_strong"),
                 background=c.surface, foreground=c.text, anchor="w").pack(fill="x")
        self.title_value = tk.StringVar(master=self, value=title)
        self.title_field = Field(self.content, theme, textvariable=self.title_value)
        self.title_field.pack(fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_M)))
        tk.Label(self.content, text=t("dialog.review_edit.memory_label"), font=theme.font("body_strong"),
                 background=c.surface, foreground=c.text, anchor="w").pack(fill="x")
        self.body = TextArea(self.content, theme, height=8)
        self.body.set(content)
        self.body.pack(fill="both", expand=True, pady=(theme.px(SPACE_XS), 0))
        self.add_button(t("dialog.review_edit.save"), self._save, variant="primary")
        self.add_button(t("common.cancel"), self.cancel)

    def _save(self) -> None:
        title, content = self.title_value.get().strip(), self.body.get().strip()
        if not title:
            self.title_field.set_error(True)
            return
        self.finish((title, content))

    def ask(self) -> tuple[str, str] | None:
        self.present(focus=self.title_field, size=(self.theme.px(560), self.theme.px(440)))
        return self.result  # type: ignore[return-value]


class NameDialog(Dialog):
    """Ask for one short name (for example a space name)."""

    def __init__(self, parent: tk.Misc, theme: Theme, *, title: str, label: str, value: str = "",
                 confirm_text: str | None = None, note: str = "") -> None:
        super().__init__(parent, theme, title)
        c = theme.colors
        tk.Label(self.content, text=title, font=theme.font("title"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        if note:
            WrapLabel(self.content, note, font=theme.font("caption"), foreground=c.text_secondary).pack(
                fill="x", pady=(theme.px(SPACE_XS), 0))
        tk.Label(self.content, text=label, font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.value = tk.StringVar(master=self, value=value)
        self.field = Field(self.content, theme, textvariable=self.value)
        self.field.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.bind("<Return>", lambda _event: self._save() if self.armed else None)
        self.add_button(t("common.save") if confirm_text is None else confirm_text, self._save, variant="primary")
        self.add_button(t("common.cancel"), self.cancel)

    def _save(self) -> None:
        name = " ".join(self.value.get().split())
        if not name or len(name) > 80:
            self.field.set_error(True)
            return
        self.finish(name)

    def ask(self) -> str | None:
        self.present(focus=self.field, size=(self.theme.px(480), self.theme.px(260)))
        return self.result  # type: ignore[return-value]


class EntryEditDialog(Dialog):
    """Edit one import entry before importing: its text and, optionally, the date the user said it."""

    def __init__(self, parent: tk.Misc, theme: Theme, *, content: str, said_at: str = "", reasons: str = "",
                 source_date: str = "") -> None:
        super().__init__(parent, theme, t("dialog.entry.title"), resizable=True)
        c = theme.colors
        tk.Label(self.content, text=t("dialog.entry.title"), font=theme.font("title"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        if reasons:
            WrapLabel(self.content, reasons, font=theme.font("caption"), foreground=c.text_secondary).pack(
                fill="x", pady=(theme.px(SPACE_XS), 0))
        if source_date:  # owner rule 2026-11-16: a changed text doesn't keep a date that was about the old one
            WrapLabel(self.content, t("dialog.entry.date_cleared", date=source_date),
                      font=theme.font("caption"), foreground=c.warning).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        WrapLabel(self.content, t("dialog.entry.instruction_hint"), font=theme.font("caption"),
                  foreground=c.text_muted).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.text = TextArea(self.content, theme, font="body")
        self.text.text.configure(height=6)
        self.text.set(content)
        self.text.pack(fill="both", expand=True, pady=(theme.px(SPACE_S), 0))
        tk.Label(self.content, text=t("dialog.entry.said_on"), font=theme.font("body_strong"),
                 background=c.surface, foreground=c.text, anchor="w").pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.date = tk.StringVar(master=self, value=said_at)
        Field(self.content, theme, textvariable=self.date).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.add_button(t("common.save"), self._save, variant="primary")
        self.add_button(t("common.cancel"), lambda: self.finish(None))
        self.result = None

    def _save(self) -> None:
        text = " ".join(self.text.get().split())
        if not text:
            self.text.set_error(True)
            return
        self.finish((text, self.date.get().strip()))

    def ask(self) -> tuple[str, str] | None:
        self.present(focus=self.text, size=(self.theme.px(560), self.theme.px(420)))
        return self.result  # type: ignore[return-value]


def export_sources() -> list[tuple[str, str]]:
    """The export dialog's source choices in the app's language, in the source filter's words (rc3: the dialog showed
    the exporter's English labels on Korean screens)."""
    from bio_ce.exporter import SOURCE_KINDS

    return [(key, t(f"dialog.export.source.{key}")) for key in SOURCE_KINDS]


class ExportDialog(Dialog):
    """Choose what to export: spaces (Personal only by ticking it), the inbox, sources, and dates."""

    def __init__(self, parent: tk.Misc, theme: Theme, *, spaces: Sequence, current: str | None,
                 sources: Sequence[tuple[str, str]]) -> None:
        super().__init__(parent, theme, t("dialog.export.title"), resizable=True)
        c = theme.colors
        tk.Label(self.content, text=t("dialog.export.title"), font=theme.font("title"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        WrapLabel(self.content, t("dialog.export.description"), font=theme.font("caption"),
                  foreground=c.text_secondary).pack(fill="x")

        def check(master, label, value=False):
            variable = tk.BooleanVar(self, value=value)
            tk.Checkbutton(master, text=label, variable=variable, font=theme.font("body"), background=c.surface,
                           foreground=c.text, activebackground=c.surface, activeforeground=c.text,
                           selectcolor=c.surface_alt, anchor="w", highlightthickness=0, borderwidth=0).pack(fill="x")
            return variable

        def heading(text):
            tk.Label(self.content, text=text, font=theme.font("body_strong"), background=c.surface,
                     foreground=c.text, anchor="w").pack(fill="x", pady=(theme.px(SPACE_M), 0))

        heading(t("dialog.export.spaces"))
        self.space_vars: dict[str, tk.BooleanVar] = {}
        for space in spaces:
            label = space_label(space)  # "개인", as on every screen (rc3); the warning below says what it holds
            self.space_vars[space.space_id] = check(self.content, label,
                                                    space.space_id == current and not space.is_personal)
            if space.is_personal:
                self.personal_box = self.content.winfo_children()[-1]
        self.personal_warning = WrapLabel(self.content, t("dialog.export.personal_warning"),
                                          font=theme.font("caption"), foreground=c.warning)
        if "personal" in self.space_vars:
            self.space_vars["personal"].trace_add("write", lambda *_: self._sync_warning())
        heading(t("dialog.export.what"))
        self.include_inbox = check(self.content, t("dialog.export.include_inbox"))
        heading(t("dialog.export.sources"))
        self.source_vars = {key: check(self.content, label, True) for key, label in sources}
        heading(t("dialog.export.dates"))
        row = tk.Frame(self.content, background=c.surface)
        row.pack(fill="x")
        self.date_from, self.date_to = tk.StringVar(master=self), tk.StringVar(master=self)
        Field(row, theme, textvariable=self.date_from).pack(side="left", fill="x", expand=True)
        tk.Label(row, text=t("dialog.export.date_to"), font=theme.font("body"), background=c.surface,
                 foreground=c.text_muted).pack(side="left", padx=theme.px(SPACE_S))
        Field(row, theme, textvariable=self.date_to).pack(side="left", fill="x", expand=True)
        self.include_claimed = check(self.content, t("dialog.export.include_claimed"))
        self.error = WrapLabel(self.content, "", font=theme.font("caption"), foreground=c.danger)
        self.error.pack(fill="x")
        self.add_button(t("dialog.export.button"), self._done, variant="primary")
        self.add_button(t("common.cancel"), lambda: self.finish(None))
        self.result = None

    def _sync_warning(self) -> None:
        if self.space_vars["personal"].get():
            self.personal_warning.pack(fill="x", after=self.personal_box)
        else:
            self.personal_warning.pack_forget()

    def _done(self) -> None:
        import re as _re
        spaces = tuple(key for key, variable in self.space_vars.items() if variable.get())
        sources = frozenset(key for key, variable in self.source_vars.items() if variable.get())
        dates = (self.date_from.get().strip(), self.date_to.get().strip())
        if not spaces or not sources:
            self.error.configure(text=t("dialog.export.choose_first"))
            return
        if any(value and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in dates):
            self.error.configure(text=t("dialog.export.bad_date"))
            return
        self.finish({"space_ids": spaces, "include_inbox": bool(self.include_inbox.get()), "sources": sources,
                     "date_from": dates[0] or None, "date_to": dates[1] or None,
                     "include_claimed": bool(self.include_claimed.get())})

    def ask(self) -> dict | None:
        self.present(size=(self.theme.px(520), self.theme.px(640)))
        return self.result  # type: ignore[return-value]


class ChoiceDialog(Dialog):
    """Pick one of a few options (for example the space to move memories to). Returns its key or None."""

    def __init__(self, parent: tk.Misc, theme: Theme, *, title: str, message: str,
                 choices: Sequence[tuple[str, str, str]], confirm_text: str, note: str = "") -> None:
        """``choices`` are (key, label, detail); the first is selected."""
        super().__init__(parent, theme, title)
        c = theme.colors
        wrap = theme.px(440)
        tk.Label(self.content, text=title, font=theme.font("title"), background=c.surface, foreground=c.text,
                 anchor="w").pack(fill="x")
        WrapLabel(self.content, message, font=theme.font("body"), foreground=c.text_secondary).pack(
            fill="x", pady=(theme.px(SPACE_S), 0))
        self.choice = tk.StringVar(master=self, value=choices[0][0] if choices else "")
        for key, label, detail in choices:
            tk.Radiobutton(self.content, text=label, value=key, variable=self.choice, font=theme.font("body_strong"),
                           background=c.surface, foreground=c.text, activebackground=c.surface,
                           activeforeground=c.text, selectcolor=c.surface_alt, anchor="w", highlightthickness=0,
                           borderwidth=0).pack(fill="x", pady=(theme.px(SPACE_S), 0))
            if detail:
                tk.Label(self.content, text=detail, font=theme.font("caption"), background=c.surface,
                         foreground=c.text_muted, anchor="w", justify="left", wraplength=wrap).pack(
                    fill="x", padx=(theme.px(SPACE_XL), 0))
        if note:
            WrapLabel(self.content, note, font=theme.font("caption"), foreground=c.text_muted).pack(
                fill="x", pady=(theme.px(SPACE_M), 0))
        self.add_button(confirm_text, lambda: self.finish(self.choice.get() or None), variant="primary")
        self.add_button(t("common.cancel"), lambda: self.finish(None))
        self.result = None

    def ask(self) -> str | None:
        self.present()
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
    body.pack(fill="x", padx=theme.px(SPACE_XXL), pady=(theme.px(SPACE_XXL), theme.px(SPACE_XL)))
    tk.Label(body, text=t("dialog.welcome.product"), font=theme.font("caption_strong"), background=c.surface,
             foreground=c.accent_text, anchor="w").pack(fill="x")
    tk.Label(body, text=t("dialog.welcome.title"), font=theme.font("display"), background=c.surface,
             foreground=c.text, anchor="w").pack(fill="x", pady=(theme.px(SPACE_XS), 0))
    WrapLabel(body, t("dialog.welcome.intro"), font=theme.font("body"), foreground=c.text_secondary).pack(
        fill="x", pady=(theme.px(SPACE_S), theme.px(SPACE_L)))
    for icon, heading_key, text_key in WELCOME_POINTS:
        heading, text = t(heading_key), t(text_key)
        row = tk.Frame(body, background=c.surface)
        row.pack(fill="x", pady=theme.px(SPACE_S))
        tk.Label(row, text=theme.icon(icon), font=theme.icon_font("normal"), background=c.surface,
                 foreground=c.warning if icon == "warning" else c.accent_text, width=2).pack(
            side="left", anchor="n", padx=(0, theme.px(SPACE_M)), pady=(theme.px(SPACE_XXS), 0))
        column = tk.Frame(row, background=c.surface)
        column.pack(side="left", fill="x", expand=True)
        tk.Label(column, text=heading, font=theme.font("body_strong"), background=c.surface, foreground=c.text,
                 anchor="w").pack(fill="x")
        WrapLabel(column, text, font=theme.font("body"), foreground=c.text_secondary).pack(fill="x")
    tk.Label(body, text=t("dialog.welcome.continue_note"), font=theme.font("caption"),
             background=c.surface, foreground=c.text_muted, anchor="w").pack(fill="x", pady=(theme.px(SPACE_L), 0))
    buttons = tk.Frame(footer, background=c.bg)
    buttons.pack(side="right", padx=theme.px(SPACE_XL), pady=theme.px(SPACE_L))
    proceed = Button(buttons, theme, t("dialog.welcome.continue"), variant="primary",
                     command=lambda: decision.set("accept"))
    proceed.pack(side="left")
    Button(buttons, theme, t("dialog.welcome.quit"), command=lambda: decision.set("decline")).pack(
        side="left", padx=(theme.px(SPACE_S), 0))
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
    "NameDialog",
    "ReviewEditDialog",
    "TextViewerDialog",
    "WELCOME_POINTS",
    "ask_privacy_consent",
]
