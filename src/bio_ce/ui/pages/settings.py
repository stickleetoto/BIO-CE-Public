# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Settings: data location, backup and restore, privacy notes, and about."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import tkinter as tk

import bio_ce
from bio_ce.ui.dialogs import TextViewerDialog
from bio_ce.ui.format import file_size, plural
from bio_ce.ui.pages import Page
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import Button, Card, Field, ScrollFrame, WrapLabel, copy_to_clipboard, section_label


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

        backup = self._card(body, "Backup and restore",
                            "A backup is a complete copy of your memory database. Backups are not encrypted, so "
                            "store them somewhere private.")
        backup_row = tk.Frame(backup, background=c.surface)
        backup_row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        Button(backup_row, theme, "Create backup…", icon="backup", command=app.backup_database).pack(side="left")
        tk.Frame(backup, height=1, background=c.border).pack(fill="x", pady=theme.px(SPACE_L))
        tk.Label(backup, text="Restore from a backup", font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        WrapLabel(backup, "Restoring replaces all current memories with the backup. BIO CE checks the file first. "
                  "Close connected AI hosts before restoring, and create a backup of your current memories if you "
                  "want to keep them.", font=theme.font("body"), foreground=c.text_secondary).pack(
            fill="x", pady=(theme.px(SPACE_XS), 0))
        restore_row = tk.Frame(backup, background=c.surface)
        restore_row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        Button(restore_row, theme, "Restore from backup…", icon="restore", variant="danger_subtle",
               command=app.restore_database).pack(side="left")

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
        tk.Label(about, text=f"BIO Community Edition {bio_ce.__version__} · {release_channel(bio_ce.__version__)}",
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
            count = self.app.service.count()
        except Exception:
            count = None
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
