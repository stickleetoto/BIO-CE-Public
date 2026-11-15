# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The inbox: what AI hosts collected in collect mode, for the user to keep, move, or discard.

Also the bar shared with the Memories page: Memories / Inbox tabs and the space picker.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from bio_ce.core.models import MemoryRevision
from bio_ce.inbox import DISCARD_NOTICE
from bio_ce.ui.dialogs import ReviewEditDialog
from bio_ce.ui.format import format_timestamp, plural, preview, relative_time
from bio_ce.ui.pages import Page
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XL, SPACE_XS
from bio_ce.ui.widgets import (
    AutoScrollbar,
    Button,
    Card,
    ClampLabel,
    EmptyState,
    FlowFrame,
    Pill,
    Tooltip,
    WrapLabel,
    fit_tree_columns,
    keep_side_pane,
    section_label,
)


def import_line(meta: dict) -> str:
    """12.1: an imported item shows when it was said only if the user confirmed it, and the source's date apart."""
    source = {"chatgpt": "ChatGPT", "claude": "Claude"}.get(meta.get("import_source"), "another AI")
    if meta.get("said_at"):
        when = f"Said on {meta['said_at']}"
    elif meta.get("claimed_date"):
        when = f"Source date {meta['claimed_date']} (not confirmed)"
    else:
        when = "Said on: unknown"
    imported = format_timestamp(meta["imported_at"]) if meta.get("imported_at") else "unknown"
    return f"Imported from {source} · {when} · Imported {imported}"


class SpaceBar(tk.Frame):
    """Memories / Inbox / Suggestions tabs on the left, the space picker on the right.

    Nothing in this bar is ever cut off (a cut-off button ignores clicks): every part keeps its requested size, and
    when one line is too narrow the tabs wrap and the space picker moves to the next line.
    """

    def __init__(self, master: tk.Misc, app, *, active: str) -> None:
        theme, c = app.theme, app.theme.colors
        super().__init__(master, background=c.bg, height=1)
        self.app = app
        self.active = active
        self.gap = theme.px(SPACE_XS)
        self.memories_tab = Button(self, theme, "Memories", variant="primary" if active == "memories" else "subtle",
                                   command=lambda: app.show_page("memories"))
        self.inbox_tab = Button(self, theme, "Inbox", variant="primary" if active == "inbox" else "subtle",
                                command=lambda: app.show_page("inbox"))
        self.suggestions_tab = Button(self, theme, "Suggestions",
                                      variant="primary" if active == "suggestions" else "subtle",
                                      command=lambda: app.show_page("suggestions"))
        self.personal_pill = Pill(self, theme, "Personal: only hosts you allow", "warning")
        Tooltip(self.personal_pill, theme, "AI hosts see Personal only with the permission you give each one on the "
                "Connections page. Session hooks never use it.")
        self.chooser = tk.Frame(self, background=c.bg)
        tk.Label(self.chooser, text="Space", font=theme.font("caption_strong"), background=c.bg,
                 foreground=c.text_muted).pack(side="left", padx=(0, theme.px(SPACE_S)))
        self.space = tk.StringVar(master=self)
        self.picker = ttk.Combobox(self.chooser, textvariable=self.space, state="readonly", width=24,
                                   style="BIO.TCombobox", font=theme.font("body"))
        # The drop-down list is a plain Tk listbox; give it the theme's colors.
        self.option_add("*TCombobox*Listbox.background", c.surface_alt)
        self.option_add("*TCombobox*Listbox.foreground", c.text)
        self.option_add("*TCombobox*Listbox.selectBackground", c.selection)
        self.option_add("*TCombobox*Listbox.selectForeground", c.text)
        self.picker.pack(side="left")
        self.picker.bind("<<ComboboxSelected>>", lambda _e: self._chosen())
        self._show_pill = False
        self._width = 0
        self._spaces: list = []
        self.bind("<Configure>", self._on_configure, add="+")
        self.after_idle(self.relayout)

    def _on_configure(self, event) -> None:
        if int(event.width) != self._width:
            self._width = int(event.width)
            self.relayout()

    def relayout(self) -> None:
        """Place the tabs (wrapping if needed), then the picker: right-aligned when it fits, else on its own line."""
        if not self.winfo_exists():
            return
        self.update_idletasks()
        width = self._width if self._width > 1 else self.winfo_width()
        items = [self.memories_tab, self.inbox_tab, self.suggestions_tab]
        if self._show_pill:
            items.append(self.personal_pill)
        else:
            self.personal_pill.place_forget()
        if width <= 1:
            width = sum(item.winfo_reqwidth() + self.gap for item in items) + self.chooser.winfo_reqwidth()
        x = y = line = 0
        for item in items:
            need, high = item.winfo_reqwidth(), item.winfo_reqheight()
            if x and x + need > width:
                x, y, line = 0, y + line + self.gap, 0
            gap = self.gap * 3 if item is self.personal_pill and x else 0
            item.place(x=x + gap, y=y, width=need, height=high)
            x += gap + need + self.gap
            line = max(line, high)
        need, high = self.chooser.winfo_reqwidth(), self.chooser.winfo_reqheight()
        if x + need <= width:
            self.chooser.place(x=width - need, y=y, width=need, height=high)
            total = y + max(line, high)
        else:
            self.chooser.place(x=0, y=y + line + self.gap, width=need, height=high)
            total = y + line + self.gap + high
        if int(self.cget("height")) != total:
            self.configure(height=total)
        one_row = sum(item.winfo_reqwidth() + self.gap for item in items) + self.chooser.winfo_reqwidth()
        if int(self.cget("width")) != one_row:
            self.configure(width=one_row)  # ask for one line's width; narrower is fine, it wraps

    def refresh(self) -> None:
        self._spaces = list(self.app.spaces())
        self.picker.configure(values=[space.display_name for space in self._spaces])
        current = self.app.current_space()
        self.space.set(current.display_name if current is not None else "General")
        self._show_pill = current is not None and current.is_personal
        if len(self._spaces) <= 1:
            self.picker.configure(state="disabled")
        else:
            self.picker.configure(state="readonly")
        count = self.app.inbox_count()
        self.inbox_tab.set_text(f"Inbox ({count})" if count else "Inbox")
        control = getattr(self.app.connection_manager, "control", None)
        try:
            waiting = int(control.pending_proposal_count()) if control is not None else 0
        except Exception:  # noqa: BLE001
            waiting = 0
        self.suggestions_tab.set_text(f"Suggestions ({waiting})" if waiting else "Suggestions")
        self.relayout()

    def _chosen(self) -> None:
        index = self.picker.current()
        if 0 <= index < len(self._spaces):
            self.app.set_space(self._spaces[index].space_id)


class InboxPage(Page):
    key = "inbox"
    nav_key = "memories"
    title = "Memories"
    subtitle = "Inbox: what AI hosts collected for you to sort"

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        self.items: dict[str, MemoryRevision] = {}
        Button(self.actions, theme, "Refresh", icon="refresh", variant="subtle",
               command=self.refresh, tooltip="Reload the inbox").pack(side="right")
        self.space_bar = SpaceBar(self, app, active="inbox")
        self.space_bar.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        intro = tk.Frame(self, background=c.bg)
        intro.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        self.import_button = Button(intro, theme, "Import…", icon="add", command=lambda: app.show_page("import"),
                                    tooltip="Import memories from ChatGPT, Claude, or another AI")
        self.import_button.pack(side="right", anchor="n", padx=(theme.px(SPACE_M), 0))
        app.gate(self.import_button, "create")
        WrapLabel(intro, "Hosts in collect mode save lasting information here without asking. Hosts don't see the "
                  "inbox unless they ask for it, and session hooks never use it. Move what you want to keep to "
                  "your memories; discard the rest.", font=theme.font("body"), foreground=c.text_secondary,
                  background=c.bg).pack(side="left", fill="x", expand=True)

        self.cleanup = Card(self, theme, padding=SPACE_L)
        section_label(self.cleanup.body, theme, "Proposed for discarding").pack(fill="x")
        WrapLabel(self.cleanup.body, "These items were not used for a while, or a host asked to remove them. Keep "
                  "them, or they are discarded on the date shown.", font=theme.font("caption"),
                  foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.cleanup_rows = tk.Frame(self.cleanup.body, background=c.surface)
        self.cleanup_rows.pack(fill="x", pady=(theme.px(SPACE_S), 0))

        self.stack = tk.Frame(self, background=c.bg)
        self.stack.pack(fill="both", expand=True)
        self.empty = EmptyState(self.stack, theme, icon="memories", title="The inbox is empty",
                                message="Nothing is waiting. In collect mode, hosts save here; switch a host's "
                                        "saving to Collect on the Connections page.")
        self.split = ttk.Panedwindow(self.stack, orient="horizontal", style="BIO.TPanedwindow")
        left = Card(self.split, theme, padding=0)
        right = Card(self.split, theme, padding=0)
        self.split.add(left, weight=2)
        self.split.add(right, weight=3)
        area = tk.Frame(left.body, background=c.surface)
        area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(area, columns=("title", "saved"), show="headings", selectmode="extended",
                                 style="BIO.Treeview", takefocus=1)
        self.tree.heading("title", text="TITLE", anchor="w")
        self.tree.heading("saved", text="SAVED", anchor="w")
        self.tree.column("title", anchor="w", minwidth=theme.px(140), width=theme.px(260), stretch=True)
        self.tree.column("saved", anchor="w", minwidth=theme.px(84), width=theme.px(110), stretch=False)
        fit_tree_columns(self.tree, theme, "title", floor=140)
        scrollbar = AutoScrollbar(area, orient="vertical", command=self.tree.yview,
                                  style=theme.scrollbar_style(c.surface))
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(theme.px(SPACE_XS), 0), pady=theme.px(SPACE_XS))
        scrollbar.grid(row=0, column=1, sticky="ns", pady=theme.px(SPACE_S))
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected())
        self.tree.bind("<Delete>", lambda _e: self.discard_selected())

        detail = tk.Frame(right.body, background=c.surface)
        detail.pack(fill="both", expand=True, padx=theme.px(SPACE_XL), pady=theme.px(SPACE_L))
        # The buttons are packed first so a long text shortens the text, never the buttons.
        buttons = FlowFrame(detail, gap=theme.px(SPACE_S), background=c.surface)
        buttons.pack(fill="x", side="bottom", pady=(theme.px(SPACE_M), 0))
        self.move_button = buttons.add(Button(buttons, theme, "Move to memories…", variant="primary",
                                              command=self.move_selected))
        self.discard_button = buttons.add(Button(buttons, theme, "Discard…", variant="danger_subtle",
                                                 command=self.discard_selected))
        # Shown for an item that is the result of an approved merge (the merged items are kept, so it can be undone).
        self.undo_merge_button = buttons.add(Button(buttons, theme, "Undo merge…", variant="link",
                                                    command=self.undo_merge))
        self.detail_buttons = buttons
        buttons.set_visible(self.undo_merge_button, False)
        self._merge_proposal: int | None = None
        # The reading pane keeps room for its widest button (on the 1024x768 CI screen at 150% it was too narrow).
        self.keep_reading_pane = keep_side_pane(
            self.split, theme,
            lambda: max(self.move_button.winfo_reqwidth(), self.discard_button.winfo_reqwidth())
            + 2 * theme.px(SPACE_XL) + theme.px(16))
        self.detail_title = ClampLabel(detail, theme, font=theme.font("title"), foreground=c.text)
        self.detail_title.pack(fill="x")
        self.detail_meta = WrapLabel(detail, font=theme.font("caption"), foreground=c.text_muted)
        self.detail_meta.pack(fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_M)))
        self.detail_body = WrapLabel(detail, font=theme.font("body"), foreground=c.text_secondary)
        self.detail_body.pack(fill="x")

    # Data -----------------------------------------------------------------

    def refresh(self) -> None:
        super().refresh()
        self.space_bar.refresh()
        try:
            items = self.app.service.inbox()
        except Exception:  # noqa: BLE001 - shown as an empty inbox with a message
            items = ()
            self.app.notify("error", "BIO CE couldn't read the inbox.", title="Inbox unavailable")
        self.items = {item.memory_id: item for item in items}
        self.tree.delete(*self.tree.get_children())
        for item in items:
            self.tree.insert("", "end", iid=item.memory_id,
                             values=(preview(item.title, 80), relative_time(item.recorded_at)))
        self._render_cleanup()
        if items:
            self.empty.pack_forget()
            self.split.pack(fill="both", expand=True)
            self.tree.selection_set(items[0].memory_id)
        else:
            self.split.pack_forget()
            self.empty.pack(fill="both", expand=True)
        self._show_selected()

    def _render_cleanup(self) -> None:
        theme, c = self.theme, self.colors
        for child in self.cleanup_rows.winfo_children():
            child.destroy()
        proposals = self.app.cleanup_proposals()
        if not proposals:
            self.cleanup.pack_forget()
            return
        self.cleanup.pack(fill="x", pady=(0, theme.px(SPACE_M)), before=self.stack)
        for item in proposals:
            row = tk.Frame(self.cleanup_rows, background=c.surface)
            row.pack(fill="x", pady=(theme.px(2), 0))
            due = format_timestamp(item.get("due_at") or "") if item.get("due_at") else "soon"
            tk.Label(row, text=f"{plural(len(item['memory_ids']), 'item')} · discarded on {due}",
                     font=theme.font("body"), background=c.surface, foreground=c.text, anchor="w").pack(side="left")
            Button(row, theme, "Discard now", variant="link",
                   command=lambda proposal=item: self.discard_proposal(proposal)).pack(side="right")
            Button(row, theme, "Keep", variant="link",
                   command=lambda proposal=item: self.keep_proposal(proposal)).pack(side="right")

    def selected(self) -> list[MemoryRevision]:
        return [self.items[iid] for iid in self.tree.selection() if iid in self.items]

    def _show_selected(self) -> None:
        chosen = self.selected()
        allowed = self.app.allowed("review").enabled  # inbox sorting is a Community-only, review-like action
        self.move_button.set_enabled(allowed and len(chosen) == 1)
        self.discard_button.set_enabled(allowed and bool(chosen))
        self._merge_proposal = self._merge_of(chosen[0]) if allowed and len(chosen) == 1 else None
        self.detail_buttons.set_visible(self.undo_merge_button, self._merge_proposal is not None)
        if len(chosen) != 1:
            self.detail_title.set_text(f"{plural(len(chosen), 'item')} selected" if chosen else "")
            self.detail_meta.configure(text="")
            self.detail_body.configure(text="")
            return
        item = chosen[0]
        meta = dict(item.source.metadata)
        parts = [f"Saved {format_timestamp(item.recorded_at)}"]
        if meta.get("host"):
            parts.append(f"by {meta['host']}")
        if meta.get("guess"):
            parts.append("a guess the host made; you did not state it")
        if meta.get("evidence") == "external_content":
            parts.append("taken from a file or page you asked about")
        if meta.get("import_source"):
            parts = [import_line(meta)]
        self.detail_title.set_text(item.title)
        self.detail_meta.configure(text=" · ".join(parts))
        self.detail_body.configure(text=item.content or "")

    def _merge_of(self, item) -> int | None:
        if not item.source.metadata.get("merged_from"):
            return None
        page = getattr(self.app, "suggestions", None)  # not built yet while the app starts
        service, space = (page.curation() if page is not None else None), self.app.current_space()
        if service is None or space is None:
            return None
        return service.result_of(space.inbox, item.memory_id)

    # Actions --------------------------------------------------------------

    def undo_merge(self) -> int:
        if self._merge_proposal is None:
            return 0
        return self.app.suggestions.undo([self._merge_proposal])

    def control(self):
        return getattr(self.app.connection_manager, "control", None)

    def move_selected(self) -> None:
        chosen = self.selected()
        control = self.control()
        if len(chosen) != 1 or control is None or not self.app.require_action("review"):
            return
        item = chosen[0]
        edited = self.app.edit_before_saving(title=item.title, content=item.content or "",
                                             reason="collected in the inbox; edit it if needed")
        if edited is None:
            return
        title, content = edited
        update = self.app.service.similar_curated(title, content)
        if update is not None:
            if self.app.confirm(title="Update the existing memory?",
                                message="Your memories already have one that says nearly the same.",
                                quote=update.title, confirm_text="Update existing", cancel_text="Add as new"):
                pass
            elif self.app.confirm(title="Add it as a new memory?", message="It is added next to the similar one.",
                                  quote=title, confirm_text="Add as new"):
                update = None
            else:
                return
        try:
            self.app.service.move_inbox(control, item.memory_id, title=title, content=content, update=update)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", str(exc) or "BIO CE couldn't move this item.", title="Not moved")
            return
        self.app.notify("success", f"{title!r} is now in your memories.", title="Moved")
        self.app.data_changed()
        self.refresh()

    def discard_selected(self) -> None:
        chosen = self.selected()
        control = self.control()
        if not chosen or control is None or not self.app.require_action("review"):
            return
        if not self.app.confirm(
            title=f"Discard {plural(len(chosen), 'item')}?",
            message="Discarded items are deleted from the inbox. This can't be undone.",
            quote=chosen[0].title if len(chosen) == 1 else None,
            points=(DISCARD_NOTICE,),
            confirm_text="Discard",
            danger=True,
        ):
            return
        try:
            result = self.app.service.discard_inbox(control, [item.memory_id for item in chosen])
        except Exception:  # noqa: BLE001
            self.app.notify("error", "BIO CE couldn't discard these items. Nothing was deleted.", title="Not discarded")
            return
        self._discarded(result.deleted, result.completed)

    def keep_proposal(self, proposal: dict) -> None:
        control = self.control()
        if control is None or not self.app.require_action("review"):
            return
        try:
            control.keep_items(int(proposal["item_id"]))
        except Exception as exc:  # noqa: BLE001
            self.app.notify("error", str(exc), title="Not kept")
            return
        self.app.notify("success", f"Kept {plural(len(proposal['memory_ids']), 'item')}.", title="Kept")
        self.app.refresh_badges()
        self.refresh()

    def discard_proposal(self, proposal: dict) -> None:
        control = self.control()
        if control is None or not self.app.require_action("review") or not self.app.confirm(
            title=f"Discard {plural(len(proposal['memory_ids']), 'item')} now?",
            message="These items are deleted from the inbox now instead of on the date shown.",
            points=(DISCARD_NOTICE,), confirm_text="Discard now", danger=True,
        ):
            return
        try:
            deleted = self.app.service.discard_proposal(control, proposal)
        except Exception:  # noqa: BLE001
            self.app.notify("error", "BIO CE couldn't discard these items. Nothing was deleted.", title="Not discarded")
            return
        waiting = bool(control.curation_items(statuses=("cleanup_pending",)))
        self._discarded(deleted, not waiting)

    def _discarded(self, count: int, completed: bool) -> None:
        if completed:
            self.app.notify("success", f"Discarded {plural(count, 'item')}.", title="Discarded")
        else:
            self.app.notify("info", f"Discarded {plural(count, 'item')}. A connected AI host is still reading the "
                            "database, so BIO CE finishes clearing the freed space once it lets go (about a minute "
                            "after its last request).", title="Finishing clean-up")
            self.app.schedule_cleanup_retry()
        self.app.refresh_badges()
        self.refresh()

    def focus_default(self) -> None:
        self.tree.focus_set()


__all__ = ["InboxPage", "SpaceBar"]
