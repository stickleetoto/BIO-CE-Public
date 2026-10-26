# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Add or revise one memory. Nothing is written until the user selects Save."""

from __future__ import annotations

import tkinter as tk

from bio_ce.core.models import MemoryNotFoundError, MemoryRevision, RevisionConflictError, ValidationError
from bio_ce.ui.format import (
    CONTENT_LIMIT,
    DEFAULT_SOURCE,
    SOURCE_LIMIT,
    TITLE_LIMIT,
    preview,
    validation_feedback,
)
from bio_ce.ui.pages import Page
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XL, SPACE_XS
from bio_ce.ui.widgets import Button, Card, Field, TextArea, WrapLabel


class EditorPage(Page):
    key = "editor"
    nav_key = "memories"

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        self.editing: MemoryRevision | None = None
        self._baseline = ("", DEFAULT_SOURCE, "")
        self.title_value = tk.StringVar(master=self)
        self.source_value = tk.StringVar(master=self, value=DEFAULT_SOURCE)

        Button(self.actions, theme, "Back to memories", icon="back", variant="subtle",
               command=self.cancel_edit, tooltip="Back without saving (Esc)").pack(side="right")

        footer = tk.Frame(self, background=c.bg)
        footer.pack(side="bottom", fill="x", pady=(theme.px(SPACE_M), 0))
        buttons = tk.Frame(footer, background=c.bg)
        buttons.pack(side="right")
        self.save_button = Button(buttons, theme, "Save memory", icon="check", variant="primary",
                                  command=self.save_memory, tooltip="Save (Ctrl+S)")
        self.save_button.pack(side="left")
        Button(buttons, theme, "Cancel", command=self.cancel_edit).pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.status = WrapLabel(footer, font=theme.font("caption"), foreground=c.text_muted, background=c.bg)
        self.status.pack(side="left", fill="x", expand=True, padx=(0, theme.px(SPACE_L)))

        card = Card(self, theme, padding=SPACE_XL)
        card.pack(fill="both", expand=True)
        form = card.body

        self.title_counter = self._label_row(form, "Title", "")
        self.title_field = Field(form, theme, textvariable=self.title_value, font="body_strong")
        self.title_field.pack(fill="x")
        self.title_error = self._error_label(form)

        self.content_counter = self._label_row(form, "Memory", "", top=SPACE_L)
        self.content = TextArea(form, theme, font="reading", height=12)
        self.content.pack(fill="both", expand=True)
        self.content_error = self._error_label(form)

        self.source_counter = self._label_row(form, "Source", "", top=SPACE_L)
        self.source_field = Field(form, theme, textvariable=self.source_value)
        self.source_field.pack(fill="x")
        self.source_error = self._error_label(form)
        WrapLabel(form, "Where this came from, such as a meeting, document, or “user-input”. It is stored as "
              "descriptive text and does not make a memory more trusted.", font=theme.font("caption"),
                  foreground=c.text_muted).pack(fill="x", pady=(theme.px(SPACE_XS), 0))

        self.title_value.trace_add("write", lambda *_: self._on_change())
        self.source_value.trace_add("write", lambda *_: self._on_change())
        self.content.text.bind("<<Modified>>", self._on_text_modified, add="+")
        self.title_field.entry.bind("<Return>", lambda _e: (self.content.text.focus_set(), "break")[1])
        self._on_change()

    @property
    def title(self) -> str:  # type: ignore[override]
        return "New memory" if self.editing is None else "Edit memory"

    @property
    def subtitle(self) -> str:  # type: ignore[override]
        if self.editing is None:
            return "Nothing is stored until you select Save"
        return f"Saving creates revision {self.editing.revision_number + 1}; earlier revisions are kept"

    def _label_row(self, master: tk.Misc, text: str, counter: str, *, top: int = 0) -> tk.Label:
        c = self.colors
        row = tk.Frame(master, background=c.surface)
        row.pack(fill="x", pady=(self.theme.px(top), self.theme.px(SPACE_XS + 2)))
        tk.Label(row, text=text, font=self.theme.font("body_strong"), background=c.surface, foreground=c.text,
                 anchor="w").pack(side="left")
        label = tk.Label(row, text=counter, font=self.theme.font("caption"), background=c.surface,
                         foreground=c.text_muted, anchor="e")
        label.pack(side="right")
        return label

    def _error_label(self, master: tk.Misc) -> WrapLabel:
        return WrapLabel(master, font=self.theme.font("caption"), foreground=self.colors.danger)

    # State ----------------------------------------------------------------

    def values(self) -> tuple[str, str, str]:
        return self.title_value.get(), self.source_value.get(), self.content.get()

    @property
    def dirty(self) -> bool:
        return self.values() != self._baseline

    def load(self, record: MemoryRevision | None) -> None:
        self.editing = record
        if record is None:
            title, source, body = "", DEFAULT_SOURCE, ""
        else:
            title, source, body = record.title, record.source.source_ref, record.content or ""
        self.title_value.set(title)
        self.source_value.set(source)
        self.content.set(body)
        self._baseline = (title, source, body)
        self._clear_errors()
        self._on_change()

    def focus_default(self) -> None:
        if self.editing is None:
            self.title_field.focus_set()
        else:
            self.content.text.focus_set()
            self.content.text.mark_set("insert", "end-1c")

    def _on_text_modified(self, _event=None) -> None:
        if self.content.text.edit_modified():
            self.content.text.edit_modified(False)
            self._on_change()

    def _on_change(self) -> None:
        title, source, body = self.values()
        c = self.colors
        for label, value, limit in ((self.title_counter, title, TITLE_LIMIT),
                                    (self.content_counter, body, CONTENT_LIMIT),
                                    (self.source_counter, source, SOURCE_LIMIT)):
            label.configure(text=f"{len(value):,} / {limit:,}", foreground=c.danger if len(value) > limit else c.text_muted)
        if self.editing is None:
            state = "New memory · not saved yet" if self.dirty else "New memory · nothing to save yet"
        else:
            state = (f"Editing revision {self.editing.revision_number} · unsaved changes" if self.dirty
                     else f"Editing revision {self.editing.revision_number} · no changes")
        self.status.configure(text=state)

    def _clear_errors(self) -> None:
        for field, label in ((self.title_field, self.title_error), (self.content, self.content_error),
                             (self.source_field, self.source_error)):
            field.set_error(False)
            label.configure(text="")
            label.pack_forget()

    def _show_error(self, field_name: str, message: str) -> None:
        field, label, before = {
            "title": (self.title_field, self.title_error, self.content_counter.master),
            "content": (self.content, self.content_error, self.source_counter.master),
            "source_ref": (self.source_field, self.source_error, None),
        }[field_name]
        field.set_error(True)
        label.configure(text=message)
        options = {"fill": "x", "pady": (self.theme.px(SPACE_XS + 2), 0)}
        if before is not None:
            options["before"] = before
        else:
            options["after"] = self.source_field
        label.pack(**options)
        field.focus_set()

    # Actions --------------------------------------------------------------

    def save_memory(self) -> MemoryRevision | None:
        title, source_ref, content = self.values()
        self._clear_errors()
        service = self.app.service
        try:
            if self.editing is None:
                saved = service.add(title=title, content=content, source_ref=source_ref)
                created = True
            else:
                saved = service.revise(self.editing, title=title, content=content, source_ref=source_ref)
                created = False
        except ValidationError as exc:
            field, message = validation_feedback(exc)
            if field is not None:
                self._show_error(field, message)
            else:
                self.app.notify("error", message, title="Check the memory")
            return None
        except (RevisionConflictError, MemoryNotFoundError):
            self.app.notify(
                "warning",
                "This memory was changed or retracted after you opened it, so BIO CE did not overwrite it. "
                "Your text is still here: copy anything you need, then reload the latest version.",
                title="Memory changed elsewhere",
                action=("Reload latest", self.reload_latest),
            )
            return None
        except Exception:
            self.app.notify("error", "BIO CE couldn't save this memory. Your text is still here; try again.",
                            title="Save failed")
            return None
        self._baseline = self.values()
        self.editing = None
        self.load(None)
        self.app.memory_saved(saved, created=created)
        return saved

    def reload_latest(self) -> None:
        if self.editing is None:
            return
        try:
            latest = self.app.service.read(self.editing.memory_id)
        except MemoryNotFoundError:
            self._baseline = self.values()
            self.app.show_page("memories")
            self.app.data_changed()
            self.app.notify("warning", "This memory has been retracted, so it can no longer be edited.",
                            title="Memory unavailable")
            return
        except Exception:
            self.app.notify("error", "BIO CE couldn't load the latest version. Try again.", title="Reload failed")
            return
        if self.dirty and not self.app.confirm(
            title="Discard your changes?",
            message="Reloading replaces the text in the editor with the latest saved version.",
            confirm_text="Discard and reload",
            danger=True,
        ):
            return
        self.load(latest)
        self.app.refresh_header()
        self.app.notify("info", f"Loaded revision {latest.revision_number} of “{preview(latest.title, 50)}”.")

    def cancel_edit(self) -> None:
        self.app.show_page("memories")

    def confirm_leave(self) -> bool:
        """Ask before discarding unsaved edits; True when it is safe to leave."""
        if not self.dirty:
            return True
        discard = self.app.confirm(
            title="Discard unsaved changes?",
            message="Your edits to this memory haven't been saved." if self.editing is not None
            else "This new memory hasn't been saved.",
            confirm_text="Discard",
            cancel_text="Keep editing",
            danger=True,
        )
        if discard:
            self.load(None)
        return discard


__all__ = ["EditorPage"]
