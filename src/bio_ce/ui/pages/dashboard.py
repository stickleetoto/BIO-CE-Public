# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Dashboard: status, counts, recent memories, and AI host overview."""

from __future__ import annotations

import tkinter as tk

from bio_ce.connections import HostStatus, auto_memory_support
from bio_ce.ui.format import host_name, plural, preview, relative_time
from bio_ce.ui.pages import Page
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XL, SPACE_XS
from bio_ce.ui.widgets import (
    Button,
    Card,
    EmptyState,
    Pill,
    RowButton,
    ScrollFrame,
    SearchBox,
    WrapLabel,
    caption_label,
    section_label,
)


RECENT_LIMIT = 6


def host_pill(status: HostStatus | None) -> tuple[str, str]:
    if status is None:
        return "Unavailable", "danger"
    if not status.installed:
        return "Not installed", "neutral"
    if status.configuration_conflict:
        return "Needs attention", "warning"
    if status.connected and status.legacy:
        return "Connected (v0.2)", "success"
    if status.connected and status.mode == "auto_memory":
        if auto_memory_support(status.host).level != "available":
            return "Auto memory (limited)", "warning"
        return "Auto memory", "success"
    if status.connected and status.mode == "paused":
        return "Paused", "warning"
    if status.connected:
        return "Connected · Read only", "success"
    return "Not connected", "neutral"


class DashboardPage(Page):
    key = "dashboard"
    nav_key = "dashboard"
    title = "Dashboard"
    subtitle = "Your local memory at a glance"

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        Button(self.actions, theme, "Add memory", icon="add", variant="primary",
               command=app.start_new_memory, tooltip="Add memory (Ctrl+N)").pack(side="right")

        self.scroll = ScrollFrame(self, theme)
        self.scroll.pack(fill="both", expand=True)
        body = self.scroll.body
        self.query = tk.StringVar(master=self)
        self.search = SearchBox(body, theme, self.query, "Search your memories and press Enter")
        self.search.entry.bind("<Return>", lambda _e: self._search())
        self.search.entry.bind("<KP_Enter>", lambda _e: self._search())
        self.search.pack(fill="x", pady=(0, theme.px(SPACE_L)))

        stats = tk.Frame(body, background=c.bg)
        stats.pack(fill="x")
        self.stats = stats
        self.status_card = Card(stats, theme, padding=SPACE_L + 2)
        self.count_card = Card(stats, theme, padding=SPACE_L + 2)
        self.hosts_card = Card(stats, theme, padding=SPACE_L + 2)
        self._stat_cards = (self.status_card, self.count_card, self.hosts_card)

        caption_label(self.status_card.body, theme, "BIO CE status").pack(fill="x")
        self.status_pill = Pill(self.status_card.body, theme, "Ready", "success")
        self.status_pill.pack(anchor="w", pady=(theme.px(SPACE_S + 2), theme.px(SPACE_S)))
        self.status_detail = caption_label(self.status_card.body, theme, "", muted=True)
        self.status_detail.pack(fill="x")

        caption_label(self.count_card.body, theme, "Stored memories").pack(fill="x")
        self.count_value = tk.Label(self.count_card.body, text="0", font=theme.font("stat"), background=c.surface,
                                    foreground=c.text, anchor="w")
        self.count_value.pack(fill="x")
        self.count_detail = caption_label(self.count_card.body, theme, "Active memories in your personal store",
                                          muted=True)
        self.count_detail.pack(fill="x")

        caption_label(self.hosts_card.body, theme, "AI connections").pack(fill="x")
        self.hosts_value = tk.Label(self.hosts_card.body, text="0", font=theme.font("stat"), background=c.surface,
                                    foreground=c.text, anchor="w")
        self.hosts_value.pack(fill="x")
        self.hosts_detail = caption_label(self.hosts_card.body, theme, "of 2 hosts connected",
                                          muted=True)
        self.hosts_detail.pack(fill="x")

        lower = tk.Frame(body, background=c.bg)
        lower.pack(fill="both", expand=True, pady=(theme.px(SPACE_L), 0))
        self.lower = lower
        self.recent_card = Card(lower, theme, padding=SPACE_L + 2)
        header = tk.Frame(self.recent_card.body, background=c.surface)
        header.pack(fill="x", pady=(0, theme.px(SPACE_S)))
        section_label(header, theme, "Recent memories").pack(side="left")
        Button(header, theme, "View all", variant="link", command=lambda: app.show_page("memories")).pack(side="right")
        self.recent_list = tk.Frame(self.recent_card.body, background=c.surface)
        self.recent_list.pack(fill="both", expand=True)
        self.recent_empty = EmptyState(
            self.recent_card.body, theme, icon="memories", title="No memories yet",
            message="Save notes, decisions, or preferences you want your AI tools to recall. "
                    "Nothing is stored until you select Save.",
            actions=(("Add your first memory", app.start_new_memory, "primary"),),
        )
        self.recent_empty.configure(height=theme.px(240))

        self.connections_card = Card(lower, theme, padding=SPACE_L + 2)
        header = tk.Frame(self.connections_card.body, background=c.surface)
        header.pack(fill="x", pady=(0, theme.px(SPACE_S)))
        section_label(header, theme, "AI hosts").pack(side="left")
        Button(header, theme, "Manage", variant="link", command=lambda: app.show_page("connections")).pack(side="right")
        self.host_rows: dict[str, Pill] = {}
        for host in ("codex", "claude"):
            row = RowButton(self.connections_card.body, theme, lambda: app.show_page("connections"))
            row.pack(fill="x", pady=theme.px(1))
            glyph = row.track(tk.Label(row.body, text=theme.icon("terminal"), font=theme.icon_font("normal"),
                                       background=c.surface, foreground=c.text_secondary, width=2))
            glyph.pack(side="left", padx=(theme.px(SPACE_XS), theme.px(SPACE_S)), pady=theme.px(SPACE_S + 2))
            row.track(tk.Label(row.body, text=host_name(host), font=theme.font("body"), background=c.surface,
                               foreground=c.text, anchor="w")).pack(side="left", fill="x", expand=True)
            pill = Pill(row.body, theme)
            pill.pack(side="right", padx=theme.px(SPACE_XS))
            row.track(pill, paint=False)
            self.host_rows[host] = pill
        note = WrapLabel(self.connections_card.body, "Connected hosts can search and read memories. With Auto "
                         "memory on they can also save lasting ones; retractions always wait for you.",
                         font=theme.font("caption"),
                         foreground=c.text_muted)
        note.pack(fill="x", pady=(theme.px(SPACE_M), 0))

        footer = tk.Frame(body, background=c.bg)
        footer.pack(fill="x", pady=(theme.px(SPACE_XL - 4), theme.px(SPACE_S)))
        tk.Label(footer, text=theme.icon("lock"), font=theme.icon_font("small"), background=c.bg,
                 foreground=c.text_muted).pack(side="left", anchor="n", padx=(0, theme.px(SPACE_S)), pady=theme.px(2))
        WrapLabel(footer, "BIO CE never records conversations. Memories are saved when you select Save or when a "
                  "host you gave Auto memory saves a lasting fact, and they stay on this PC.", font=theme.font("caption"),
                  foreground=c.text_muted).pack(side="left", fill="x", expand=True)

        self._layout_mode: str | None = None
        self.bind("<Configure>", self._relayout, add="+")
        self._apply_layout("wide")

    def focus_default(self) -> None:
        self.search.focus_set()

    def _search(self) -> str:
        query = self.query.get().strip()
        self.query.set("")
        self.app.open_search(query)
        return "break"

    def _relayout(self, event) -> None:
        width = int(event.width)
        mode = "wide" if width >= self.theme.px(820) else "medium" if width >= self.theme.px(560) else "narrow"
        if mode != self._layout_mode:
            self._apply_layout(mode)

    def _apply_layout(self, mode: str) -> None:
        self._layout_mode = mode
        gap = self.theme.px(SPACE_M)
        for card in self._stat_cards:
            card.grid_forget()
        for index in range(3):
            self.stats.columnconfigure(index, weight=0, uniform="")
        if mode == "narrow":
            for row, card in enumerate(self._stat_cards):
                card.grid(row=row, column=0, sticky="nsew", pady=(0 if row == 0 else gap, 0))
            self.stats.columnconfigure(0, weight=1)
        else:
            for column, card in enumerate(self._stat_cards):
                card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else gap, 0))
                self.stats.columnconfigure(column, weight=1, uniform="stat")
        self.recent_card.grid_forget()
        self.connections_card.grid_forget()
        for index in range(2):
            self.lower.columnconfigure(index, weight=0, uniform="")
        if mode == "wide":
            self.recent_card.grid(row=0, column=0, sticky="nsew")
            self.connections_card.grid(row=0, column=1, sticky="nsew", padx=(gap, 0))
            self.lower.columnconfigure(0, weight=3, uniform="lower")
            self.lower.columnconfigure(1, weight=2, uniform="lower")
        else:
            self.recent_card.grid(row=0, column=0, sticky="nsew")
            self.connections_card.grid(row=1, column=0, sticky="nsew", pady=(gap, 0))
            self.lower.columnconfigure(0, weight=1)

    def refresh(self) -> None:
        super().refresh()
        theme, c = self.theme, self.colors
        try:
            count = self.app.service.count()
            recent = self.app.service.list(limit=RECENT_LIMIT)
        except Exception:
            self.status_pill.set("Needs attention", "danger")
            self.status_detail.configure(text="The memory database could not be read. Restart BIO CE and try again.")
            count, recent = None, ()
        else:
            self.status_pill.set("Ready", "success")
            self.status_detail.configure(text="Database open · stored only on this PC")
        self.count_value.configure(text="—" if count is None else f"{count:,}")
        self.count_detail.configure(
            text="Active memories in your personal store" if count is None
            else f"Active {'memory' if count == 1 else 'memories'} in your personal store")

        for child in self.recent_list.winfo_children():
            child.destroy()
        if recent:
            self.recent_empty.pack_forget()
            self.recent_list.pack(fill="both", expand=True)
            for record in recent:
                row = RowButton(self.recent_list, theme, lambda memory_id=record.memory_id: self.app.open_memory(memory_id))
                row.pack(fill="x", pady=theme.px(1))
                row.track(tk.Label(row.body, text=relative_time(record.recorded_at), font=theme.font("caption"),
                                   background=c.surface, foreground=c.text_muted)).pack(
                    side="right", anchor="n", padx=theme.px(SPACE_S), pady=theme.px(SPACE_S))
                text_column = row.track(tk.Frame(row.body, background=c.surface))
                text_column.pack(side="left", fill="x", expand=True, padx=theme.px(SPACE_S), pady=theme.px(SPACE_S))
                row.track(tk.Label(text_column, text=preview(record.title, 80), font=theme.font("body_strong"),
                                   background=c.surface, foreground=c.text, anchor="w")).pack(fill="x")
                snippet = preview(record.content, 110) or "No memory text"
                row.track(tk.Label(text_column, text=snippet, font=theme.font("caption"), background=c.surface,
                                   foreground=c.text_secondary, anchor="w")).pack(fill="x")
        else:
            self.recent_list.pack_forget()
            if count is not None:
                self.recent_empty.pack(fill="both", expand=True)

        statuses = self.app.host_statuses(refresh=False)
        connected = 0
        for host, pill in self.host_rows.items():
            status = statuses.get(host)
            text, kind = host_pill(status)
            pill.set(text, kind)
            if status is not None and status.connected:
                connected += 1
        self.hosts_value.configure(text=str(connected))
        self.hosts_detail.configure(text=f"of {plural(len(self.host_rows), 'host')} connected")


__all__ = ["DashboardPage", "host_pill"]
