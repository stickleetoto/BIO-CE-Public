# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Settings: data location, backup and restore, privacy notes, and about."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys
import tkinter as tk

import bio_ce
from bio_ce.inbox import DISCARD_NOTICE
from bio_ce.ui.dialogs import TextViewerDialog
from bio_ce.ui.format import file_size, plural
from bio_ce.engine.presentation import SEPARATE_DATABASES_NOTE, engine_rows
from bio_ce.ui.pages import Page
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import (
    Button,
    Card,
    Field,
    Pill,
    ScrollFrame,
    Tooltip,
    WrapLabel,
    copy_to_clipboard,
    section_label,
)


SHORTCUTS = (
    ("Ctrl+1 – Ctrl+4", "Go to Dashboard, Memories, Connections, Settings"),
    ("Ctrl+N", "Add a memory"),
    ("Ctrl+F", "Search memories"),
    ("Ctrl+S", "Save the memory you are editing"),
    ("Esc", "Leave the editor or close a dialog"),
    ("Ctrl+E", "Edit the selected memory"),
    ("Ctrl+H", "Show revision history"),
    ("Delete", "Retract the selected memory (asks first)"),
    ("F5", "Refresh the current page"),
    ("Tab / Shift+Tab", "Move between controls; Enter or Space activates"),
)

PRIVACY_POINTS = (
    ("shield", "Stored only on this PC",
     "Memories live in a SQLite file in your Windows user profile. BIO CE does not upload or sync them."),
    ("edit", "Nothing is recorded behind your back",
     "BIO CE never records conversations. AI hosts can save memories only after you turn on Auto memory, and "
     "BIO CE refuses secrets and content taken from documents."),
    ("lock", "You control AI access",
     "Hosts are read only unless you turn on Auto memory. Pause or disconnect any host on the Connections page; "
     "uncertain changes and every retraction wait for your review there."),
    ("warning", "No encryption at rest",
     "Anyone who can sign in to your Windows account can read the database and backups. Protect your account."),
    ("retract", "Retraction is not secure erase",
     "Retracted memories disappear from BIO CE and AI hosts, but earlier revisions remain in the database file."),
)


def resource_path(frozen_name: str, source_name: str) -> Path:
    """Locate a file bundled beside the installed app or in the source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / frozen_name
    return Path(__file__).resolve().parents[4] / source_name


def release_channel(version: str) -> str:
    """Name the release stage encoded in a PEP 440 version string."""
    if ".dev" in version or re.search(r"\d(a|b)\d", version):
        return "Developer Preview"
    if re.search(r"\drc\d", version):
        return "Release Candidate"
    return "Release"


def database_size(database: Path) -> int:
    total = 0
    for suffix in ("", "-wal"):
        try:
            total += database.with_name(database.name + suffix).stat().st_size
        except OSError:
            pass
    return total


SWITCHING_DISABLED = ("Choosing another engine is not available in this version of BIO CE. "
                      "Your memories stay in the Community Engine.")
_PILL_KIND = {"success": "success", "neutral": "neutral", "warning": "warning", "error": "danger"}


@dataclass(frozen=True, slots=True)
class EngineRowWidgets:
    engine_id: str
    active: bool
    pill: Pill
    button: Button | None  # None for the engine in use
    frame: tk.Frame


class SettingsPage(Page):
    key = "settings"
    nav_key = "settings"
    title = "Settings"
    subtitle = "Where your data lives and how it is protected"

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        self.viewer: TextViewerDialog | None = None
        self.scroll = ScrollFrame(self, theme, max_width=900)
        self.scroll.pack(fill="both", expand=True)
        body = self.scroll.body

        self._build_engine_card(body)

        storage = self._card(body, "Memory database",
                             "Your memories are stored in this file. Keep it in your user profile so other "
                             "Windows users can't read it.")
        self.path_value = tk.StringVar(master=self, value=str(app.paths.user_database))
        row = tk.Frame(storage, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        Field(row, theme, textvariable=self.path_value, font="mono", readonly=True).pack(side="left", fill="x",
                                                                                        expand=True)
        Button(row, theme, "Open folder", icon="folder", command=app.open_data_folder).pack(
            side="right", padx=(theme.px(SPACE_S), 0))
        Button(row, theme, "", icon="copy", tooltip="Copy path", command=self._copy_path, padx=9).pack(
            side="right", padx=(theme.px(SPACE_S), 0))
        self.storage_stats = tk.Label(storage, font=theme.font("caption"), background=c.surface,
                                      foreground=c.text_muted, anchor="w")
        self.storage_stats.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        WrapLabel(storage, f"Demo data is kept separately in {app.paths.demo_database} and is never mixed into your "
                  "memories.", font=theme.font("caption"), foreground=c.text_muted).pack(
            fill="x", pady=(theme.px(SPACE_XS), 0))

        self._build_spaces_card(body)
        self._build_inbox_card(body)

        backup = self._card(body, "Backup and restore",
                            "A backup is two files: a complete copy of your memories (name.sqlite3) and your "
                            "connection records (name.control.sqlite3). Keep them together. Backups are not "
                            "encrypted, so store them somewhere private and don't share them.")
        backup_row = tk.Frame(backup, background=c.surface)
        backup_row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.backup_button = Button(backup_row, theme, "Create backup…", icon="backup", command=app.backup_database)
        self.backup_button.pack(side="left")
        app.gate(self.backup_button, "backup")
        tk.Frame(backup, height=1, background=c.border).pack(fill="x", pady=theme.px(SPACE_L))
        tk.Label(backup, text="Restore from a backup", font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        WrapLabel(backup, "Restoring replaces all current memories with the backup. BIO CE checks the file first. "
                  "Connections and permissions stay as they are now. Close connected AI hosts before restoring, "
                  "and create a backup of your current memories if you want to keep them.",
                  font=theme.font("body"), foreground=c.text_secondary).pack(
            fill="x", pady=(theme.px(SPACE_XS), 0))
        restore_row = tk.Frame(backup, background=c.surface)
        restore_row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.restore_button = Button(restore_row, theme, "Restore from backup…", icon="restore",
                                     variant="danger_subtle", command=app.restore_database)
        self.restore_button.pack(side="left")
        app.gate(self.restore_button, "restore")

        privacy = self._card(body, "Privacy and security", None)
        for icon, heading, text in PRIVACY_POINTS:
            self._point(privacy, icon, heading, text)
        backup_note = tk.Frame(privacy, background=c.surface)
        backup_note.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self._point(backup_note, "backup", "Connection settings backups",
                    "Connecting or disconnecting a host first copies its MCP settings to your BIO CE folder. The "
                    "copies can include other servers’ settings or environment values. Delete them when you no "
                    "longer need them.")
        Button(privacy, theme, "Open settings backups folder", variant="link", command=app.open_connection_backups,
               anchor="w").pack(anchor="w", padx=(theme.px(30), 0))

        shortcuts = self._card(body, "Keyboard shortcuts", None)
        grid = tk.Frame(shortcuts, background=c.surface)
        grid.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        for index, (keys, action) in enumerate(SHORTCUTS):
            tk.Label(grid, text=keys, font=theme.font("mono"), background=c.surface_alt, foreground=c.text,
                     padx=theme.px(SPACE_S), pady=theme.px(1)).grid(row=index, column=0, sticky="w",
                                                                    pady=theme.px(3))
            tk.Label(grid, text=action, font=theme.font("body"), background=c.surface, foreground=c.text_secondary,
                     anchor="w").grid(row=index, column=1, sticky="w", padx=(theme.px(SPACE_M), 0))

        about = self._card(body, "About BIO CE", None)
        tk.Label(about, text=f"BIO Community Edition {bio_ce.display_version()} · {release_channel(bio_ce.__version__)}",
                 font=theme.font("body"), background=c.surface, foreground=c.text, anchor="w").pack(
            fill="x", pady=(theme.px(SPACE_XS), 0))
        WrapLabel(about, "Copyright 2026 stickleetoto. Licensed under the Apache License 2.0. This build is "
                  "unsigned and provided without warranty.", font=theme.font("caption"),
                  foreground=c.text_muted).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        about_row = tk.Frame(about, background=c.surface)
        about_row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.license_path = resource_path("LICENSE", "LICENSE")
        self.notices_path = resource_path("THIRD_PARTY_NOTICES", "docs/THIRD_PARTY_LICENSES.md")
        self.license_button = Button(about_row, theme, "View license", icon="document",
                                     command=lambda: self.view_file("Apache License 2.0", self.license_path))
        self.license_button.pack(side="left")
        self.notices_button = Button(about_row, theme, "Third-party notices",
                                     command=lambda: self.view_file("Third-party notices", self.notices_path))
        self.notices_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.license_button.set_enabled(self.license_path.is_file())
        self.notices_button.set_enabled(self.notices_path.is_file())
        tk.Frame(body, height=theme.px(SPACE_S), background=c.bg).pack()

    # Spaces --------------------------------------------------------------------------------------

    def _build_spaces_card(self, body: tk.Misc) -> None:
        theme, c = self.theme, self.colors
        card = self._card(body, "Spaces",
                          "General holds your memories as before. A project space keeps one project's memories "
                          "apart. Link a project folder and the session hooks use that space when you work there. "
                          "BIO CE stores only a fingerprint of the folder path and the folder's name.")
        self.spaces_list = tk.Frame(card, background=c.surface)
        self.spaces_list.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        row = tk.Frame(card, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.new_space_button = Button(row, theme, "New project space…", icon="add", command=self.new_space)
        self.new_space_button.pack(side="left")
        self.space_rows: dict[str, tk.Frame] = {}
        self.render_spaces()

    def spaces_control(self):
        return getattr(self.app.connection_manager, "control", None)

    def render_spaces(self) -> None:
        theme, c = self.theme, self.colors
        for child in self.spaces_list.winfo_children():
            child.destroy()
        self.space_rows = {}
        control = self.spaces_control()
        try:
            spaces = control.spaces() if control is not None else ()
            links = control.folder_links() if control is not None else ()
        except Exception:  # noqa: BLE001 - never break Settings because of the control file
            spaces, links = (), ()
        if not spaces:
            WrapLabel(self.spaces_list, "Spaces are unavailable right now.", font=theme.font("caption"),
                      foreground=c.text_muted).pack(fill="x")
            self.new_space_button.set_enabled(False)
            return
        self.new_space_button.set_enabled(True)
        for space in spaces:
            frame = tk.Frame(self.spaces_list, background=c.surface_alt, highlightthickness=1,
                             highlightbackground=c.border)
            frame.pack(fill="x", pady=(0, theme.px(SPACE_S)))
            inner = tk.Frame(frame, background=c.surface_alt)
            inner.pack(fill="x", padx=theme.px(SPACE_M), pady=theme.px(SPACE_S))
            top = tk.Frame(inner, background=c.surface_alt)
            top.pack(fill="x")
            tk.Label(top, text=space.display_name, font=theme.font("body_strong"), background=c.surface_alt,
                     foreground=c.text, anchor="w").pack(side="left")
            folders = [(key, label) for space_id, key, label in links if space_id == space.space_id]
            if space.is_general:
                detail = "Always available. Used when no project space fits."
            else:
                detail = (f"{plural(len(folders), 'linked folder')}" if folders else "No folder linked yet")
                Button(top, theme, "Archive", variant="link",
                       command=lambda item=space: self.archive_space(item)).pack(side="right")
                Button(top, theme, "Rename", variant="link",
                       command=lambda item=space: self.rename_space(item)).pack(side="right")
                Button(top, theme, "Link folder…", variant="link",
                       command=lambda item=space: self.link_folder(item)).pack(side="right")
            tk.Label(inner, text=detail, font=theme.font("caption"), background=c.surface_alt,
                     foreground=c.text_muted, anchor="w").pack(fill="x")
            for key, label in folders:
                line = tk.Frame(inner, background=c.surface_alt)
                line.pack(fill="x", pady=(theme.px(2), 0))
                tk.Label(line, text=f"  {label}", font=theme.font("body"), background=c.surface_alt,
                         foreground=c.text_secondary, anchor="w").pack(side="left")
                Button(line, theme, "Unlink", variant="link",
                       command=lambda item=space, k=key: self.unlink_folder(item, k)).pack(side="right")
            self.space_rows[space.space_id] = frame

    def _space_action(self, title: str, action) -> bool:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", str(exc) or "BIO CE couldn't change the space.", title=title)
            return False
        self.render_spaces()
        return True

    def new_space(self) -> None:
        control = self.spaces_control()
        name = self.app.ask_name(title="New project space", label="Name", confirm_text="Create space",
                                 note="For example the project's name. You can rename it later.")
        if control is None or not name:
            return
        if self._space_action("Space not created", lambda: control.create_space(name)):
            self.app.notify("success", f"Created the space {name!r}. Link its folder so hooks pick it up.",
                            title="Space created")

    def rename_space(self, space) -> None:
        control = self.spaces_control()
        name = self.app.ask_name(title="Rename space", label="Name", value=space.display_name,
                                 confirm_text="Rename",
                                 note="Memories stay in the space; only its name changes.")
        if control is None or not name or name == space.display_name:
            return
        self._space_action("Space not renamed", lambda: control.rename_space(space.space_id, name))

    def archive_space(self, space) -> None:
        control = self.spaces_control()
        if control is None or not self.app.confirm(
            title=f"Archive {space.display_name}?",
            message="AI hosts can no longer read or write this space, and its folder links stop working.",
            quote=space.display_name,
            points=("Its memories stay in your database and in backups.",
                    "Hosts use General for folders that were linked to it."),
            confirm_text="Archive space",
        ):
            return
        self._space_action("Space not archived", lambda: control.archive_space(space.space_id))

    def link_folder(self, space) -> None:
        control = self.spaces_control()
        folder = self.app.ask_folder(title=f"Choose a folder for {space.display_name}")
        if control is None or not folder:
            return
        self._space_action("Folder not linked", lambda: control.link_folder(space.space_id, folder))

    def unlink_folder(self, space, key: str) -> None:
        control = self.spaces_control()
        if control is None:
            return
        self._space_action("Folder not unlinked", lambda: control.unlink_folder(space.space_id, key))

    # Inbox ---------------------------------------------------------------------------------------

    INBOX_FIELDS = (
        ("inbox_expire_days", "Propose discarding after", "days unused (7–365)"),
        ("inbox_wait_days", "Then discard after", "more days unless kept (1–30)"),
        ("file_content_limit", "File text limit", "characters (200–2000)"),
    )

    def _build_inbox_card(self, body: tk.Misc) -> None:
        theme, c = self.theme, self.colors
        card = self._card(body, "Inbox",
                          "Hosts in collect mode save to the inbox. Unused items are proposed for discarding and "
                          "then discarded unless you keep them. Text a host takes from a file has a size limit.")
        grid = tk.Frame(card, background=c.surface)
        grid.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.inbox_values: dict[str, tk.StringVar] = {}
        for row, (key, label, unit) in enumerate(self.INBOX_FIELDS):
            tk.Label(grid, text=label, font=theme.font("body"), background=c.surface, foreground=c.text,
                     anchor="w").grid(row=row, column=0, sticky="w", pady=theme.px(3))
            value = tk.StringVar(master=self)
            Field(grid, theme, textvariable=value, width=8).grid(row=row, column=1, sticky="w",
                                                                  padx=(theme.px(SPACE_M), theme.px(SPACE_S)))
            tk.Label(grid, text=unit, font=theme.font("caption"), background=c.surface, foreground=c.text_muted,
                     anchor="w").grid(row=row, column=2, sticky="w")
            self.inbox_values[key] = value
        Button(card, theme, "Save inbox settings", command=self.save_inbox_settings).pack(
            anchor="w", pady=(theme.px(SPACE_M), 0))
        WrapLabel(card, DISCARD_NOTICE, font=theme.font("caption"), foreground=c.text_muted).pack(
            fill="x", pady=(theme.px(SPACE_M), 0))
        self.render_inbox_settings()

    def render_inbox_settings(self) -> None:
        control = self.spaces_control()
        try:
            values = control.inbox_settings() if control is not None else {}
        except Exception:  # noqa: BLE001
            values = {}
        for key, variable in self.inbox_values.items():
            variable.set(str(values.get(key, "")))

    def save_inbox_settings(self) -> None:
        control = self.spaces_control()
        if control is None:
            return
        try:
            for key, variable in self.inbox_values.items():
                control.set_inbox_setting(key, int(variable.get().strip()))
        except (ValueError, TypeError) as exc:
            self.app.notify("error", f"{exc}. Nothing after it was saved.", title="Inbox settings")
            self.render_inbox_settings()
            return
        self.app.notify("success", "Inbox settings saved.", title="Inbox settings")
        self.render_inbox_settings()

    # Memory engine -------------------------------------------------------------------------------

    def _build_engine_card(self, body: tk.Misc) -> None:
        theme, c = self.theme, self.colors
        card = self._card(body, "Memory engine",
                          "The engine stores and finds your memories. BIO CE includes the Community Engine; other "
                          "engines are installed separately.")
        self.engine_banner_title = tk.Label(card, font=theme.font("body_strong"), background=c.surface,
                                            foreground=c.text, anchor="w")
        self.engine_banner_title.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.engine_banner_message = WrapLabel(card, font=theme.font("body"), foreground=c.text_secondary)
        self.engine_banner_message.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.engine_list = tk.Frame(card, background=c.surface)
        self.engine_list.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.engine_note = WrapLabel(card, SEPARATE_DATABASES_NOTE, font=theme.font("caption"),
                                     foreground=c.text_muted)
        self.engine_note.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        row = tk.Frame(card, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.engine_check_button = Button(row, theme, "Check again", icon="refresh", variant="subtle",
                                          command=self.check_engines, tooltip="Check each engine's status again")
        self.engine_check_button.pack(side="left")
        self.engine_rows: dict[str, EngineRowWidgets] = {}
        self.render_engines()

    def render_engines(self) -> None:
        theme, c = self.theme, self.colors
        shown = self.app.engine_banner()
        self.engine_banner_title.configure(text=shown.title,
                                           foreground=c.text if shown.connected else c.warning)
        # The separate-databases notice is shown once, below the list.
        message = "" if shown.message == SEPARATE_DATABASES_NOTE else shown.message
        self.engine_banner_message.configure(text=message)
        if message and not self.engine_banner_message.winfo_manager():
            self.engine_banner_message.pack(fill="x", pady=(self.theme.px(SPACE_XS), 0), before=self.engine_list)
        elif not message:
            self.engine_banner_message.pack_forget()
        for child in self.engine_list.winfo_children():
            child.destroy()
        self.engine_rows = {}
        for entry in engine_rows(self.app.engine_selection, self.app.engine_statuses()):
            frame = tk.Frame(self.engine_list, background=c.surface_alt, highlightthickness=1,
                             highlightbackground=c.accent if entry.active else c.border)
            frame.pack(fill="x", pady=(0, theme.px(SPACE_S)))
            inner = tk.Frame(frame, background=c.surface_alt)
            inner.pack(fill="x", padx=theme.px(SPACE_M), pady=theme.px(SPACE_S))
            top = tk.Frame(inner, background=c.surface_alt)
            top.pack(fill="x")
            tk.Label(top, text=entry.name, font=theme.font("body_strong"), background=c.surface_alt,
                     foreground=c.text, anchor="w").pack(side="left")
            pill = Pill(top, theme, entry.state_text, _PILL_KIND.get(entry.tone, "neutral"))
            pill.pack(side="left", padx=(theme.px(SPACE_S), 0))
            if entry.active:
                Pill(top, theme, "In use", "info").pack(side="left", padx=(theme.px(SPACE_XS), 0))
            # Engine switching is not enabled in this version: every choice button stays disabled.
            button = None
            if not entry.active:  # the active row already says "In use"
                button = Button(top, theme, "Use this engine", variant="subtle")
                button.pack(side="right")
                button.set_enabled(False)
                Tooltip(button, theme, SWITCHING_DISABLED)
            if entry.detail:
                WrapLabel(inner, entry.detail, font=theme.font("caption"), foreground=c.text_muted,
                          background=c.surface_alt).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
            self.engine_rows[entry.engine_id] = EngineRowWidgets(entry.engine_id, entry.active, pill, button, frame)

    def check_engines(self) -> None:
        self.app.refresh_engine_status()
        self.render_engines()
        self.app.notify("info", self.app.engine_banner().title, title="Memory engine checked")

    def _card(self, body: tk.Misc, title: str, description: str | None) -> tk.Frame:
        theme, c = self.theme, self.colors
        card = Card(body, theme, padding=SPACE_L + 4)
        card.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        section_label(card.body, theme, title).pack(fill="x")
        if description:
            WrapLabel(card.body, description, font=theme.font("body"), foreground=c.text_secondary).pack(
                fill="x", pady=(theme.px(SPACE_XS), 0))
        return card.body

    def _point(self, master: tk.Misc, icon: str, heading: str, text: str) -> None:
        theme, c = self.theme, self.colors
        row = tk.Frame(master, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_S + 2), 0))
        tk.Label(row, text=theme.icon(icon), font=theme.icon_font("normal"), background=c.surface,
                 foreground=c.warning if icon in {"warning", "retract"} else c.accent_text, width=2).pack(
            side="left", anchor="n", padx=(0, theme.px(SPACE_S)), pady=(theme.px(2), 0))
        column = tk.Frame(row, background=c.surface)
        column.pack(side="left", fill="x", expand=True)
        tk.Label(column, text=heading, font=theme.font("body_strong"), background=c.surface, foreground=c.text,
                 anchor="w").pack(fill="x")
        WrapLabel(column, text, font=theme.font("body"), foreground=c.text_secondary).pack(fill="x")

    def refresh(self) -> None:
        super().refresh()
        try:
            count = self.app.memory_engine().count()
        except Exception:
            count = None
        self.render_engines()
        self.render_spaces()
        self.render_inbox_settings()
        size = database_size(self.app.paths.user_database)
        parts = [plural(count, "active memory", "active memories") if count is not None else "Memory count unavailable",
                 f"{file_size(size)} on disk"]
        self.storage_stats.configure(text=" · ".join(parts))

    def _copy_path(self) -> None:
        copy_to_clipboard(self, str(self.app.paths.user_database))
        self.app.notify("success", "Database path copied to the clipboard.")

    def view_file(self, title: str, path: Path) -> TextViewerDialog | None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            self.app.notify("error", f"BIO CE couldn't open {path.name}. Reinstall BIO CE to restore it.",
                            title="File unavailable")
            return None
        if self.viewer is not None and self.viewer.winfo_exists():
            self.viewer.destroy()
        self.viewer = TextViewerDialog(self, self.theme, title, text).show()
        return self.viewer

    def focus_default(self) -> None:
        self.scroll.canvas.yview_moveto(0)
        self.focus_set()


__all__ = ["PRIVACY_POINTS", "SHORTCUTS", "SettingsPage", "database_size", "resource_path"]
