# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Quick ways on the memory screen (v0.4.4): quick add (F5), the bar for several chosen cards (F7), and copying a
memory's text (F10)."""

from __future__ import annotations

import tkinter as tk

from bio_ce.core.models import MemoryNotFoundError, ValidationError
from bio_ce.engine.contract import EngineUnavailable, UnsupportedCapability, WriteStatus
from bio_ce.exporter import UNENCRYPTED_NOTICE, write_export
from bio_ce.memory_policy import detect_secrets
from bio_ce.ui.format import preview
from bio_ce.ui.hub.common import in_space, space_label
from bio_ce.ui.hub.data import INBOX, MEMORIES
from bio_ce.ui.i18n import t
from bio_ce.ui.service_text import say
from bio_ce.ui.theme import SPACE_M, SPACE_S, SPACE_XS, SPACE_XXS
from bio_ce.ui.widgets import Button, Field, FlowFrame

TITLE_LIMIT = 60


def split_quick_text(text: str) -> tuple[str, str]:
    """A title and the memory text from one line: the first sentence (at most 60 characters, shortened at a word)
    as the title, the whole line as the text."""
    text = " ".join(text.split())
    first = text
    for end in (". ", "? ", "! ", "。", "다. "):
        if end in first:
            first = first.split(end, 1)[0] + end.strip()[-1:]
            break
    if len(first) > TITLE_LIMIT:
        cut = first[:TITLE_LIMIT].rsplit(" ", 1)[0] or first[:TITLE_LIMIT]
        first = cut.rstrip(" ,;:") + "…"
    return first, text


class QuickAdd(Field):
    """One line above the cards: type a memory, Enter saves it in the shown space (General when all are shown)."""

    def __init__(self, master: tk.Misc, hub) -> None:
        self.hub, self.app = hub, hub.app
        theme = hub.theme
        self.text = tk.StringVar(master=master)
        super().__init__(master, theme, textvariable=self.text)
        self.entry.pack_configure(padx=(theme.px(SPACE_XS), theme.px(SPACE_XS)))
        glyph = theme.icon("add")
        if glyph:
            icon = tk.Label(self.content, text=glyph, font=theme.icon_font("small"), background=self._fill,
                            foreground=theme.colors.text_muted)
            icon.pack(side="left", padx=(theme.px(SPACE_M), theme.px(SPACE_XXS)), before=self.entry)
            icon.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.placeholder = tk.Label(self.content, text=t("hub.quick.placeholder"), font=theme.font("body"),
                                    background=self._fill, foreground=theme.colors.text_muted, borderwidth=0)
        self.placeholder.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.text.trace_add("write", lambda *_: self._sync())
        self.entry.bind("<Return>", lambda _e: (self.save(), "break")[1])
        self.entry.bind("<KP_Enter>", lambda _e: (self.save(), "break")[1])
        self.entry.bind("<Escape>", lambda _e: self.text.set(""), add="+")
        self._sync()

    def _sync(self) -> None:
        if self.text.get():
            self.placeholder.place_forget()
        else:
            self.placeholder.place(in_=self.entry, x=1, rely=0.5, anchor="w")

    def save(self):
        raw = self.text.get().strip()
        if not raw or not self.app.require_action("create"):
            return None
        title, content = split_quick_text(raw)
        if detect_secrets(title, content):
            self.app.notify("warning", t("hub.quick.secret"), title=t("hub.quick.not_saved"))
            return None
        space = self.hub.filter_space() or self.app.current_space()
        try:
            engine = self.app.memory_engine()
            with in_space(self.app, space):
                outcome = engine.create(title=title, content=content, source_ref="bio-ce-quick-add")
                saved = engine.get(outcome.memory_id) if outcome.persisted else None
        except ValidationError as exc:
            self.app.notify("error", say(exc), title=t("hub.quick.not_saved"))
            return None
        except (EngineUnavailable, UnsupportedCapability):
            self.app.notify("error", t("hub.editor.engine_down"), title=t("hub.engine_down_title"))
            return None
        if saved is None:
            kind = "info" if outcome.status is WriteStatus.PENDING_REVIEW else "warning"
            self.app.notify(kind, say("; ".join(outcome.reasons)) or t("hub.quick.not_saved"),
                            title=t("hub.quick.not_saved"))
            return None
        self.text.set("")
        self.hub.state = MEMORIES
        self.app.data_changed()
        self.hub.refresh()
        self.app.notify("success", t("hub.saved.where", title=preview(saved.title, 60), space=space_label(space)),
                        title=t("hub.saved.new"),
                        action=(t("common.undo"), lambda: self.undo(saved, space)))
        return saved

    def undo(self, saved, space) -> bool:
        """Retract what quick add just saved (only if it is still that revision)."""
        try:
            engine = self.app.memory_engine()
            with in_space(self.app, space):
                outcome = engine.retract(saved.memory_id, expected_revision_id=saved.revision_id)
        except (EngineUnavailable, MemoryNotFoundError):
            return False
        if outcome.status is WriteStatus.CONFLICT or not outcome.persisted:
            self.app.notify("warning", t("hub.quick.undo_changed"), title=t("hub.quick.undo_failed"))
            return False
        self.app.data_changed()
        self.hub.refresh()
        return True


class SelectionBar(FlowFrame):
    """Shown while two or more cards are chosen: how many, and Move, Delete, Export, Copy, Clear for all of them."""

    def __init__(self, master: tk.Misc, hub) -> None:
        theme = hub.theme
        super().__init__(master, gap=theme.px(SPACE_S), background=theme.colors.bg)
        self.hub, self.app = hub, hub.app
        self.count_label = self.add(tk.Label(self, text="", font=theme.font("body_strong"), background=theme.colors.bg,
                                             foreground=theme.colors.text))
        self.move_button = self.add(Button(self, theme, t("hub.drawer.move"), variant="secondary",
                                           command=lambda: hub.move_menu(hub.chosen_items(), self.move_button)))
        self.delete_button = self.add(Button(self, theme, t("hub.card.delete"), variant="danger_subtle",
                                             command=lambda: hub.delete_items(hub.chosen_items())))
        self.export_button = self.add(Button(self, theme, t("hub.selection.export"), variant="secondary",
                                             command=self.export))
        self.copy_button = self.add(Button(self, theme, t("hub.copy"), variant="secondary",
                                           command=lambda: copy_items(self.app, hub.chosen_items())))
        self.clear_button = self.add(Button(self, theme, t("hub.selection.clear"), variant="subtle",
                                            command=hub.clear_selection))

    def show_for(self, items: list) -> bool:
        """Show the bar for ``items`` (the chosen cards); False (hidden) for fewer than two."""
        if len(items) < 2:
            return False
        self.count_label.configure(text=t("hub.selection.count", count=len(items)))
        memories = all(item.state == MEMORIES for item in items)
        self.set_visible(self.export_button, memories)
        self.set_visible(self.copy_button, all(item.state in (MEMORIES, INBOX) for item in items))
        self.relayout()
        return True

    def export(self):
        items = [item for item in self.hub.chosen_items() if item.state == MEMORIES]
        if not items or not self.app.require_action("browse"):
            return None
        if any(item.space is not None and item.space.is_personal for item in items) and not self.app.confirm(
                title=t("hub.selection.personal_title"), message=t("hub.selection.personal_message"),
                points=(UNENCRYPTED_NOTICE,), confirm_text=t("hub.selection.personal_button")):
            return None
        lines = []
        for space in {id(item.space): item.space for item in items}.values():
            with in_space(self.app, space):
                lines.append(self.app.service.export_selected([i.item_id for i in items if i.space is space]))
        path = self.app.ask_save_path(title=t("hub.selection.export_title"), defaultextension=".md",
                                      initialfile="bio-ce-selected.md", filetypes=((t("hub.selection.file_type"), "*.md"),))
        if not path:
            return None
        try:
            written = write_export(path, "\n".join(line for line in lines if line) + "\n")
        except Exception:  # noqa: BLE001 - a file that exists is never overwritten (write_export refuses)
            self.app.notify("error", t("hub.selection.export_failed"), title=t("hub.selection.not_exported"))
            return None
        self.app.notify("success", t("hub.selection.exported", count=len(items)) + " " + UNENCRYPTED_NOTICE,
                        title=t("hub.selection.exported_title"),
                        action=(t("hub.selection.show_folder"), lambda: self.app.reveal_file(written)))
        return written


def copy_items(app, items: list) -> bool:
    """F10: the memories' text to the clipboard (title and text), to paste into a conversation."""
    parts = []
    for item in items:
        if item.state not in (MEMORIES, INBOX):
            continue
        text = (item.text or "").strip()
        parts.append(f"{item.title}\n{text}" if item.title and not text.startswith(item.title) else text)
    if not parts:
        return False
    app.root.clipboard_clear()
    app.root.clipboard_append("\n\n".join(parts))
    app.notify("success", t("hub.copied", count=len(parts)), title=t("hub.copied_title"))
    return True

