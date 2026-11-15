# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Import memories from another AI (v0.4.3 B): paste or open a file, preview every entry, then import to the inbox.

The destination space is always chosen by the user. The list starts empty, Personal is recommended, and nothing
goes to General unless the user picks it (with one more sentence about what General means).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from bio_ce.importer import (
    BLOCKED,
    BATCH_DUPLICATE,
    CONFLICT,
    EXISTS,
    NEW,
    PATH_REVIEW,
    SENSITIVE_LABELS,
    STATE_LABELS,
    ImportCancelled,
    ImportRejected,
    parse_text,
    read_import_file,
)
from bio_ce.ui.dialogs import EntryEditDialog
from bio_ce.ui.format import format_timestamp, plural, preview as short
from bio_ce.ui.pages import Page
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import (
    AutoScrollbar,
    Button,
    Card,
    FlowFrame,
    Pill,
    fit_tree_columns,
    ScrollFrame,
    TextArea,
    WrapLabel,
    section_label,
)

PERSONAL_CHOICE = "Personal (recommended: memories from another AI are mostly about you)"
GENERAL_NOTE = ("General is shared with every connected AI host and recalled by session hooks. Personal details "
                "belong in Personal.")
SOURCE_LABELS = (("chatgpt", "ChatGPT"), ("claude", "Claude"), ("other", "Other"))
FILTERS = (("all", "All entries"), ("new", "New"), ("exists", "Already there"), ("review", "Goes to review"),
           ("sensitive", "Sensitive only"), ("blocked", "Blocked"))


class ImportPage(Page):
    key = "import"
    nav_key = "memories"
    title = "Import memories"
    subtitle = "From ChatGPT, Claude, or another AI: preview first, nothing is overwritten"

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        self.preview = None
        self.planner = None
        self.encoding = "text"
        self._cancel = threading.Event()
        self._progress = [0, 0]
        self._destinations: list[tuple[str, str]] = []
        Button(self.actions, theme, "Back to inbox", variant="subtle",
               command=lambda: app.show_page("inbox")).pack(side="right")
        scroll = ScrollFrame(self, theme)
        scroll.pack(fill="both", expand=True)
        body = scroll.body

        form = Card(body, theme, padding=SPACE_L)
        form.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        section_label(form.body, theme, "1. What to import").pack(fill="x")
        WrapLabel(form.body, "Paste the list another AI gave you, or open a .md or .txt file. Each line looks like "
                  "\"[2025-03-14] - content\". Dates written by another AI are kept as the source's date until you "
                  "confirm them.", font=theme.font("caption"), foreground=c.text_secondary).pack(
            fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_S)))
        self.text = TextArea(form.body, theme, font="body")
        self.text.text.configure(height=8)
        self.text.pack(fill="x")
        row = tk.Frame(form.body, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        Button(row, theme, "Open file…", command=self.open_file).pack(side="left")
        self.encoding_label = tk.Label(row, text="", font=theme.font("caption"), background=c.surface,
                                       foreground=c.text_muted)
        self.encoding_label.pack(side="left", padx=(theme.px(SPACE_S), 0))

        choose = tk.Frame(form.body, background=c.surface)
        choose.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        tk.Label(choose, text="Source", font=theme.font("body_strong"), background=c.surface, foreground=c.text,
                 width=12, anchor="w").pack(side="left")
        self.source = tk.StringVar(master=self, value="other")
        for key, label in SOURCE_LABELS:
            tk.Radiobutton(choose, text=label, value=key, variable=self.source, font=theme.font("body"),
                           background=c.surface, foreground=c.text, activebackground=c.surface,
                           activeforeground=c.text, selectcolor=c.surface_alt, highlightthickness=0,
                           borderwidth=0).pack(side="left", padx=(0, theme.px(SPACE_M)))
        where = tk.Frame(form.body, background=c.surface)
        where.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        tk.Label(where, text="Destination", font=theme.font("body_strong"), background=c.surface, foreground=c.text,
                 width=12, anchor="w").pack(side="left")
        self.destination = tk.StringVar(master=self, value="")
        # Narrow request, then as wide as the row allows (a 60-character request was cut at 150% scaling).
        self.destination_picker = ttk.Combobox(where, textvariable=self.destination, state="readonly", width=24,
                                               style="BIO.TCombobox", font=theme.font("body"))
        self.destination_picker.pack(side="left", fill="x", expand=True)
        self.destination_picker.bind("<<ComboboxSelected>>", lambda _e: self._destination_chosen())
        self.destination_note = WrapLabel(form.body, "", font=theme.font("caption"), foreground=c.text_secondary)
        self.destination_note.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.turn_on_button = Button(form.body, theme, "Turn on Personal…", variant="link",
                                     command=self.turn_on_personal)
        actions = tk.Frame(form.body, background=c.surface)
        actions.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.preview_button = Button(actions, theme, "Preview", variant="primary", command=self.start_preview)
        self.preview_button.pack(side="left")
        self.cancel_button = Button(actions, theme, "Cancel", variant="subtle", command=self.cancel_preview)
        self.progress = ttk.Progressbar(actions, mode="determinate", style="BIO.Horizontal.TProgressbar",
                                        length=theme.px(220))
        self.app.gate(self.preview_button, "create")

        self.result = Card(body, theme, padding=SPACE_L)
        section_label(self.result.body, theme, "2. Check the preview").pack(fill="x")
        self.summary = WrapLabel(self.result.body, "", font=theme.font("body_strong"), foreground=c.text)
        self.summary.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.date_warning = WrapLabel(self.result.body, "", font=theme.font("body"), foreground=c.warning)
        self.notes_box = tk.Frame(self.result.body, background=c.surface_alt, highlightthickness=1,
                                  highlightbackground=c.border)
        tk.Label(self.notes_box, text="Source notes (not memories, not saved)", font=theme.font("caption_strong"),
                 background=c.surface_alt, foreground=c.text_muted, anchor="w").pack(
            fill="x", padx=theme.px(SPACE_M), pady=(theme.px(SPACE_S), 0))
        self.notes = ttk.Treeview(self.notes_box, columns=("line", "text"), show="headings", height=3,
                                  selectmode="browse", style="BIO.Treeview")
        self.notes.heading("line", text="LINE", anchor="w")
        self.notes.heading("text", text="TEXT", anchor="w")
        self.notes.column("line", width=theme.px(56), stretch=False)
        self.notes.column("text", width=theme.px(600), stretch=True)
        fit_tree_columns(self.notes, theme, "text", floor=120)
        self.notes.pack(fill="x", padx=theme.px(SPACE_M), pady=theme.px(SPACE_XS))
        Button(self.notes_box, theme, "Import this line as a memory", variant="link",
               command=self.note_to_entry).pack(anchor="w", padx=theme.px(SPACE_M), pady=(0, theme.px(SPACE_S)))

        tools = FlowFrame(self.result.body, gap=theme.px(SPACE_S), background=c.surface)
        tools.pack(fill="x", pady=(theme.px(SPACE_M), theme.px(SPACE_XS)))
        self.filter = tk.StringVar(master=self, value=FILTERS[0][1])
        filter_box = ttk.Combobox(tools, textvariable=self.filter, state="readonly", width=18, style="BIO.TCombobox",
                                  values=[label for _key, label in FILTERS], font=theme.font("body"))
        tools.add(filter_box)
        filter_box.bind("<<ComboboxSelected>>", lambda _e: self.render_items())
        for text, command in (("Check visible", lambda: self.check_visible(True)),
                              ("Uncheck visible", lambda: self.check_visible(False)),
                              ("Destination…", self.destination_for_selected),
                              ("Confirm dates…", self.confirm_dates_selected),
                              ("Edit…", self.edit_selected),
                              ("Not a memory", self.entry_to_note)):
            tools.add(Button(tools, theme, text, variant="link", command=command))
        area = tk.Frame(self.result.body, background=c.surface)
        area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(area, columns=("check", "state", "date", "text", "space", "sensitive"),
                                 show="headings", selectmode="extended", height=14, style="BIO.Treeview")
        # Fixed columns are compact; TEXT takes whatever width is left (at least 150 px), so the SENSITIVE column on
        # the right is never off the edge (GUI check I6). A horizontal scroll bar appears only if even that can't fit.
        self._fixed_columns = {"check": 30, "state": 150, "date": 150, "space": 100, "sensitive": 110}
        for column, label in (("check", ""), ("state", "STATE"), ("date", "DATE"), ("text", "TEXT"),
                              ("space", "DESTINATION"), ("sensitive", "SENSITIVE")):
            self.tree.heading(column, text=label, anchor="w")
            width = self._fixed_columns.get(column, 150)
            self.tree.column(column, width=theme.px(width), minwidth=theme.px(width if column != "text" else 150),
                             stretch=False, anchor="w")
        bar = AutoScrollbar(area, orient="vertical", command=self.tree.yview, style=theme.scrollbar_style(c.surface))
        across = AutoScrollbar(area, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=bar.set, xscrollcommand=across.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        area.columnconfigure(0, weight=1)
        fit_tree_columns(self.tree, theme, "text", floor=120)
        self.tree.bind("<ButtonRelease-1>", self._clicked)
        self.tree.bind("<space>", lambda _e: self.toggle_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_detail())
        self.detail = WrapLabel(self.result.body, "", font=theme.font("caption"), foreground=c.text_secondary)
        self.detail.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.unreadable_toggle = Button(self.result.body, theme, "", variant="link", command=self.toggle_unreadable)
        self.unreadable_list = ttk.Treeview(self.result.body, columns=("line", "text"), show="headings", height=3,
                                            selectmode="browse", style="BIO.Treeview")
        self.unreadable_list.heading("line", text="LINE", anchor="w")
        self.unreadable_list.heading("text", text="LINES BIO CE COULDN'T READ (not saved)", anchor="w")
        self.unreadable_list.column("line", width=theme.px(56), stretch=False)
        footer = tk.Frame(self.result.body, background=c.surface)
        footer.pack(fill="x", side="bottom", pady=(theme.px(SPACE_M), 0))
        self.import_button = Button(footer, theme, "Import", variant="primary", command=self.do_import)
        self.import_button.pack(side="left")
        self.app.gate(self.import_button, "create")

        self.history = Card(body, theme, padding=SPACE_L)
        self.history.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        section_label(self.history.body, theme, "Recent imports").pack(fill="x")
        WrapLabel(self.history.body, "Undo removes what is still in the inbox from that import and closes its "
                  "waiting reviews. Entries you already moved to your memories stay.",
                  font=theme.font("caption"), foreground=c.text_secondary).pack(fill="x")
        self.history_rows = tk.Frame(self.history.body, background=c.surface)
        self.history_rows.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.batch_rows: dict[str, tk.Frame] = {}

    # Setup ----------------------------------------------------------------------------------------------

    @property
    def control(self):
        return getattr(self.app.connection_manager, "control", None)

    def refresh(self) -> None:
        super().refresh()
        personal_on = self.app.personal_enabled()
        projects = [space for space in self.app.spaces() if not space.is_general and not space.is_personal]
        self._destinations = [("personal", PERSONAL_CHOICE), ("general", "General")]
        self._destinations += [(space.space_id, space.display_name) for space in projects]
        self.destination_picker.configure(values=[label for _key, label in self._destinations])
        if self.destination_id() == "personal" and personal_on:
            self.turn_on_button.pack_forget()
        self.render_history()
        self._sync_buttons()

    def spaces(self) -> tuple:
        return self.app.spaces()

    def destination_id(self) -> str | None:
        label = self.destination.get()
        return next((key for key, text in self._destinations if text == label), None)

    def set_text(self, text: str, encoding: str = "text") -> None:
        self.text.set(text)
        self.encoding = encoding
        self.encoding_label.configure(text="" if encoding == "text" else f"Read as {encoding}")
        self._sync_buttons()

    def open_file(self) -> None:
        path = self.app.ask_open_path(title="Open a memory list",
                                      filetypes=(("Text and Markdown", "*.md *.txt *.markdown"),))
        if not path:
            return
        try:
            text, encoding = read_import_file(path)
        except (ImportRejected, OSError) as exc:
            self.app.notify("error", str(exc) or "BIO CE couldn't read this file.", title="Not opened")
            return
        self.set_text(text, encoding)

    def choose_destination(self, space_id: str) -> bool:
        label = next((text for key, text in self._destinations if key == space_id), None)
        if label is None:
            return False
        self.destination.set(label)
        return self._destination_chosen()

    def _destination_chosen(self) -> bool:
        chosen = self.destination_id()
        self.turn_on_button.pack_forget()
        if chosen == "personal" and not self.app.personal_enabled():
            self.destination_note.configure(text="Personal must be turned on first. Or choose General or a project "
                                                 "space yourself.")
            self.turn_on_button.pack(anchor="w", after=self.destination_note)
            self.destination.set("")
            self._sync_buttons()
            return False
        self.destination_note.configure(text=GENERAL_NOTE if chosen == "general" else "")
        if self.preview is not None and chosen:
            self.planner.set_destination(self.preview, [item.key for item in self.preview.items], chosen)
            self.render_items()
        self._sync_buttons()
        return True

    def turn_on_personal(self) -> bool:
        if not self.app.pages["settings"].turn_on_personal():
            return False
        self.refresh()
        return self.choose_destination("personal")

    # Preview --------------------------------------------------------------------------------------------

    def start_preview(self) -> None:
        destination = self.destination_id()
        text = self.text.get()
        control = self.control
        if not destination or not text.strip() or control is None or not self.app.require_action("create"):
            self._sync_buttons()
            return
        folders = [label for _space, _key, label in control.folder_links()]
        self.planner = self.app.service.import_planner(
            self._planner_spaces(), size_limit=control.inbox_settings()["file_content_limit"],
            folder_labels=folders)
        planner, source, encoding = self.planner, self.source.get(), self.encoding
        self._cancel.clear()
        self._progress[:] = [0, 0]

        def progress(done: int, total: int) -> bool:
            self._progress[:] = [done, total]
            return not self._cancel.is_set()

        def work():
            return planner.preview(parse_text(text, encoding=encoding), source=source, destination=destination,
                                   progress=progress)

        self.preview_button.set_enabled(False)
        self.cancel_button.pack(side="left", padx=(self.theme.px(SPACE_S), 0))
        self.progress.pack(side="left", padx=(self.theme.px(SPACE_M), 0))
        self.after(150, self._poll_progress)
        self.app.tasks.submit(work, self._preview_done, self._preview_failed)

    def _planner_spaces(self) -> tuple:
        return tuple(self.app.spaces())

    def _poll_progress(self) -> None:
        if not self.app.tasks.busy:
            return
        done, total = self._progress
        self.progress.configure(maximum=max(total, 1), value=done)
        self.after(150, self._poll_progress)

    def cancel_preview(self) -> None:
        self._cancel.set()

    def _end_progress(self) -> None:
        self.cancel_button.pack_forget()
        self.progress.pack_forget()
        self._sync_buttons()

    def _preview_failed(self, error: BaseException) -> None:
        self._end_progress()
        if isinstance(error, ImportCancelled):
            self.app.notify("info", "The preview was cancelled. Nothing was imported.", title="Cancelled")
            return
        self.app.notify("error", str(error) if isinstance(error, (ImportRejected, ValueError)) else
                        "BIO CE couldn't read this list. Nothing was imported.", title="Preview failed")

    def _preview_done(self, preview) -> None:
        self.preview = preview
        self._end_progress()
        self.result.pack(fill="x", before=self.history)
        self.render_items()

    # Table ----------------------------------------------------------------------------------------------

    def _names(self) -> dict[str, str]:
        return {space.space_id: space.display_name for space in self._planner_spaces()}

    def visible_items(self) -> list:
        if self.preview is None:
            return []
        wanted = next((key for key, label in FILTERS if label == self.filter.get()), "all")
        tests = {
            "all": lambda item: True, "new": lambda item: item.state == NEW,
            "exists": lambda item: item.state == EXISTS,
            "review": lambda item: item.state in (CONFLICT, PATH_REVIEW),
            "sensitive": lambda item: bool(item.sensitive),
            "blocked": lambda item: item.state in BLOCKED or item.state == BATCH_DUPLICATE,
        }
        return [item for item in self.preview.items if tests[wanted](item)]

    def render_items(self) -> None:
        preview = self.preview
        if preview is None:
            return
        names = self._names()
        selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for item in self.visible_items():
            if item.said_at:
                when = f"Said {item.said_at}"
            elif item.claimed_date:
                when = f"{item.claimed_date} (unconfirmed)"
            else:
                when = "Unknown"
            iid = str(item.key)
            self.tree.insert("", "end", iid=iid, values=(
                "☑" if item.checked else "☐", STATE_LABELS[item.state], when, short(item.display_content, 140),
                names.get(item.destination or "", "Choose…"),
                ", ".join(SENSITIVE_LABELS[key] for key in item.sensitive)))
            if iid in selection:
                self.tree.selection_add(iid)
        summary = preview.summary()
        self.summary.configure(text=(
            f"New {summary['new']} · Already there {summary['exists']} · To review "
            f"{summary['conflict'] + summary['path_review']} · Sensitive {summary['sensitive']} · Blocked "
            f"{summary['blocked']} · Source notes {summary['source_notes']} · Unreadable lines {summary['unreadable']}"))
        if preview.same_date_warning:
            self.date_warning.configure(text=(
                "These dates may be when the list was exported, not when you said it: "
                + ", ".join(preview.same_date_warning) + ". They are left out of \"Confirm dates\" unless you "
                "choose them yourself."))
            self.date_warning.pack(fill="x", pady=(theme_px(self, SPACE_XS), 0), after=self.summary)
        else:
            self.date_warning.pack_forget()
        self.notes.delete(*self.notes.get_children())
        for number, text in preview.source_notes:
            self.notes.insert("", "end", iid=f"n{number}", values=(number, text))
        if preview.source_notes:
            self.notes_box.pack(fill="x", pady=(theme_px(self, SPACE_S), 0), after=self.summary)
        else:
            self.notes_box.pack_forget()
        self.unreadable_list.delete(*self.unreadable_list.get_children())
        for number, text in preview.unreadable:
            self.unreadable_list.insert("", "end", iid=f"u{number}", values=(number, text))
        if preview.unreadable:
            self.unreadable_toggle.set_text(f"Show {plural(len(preview.unreadable), 'line')} BIO CE couldn't read")
            self.unreadable_toggle.pack(anchor="w", pady=(theme_px(self, SPACE_XS), 0), after=self.detail)
        else:
            self.unreadable_toggle.pack_forget()
            self.unreadable_list.pack_forget()
        self._sync_buttons()

    def toggle_unreadable(self) -> None:
        if self.unreadable_list.winfo_manager():
            self.unreadable_list.pack_forget()
        else:
            self.unreadable_list.pack(fill="x", after=self.unreadable_toggle)

    def selected_keys(self) -> list[int]:
        return [int(iid) for iid in self.tree.selection()]

    def _clicked(self, event) -> None:
        if self.tree.identify_column(event.x) == "#1":
            row = self.tree.identify_row(event.y)
            if row:
                self.toggle([int(row)])

    def toggle_selected(self) -> str:
        self.toggle(self.selected_keys())
        return "break"

    def toggle(self, keys: list[int]) -> None:
        if self.preview is None or not keys:
            return
        for key in keys:
            item = self.preview.by_key(key)
            self.planner.set_checked(self.preview, [key], not item.checked)
        self.render_items()

    def check_visible(self, checked: bool) -> None:
        if self.preview is None:
            return
        self.planner.set_checked(self.preview, [item.key for item in self.visible_items()], checked)
        self.render_items()

    def destination_for_selected(self) -> None:
        keys = self.selected_keys()
        if self.preview is None or not keys:
            self.app.notify("info", "Select one or more entries first.")
            return
        details = {"general": GENERAL_NOTE, "personal": "Hosts see it only with your permission."}
        choice = self.app.ask_choice(
            title=f"Destination for {plural(len(keys), 'entry', 'entries')}",
            message="Already-there and conflict checks run again for the new space.",
            choices=[(space.space_id, space.display_name, details.get(space.space_id, "Project space"))
                     for space in self._planner_spaces()],
            confirm_text="Change")
        if choice:
            self.planner.set_destination(self.preview, keys, choice)
            self.render_items()

    def confirm_dates_selected(self, keys: list[int] | None = None) -> int:
        """12.1: confirmed dates become "said on". The selected entries, or all that are offered when none is."""
        if self.preview is None:
            return 0
        keys = keys if keys is not None else self.selected_keys() or self.planner.bulk_confirmable(self.preview)
        dated = [key for key in keys if self.preview.by_key(key).claimed_date]
        if not dated:
            self.app.notify("info", "None of these entries has a date to confirm.")
            return 0
        if not self.app.confirm(
            title=f"Confirm {plural(len(dated), 'date')}?",
            message="Dates an AI wrote may not be when you said it. Confirm only dates you know are right.",
            points=("Confirmed dates are shown as \"said on\" and used in exports.",),
            confirm_text="Confirm dates",
        ):
            return 0
        count = self.planner.confirm_dates(self.preview, dated,
                                           how="preview-item" if len(dated) == 1 else "preview-bulk")
        self.render_items()
        return count

    def edit_selected(self) -> None:
        keys = self.selected_keys()
        if self.preview is None or len(keys) != 1:
            self.app.notify("info", "Select one entry to edit.")
            return
        item = self.preview.by_key(keys[0])
        answer = EntryEditDialog(self.app.root, self.theme, content=item.content, said_at=item.said_at or "",
                                 reasons="; ".join(item.reasons)).ask()
        if answer is None:
            return
        content, said_at = answer
        self.planner.edit(self.preview, item.key, content)
        try:
            self.planner.set_date(self.preview, item.key, said_at)
        except ValueError as exc:
            self.app.notify("warning", str(exc), title="Date not changed")
        self.render_items()

    def entry_to_note(self) -> None:
        keys = self.selected_keys()
        if self.preview is None or not keys:
            return
        for key in keys:
            self.preview.to_note(key)
        self.planner.recompute(self.preview, set())
        self.render_items()

    def note_to_entry(self, line_no: int | None = None) -> None:
        if self.preview is None:
            return
        if line_no is None:
            chosen = self.notes.selection() or self.unreadable_list.selection()
            if not chosen:
                self.app.notify("info", "Select a line first.")
                return
            line_no = int(chosen[0][1:])
        key = self.preview.from_note(line_no)
        self.planner.recompute(self.preview, {key})
        self.render_items()

    def _show_detail(self) -> None:
        keys = self.selected_keys()
        if self.preview is None or len(keys) != 1:
            self.detail.configure(text="")
            return
        item = self.preview.by_key(keys[0])
        parts = list(item.reasons)
        if item.match_title:
            parts.append(f"Existing memory: “{short(item.match_title, 60)}”")
        if item.project_hint:
            parts.append(f"Mentions {item.project_hint}: move it to that project space?")
        if item.destination == "general":
            parts.append("General: shared with every connected host")
        if item.section:
            parts.append(f"Section: {item.section}")
        self.detail.configure(text=" · ".join(parts))

    # Import ---------------------------------------------------------------------------------------------

    def import_label(self) -> str:
        if self.preview is None:
            return "Import"
        counts = self.preview.counts_by_space(self._names())
        total = sum(counts.values())
        if not total:
            return "Import"
        return f"Import {plural(total, 'entry', 'entries')}: " + ", ".join(
            f"{name} {count}" for name, count in counts.items())

    def _sync_buttons(self) -> None:
        enabled = self.app.allowed("create").enabled
        self.preview_button.set_enabled(enabled and bool(self.destination_id()) and bool(self.text.get().strip())
                                        and not self.app.tasks.busy)
        ready = self.preview is not None and self.preview.ready()
        self.import_button.set_text(self.import_label())
        self.import_button.set_enabled(enabled and ready and not self.app.tasks.busy)

    def do_import(self) -> None:
        preview, control = self.preview, self.control
        if preview is None or control is None or not preview.ready() or not self.app.require_action("create"):
            return
        names = self._names()
        general = sum(1 for item in preview.selected() if item.destination == "general")
        points = [f"{name}: {plural(count, 'entry', 'entries')}"
                  for name, count in preview.counts_by_space(names).items()]
        if general:
            points.append(GENERAL_NOTE)
        if not self.app.confirm(
            title="Import these entries?",
            message="New entries go to each space's inbox, where you keep or discard them. Entries that may "
                    "conflict with a memory you have go to your review queue. Nothing is overwritten.",
            points=points, confirm_text="Import"):
            return
        service = self.app.service.import_service(control, self._planner_spaces())
        self.import_button.set_enabled(False)
        self.app.tasks.submit(lambda: service.commit(preview), self._imported,
                              lambda exc: self._import_failed(exc))

    def _imported(self, result) -> None:
        self.app.data_changed()
        self.app.find_suggestions(batch_id=result.batch_id, quiet=True)
        self.render_history()
        if result.status == "partial":
            self.app.notify("warning", f"Only part of the import was saved ({result.to_inbox} to the inbox). Use "
                            "Retry in Recent imports, or Undo.", title="Import interrupted")
        else:
            self.app.notify("success", f"Imported {plural(result.to_inbox, 'entry', 'entries')} to the inbox"
                            + (f" and sent {result.to_review} to review" if result.to_review else "") + ".",
                            title="Imported", action=("Open inbox", lambda: self.app.show_page("inbox")))
        self.preview = None
        self.result.pack_forget()
        self.text.set("")
        self._sync_buttons()

    def _import_failed(self, error: BaseException) -> None:
        self._sync_buttons()
        self.app.notify("error", str(error) if isinstance(error, ImportRejected) else
                        "BIO CE couldn't import. Nothing more was changed.", title="Import failed")

    # History --------------------------------------------------------------------------------------------

    def render_history(self) -> None:
        theme, c = self.theme, self.colors
        for child in self.history_rows.winfo_children():
            child.destroy()
        self.batch_rows = {}
        control = self.control
        try:
            batches = control.import_batches(limit=20) if control is not None else ()
        except Exception:  # noqa: BLE001
            batches = ()
        if not batches:
            tk.Label(self.history_rows, text="No imports yet.", font=theme.font("caption"), background=c.surface,
                     foreground=c.text_muted, anchor="w").pack(fill="x")
            return
        for batch in batches:
            row = tk.Frame(self.history_rows, background=c.surface)
            row.pack(fill="x", pady=(0, theme.px(SPACE_XS)))
            counts = batch["counts"]
            text = (f"{format_timestamp(batch['created_at'])} · {batch['source']} · "
                    f"{plural(int(counts.get('inbox', 0)), 'entry', 'entries')} to the inbox, "
                    f"{int(counts.get('review', 0))} to review")
            tk.Label(row, text=text, font=theme.font("body"), background=c.surface, foreground=c.text_secondary,
                     anchor="w").pack(side="left")
            status = {"complete": ("Done", "success"), "partial": ("Partial", "warning"),
                      "undone": ("Undone", "neutral")}[batch["status"]]
            Pill(row, theme, *status).pack(side="left", padx=(theme.px(SPACE_S), 0))
            if batch["status"] != "undone":
                Button(row, theme, "Undo import…", variant="link",
                       command=lambda b=batch["batch_id"]: self.undo_batch(b)).pack(side="right")
                Button(row, theme, "Review and keep…", variant="link",
                       command=lambda b=batch["batch_id"]: self.review_and_keep(b)).pack(side="right")
            self.batch_rows[batch["batch_id"]] = row

    def review_and_keep(self, batch_id: str) -> int:
        """Rule (c): suggest keeping every entry of this import that is still in the inbox, then show them."""
        control = self.control
        if control is None or not self.app.require_action("review"):
            return 0
        try:
            added = self.app.service.curation(control, self._planner_spaces()).promote_batch(batch_id)
        except Exception:  # noqa: BLE001 - shown to the user
            self.app.notify("error", "BIO CE couldn't prepare the suggestions.", title="Suggestions")
            return 0
        self.app.refresh_badges()
        self.app.show_page("suggestions")
        self.app.suggestions.show_batch(batch_id)
        return added

    def undo_batch(self, batch_id: str) -> dict | None:
        control = self.control
        if control is None or not self.app.require_action("create"):
            return None
        if not self.app.confirm(
            title="Undo this import?",
            message="Entries from this import that are still in the inbox are deleted. Its reviews that are still "
                    "waiting are closed.",
            points=("Entries you already moved to your memories stay. BIO CE tells you how many.",
                    "The deleted entries' text is overwritten in the database file as far as BIO CE can; older "
                    "backups still contain them."),
            confirm_text="Undo import", danger=True):
            return None
        service = self.app.service.import_service(control, self._planner_spaces())
        try:
            outcome = service.undo(batch_id)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", str(exc) or "BIO CE couldn't undo this import.", title="Not undone")
            return None
        self.app.data_changed()
        self.render_history()
        kept = outcome["kept"]
        self.app.notify("success", f"Removed {plural(outcome['removed'], 'entry', 'entries')} from the inbox"
                        + (f"; {plural(kept, 'entry', 'entries')} you already sorted stay" if kept else "")
                        + (f"; closed {plural(outcome['reviews_closed'], 'review')}" if outcome["reviews_closed"]
                           else "") + ".", title="Import undone")
        return outcome


def theme_px(page: Page, value: int) -> int:
    return page.theme.px(value)


__all__ = ["ImportPage", "PERSONAL_CHOICE", "GENERAL_NOTE"]
