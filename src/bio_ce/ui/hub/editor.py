# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Add or edit one memory inside the drawer (v0.4.4 §2.2; the separate editor page is gone, owner decision Q11).

Nothing is written until the user saves (Save, Ctrl+S, Enter in the title, Ctrl+Enter in the text). A memory that
changed elsewhere in the meantime is never overwritten: the user's text stays and "Reload latest" loads the newer one.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from bio_ce.core.models import MemoryNotFoundError, RevisionConflictError, ValidationError
from bio_ce.engine.contract import EngineUnavailable, MemoryView, UnsupportedCapability, WriteStatus
from bio_ce.engine.presentation import outcome_message
from bio_ce.ui.format import CONTENT_LIMIT, DEFAULT_SOURCE, SOURCE_LIMIT, TITLE_LIMIT, preview, validation_feedback
from bio_ce.ui.hub.common import in_space, space_label
from bio_ce.ui.i18n import t
from bio_ce.ui.service_text import say
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import Button, Field, FlowFrame, TextArea, WrapLabel


class DrawerEditor(tk.Frame):
    def __init__(self, master: tk.Misc, hub) -> None:
        theme, c = hub.theme, hub.colors
        super().__init__(master, background=c.surface)
        self.hub = hub
        self.app = hub.app
        self.theme = theme
        self.colors = c
        self.editing: MemoryView | None = None
        self.space = None
        self._spaces: list = []
        self._baseline = ("", DEFAULT_SOURCE, "")
        self.title_value = tk.StringVar(master=self)
        self.source_value = tk.StringVar(master=self, value=DEFAULT_SOURCE)
        self.space_value = tk.StringVar(master=self)

        self.heading = tk.Label(self, font=theme.font("title"), background=c.surface, foreground=c.text, anchor="w")
        self.heading.pack(fill="x")
        self.space_row = tk.Frame(self, background=c.surface)
        tk.Label(self.space_row, text=t("hub.editor.space"), font=theme.font("caption_strong"), background=c.surface,
                 foreground=c.text_muted).pack(side="left", padx=(0, theme.px(SPACE_S)))
        self.space_picker = ttk.Combobox(self.space_row, textvariable=self.space_value, state="readonly", width=24,
                                         style="BIO.TCombobox", font=theme.font("body"))
        self.space_picker.pack(side="left")
        self.space_picker.bind("<<ComboboxSelected>>", lambda _e: self._space_chosen())

        self.title_counter = self._label_row(t("hub.editor.title"), top=SPACE_M)
        self.title_field = Field(self, theme, textvariable=self.title_value, font="body_strong")
        self.title_field.pack(fill="x")
        self.title_error = self._error_label()
        self.content_counter = self._label_row(t("hub.editor.memory"), top=SPACE_L)
        self.content = TextArea(self, theme, font="reading", height=10)
        self.content.pack(fill="both", expand=True)
        self.content_error = self._error_label()
        self.source_counter = self._label_row(t("hub.editor.source"), top=SPACE_L)
        self.source_field = Field(self, theme, textvariable=self.source_value)
        self.source_field.pack(fill="x")
        self.source_error = self._error_label()
        WrapLabel(self, t("hub.editor.source_note"), font=theme.font("caption"),
                  foreground=c.text_muted).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        buttons = FlowFrame(self, gap=theme.px(SPACE_S), background=c.surface)
        buttons.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.save_button = buttons.add(Button(buttons, theme, t("hub.editor.save"), icon="check", variant="primary",
                                              command=self.save_memory, tooltip=t("hub.editor.save_tip")))
        self.cancel_button = buttons.add(Button(buttons, theme, t("common.cancel"), command=self.cancel_edit,
                                                tooltip=t("hub.editor.cancel_tip")))
        self.status = WrapLabel(self, font=theme.font("caption"), foreground=c.text_muted)
        self.status.pack(fill="x", pady=(theme.px(SPACE_XS), 0))

        self.title_value.trace_add("write", lambda *_: self._on_change())
        self.source_value.trace_add("write", lambda *_: self._on_change())
        self.content.text.bind("<<Modified>>", self._on_text_modified, add="+")
        self.title_field.entry.bind("<Return>", lambda _e: (self.save_memory(), "break")[1])
        self.title_field.entry.bind("<KP_Enter>", lambda _e: (self.save_memory(), "break")[1])
        self.content.text.bind("<Control-Return>", lambda _e: (self.save_memory(), "break")[1])
        for widget in (self.title_field.entry, self.content.text, self.source_field.entry):
            widget.bind("<Escape>", lambda _e: (self.cancel_edit(), "break")[1])
        self._on_change()

    def _label_row(self, text: str, *, top: int = 0) -> tk.Label:
        c = self.colors
        row = tk.Frame(self, background=c.surface)
        row.pack(fill="x", pady=(self.theme.px(top), self.theme.px(SPACE_XS + 2)))
        tk.Label(row, text=text, font=self.theme.font("body_strong"), background=c.surface, foreground=c.text,
                 anchor="w").pack(side="left")
        label = tk.Label(row, font=self.theme.font("caption"), background=c.surface, foreground=c.text_muted,
                         anchor="e")
        label.pack(side="right")
        return label

    def _error_label(self) -> WrapLabel:
        return WrapLabel(self, font=self.theme.font("caption"), foreground=self.colors.danger)

    # State ------------------------------------------------------------------------------------------------------

    def values(self) -> tuple[str, str, str]:
        return self.title_value.get(), self.source_value.get(), self.content.get()

    @property
    def dirty(self) -> bool:
        return self.values() != self._baseline

    def load(self, record: MemoryView | None, space=None) -> None:
        """Start a new memory (``record`` None) in ``space``, or edit ``record`` of ``space``."""
        self.editing = record
        self._spaces = list(self.app.spaces())
        self.space = space if space is not None else self.app.current_space()
        if record is None:
            title, source, body = "", DEFAULT_SOURCE, ""
        else:
            title, source, body = record.title, record.source_ref, record.content or ""
        self.title_value.set(title)
        self.source_value.set(source)
        self.content.set(body)
        self._baseline = (title, source, body)
        self.heading.configure(text=t("hub.editor.new") if record is None else t("hub.editor.edit"))
        if record is None and len(self._spaces) > 1:
            self.space_picker.configure(values=[space_label(s) for s in self._spaces])
            self.space_value.set(space_label(self.space))
            if not self.space_row.winfo_manager():
                self.space_row.pack(fill="x", pady=(self.theme.px(SPACE_S), 0), after=self.heading)
        else:
            self.space_row.pack_forget()
        self._clear_errors()
        self._on_change()

    def _space_chosen(self) -> None:
        index = self.space_picker.current()
        if 0 <= index < len(self._spaces):
            self.space = self._spaces[index]

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
            label.configure(text=f"{len(value):,} / {limit:,}",
                            foreground=c.danger if len(value) > limit else c.text_muted)
        if self.editing is None:
            state = t("hub.editor.new_dirty") if self.dirty else t("hub.editor.new_clean")
        else:
            number = self.editing.revision_number
            state = (t("hub.editor.edit_dirty", number=number) if self.dirty
                     else t("hub.editor.edit_clean", number=number))
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

    # Actions ----------------------------------------------------------------------------------------------------

    def save_memory(self) -> MemoryView | None:
        title, source_ref, content = self.values()
        self._clear_errors()
        created = self.editing is None
        if not self.app.require_action("create" if created else "edit"):
            return None
        space = self.space
        try:
            engine = self.app.memory_engine()
            with in_space(self.app, space):
                if created:
                    outcome = engine.create(title=title, content=content, source_ref=source_ref)
                else:
                    outcome = engine.revise(self.editing.memory_id, expected_revision_id=self.editing.revision_id,
                                            title=title, content=content, source_ref=source_ref)
                if outcome.status is WriteStatus.CONFLICT:
                    raise RevisionConflictError("the memory changed")
                saved = engine.get(outcome.memory_id) if outcome.persisted else None
        except ValidationError as exc:
            field, message = validation_feedback(exc)
            if field is not None:
                self._show_error(field, message)
            else:
                self.app.notify("error", message, title=t("hub.editor.check"))
            return None
        except (RevisionConflictError, MemoryNotFoundError):
            self.app.notify("warning", t("hub.editor.conflict"), title=t("hub.editor.conflict_title"),
                            action=(t("hub.editor.reload"), self.reload_latest))
            return None
        except EngineUnavailable:
            self.app.notify("error", t("hub.editor.engine_down"), title=t("hub.engine_down_title"))
            return None
        except UnsupportedCapability as exc:
            self.app.notify("warning", say(exc), title=t("hub.not_available"))
            return None
        except Exception:  # noqa: BLE001 - shown to the user
            self.app.notify("error", t("hub.editor.failed"), title=t("hub.editor.failed_title"))
            return None
        if saved is None:
            message = outcome_message(outcome)
            if outcome.status is WriteStatus.PENDING_REVIEW:
                # A proposal is not a memory: close the form, but never say it was saved.
                self._baseline = self.values()
                self.load(None, space)
                self.hub.close_drawer(force=True)
                self.app.notify("info", message.message, title=message.title)
            else:
                self.app.notify("warning", message.message, title=message.title)
            return None
        self._baseline = self.values()
        self.editing = None
        self.load(None, space)
        self.hub.memory_saved(saved, created=created, space=space)
        return saved

    def reload_latest(self) -> None:
        if self.editing is None:
            return
        try:
            with in_space(self.app, self.space):
                latest = self.app.memory_engine().get(self.editing.memory_id)
        except MemoryNotFoundError:
            self._baseline = self.values()
            self.hub.close_drawer(force=True)
            self.app.data_changed()
            self.app.notify("warning", t("hub.editor.gone"), title=t("hub.editor.gone_title"))
            return
        except Exception:  # noqa: BLE001
            self.app.notify("error", t("hub.editor.reload_failed"), title=t("hub.editor.reload_failed_title"))
            return
        if self.dirty and not self.app.confirm(
                title=t("hub.editor.discard_title"), message=t("hub.editor.discard_reload"),
                confirm_text=t("hub.editor.discard_reload_button"), danger=True):
            return
        self.load(latest, self.space)
        self.app.notify("info", t("hub.editor.reloaded", number=latest.revision_number,
                                  title=preview(latest.title, 50)))

    def cancel_edit(self) -> None:
        if self.confirm_leave():
            self.hub.editor_closed()

    def confirm_leave(self) -> bool:
        """Ask before throwing away unsaved text; True when it is safe to leave the form."""
        if not self.winfo_ismapped() and not self.dirty:
            return True
        if not self.dirty:
            return True
        discard = self.app.confirm(
            title=t("hub.editor.discard_title"),
            message=t("hub.editor.discard_edit") if self.editing is not None else t("hub.editor.discard_new"),
            confirm_text=t("hub.editor.discard_button"), cancel_text=t("hub.editor.keep_editing"), danger=True)
        if discard:
            self.load(None, self.space)
        return discard


__all__ = ["DrawerEditor"]
