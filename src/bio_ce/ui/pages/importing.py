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
    EMPTY,
    EXISTS,
    INSTRUCTION,
    NEW,
    PATH_REVIEW,
    SECRET,
    SENSITIVE_LABELS,
    STATE_LABELS,
    TOO_LONG,
    ImportCancelled,
    ImportRejected,
    parse_date,
    parse_text,
    read_import_file,
)
from bio_ce.ui.dialogs import Dialog, EntryEditDialog
from bio_ce.ui.format import format_timestamp, preview as short
from bio_ce.ui.hub.common import space_label
from bio_ce.ui.hub.data import INBOX, SUGGESTIONS
from bio_ce.ui.i18n import t
from bio_ce.ui.service_text import say
from bio_ce.ui.pages import Page
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.tree_text import ElidedColumn, RowTooltip
from bio_ce.ui.widgets import (
    AutoScrollbar,
    Button,
    Card,
    Field,
    FlowFrame,
    Pill,
    fit_tree_columns,
    ScrollFrame,
    TextArea,
    WrapLabel,
    section_label,
)

def personal_choice() -> str:
    """"개인" as on every screen (rc3); the recommendation is the note below the box when it is chosen."""
    return t("space.personal")


def general_note() -> str:
    return t("import.general_note")


def source_labels() -> tuple[tuple[str, str], ...]:
    return (("chatgpt", "ChatGPT"), ("claude", "Claude"), ("other", t("import.source.other")))


def filters() -> tuple[tuple[str, str], ...]:
    return (("all", t("import.filter.all")), ("new", t("import.filter.new")), ("exists", t("import.filter.exists")),
            ("review", t("import.filter.review")), ("sensitive", t("import.filter.sensitive")),
            ("blocked", t("import.filter.blocked")))


def state_label(state: str) -> str:
    """The preview's STATE cell in the app's language; a state this screen doesn't know keeps the importer's label."""
    labels = {
        NEW: t("import.state.new"), EXISTS: t("import.state.exists"), CONFLICT: t("import.state.conflict"),
        BATCH_DUPLICATE: t("import.state.batch_duplicate"), SECRET: t("import.state.secret"),
        INSTRUCTION: t("import.state.instruction"), TOO_LONG: t("import.state.too_long"),
        PATH_REVIEW: t("import.state.path_review"), EMPTY: t("import.state.empty"),
    }
    return labels.get(state) or STATE_LABELS[state]


def sensitive_label(key: str) -> str:
    """A sensitive kind in the app's language; one this screen doesn't know keeps the importer's label."""
    labels = {
        "health": t("import.sensitive.health"), "military": t("import.sensitive.military"),
        "school": t("import.sensitive.school"), "family": t("import.sensitive.family"),
        "other": t("import.sensitive.other"),
    }
    return labels.get(key) or SENSITIVE_LABELS[key]


class ImportPage(Page):
    key = "import"
    nav_key = "memories"

    @property
    def title(self) -> str:  # type: ignore[override]
        return t("import.title")

    @property
    def subtitle(self) -> str:  # type: ignore[override]
        return t("import.subtitle")

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        self.preview = None
        self.planner = None
        self.encoding = "text"
        self._cancel = threading.Event()
        self._progress = [0, 0]
        self._destinations: list[tuple[str, str]] = []
        Button(self.actions, theme, t("import.back"), icon="back", variant="subtle",
               command=lambda: app.open_state(INBOX)).pack(side="right")
        scroll = ScrollFrame(self, theme)
        scroll.pack(fill="both", expand=True)
        body = scroll.body

        form = Card(body, theme, padding=SPACE_L)
        form.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        section_label(form.body, theme, t("import.what")).pack(fill="x")
        WrapLabel(form.body, t("import.what_note"), font=theme.font("caption"), foreground=c.text_secondary).pack(
            fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_S)))
        self.text = TextArea(form.body, theme, font="body")
        self.text.text.configure(height=8)
        self.text.pack(fill="x")
        row = tk.Frame(form.body, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        Button(row, theme, t("import.open_file"), command=self.open_file).pack(side="left")
        self.encoding_label = tk.Label(row, text="", font=theme.font("caption"), background=c.surface,
                                       foreground=c.text_muted)
        self.encoding_label.pack(side="left", padx=(theme.px(SPACE_S), 0))

        choose = tk.Frame(form.body, background=c.surface)
        choose.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        tk.Label(choose, text=t("import.source"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, width=12, anchor="w").pack(side="left")
        self.source = tk.StringVar(master=self, value="other")
        for key, label in source_labels():
            tk.Radiobutton(choose, text=label, value=key, variable=self.source, font=theme.font("body"),
                           background=c.surface, foreground=c.text, activebackground=c.surface,
                           activeforeground=c.text, selectcolor=c.surface_alt, highlightthickness=0,
                           borderwidth=0).pack(side="left", padx=(0, theme.px(SPACE_M)))
        where = tk.Frame(form.body, background=c.surface)
        where.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        tk.Label(where, text=t("import.destination"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, width=12, anchor="w").pack(side="left")
        self.destination = tk.StringVar(master=self, value="")
        # Narrow request, then as wide as the row allows (a 60-character request was cut at 150% scaling).
        self.destination_picker = ttk.Combobox(where, textvariable=self.destination, state="readonly", width=24,
                                               style="BIO.TCombobox", font=theme.font("body"))
        self.destination_picker.pack(side="left", fill="x", expand=True)
        self.destination_picker.bind("<<ComboboxSelected>>", lambda _e: self._destination_chosen())
        self.destination_note = WrapLabel(form.body, "", font=theme.font("caption"), foreground=c.text_secondary)
        self.destination_note.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.turn_on_button = Button(form.body, theme, t("import.turn_on_personal"), variant="link",
                                     command=self.turn_on_personal)
        actions = tk.Frame(form.body, background=c.surface)
        actions.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.preview_button = Button(actions, theme, t("import.preview"), variant="primary",
                                     command=self.start_preview)
        self.preview_button.pack(side="left")
        self.cancel_button = Button(actions, theme, t("common.cancel"), variant="subtle", command=self.cancel_preview)
        self.progress = ttk.Progressbar(actions, mode="determinate", style="BIO.Horizontal.TProgressbar",
                                        length=theme.px(220))
        self.app.gate(self.preview_button, "create")

        self.result = Card(body, theme, padding=SPACE_L)
        section_label(self.result.body, theme, t("import.check")).pack(fill="x")
        self.summary = WrapLabel(self.result.body, "", font=theme.font("body_strong"), foreground=c.text)
        self.summary.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.date_warning = WrapLabel(self.result.body, "", font=theme.font("body"), foreground=c.warning)
        self.notes_box = tk.Frame(self.result.body, background=c.surface_alt, highlightthickness=1,
                                  highlightbackground=c.border)
        tk.Label(self.notes_box, text=t("import.notes_title"), font=theme.font("caption_strong"),
                 background=c.surface_alt, foreground=c.text_muted, anchor="w").pack(
            fill="x", padx=theme.px(SPACE_M), pady=(theme.px(SPACE_S), 0))
        self.notes = ttk.Treeview(self.notes_box, columns=("line", "text"), show="headings", height=3,
                                  selectmode="browse", style="BIO.Treeview")
        self.notes.heading("line", text=t("import.column.line"), anchor="w")
        self.notes.heading("text", text=t("import.column.text"), anchor="w")
        self.notes.column("line", width=theme.px(56), stretch=False)
        self.notes.column("text", width=theme.px(600), stretch=True)
        fit_tree_columns(self.notes, theme, "text", floor=120)
        self.notes.pack(fill="x", padx=theme.px(SPACE_M), pady=theme.px(SPACE_XS))
        Button(self.notes_box, theme, t("import.note_to_entry"), variant="link",
               command=self.note_to_entry).pack(anchor="w", padx=theme.px(SPACE_M), pady=(0, theme.px(SPACE_S)))

        tools = FlowFrame(self.result.body, gap=theme.px(SPACE_S), background=c.surface)
        tools.pack(fill="x", pady=(theme.px(SPACE_M), theme.px(SPACE_XS)))
        self.filters = filters()
        self.filter = tk.StringVar(master=self, value=self.filters[0][1])
        filter_box = ttk.Combobox(tools, textvariable=self.filter, state="readonly", width=18, style="BIO.TCombobox",
                                  values=[label for _key, label in self.filters], font=theme.font("body"))
        tools.add(filter_box)
        filter_box.bind("<<ComboboxSelected>>", lambda _e: self.render_items())
        for text, command in ((t("import.check_visible"), lambda: self.check_visible(True)),
                              (t("import.uncheck_visible"), lambda: self.check_visible(False)),
                              (t("import.destination_button"), self.destination_for_selected),
                              (t("import.confirm_dates_button"), self.confirm_dates_selected),
                              (t("import.set_date.button"), self.set_date_selected),
                              (t("import.edit_button"), self.edit_selected),
                              (t("import.not_a_memory"), self.entry_to_note)):
            button = Button(tools, theme, text, variant="link", command=command)
            tools.add(button)
            if command == self.set_date_selected:
                self.set_date_button = button
        area = tk.Frame(self.result.body, background=c.surface)
        area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(area, columns=("check", "state", "date", "text", "space", "sensitive"),
                                 show="headings", selectmode="extended", height=14, style="BIO.Treeview")
        # Fixed columns are compact; TEXT takes whatever width is left (at least 150 px), so the SENSITIVE column on
        # the right is never off the edge (GUI check I6). A horizontal scroll bar appears only if even that can't fit.
        self._fixed_columns = {"check": 30, "state": 150, "date": 150, "space": 100, "sensitive": 110}
        for column, label in (("check", ""), ("state", t("import.column.state")), ("date", t("import.column.date")),
                              ("text", t("import.column.text")), ("space", t("import.column.destination")),
                              ("sensitive", t("import.column.sensitive"))):
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
        self.fit_contents = fit_tree_columns(self.tree, theme, "text", floor=120)
        # K3: TEXT ends in "…" when it doesn't fit, and the row's tooltip has the whole entry.
        self.text_cells = ElidedColumn(self.tree, theme, "text")
        self.text_tip = RowTooltip(self.tree, theme, self._row_text)
        self.tree.bind("<ButtonRelease-1>", self._clicked)
        self.tree.bind("<space>", lambda _e: self.toggle_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_detail())
        self.detail = WrapLabel(self.result.body, "", font=theme.font("caption"), foreground=c.text_secondary)
        self.detail.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.unreadable_toggle = Button(self.result.body, theme, "", variant="link", command=self.toggle_unreadable)
        self.unreadable_list = ttk.Treeview(self.result.body, columns=("line", "text"), show="headings", height=3,
                                            selectmode="browse", style="BIO.Treeview")
        self.unreadable_list.heading("line", text=t("import.column.line"), anchor="w")
        self.unreadable_list.heading("text", text=t("import.column.unreadable"), anchor="w")
        self.unreadable_list.column("line", width=theme.px(56), stretch=False)
        footer = tk.Frame(self.result.body, background=c.surface)
        footer.pack(fill="x", side="bottom", pady=(theme.px(SPACE_M), 0))
        self.import_button = Button(footer, theme, t("import.button"), variant="primary", command=self.do_import)
        self.import_button.pack(side="left")
        self.app.gate(self.import_button, "create")

        self.history = Card(body, theme, padding=SPACE_L)
        self.history.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        section_label(self.history.body, theme, t("import.recent")).pack(fill="x")
        WrapLabel(self.history.body, t("import.recent_note"), font=theme.font("caption"),
                  foreground=c.text_secondary).pack(fill="x")
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
        self._destinations = [("personal", personal_choice()), ("general", t("space.general"))]
        self._destinations += [(space.space_id, space_label(space)) for space in projects]
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
        self.encoding_label.configure(text="" if encoding == "text" else t("import.read_as", encoding=encoding))
        self._sync_buttons()

    def open_file(self) -> None:
        path = self.app.ask_open_path(title=t("import.open_title"),
                                      filetypes=((t("import.open_types"), "*.md *.txt *.markdown"),))
        if not path:
            return
        try:
            text, encoding = read_import_file(path)
        except (ImportRejected, OSError) as exc:
            self.app.notify("error", say(exc) or t("import.open_failed"), title=t("import.open_failed_title"))
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
            self.destination_note.configure(text=t("import.personal_off"))
            self.turn_on_button.pack(anchor="w", after=self.destination_note)
            self.destination.set("")
            self._sync_buttons()
            return False
        notes = {"general": general_note(), "personal": t("import.personal_note")}
        self.destination_note.configure(text=notes.get(chosen, ""))
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
            self.app.notify("info", t("import.cancelled"), title=t("import.cancelled_title"))
            return
        self.app.notify("error", say(error) if isinstance(error, (ImportRejected, ValueError)) else
                        t("import.preview_failed"), title=t("import.preview_failed_title"))

    def _preview_done(self, preview) -> None:
        self.preview = preview
        self._end_progress()
        self.result.pack(fill="x", before=self.history)
        self.render_items()

    # Table ----------------------------------------------------------------------------------------------

    def _names(self) -> dict[str, str]:
        return {space.space_id: space_label(space) for space in self._planner_spaces()}

    def visible_items(self) -> list:
        if self.preview is None:
            return []
        wanted = next((key for key, label in self.filters if label == self.filter.get()), "all")
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
        self.text_cells.clear()
        for item in self.visible_items():
            if item.said_at:
                when = t("import.when.said", date=item.said_at)
            elif item.claimed_date:
                when = t("import.when.unconfirmed", date=item.claimed_date)
            else:
                when = t("import.when.unknown")
            iid = str(item.key)
            self.text_cells.set(iid, item.display_content)
            self.tree.insert("", "end", iid=iid, values=(
                "☑" if item.checked else "☐", state_label(item.state), when, self.text_cells.text(iid),
                names.get(item.destination or "", t("import.choose")),
                ", ".join(sensitive_label(key) for key in item.sensitive)))
            if iid in selection:
                self.tree.selection_add(iid)
        self.fit_contents(("state", "date", "space", "sensitive"))
        self.text_cells.fit()
        summary = preview.summary()
        self.summary.configure(text=t(
            "import.summary", new=summary["new"], exists=summary["exists"],
            review=summary["conflict"] + summary["path_review"], sensitive=summary["sensitive"],
            blocked=summary["blocked"], notes=summary["source_notes"], unreadable=summary["unreadable"]))
        if preview.same_date_warning:
            self.date_warning.configure(text=t("import.date_warning", dates=", ".join(preview.same_date_warning)))
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
            self.unreadable_toggle.set_text(t("import.show_unreadable", count=len(preview.unreadable)))
            self.unreadable_toggle.pack(anchor="w", pady=(theme_px(self, SPACE_XS), 0), after=self.detail)
        else:
            self.unreadable_toggle.pack_forget()
            self.unreadable_list.pack_forget()
        self._sync_buttons()

    def _row_text(self, iid: str) -> str:
        """The whole entry of a preview row, for its tooltip."""
        if self.preview is None or not iid.isdigit():
            return ""
        try:
            return self.preview.by_key(int(iid)).display_content
        except (KeyError, LookupError, ValueError):
            return ""

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
            self.app.notify("info", t("import.set_date.select_first"))
            return
        details = {"general": general_note(), "personal": t("import.choice.personal")}
        choice = self.app.ask_choice(
            title=t("import.choice.title", count=len(keys)),
            message=t("import.choice.message"),
            choices=[(space.space_id, space_label(space), details.get(space.space_id, t("import.choice.project")))
                     for space in self._planner_spaces()],
            confirm_text=t("import.choice.confirm"))
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
            self.app.notify("info", t("import.dates.none"))
            return 0
        if not self.app.confirm(
            title=t("import.dates.title", count=len(dated)),
            message=t("import.dates.message"),
            points=(t("import.dates.point"),),
            confirm_text=t("import.dates.confirm"),
        ):
            return 0
        count = self.planner.confirm_dates(self.preview, dated,
                                           how="preview-item" if len(dated) == 1 else "preview-bulk")
        self.render_items()
        return count

    def set_date_selected(self) -> int:
        """K5: put a date the user knows on the selected entries, e.g. after Edit cleared the source date. The same
        rules as the date in Edit: a date typed here counts as confirmed ("said on")."""
        keys = self.selected_keys()
        if self.preview is None or not keys:
            self.app.notify("info", t("import.set_date.select_first"))
            return 0
        dates = {self.preview.by_key(key).said_at or "" for key in keys}
        answer = SetDateDialog(self.app.root, self.theme, count=len(keys),
                               value=dates.pop() if len(dates) == 1 else "").ask()
        if answer is None:
            return 0
        changed = 0
        for key in keys:
            try:
                self.planner.set_date(self.preview, key, answer)
            except ValueError:
                self.app.notify("warning", t("import.set_date.invalid"), title=t("import.set_date.not_changed"))
                break
            changed += 1
        self.render_items()
        return changed

    def edit_selected(self) -> None:
        keys = self.selected_keys()
        if self.preview is None or len(keys) != 1:
            self.app.notify("info", t("import.edit.select_one"))
            return
        item = self.preview.by_key(keys[0])
        before_said, before_how = item.said_at or "", item.said_at_confirmed
        answer = EntryEditDialog(self.app.root, self.theme, content=item.content, said_at=before_said,
                                 reasons="; ".join(say(reason) for reason in item.reasons),
                                 source_date=item.claimed_date or "").ask()
        if answer is None:
            return
        content, said_at = answer
        self.planner.edit(self.preview, item.key, content)
        # The date field came filled in: unchanged, it isn't a date the user typed. If the edit cleared a "said" date
        # that came from the source date, don't write it back as typed.
        if not (said_at == before_said and before_how != "edited" and item.said_at is None):
            try:
                self.planner.set_date(self.preview, item.key, said_at)
            except ValueError as exc:
                self.app.notify("warning", say(exc), title=t("import.set_date.not_changed"))
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
                self.app.notify("info", t("import.line.select_first"))
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
        parts = [say(reason) for reason in item.reasons]
        if item.match_title:
            parts.append(t("import.detail.existing", title=short(item.match_title, 60)))
        if item.project_hint:
            parts.append(t("import.detail.mentions", project=item.project_hint))
        if item.destination == "general":
            parts.append(t("import.detail.general"))
        if item.section:
            parts.append(t("import.detail.section", section=item.section))
        self.detail.configure(text=" · ".join(parts))

    # Import ---------------------------------------------------------------------------------------------

    def import_label(self) -> str:
        if self.preview is None:
            return t("import.button")
        counts = self.preview.counts_by_space(self._names())
        total = sum(counts.values())
        if not total:
            return t("import.button")
        return t("import.button_count", count=total,
                 spaces=", ".join(f"{name} {count}" for name, count in counts.items()))

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
        points = [t("import.confirm.point", space=name, count=count)
                  for name, count in preview.counts_by_space(names).items()]
        if general:
            points.append(general_note())
        if not self.app.confirm(
            title=t("import.confirm.title"),
            message=t("import.confirm.message"),
            points=points, confirm_text=t("import.button")):
            return
        service = self.app.service.import_service(control, self._planner_spaces())
        self.import_button.set_enabled(False)
        self.app.tasks.submit(lambda: service.commit(preview), self._imported,
                              lambda exc: self._import_failed(exc))

    def _imported(self, result) -> None:
        self.app.data_changed()
        suggested = self.app.find_suggestions(batch_id=result.batch_id, quiet=True)
        self.render_history()
        if result.status == "partial":
            # There is no "Retry" button (inventory §13 item 2): previewing the same text again shows what was saved
            # as already there, so importing again adds only the rest.
            self.app.notify("warning", t("import.partial", count=result.to_inbox), title=t("import.partial_title"),
                            action=(t("hub.open_inbox"), lambda: self.app.open_state(INBOX)))
        else:
            message = (t("import.done_review", count=result.to_inbox, review=result.to_review) if result.to_review
                       else t("import.done", count=result.to_inbox))
            if suggested:
                message += " " + t("import.suggested", count=suggested)
            self.app.notify("success", message, title=t("import.done_title"),
                            action=(t("hub.open_inbox"), lambda: self.app.open_state(INBOX)))
        self.preview = None
        self.result.pack_forget()
        self.text.set("")
        self._sync_buttons()

    def _import_failed(self, error: BaseException) -> None:
        self._sync_buttons()
        self.app.notify("error", say(error) if isinstance(error, ImportRejected) else
                        t("import.failed"), title=t("import.failed_title"))

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
            tk.Label(self.history_rows, text=t("import.recent_none"), font=theme.font("caption"),
                     background=c.surface, foreground=c.text_muted, anchor="w").pack(fill="x")
            return
        for batch in batches:
            row = tk.Frame(self.history_rows, background=c.surface)
            row.pack(fill="x", pady=(0, theme.px(SPACE_XS)))
            counts = batch["counts"]
            text = t("import.recent_row", when=format_timestamp(batch["created_at"]), source=batch["source"],
                     count=int(counts.get("inbox", 0)), review=int(counts.get("review", 0)))
            tk.Label(row, text=text, font=theme.font("body"), background=c.surface, foreground=c.text_secondary,
                     anchor="w").pack(side="left")
            status = {"complete": (t("import.status.complete"), "success"),
                      "partial": (t("import.status.partial"), "warning"),
                      "undone": (t("import.status.undone"), "neutral")}[batch["status"]]
            Pill(row, theme, *status).pack(side="left", padx=(theme.px(SPACE_S), 0))
            if batch["status"] != "undone":
                Button(row, theme, t("import.undo_button"), variant="link",
                       command=lambda b=batch["batch_id"]: self.undo_batch(b)).pack(side="right")
                Button(row, theme, t("import.review_keep_button"), variant="link",
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
            self.app.notify("error", t("import.review_keep_failed"), title=t("import.review_keep_failed_title"))
            return 0
        self.app.refresh_badges()
        self.app.open_state(SUGGESTIONS, batch_id=batch_id)
        return added

    def undo_batch(self, batch_id: str) -> dict | None:
        control = self.control
        if control is None or not self.app.require_action("create"):
            return None
        if not self.app.confirm(
            title=t("import.undo.title"),
            message=t("import.undo.message"),
            points=(t("import.undo.point_kept"), t("import.undo.point_overwrite")),
            confirm_text=t("import.undo.confirm"), danger=True):
            return None
        service = self.app.service.import_service(control, self._planner_spaces())
        try:
            outcome = service.undo(batch_id)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", say(exc) or t("import.undo.failed"), title=t("import.undo.failed_title"))
            return None
        self.app.data_changed()
        self.render_history()
        kept = outcome["kept"]
        self.app.notify("success", t("import.undo.removed", count=outcome["removed"])
                        + (t("import.undo.kept", count=kept) if kept else "")
                        + (t("import.undo.closed", count=outcome["reviews_closed"]) if outcome["reviews_closed"]
                           else "") + ".", title=t("import.undo.done_title"))
        return outcome


class SetDateDialog(Dialog):
    """K5: one date for the selected preview entries. It accepts what the Edit window's date accepts (the importer's
    ``parse_date``, which the planner's ``set_date`` uses); empty is refused here, since clearing is not the point."""

    def __init__(self, parent: tk.Misc, theme, *, count: int, value: str = "") -> None:
        super().__init__(parent, theme, t("import.set_date.title", count=count))
        c = theme.colors
        tk.Label(self.content, text=t("import.set_date.title", count=count), font=theme.font("title"),
                 background=c.surface, foreground=c.text, anchor="w").pack(fill="x")
        WrapLabel(self.content, t("import.set_date.note"), font=theme.font("caption"), wraplength=theme.px(380),
                  foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        tk.Label(self.content, text=t("import.set_date.label"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.date = tk.StringVar(master=self, value=value)
        self.field = Field(self.content, theme, textvariable=self.date)
        self.field.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.error = WrapLabel(self.content, t("import.set_date.invalid"), font=theme.font("caption"),
                               wraplength=theme.px(380), foreground=c.danger)
        self.field.entry.bind("<Return>", lambda _event: self._save())
        self.add_button(t("import.set_date.save"), self._save, variant="primary")
        self.add_button(t("common.cancel"), lambda: self.finish(None))
        self.result = None

    def _save(self) -> None:
        value = self.date.get().strip()
        parsed, _precision = parse_date(value) if value else (None, None)
        if parsed is None:
            self.field.set_error(True)
            self.error.pack(fill="x", pady=(self.theme.px(SPACE_XS), 0))
            return
        self.finish(value)

    def ask(self) -> str | None:
        self.present(focus=self.field)
        return self.result  # type: ignore[return-value]


def theme_px(page: Page, value: int) -> int:
    return page.theme.px(value)


__all__ = ["ImportPage", "general_note", "personal_choice", "sensitive_label", "state_label"]
