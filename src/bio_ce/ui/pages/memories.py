# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Memories: search, list, read, and act on one memory at a time."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from bio_ce.core.models import MemoryNotFoundError, RevisionConflictError
from bio_ce.engine.contract import EngineUnavailable, MemoryView, UnsupportedCapability, WriteStatus
from bio_ce.ui.dialogs import HistoryDialog
from bio_ce.ui.format import format_timestamp, middle_ellipsis, plural, preview, relative_time
from bio_ce.ui.pages import Page
from bio_ce.ui.pages.inbox import SpaceBar
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XL, SPACE_XS
from bio_ce.ui.widgets import (
    AutoScrollbar,
    Button,
    Card,
    EmptyState,
    FlowFrame,
    IconButton,
    Pill,
    SearchBox,
    TextArea,
    WrapLabel,
    copy_to_clipboard,
    divider,
    reading_padding,
)


class MemoriesPage(Page):
    key = "memories"
    nav_key = "memories"
    title = "Memories"
    subtitle = "Search, read, and manage what BIO CE remembers"
    PAGE_SIZE = 100
    SEARCH_LIMIT = 50
    SEARCH_DELAY_MS = 300

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        self.selected: MemoryView | None = None
        self.records: dict[str, MemoryView] = {}
        self.history_dialog: HistoryDialog | None = None
        self._search_after: str | None = None
        self._loaded = 0
        self._total = 0
        self._details_open = False

        self.add_button = Button(self.actions, theme, "Add memory", icon="add", variant="primary",
                                 command=app.start_new_memory, tooltip="Add memory (Ctrl+N)")
        self.add_button.pack(side="right")
        app.gate(self.add_button, "create")
        Button(self.actions, theme, "Refresh", icon="refresh", variant="subtle",
               command=self.refresh, tooltip="Reload the list (F5)").pack(side="right", padx=(0, theme.px(SPACE_S)))

        self.space_bar = SpaceBar(self, app, active="memories")
        self.space_bar.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        toolbar = tk.Frame(self, background=c.bg)
        toolbar.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        self.query = tk.StringVar(master=self)
        self.export_button = Button(toolbar, theme, "Export…", variant="subtle", command=app.export_memories,
                                    tooltip="Save memories as a text file to paste into another AI")
        self.export_button.pack(side="right", padx=(theme.px(SPACE_S), 0))
        app.gate(self.export_button, "browse")
        self.move_button = Button(toolbar, theme, "Move to…", command=self.move_selected,
                                  tooltip="Move the selected memories to another space (or right-click them)")
        self.move_button.pack(side="right", padx=(theme.px(SPACE_S), 0))
        app.gate(self.move_button, "edit")
        self.result_label = tk.Label(toolbar, text="", font=theme.font("caption"), background=c.bg,
                                     foreground=c.text_muted, anchor="e")
        self.result_label.pack(side="right", padx=(theme.px(SPACE_M), 0))
        self.search = SearchBox(toolbar, theme, self.query, "Search titles and text", on_clear=self.refresh)
        self.search.pack(side="left", fill="x", expand=True)
        self.search.entry.bind("<Return>", lambda _e: self._search_now())
        self.search.entry.bind("<KP_Enter>", lambda _e: self._search_now())
        self.search.entry.bind("<Down>", lambda _e: self._focus_list())
        self.query.trace_add("write", lambda *_: self._schedule_search())

        self.stack = tk.Frame(self, background=c.bg)
        self.stack.pack(fill="both", expand=True)
        self.empty_all = EmptyState(
            self.stack, theme, icon="memories", title="Your memory is empty",
            message="Memories you save stay on this PC. Add notes, decisions, or preferences you want your AI "
                    "tools to recall, then connect a host on the Connections page.",
            actions=(("Add memory", app.start_new_memory, "primary"),
                     ("Restore a backup", lambda: app.show_page("settings"), "secondary")),
        )
        self.split = ttk.Panedwindow(self.stack, orient="horizontal", style="BIO.TPanedwindow")
        left = Card(self.split, theme, padding=0)
        right = Card(self.split, theme, padding=0)
        self.split.add(left, weight=2)
        self.split.add(right, weight=3)
        self.reading_card = right
        # Keep the reading pane wide enough for its buttons, whatever the first layout or a dragged divider did
        # (on a 1024x768 screen at 125% it once got 42 px and its buttons were hidden).
        self.split.bind("<Configure>", lambda _e: self.after_idle(self.keep_reading_pane), add="+")
        self.split.bind("<ButtonRelease-1>", lambda _e: self.after_idle(self.keep_reading_pane), add="+")

        list_area = tk.Frame(left.body, background=c.surface)
        list_area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(list_area, columns=("title", "updated"), show="headings", selectmode="extended",
                                 style="BIO.Treeview", takefocus=1)
        self.tree.heading("title", text="TITLE", anchor="w")
        self.tree.heading("updated", text="UPDATED", anchor="w")
        self.tree.column("title", anchor="w", minwidth=theme.px(140), width=theme.px(260), stretch=True)
        self.tree.column("updated", anchor="w", minwidth=theme.px(84), width=theme.px(110), stretch=False)
        scrollbar = AutoScrollbar(list_area, orient="vertical", command=self.tree.yview,
                                  style=theme.scrollbar_style(c.surface))
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(theme.px(SPACE_XS), 0), pady=theme.px(SPACE_XS))
        scrollbar.grid(row=0, column=1, sticky="ns", pady=theme.px(SPACE_S))
        list_area.rowconfigure(0, weight=1)
        list_area.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Delete>", lambda _e: self.retract_selected())
        self.tree.bind("<Button-3>", self._right_click)
        self.tree.bind("<Shift-F10>", lambda _e: self._menu_from_keyboard())
        self.tree.bind("<App>", lambda _e: self._menu_from_keyboard())
        self.tree.bind("<Return>", lambda _e: self.reader.text.focus_set())
        self.no_results = EmptyState(
            list_area, theme, icon="search", title="No matches",
            message="Try different words. Search looks for whole words in titles and memory text.",
            actions=(("Clear search", self.search.clear, "secondary"),),
        )
        self.more_bar = tk.Frame(left.body, background=c.surface)
        divider(self.more_bar, theme).pack(fill="x")
        self.more_button = Button(self.more_bar, theme, "Load more", variant="subtle", command=self.load_more)
        self.more_button.pack(fill="x", padx=theme.px(SPACE_S), pady=theme.px(SPACE_S))

        self.detail_empty = EmptyState(
            right.body, theme, icon="document", title="Select a memory",
            message="Choose a memory from the list to read it here. Use the arrow keys to move through the list.",
        )
        self.detail = tk.Frame(right.body, background=c.surface)
        self._build_detail(self.detail)
        self.detail_empty.pack(fill="both", expand=True)

    def _build_detail(self, frame: tk.Frame) -> None:
        theme, c = self.theme, self.colors
        head = tk.Frame(frame, background=c.surface)
        head.pack(fill="x", padx=theme.px(SPACE_XL), pady=(theme.px(SPACE_L + 4), theme.px(SPACE_M)))
        self.detail_title = WrapLabel(head, font=theme.font("title"), foreground=c.text)
        self.detail_title.pack(fill="x")
        meta = tk.Frame(head, background=c.surface)
        meta.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.revision_pill = Pill(meta, theme)
        self.revision_pill.pack(side="left")
        self.meta_label = tk.Label(meta, font=theme.font("caption"), background=c.surface, foreground=c.text_muted,
                                   anchor="w")
        self.meta_label.pack(side="left", padx=(theme.px(SPACE_M), 0))
        actions = FlowFrame(head, gap=theme.px(SPACE_S), background=c.surface)
        actions.pack(fill="x", pady=(theme.px(SPACE_M + 2), 0))
        self.detail_actions = actions
        self.edit_button = actions.add(Button(actions, theme, "Edit", icon="edit", command=self.app.start_edit_memory,
                                              tooltip="Edit this memory (Ctrl+E)"))
        self.history_button = actions.add(Button(actions, theme, "History", icon="history", command=self.show_history,
                                                 tooltip="See every revision (Ctrl+H)"))
        self.retract_button = actions.add(Button(actions, theme, "Retract…", icon="retract", variant="danger_subtle",
                                                 command=self.retract_selected,
                                                 tooltip="Hide this memory everywhere (Delete)"))
        self.app.gate(self.edit_button, "edit")
        self.app.gate(self.history_button, "history")
        self.app.gate(self.retract_button, "retract")
        divider(frame, theme).pack(fill="x")

        footer = tk.Frame(frame, background=c.surface)
        footer.pack(side="bottom", fill="x")
        divider(footer, theme).pack(fill="x")
        self.details_toggle = Button(footer, theme, "Show details", icon="chevron_right", variant="link",
                                     command=self.toggle_details, anchor="w")
        self.details_toggle.pack(anchor="w", padx=theme.px(SPACE_XL - 6), pady=theme.px(SPACE_XS))
        self.details_grid = tk.Frame(footer, background=c.surface)
        self.detail_values: dict[str, tk.Label] = {}
        rows = (("memory_id", "Memory ID", True), ("revision_id", "Revision ID", True), ("source", "Source", False),
                ("recorded", "Recorded", False), ("valid_from", "Valid from", False), ("valid_until", "Valid until", False))
        for index, (key, label, copyable) in enumerate(rows):
            tk.Label(self.details_grid, text=label, font=theme.font("caption"), background=c.surface,
                     foreground=c.text_muted, anchor="w").grid(row=index, column=0, sticky="w", pady=theme.px(2))
            value = tk.Label(self.details_grid, font=theme.font("mono" if copyable else "caption"),
                             background=c.surface, foreground=c.text_secondary, anchor="w")
            value.grid(row=index, column=1, sticky="w", padx=(theme.px(SPACE_M), 0))
            if copyable:
                IconButton(self.details_grid, theme, "copy", f"Copy {label.lower()}",
                           command=lambda k=key, name=label: self._copy(k, name)).grid(row=index, column=2, sticky="w")
            self.detail_values[key] = value
        self.details_grid.columnconfigure(1, weight=1)

        self.reader = TextArea(frame, theme, font="reading", readonly=True, bordered=False)
        self.reader.text.configure(spacing2=theme.px(4), spacing3=theme.px(2))
        self.reader.text.tag_configure("empty", foreground=c.text_muted, font=theme.font("body"))
        self.reader.pack(fill="both", expand=True, padx=(theme.px(SPACE_XL), theme.px(SPACE_S)),
                         pady=(theme.px(SPACE_L), theme.px(SPACE_S)))
        frame.bind("<Configure>", self._fit_reader, add="+")
        frame.bind("<Configure>", lambda _e: self.after_idle(self.keep_reading_pane), add="+")

    def keep_reading_pane(self) -> None:
        """At least 40% of the split, or the widest action button with its margins; the list keeps 200 px."""
        try:
            total = self.split.winfo_width()
            if total < self.theme.px(400) or len(self.split.panes()) < 2:
                return
            widest = max(button.winfo_reqwidth() for button in (self.edit_button, self.history_button,
                                                                 self.retract_button))
            need = max(int(total * 0.4), widest + 2 * self.theme.px(SPACE_XL) + self.theme.px(16))
            need = min(need, total - self.theme.px(200))
            if total - int(self.split.sashpos(0)) < need:
                self.split.sashpos(0, total - need)
        except tk.TclError:
            return  # the window is closing

    def _fit_reader(self, event) -> None:
        extra = reading_padding(self.theme, int(event.width) - self.theme.px(SPACE_XL + SPACE_S))
        self.reader.pack_configure(padx=(self.theme.px(SPACE_XL), self.theme.px(SPACE_S) + extra))

    def focus_default(self) -> None:
        if self.records:
            self._focus_list()
        else:
            self.search.focus_set()

    def _focus_list(self) -> str:
        children = self.tree.get_children()
        if children:
            if not self.tree.selection():
                self.tree.selection_set(children[0])
            self.tree.focus(self.tree.selection()[0])
            self.tree.focus_set()
        return "break"

    # Data -----------------------------------------------------------------

    def _schedule_search(self) -> None:
        if self._search_after is not None:
            self.after_cancel(self._search_after)
        self._search_after = self.after(self.SEARCH_DELAY_MS, self._search_now)

    def _search_now(self) -> str:
        if self._search_after is not None:
            self.after_cancel(self._search_after)
            self._search_after = None
        self.refresh()
        return "break"

    def refresh(self, select: str | None = None) -> None:
        super().refresh()
        self.space_bar.refresh()
        if self._search_after is not None:
            self.after_cancel(self._search_after)
            self._search_after = None
        query = self.query.get().strip()
        keep = select or (self.selected.memory_id if self.selected else None)
        self.selected = None  # re-read on reselect so the detail never shows a stale revision
        try:
            engine = self.app.memory_engine()
            self._total = engine.count()
            if query:
                records: list[MemoryView] = []
                for hit in engine.search(query, limit=self.SEARCH_LIMIT):
                    try:
                        records.append(engine.get(hit.memory_id))
                    except MemoryNotFoundError:
                        continue
            else:
                records = list(engine.list(limit=self.PAGE_SIZE))
        except (EngineUnavailable, UnsupportedCapability) as exc:
            # Never show another engine's memories in place of the selected one.
            self._populate([], append=False)
            self._show_record(None)
            self.result_label.configure(text="")
            unsupported = isinstance(exc, UnsupportedCapability)
            self.app.notify("warning" if unsupported else "error",
                            str(exc) if unsupported else "BIO CE can't reach the memory engine right now. Nothing from any other engine is shown in its place.",
                            title="Not available" if unsupported else "Memory engine unavailable")
            return
        except Exception:
            self.result_label.configure(text="")
            self.app.notify("error", "BIO CE couldn't read your memories. Try again, or restart BIO CE if this "
                            "keeps happening.", title="Memories unavailable")
            return
        self._populate(records, append=False)
        self._update_states(query, len(records))
        if keep and self.tree.exists(keep):
            self.select(keep)
        else:
            self._show_record(None)

    def load_more(self) -> None:
        try:
            engine = self.app.memory_engine()
            records = list(engine.list(limit=self.PAGE_SIZE, offset=self._loaded))
            self._total = engine.count()
        except Exception:
            self.app.notify("error", "BIO CE couldn't load more memories. Try again.", title="Memories unavailable")
            return
        self._populate(records, append=True)
        self._update_states("", self._loaded)

    def _populate(self, records: list[MemoryView], *, append: bool) -> None:
        if not append:
            self.tree.delete(*self.tree.get_children())
            self.records = {}
            self._loaded = 0
        for record in records:
            if record.memory_id in self.records:
                continue
            self.records[record.memory_id] = record
            self.tree.insert("", tk.END, iid=record.memory_id,
                             values=(preview(record.title, 120), relative_time(record.recorded_at)))
        self._loaded = len(self.records)

    def _update_states(self, query: str, shown: int) -> None:
        if self._total == 0 and not query:
            self.split.pack_forget()
            self.empty_all.pack(fill="both", expand=True)
            self.result_label.configure(text="")
            return
        self.empty_all.pack_forget()
        if not self.split.winfo_manager():
            self.split.pack(fill="both", expand=True)
        if query:
            label = f"{plural(shown, 'result')} for “{preview(query, 40)}”"
            if shown >= self.SEARCH_LIMIT:
                label += f" · top {self.SEARCH_LIMIT}"
            self.result_label.configure(text=label)
        elif self._total is None:  # the engine does not report a total
            self.result_label.configure(text=f"Showing {plural(shown, 'memory', 'memories')}")
        elif shown < self._total:
            self.result_label.configure(text=f"Showing {shown:,} of {plural(self._total, 'memory', 'memories')}")
        else:
            self.result_label.configure(text=plural(self._total, "memory", "memories"))
        if query and shown == 0:
            self.no_results.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.no_results.lift()
        else:
            self.no_results.place_forget()
        more = (shown < self._total) if self._total is not None else (shown > 0 and shown % self.PAGE_SIZE == 0)
        if not query and more:
            self.more_bar.pack(side="bottom", fill="x", before=self.tree.master)
        else:
            self.more_bar.pack_forget()

    def select(self, memory_id: str) -> None:
        if not self.tree.exists(memory_id):
            return
        self.tree.selection_set(memory_id)
        self.tree.focus(memory_id)
        self.tree.see(memory_id)
        self._on_select()

    def _on_select(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        if self.selected is not None and self.selected.memory_id == selection[0] and self.detail.winfo_manager():
            return
        try:
            record = self.app.memory_engine().get(selection[0])
        except MemoryNotFoundError:
            self._show_record(None)
            self.app.notify("warning", "This memory is no longer available. It may have been retracted or "
                            "restored from a backup.", title="Memory not found",
                            action=("Refresh list", self.refresh))
            return
        except Exception:
            self._show_record(None)
            self.app.notify("error", "BIO CE couldn't open this memory. Try again.", title="Memory unavailable")
            return
        self._show_record(record)

    def _show_record(self, record: MemoryView | None) -> None:
        self.selected = record
        self.after_idle(self.keep_reading_pane)
        if record is None:
            self.detail.pack_forget()
            self.detail_empty.pack(fill="both", expand=True)
            return
        self.detail_empty.pack_forget()
        self.detail.pack(fill="both", expand=True)
        self.detail_title.configure(text=record.title)
        self.revision_pill.set(f"Revision {record.revision_number}", "neutral")
        meta = f"Updated {format_timestamp(record.recorded_at)}"
        if record.source_ref:
            meta += f" · Source: {preview(record.source_ref, 48)}"
        self.meta_label.configure(text=meta)
        text = self.reader.text
        text.configure(state="normal")
        text.delete("1.0", tk.END)
        if record.content:
            text.insert("1.0", record.content)
        else:
            text.insert("1.0", "This memory has a title but no text.", "empty")
        text.configure(state="disabled")
        text.yview_moveto(0)
        values = {
            "memory_id": middle_ellipsis(record.memory_id, 40),
            "revision_id": middle_ellipsis(record.revision_id, 40),
            "source": f"{record.source_type} · {record.source_ref}",
            "recorded": format_timestamp(record.recorded_at),
            "valid_from": format_timestamp(record.valid_from),
            "valid_until": format_timestamp(record.valid_until),
        }
        for key, value in values.items():
            self.detail_values[key].configure(text=value)

    def toggle_details(self) -> None:
        self._details_open = not self._details_open
        if self._details_open:
            self.details_grid.pack(fill="x", padx=self.theme.px(SPACE_XL), pady=(0, self.theme.px(SPACE_M)))
            self.details_toggle.set_text("Hide details")
            if self.details_toggle.icon_label is not None:
                self.details_toggle.icon_label.configure(text=self.theme.icon("chevron_down"))
        else:
            self.details_grid.pack_forget()
            self.details_toggle.set_text("Show details")
            if self.details_toggle.icon_label is not None:
                self.details_toggle.icon_label.configure(text=self.theme.icon("chevron_right"))

    def _copy(self, key: str, name: str) -> None:
        if self.selected is None:
            return
        value = self.selected.memory_id if key == "memory_id" else self.selected.revision_id
        copy_to_clipboard(self, value)
        self.app.notify("success", f"{name} copied to the clipboard.")

    # Actions --------------------------------------------------------------

    def retract_selected(self) -> None:
        record = self.selected
        if record is None:
            self.app.notify("info", "Select a memory in the list first.")
            return
        if not self.app.require_action("retract"):
            return
        accepted = self.app.confirm(
            title="Retract this memory?",
            message="BIO CE and connected AI hosts will no longer find or read this memory.",
            points=(
                "Earlier revisions stay inside the database file. Retraction is not a secure erase.",
                "This can't be undone from BIO CE. Restoring an older backup is the only way back.",
            ),
            quote=record.title,
            confirm_text="Retract memory",
            danger=True,
        )
        if not accepted:
            return
        changed = ("This memory changed after you opened it, so nothing was retracted. "
                   "Review the latest version and try again.")
        try:
            outcome = self.app.memory_engine().retract(record.memory_id, expected_revision_id=record.revision_id)
        except (RevisionConflictError, MemoryNotFoundError):
            self.app.notify("warning", changed, title="Memory changed")
            self.app.data_changed()
            return
        except EngineUnavailable:
            self.app.notify("error", "BIO CE can't reach the memory engine, so nothing was retracted.",
                            title="Memory engine unavailable")
            return
        except Exception:
            self.app.notify("error", "BIO CE couldn't retract this memory. Nothing was changed.",
                            title="Retraction failed")
            return
        if outcome.status is WriteStatus.CONFLICT:
            self.app.notify("warning", changed, title="Memory changed")
            self.app.data_changed()
            return
        if not outcome.persisted:
            self.app.notify("warning", "; ".join(outcome.reasons) or "The memory engine did not retract it.",
                            title="Nothing was retracted")
            return
        self.selected = None
        self.app.data_changed()
        self.app.notify("success", f"“{preview(record.title, 60)}” no longer appears in BIO CE or to "
                        "connected AI hosts.", title="Memory retracted")

    # Right-click menu ---------------------------------------------------------------------------------

    def _right_click(self, event) -> str:
        """Right-click a row: it becomes the selection unless it is already part of it, then the menu opens."""
        row = self.tree.identify_row(event.y)
        if not row:
            return "break"
        if row not in self.tree.selection():
            self.tree.selection_set(row)
            self.tree.focus(row)
            self._on_select()
        self.context_menu().tk_popup(event.x_root, event.y_root)
        return "break"

    def _menu_from_keyboard(self) -> str:
        if self.tree.selection():
            bbox = self.tree.bbox(self.tree.selection()[0]) or (0, 0, 0, 0)
            self.context_menu().tk_popup(self.tree.winfo_rootx() + bbox[0] + 20, self.tree.winfo_rooty() + bbox[1])
        return "break"

    def move_targets(self) -> list:
        current = self.app.current_space()
        return [space for space in self.app.spaces() if current is None or space.space_id != current.space_id]

    def context_menu(self) -> tk.Menu:
        """Edit, History, Move to ▸ (each other space), Retract… for the selected memories."""
        c = self.colors
        style = {"tearoff": 0, "background": c.surface_alt, "foreground": c.text, "activebackground": c.selection,
                 "activeforeground": c.text, "disabledforeground": c.text_muted, "relief": "flat", "borderwidth": 1,
                 "font": self.theme.font("body")}
        menu = tk.Menu(self, **style)
        selected = [iid for iid in self.tree.selection() if iid in self.records]
        single = "normal" if len(selected) == 1 else "disabled"
        menu.add_command(label="Edit", command=self.app.start_edit_memory,
                         state=single if self.app.allowed("edit").enabled else "disabled")
        menu.add_command(label="History", command=self.show_history,
                         state=single if self.app.allowed("history").enabled else "disabled")
        spaces = tk.Menu(menu, **style)
        for space in self.move_targets():
            spaces.add_command(label=space.display_name,
                               command=lambda target=space.space_id: self.move_selected(target))
        menu.add_cascade(label="Move to", menu=spaces,
                         state="normal" if selected and spaces.index("end") is not None
                         and self.app.allowed("edit").enabled else "disabled")
        menu.add_separator()
        menu.add_command(label="Retract…", command=self.retract_selected,
                         state=single if self.app.allowed("retract").enabled else "disabled")
        return menu

    def move_selected(self, target_id: str | None = None) -> None:
        """Move one or more selected memories to General, Personal, or a project space (same ids and history).

        ``target_id`` comes from the right-click menu, where the space was already chosen.
        """
        ids = [iid for iid in self.tree.selection() if iid in self.records]
        if not ids:
            self.app.notify("info", "Select one or more memories in the list first.")
            return
        targets = self.move_targets()
        if target_id is not None:
            target = next((space for space in targets if space.space_id == target_id), None)
            if target is not None:
                self.app.move_memories(ids, target)
            return
        if not targets:
            self.app.notify("info", "There is no other space yet. Create a project space or turn on Personal in "
                            "Settings → Spaces.", title="Nowhere to move")
            return
        details = {"general": "Shared with every connected AI host and used by session hooks.",
                   "personal": "Hosts see it only with your permission; session hooks never use it."}
        key = self.app.ask_choice(
            title=f"Move {plural(len(ids), 'memory', 'memories')}",
            message="The memories keep their history. BIO CE makes a backup first.",
            choices=[(space.space_id, space.display_name,
                      details.get(space.space_id, "Project space: hosts with project access can use it."))
                     for space in targets],
            confirm_text="Move")
        target = next((space for space in targets if space.space_id == key), None)
        if target is not None:
            self.app.move_memories(ids, target)

    def show_history(self) -> HistoryDialog | None:
        record = self.selected
        if record is None:
            self.app.notify("info", "Select a memory in the list first.")
            return None
        if not self.app.require_action("history"):
            return None
        try:
            revisions = self.app.memory_engine().history(record.memory_id)
        except Exception:
            self.app.notify("error", "BIO CE couldn't read the history of this memory. Refresh and try again.",
                            title="History unavailable")
            return None
        if self.history_dialog is not None and self.history_dialog.winfo_exists():
            self.history_dialog.destroy()
        self.history_dialog = HistoryDialog(self, self.theme, revisions).show()
        return self.history_dialog


__all__ = ["MemoriesPage"]
