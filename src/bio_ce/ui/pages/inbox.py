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
from bio_ce.ui.widgets import AutoScrollbar, Button, Card, EmptyState, WrapLabel, section_label


class SpaceBar(tk.Frame):
    """Memories / Inbox tabs on the left, the space picker on the right."""

    def __init__(self, master: tk.Misc, app, *, active: str) -> None:
        theme, c = app.theme, app.theme.colors
        super().__init__(master, background=c.bg)
        self.app = app
        self.active = active
        self.memories_tab = Button(self, theme, "Memories", variant="primary" if active == "memories" else "subtle",
                                   command=lambda: app.show_page("memories"))
        self.memories_tab.pack(side="left")
        self.inbox_tab = Button(self, theme, "Inbox", variant="primary" if active == "inbox" else "subtle",
                                command=lambda: app.show_page("inbox"))
        self.inbox_tab.pack(side="left", padx=(theme.px(SPACE_XS), 0))
        self.space = tk.StringVar(master=self)
        self.picker = ttk.Combobox(self, textvariable=self.space, state="readonly", width=28, style="BIO.TCombobox",
                                   font=theme.font("body"))
        # The drop-down list is a plain Tk listbox; give it the theme's colors.
        self.option_add("*TCombobox*Listbox.background", c.surface_alt)
        self.option_add("*TCombobox*Listbox.foreground", c.text)
        self.option_add("*TCombobox*Listbox.selectBackground", c.selection)
        self.option_add("*TCombobox*Listbox.selectForeground", c.text)
        self.picker.pack(side="right")
        tk.Label(self, text="Space", font=theme.font("caption_strong"), background=c.bg,
                 foreground=c.text_muted).pack(side="right", padx=(0, theme.px(SPACE_S)))
        self.picker.bind("<<ComboboxSelected>>", lambda _e: self._chosen())
        self._spaces: list = []

    def refresh(self) -> None:
        self._spaces = list(self.app.spaces())
        self.picker.configure(values=[space.display_name for space in self._spaces])
        current = self.app.current_space()
        self.space.set(current.display_name if current is not None else "General")
        if len(self._spaces) <= 1:
            self.picker.configure(state="disabled")
        else:
            self.picker.configure(state="readonly")
        count = self.app.inbox_count()
        self.inbox_tab.set_text(f"Inbox ({count})" if count else "Inbox")

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
        WrapLabel(self, "Hosts in collect mode save lasting information here without asking. Hosts don't see the "
                  "inbox unless they ask for it, and session hooks never use it. Move what you want to keep to "
                  "your memories; discard the rest.", font=theme.font("body"), foreground=c.text_secondary,
                  background=c.bg).pack(fill="x", pady=(0, theme.px(SPACE_M)))

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
        self.detail_title = WrapLabel(detail, font=theme.font("title"), foreground=c.text)
        self.detail_title.pack(fill="x")
        self.detail_meta = WrapLabel(detail, font=theme.font("caption"), foreground=c.text_muted)
        self.detail_meta.pack(fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_M)))
        self.detail_body = WrapLabel(detail, font=theme.font("body"), foreground=c.text_secondary)
        self.detail_body.pack(fill="x")
        buttons = tk.Frame(detail, background=c.surface)
        buttons.pack(fill="x", side="bottom", pady=(theme.px(SPACE_M), 0))
        self.move_button = Button(buttons, theme, "Move to memories…", variant="primary", command=self.move_selected)
        self.move_button.pack(side="left")
        self.discard_button = Button(buttons, theme, "Discard…", variant="danger_subtle",
                                     command=self.discard_selected)
        self.discard_button.pack(side="left", padx=(theme.px(SPACE_S), 0))

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
        if len(chosen) != 1:
            self.detail_title.configure(text=f"{plural(len(chosen), 'item')} selected" if chosen else "")
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
        self.detail_title.configure(text=item.title)
        self.detail_meta.configure(text=" · ".join(parts))
        self.detail_body.configure(text=item.content or "")

    # Actions --------------------------------------------------------------

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
