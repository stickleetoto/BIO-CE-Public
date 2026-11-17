# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The drawer (v0.4.4 §2.2, §3.1–§3.3): opens when a card is clicked; closes with Esc, ×, or the same card.

The action row stays at the top whatever the drawer's height (it replaced the fixed reading pane, whose buttons a
short window pushed out: K1, K2); only the content below it scrolls, and the text keeps a reading width.
"""

from __future__ import annotations

import tkinter as tk

from bio_ce.core.models import MemoryNotFoundError
from bio_ce.engine.contract import MemoryView
from bio_ce.ui.format import format_timestamp, middle_ellipsis, preview, revision_kind_label
from bio_ce.ui.hub.common import READING_WIDTH, AutoText, in_space, space_label, when
from bio_ce.ui.hub.data import INBOX, MEMORIES, RETRACTED, HubItem
from bio_ce.ui.hub.editor import DrawerEditor
from bio_ce.ui.hub.filters import source_text
from bio_ce.ui.hub.quick import copy_items
from bio_ce.ui.i18n import t
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XL, SPACE_XS, raised
from bio_ce.ui.widgets import (
    Button,
    ClampLabel,
    Disclosure,
    ElideLabel,
    FlowFrame,
    IconButton,
    ScrollFrame,
    WrapLabel,
    copy_to_clipboard,
    divider,
)


def import_line(meta: dict) -> str:
    """12.1: an imported item shows when it was said only if the user confirmed it, and the source's date apart."""
    source = {"chatgpt": "ChatGPT", "claude": "Claude"}.get(meta.get("import_source"), t("hub.inbox.another_ai"))
    if meta.get("said_at"):
        said = t("hub.inbox.said_on", date=meta["said_at"])
    elif meta.get("claimed_date"):
        said = t("hub.inbox.source_date", date=meta["claimed_date"])
    else:
        said = t("hub.inbox.said_unknown")
    imported = format_timestamp(meta["imported_at"]) if meta.get("imported_at") else t("hub.inbox.unknown")
    return t("hub.inbox.import_line", source=source, said=said, imported=imported)


def inbox_meta(item) -> str:
    meta = dict(item.source.metadata)
    if meta.get("import_source"):
        return import_line(meta)
    parts = [t("hub.inbox.saved", when=format_timestamp(item.recorded_at))]
    if meta.get("host"):  # the tool's name, not its key ("저장 · codex" in rc1)
        host = meta["host"]
        known = host in ("codex", "claude", "claude_desktop")
        parts.append(t("hub.inbox.by_host", host=t(f"hub.filter.host.{host}") if known else host))
    if meta.get("guess"):
        parts.append(t("hub.inbox.guess"))
    if meta.get("evidence") == "external_content":
        parts.append(t("hub.inbox.external"))
    return " · ".join(parts)


Section = Disclosure  # the drawer's History and Details (moved to widgets.py for every screen, POLISH §3.0)


class Drawer(tk.Frame):
    def __init__(self, master: tk.Misc, hub) -> None:
        theme, c = hub.theme, raised(hub.colors)  # one layer above the cards beside it (POLISH §2.3)
        super().__init__(master, background=c.surface, highlightthickness=1, highlightbackground=c.border_strong,
                         highlightcolor=c.border_strong)
        self.hub = hub
        self.app = hub.app
        self.theme = theme
        self.colors = c
        self.mode: str | None = None
        self.item: HubItem | None = None
        self.record: MemoryView | None = None
        self.revisions: tuple = ()
        self._merge_proposal: int | None = None

        top = tk.Frame(self, background=c.surface)
        top.pack(fill="x", padx=theme.px(SPACE_L), pady=(theme.px(SPACE_M), theme.px(SPACE_S)))
        self.close_button = IconButton(top, theme, "close", t("hub.drawer.close"), command=hub.close_drawer)
        self.close_button.pack(side="right", anchor="n")
        # Shown only when the drawer has the whole body (too narrow for the list beside it, POLISH §1.3).
        self.back_button = Button(top, theme, t("hub.drawer.back"), variant="link", command=hub.close_drawer)
        self.action_row = FlowFrame(top, gap=theme.px(SPACE_S), background=c.surface)
        self.action_row.pack(side="left", fill="x", expand=True)
        self.edit_button = self.action_row.add(Button(self.action_row, theme, t("hub.card.edit"), icon="edit",
                                                      command=self.start_edit, tooltip=t("hub.drawer.edit_tip")))
        self.to_memories_button = self.action_row.add(Button(
            self.action_row, theme, t("hub.inbox.to_memories"), variant="primary",
            command=lambda: self.item is not None and hub.do.to_memories(self.item)))
        self.move_button = self.action_row.add(Button(self.action_row, theme, t("hub.drawer.move"),
                                                      command=lambda: self.item is not None
                                                      and hub.move_menu([self.item], self.move_button),
                                                      tooltip=t("hub.drawer.move_tip")))
        self.history_button = self.action_row.add(Button(self.action_row, theme, t("hub.drawer.history"),
                                                         icon="history", command=self.open_history,
                                                         tooltip=t("hub.drawer.history_tip")))
        self.delete_button = self.action_row.add(Button(self.action_row, theme, t("hub.card.delete"),
                                                        icon="retract", variant="danger_subtle",
                                                        command=lambda: self.item is not None
                                                        and hub.delete_items([self.item]),
                                                        tooltip=t("hub.drawer.delete_tip")))
        self.copy_button = self.action_row.add(Button(self.action_row, theme, t("hub.copy"), variant="subtle",
                                                      command=lambda: self.item is not None
                                                      and copy_items(self.app, [self.item]),
                                                      tooltip=t("hub.copy_tip")))
        self.undo_merge_button = self.action_row.add(Button(self.action_row, theme, t("hub.inbox.undo_merge"),
                                                            variant="link", command=self.undo_merge))
        self.forget_action = self.action_row.add(Button(self.action_row, theme, t("hub.drawer.forget"),
                                                        variant="danger_subtle",
                                                        command=lambda: self.item is not None
                                                        and hub.forget_item(self.item)))
        self.app.gate(self.forget_action, "retract")
        self.app.gate(self.edit_button, "edit")
        self.app.gate(self.move_button, "edit")
        self.app.gate(self.history_button, "history")
        self.app.gate(self.to_memories_button, "review")
        divider(self, theme).pack(fill="x")

        self.scroll = ScrollFrame(self, theme)
        self.scroll.pack(fill="both", expand=True)
        self.column = tk.Frame(self.scroll.body, background=c.surface)
        self.column.pack(fill="x", padx=theme.px(SPACE_XL), pady=(theme.px(SPACE_L), theme.px(SPACE_L)))
        self.scroll.body.bind("<Configure>", self._fit_column, add="+")

        # Memory and inbox item view
        self.view = tk.Frame(self.column, background=c.surface)
        self.title_label = ClampLabel(self.view, theme, font=theme.font("title"), foreground=c.text, cursor="xterm")
        self.title_label.pack(fill="x")
        self.meta_label = ElideLabel(self.view, font=theme.font("caption"), background=c.surface,
                                     foreground=c.text_muted, width=1)
        self.meta_label.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.inbox_meta = WrapLabel(self.view, font=theme.font("caption"), foreground=c.text_muted)
        self.reader = AutoText(self.view, theme, font="reading", foreground=c.text)
        self.reader.tag_configure("empty", foreground=c.text_muted, font=theme.font("body"))
        self.reader.pack(fill="x", pady=(theme.px(SPACE_L), theme.px(SPACE_M)))
        self.title_label.bind("<Button-1>", lambda _e: self._click_to_edit(), add="+")
        self.reader.bind("<Double-Button-1>", lambda _e: self._click_to_edit(), add="+")

        self.history = Section(self.view, theme, t("hub.drawer.history"), on_open=self._fill_history)
        self.history.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.details = Section(self.view, theme, t("hub.drawer.details"))
        self.details.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.detail_values: dict[str, tk.Label] = {}
        rows = (("memory_id", t("hub.drawer.memory_id"), True), ("revision_id", t("hub.drawer.revision_id"), True),
                ("source", t("hub.drawer.source"), False), ("recorded", t("hub.drawer.recorded"), False),
                ("valid_from", t("hub.drawer.valid_from"), False), ("valid_until", t("hub.drawer.valid_until"), False))
        for index, (key, label, copyable) in enumerate(rows):
            tk.Label(self.details.body, text=label, font=theme.font("caption"), background=c.surface,
                     foreground=c.text_muted, anchor="w").grid(row=index, column=0, sticky="w", pady=theme.px(2))
            # One line that ends in "…" in a narrow drawer (the copy button copies the whole id).
            value = ElideLabel(self.details.body, font=theme.font("mono" if copyable else "caption"),
                               background=c.surface, foreground=c.text_secondary, width=1)
            value.grid(row=index, column=1, sticky="we", padx=(theme.px(SPACE_M), 0))
            if copyable:
                IconButton(self.details.body, theme, "copy", t("hub.drawer.copy", name=label),
                           command=lambda k=key, name=label: self.copy(k, name)).grid(row=index, column=2, sticky="w")
            self.detail_values[key] = value
        self.details.body.columnconfigure(1, weight=1)

        # The danger area: "Forget completely" (D1, v0.4.4 §7.1). Shown only when the service can do it.
        self.danger = tk.Frame(self.view, background=c.surface, highlightthickness=1, highlightbackground=c.danger,
                               highlightcolor=c.danger)
        danger_body = tk.Frame(self.danger, background=c.surface)
        danger_body.pack(fill="x", padx=theme.px(SPACE_M), pady=theme.px(SPACE_S))
        WrapLabel(danger_body, t("hub.drawer.danger_note"), font=theme.font("caption"),
                  foreground=c.text_secondary).pack(fill="x")
        self.forget_button = Button(danger_body, theme, t("hub.drawer.forget"), variant="danger_subtle",
                                    command=lambda: self.item is not None and hub.forget_item(self.item))
        self.forget_button.pack(anchor="w", pady=(theme.px(SPACE_S), 0))
        self.app.gate(self.forget_button, "retract")

        # Add / edit form
        self.editor = DrawerEditor(self.column, hub)

    # Layout -----------------------------------------------------------------------------------------------------

    def show_back(self, show: bool) -> None:
        if show and not self.back_button.winfo_manager():
            self.back_button.pack(side="left", anchor="n", padx=(0, self.theme.px(SPACE_S)), before=self.action_row)
        elif not show and self.back_button.winfo_manager():
            self.back_button.pack_forget()

    def _fit_column(self, event) -> None:
        pad = self.theme.px(SPACE_XL)
        extra = max(0, int(event.width) - 2 * pad - self.theme.px(READING_WIDTH))
        self.column.pack_configure(padx=(pad, pad + extra))

    def _show_actions(self, keys: set[str]) -> None:
        buttons = {"edit": self.edit_button, "to_memories": self.to_memories_button, "move": self.move_button,
                   "history": self.history_button, "delete": self.delete_button, "undo_merge": self.undo_merge_button,
                   "forget": self.forget_action, "copy": self.copy_button}
        for key, button in buttons.items():
            self.action_row.set_visible(button, key in keys)

    def _show(self, frame: tk.Frame) -> None:
        for part in (self.view, self.editor):
            if part is not frame:
                part.pack_forget()
        if not frame.winfo_manager():
            frame.pack(fill="x")
        self.scroll.canvas.yview_moveto(0)

    # Modes ------------------------------------------------------------------------------------------------------

    def show_memory(self, item: HubItem) -> bool:
        try:
            with in_space(self.app, item.space):
                record = self.app.memory_engine().get(item.item_id)
        except MemoryNotFoundError:
            self.app.notify("warning", t("hub.drawer.not_found"), title=t("hub.drawer.not_found_title"),
                            action=(t("hub.drawer.refresh"), self.hub.refresh))
            return False
        except Exception:  # noqa: BLE001
            self.app.notify("error", t("hub.drawer.open_failed"), title=t("hub.drawer.open_failed_title"))
            return False
        self.mode, self.item, self.record, self.revisions = MEMORIES, item, record, ()
        self._merge_proposal = None
        self._show_actions({"edit", "move", "history", "copy", "delete"})
        self.delete_button.set_text(t("hub.card.delete"))
        self.delete_button.set_enabled(self.app.allowed("retract").enabled)
        self.title_label.set_text(record.title)
        meta = [space_label(item.space), t("hub.drawer.revision", number=record.revision_number),
                t("hub.drawer.updated", when=when(record.recorded_at))]
        meta.append(t("hub.drawer.source_short", source=source_text(record)))
        self.meta_label.set_text(" · ".join(meta))
        self.meta_label.pack(fill="x", pady=(self.theme.px(SPACE_XS), 0), after=self.title_label)
        self.inbox_meta.pack_forget()
        if record.content:
            self.reader.set(record.content)
        else:
            self.reader.set(t("hub.drawer.no_text"), "empty")
        values = {"memory_id": middle_ellipsis(record.memory_id, 40),
                  "revision_id": middle_ellipsis(record.revision_id, 40),
                  "source": source_text(record),
                  "recorded": format_timestamp(record.recorded_at),
                  "valid_from": format_timestamp(record.valid_from),
                  "valid_until": format_timestamp(record.valid_until)}
        for key, value in values.items():
            self.detail_values[key].set_text(value)
        self.history.pack(fill="x", pady=(self.theme.px(SPACE_S), 0), after=self.reader)
        self.details.pack(fill="x", pady=(self.theme.px(SPACE_XS), 0), after=self.history)
        self.history.set_label(t("hub.drawer.history"))
        self.history.set_open(False)
        self.details.set_open(False)
        if hasattr(self.app.service, "forget"):
            self.danger.pack(fill="x", pady=(self.theme.px(SPACE_L), 0))
        else:
            self.danger.pack_forget()
        self._show(self.view)
        return True

    def show_inbox(self, item: HubItem) -> bool:
        self.mode, self.item, self.record, self.revisions = INBOX, item, None, ()
        revision = item.record
        allowed = self.app.allowed("review").enabled
        self._merge_proposal = self.hub.merge_proposal_of(item) if allowed else None
        keys = {"to_memories", "move", "copy", "delete"} | ({"undo_merge"} if self._merge_proposal is not None else set())
        self._show_actions(keys)
        self.delete_button.set_text(t("hub.card.discard"))
        self.delete_button.set_enabled(allowed)
        self.title_label.set_text(item.title)
        self.meta_label.set_text(space_label(item.space))
        self.inbox_meta.configure(text=inbox_meta(revision) if revision is not None else "")
        self.inbox_meta.pack(fill="x", pady=(self.theme.px(SPACE_XS), 0), after=self.meta_label)
        self.reader.set(item.text or "")
        for section in (self.history, self.details):
            section.pack_forget()
        self.danger.pack_forget()
        self._show(self.view)
        return True

    def show_retracted(self, item: HubItem) -> bool:
        """A retracted memory: what it said last and when it was retracted; it can only be forgotten completely."""
        self.mode, self.item, self.record, self.revisions = RETRACTED, item, item.record.last, ()
        self._merge_proposal = None
        self._show_actions({"forget"})
        self.title_label.set_text(item.title)
        self.meta_label.set_text(" · ".join((space_label(item.space),
                                             t("hub.retracted.when", when=format_timestamp(item.when)))))
        self.inbox_meta.configure(text=t("hub.retracted.note"))
        self.inbox_meta.pack(fill="x", pady=(self.theme.px(SPACE_XS), 0), after=self.meta_label)
        self.reader.set(item.text or t("hub.drawer.no_text"))
        for section in (self.history, self.details):
            section.pack_forget()
        self.danger.pack_forget()
        self._show(self.view)
        return True

    def start_new(self, space) -> None:
        self.mode, self.item, self.record = "new", None, None
        self._show_actions(set())
        self.editor.load(None, space)
        self._show(self.editor)
        self.editor.focus_default()

    def start_edit(self) -> None:
        if self.mode != MEMORIES or self.record is None or not self.app.require_action("edit"):
            return
        self.mode = "edit"
        self._show_actions(set())
        self.editor.load(self.record, self.item.space if self.item is not None else None)
        self._show(self.editor)
        self.editor.focus_default()

    def _click_to_edit(self) -> None:
        if self.mode == MEMORIES and self.app.allowed("edit").enabled:
            self.start_edit()

    @property
    def editing(self) -> bool:
        return self.mode in ("edit", "new")

    # History, details, merge ------------------------------------------------------------------------------------

    def open_history(self) -> None:
        if self.mode != MEMORIES or not self.app.require_action("history"):
            return
        self.history.set_open(True)
        self.scroll.scroll_to_widget(self.history)

    def _fill_history(self) -> None:
        theme, c = self.theme, self.colors
        for child in self.history.body.winfo_children():
            child.destroy()
        if self.record is None or self.item is None:
            return
        try:
            with in_space(self.app, self.item.space):
                self.revisions = tuple(self.app.memory_engine().history(self.record.memory_id))
        except Exception:  # noqa: BLE001
            self.app.notify("error", t("hub.drawer.history_failed"), title=t("hub.drawer.history_failed_title"))
            return
        self.history.set_label(t("hub.drawer.history_count", count=len(self.revisions)))
        for index, revision in enumerate(reversed(self.revisions)):
            row = tk.Frame(self.history.body, background=c.surface)
            row.pack(fill="x", pady=(0, theme.px(SPACE_S)))
            head = t("hub.drawer.revision_line", number=revision.revision_number,
                     kind=revision_kind_label(revision.kind), when=format_timestamp(revision.recorded_at))
            if index == 0:
                head += " · " + t("hub.drawer.current")
            tk.Label(row, text=head, font=theme.font("caption_strong"), background=c.surface,
                     foreground=c.success if index == 0 else c.text_muted, anchor="w").pack(fill="x")
            WrapLabel(row, preview(f"{revision.title} — {revision.content or ''}", 240), font=theme.font("caption"),
                      foreground=c.text_secondary).pack(fill="x")
        buttons = FlowFrame(self.history.body, gap=theme.px(SPACE_S), background=c.surface)
        buttons.pack(fill="x")
        proposal = self.hub.suggestion_result_of(self.item)
        if proposal is not None:  # its current text came from an approved suggestion (v0.4.3): keep its undo
            self.undo_suggestion_button = buttons.add(Button(
                buttons, theme, t("hub.drawer.undo_suggestion"),
                command=lambda: self.hub.suggestions.undo([proposal])))
        buttons.add(Button(buttons, theme, t("hub.drawer.full_history"), variant="link",
                           command=self.hub.show_history))

    def undo_merge(self) -> int:
        if self._merge_proposal is None:
            return 0
        return self.hub.suggestions.undo([self._merge_proposal])

    def copy(self, key: str, name: str) -> None:
        if self.record is None:
            return
        value = self.record.memory_id if key == "memory_id" else self.record.revision_id
        copy_to_clipboard(self, value)
        self.app.notify("success", t("hub.drawer.copied", name=name))


__all__ = ["Drawer", "Section", "import_line", "inbox_meta"]
