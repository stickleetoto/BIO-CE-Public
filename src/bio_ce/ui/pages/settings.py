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
from bio_ce.ui.format import file_size
from bio_ce.engine.presentation import SEPARATE_DATABASES_NOTE, engine_rows
from bio_ce.ui.hub.common import space_label
from bio_ce.ui.i18n import AUTO, NAMES, language, resolve, t
from bio_ce.ui.pages import Page
from bio_ce.ui.service_text import say
from bio_ce.ui.shortcuts import SHORTCUTS
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



#: (icon, heading key, text key); the texts are looked up when the page is built, in the language shown then.
PRIVACY_POINTS = (
    ("shield", "settings.privacy.local", "settings.privacy.local_text"),
    ("edit", "settings.privacy.no_recording", "settings.privacy.no_recording_text"),
    ("lock", "settings.privacy.control", "settings.privacy.control_text"),
    ("warning", "settings.privacy.no_encryption", "settings.privacy.no_encryption_text"),
    ("retract", "settings.privacy.not_erase", "settings.privacy.not_erase_text"),
)


def resource_path(frozen_name: str, source_name: str) -> Path:
    """Locate a file bundled beside the installed app or in the source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / frozen_name
    return Path(__file__).resolve().parents[4] / source_name


def release_channel(version: str) -> str:
    """Name the release stage encoded in a PEP 440 version string."""
    if ".dev" in version or re.search(r"\d(a|b)\d", version):
        return t("settings.about.preview")
    if re.search(r"\drc\d", version):
        return t("settings.about.candidate")
    return t("settings.about.release")


def database_size(database: Path) -> int:
    total = 0
    for suffix in ("", "-wal"):
        try:
            total += database.with_name(database.name + suffix).stat().st_size
        except OSError:
            pass
    return total


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

    @property
    def title(self) -> str:  # type: ignore[override]
        return t("nav.settings")

    @property
    def subtitle(self) -> str:  # type: ignore[override]
        return t("settings.subtitle")

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        self.viewer: TextViewerDialog | None = None
        self.scroll = ScrollFrame(self, theme, max_width=900)
        self.scroll.pack(fill="both", expand=True)
        body = self.scroll.body

        self._build_language_card(body)
        self._build_engine_card(body)

        storage = self._card(body, t("settings.storage.title"), t("settings.storage.description"))
        self.path_value = tk.StringVar(master=self, value=str(app.paths.user_database))
        row = tk.Frame(storage, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        Field(row, theme, textvariable=self.path_value, font="mono", readonly=True).pack(side="left", fill="x",
                                                                                        expand=True)
        Button(row, theme, t("settings.storage.open_folder"), icon="folder", command=app.open_data_folder).pack(
            side="right", padx=(theme.px(SPACE_S), 0))
        Button(row, theme, "", icon="copy", tooltip=t("settings.storage.copy_path"), command=self._copy_path,
               padx=9).pack(
            side="right", padx=(theme.px(SPACE_S), 0))
        self.storage_stats = tk.Label(storage, font=theme.font("caption"), background=c.surface,
                                      foreground=c.text_muted, anchor="w")
        self.storage_stats.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        WrapLabel(storage, t("settings.storage.demo", path=app.paths.demo_database), font=theme.font("caption"),
                  foreground=c.text_muted).pack(
            fill="x", pady=(theme.px(SPACE_XS), 0))

        self._build_spaces_card(body)
        self._build_inbox_card(body)

        backup = self._card(body, t("settings.backup.title"), t("settings.backup.description"))
        backup_row = tk.Frame(backup, background=c.surface)
        backup_row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.backup_button = Button(backup_row, theme, t("settings.backup.create"), icon="backup",
                                    command=app.backup_database)
        self.backup_button.pack(side="left")
        app.gate(self.backup_button, "backup")
        Button(backup_row, theme, t("settings.backup.export"), variant="link", command=app.export_memories).pack(
            side="left", padx=(theme.px(SPACE_M), 0))
        # v0.4.4 §7.2: BIO CE's own automatic backups (before a move or a restore) are limited to the latest N pairs.
        keep_row = tk.Frame(backup, background=c.surface)
        keep_row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        tk.Label(keep_row, text=t("settings.backups.keep_label"), font=theme.font("body"), background=c.surface,
                 foreground=c.text, anchor="w").pack(side="left")
        self.auto_backup_value = tk.StringVar(master=self)
        Field(keep_row, theme, textvariable=self.auto_backup_value, width=5).pack(
            side="left", padx=(theme.px(SPACE_M), theme.px(SPACE_S)))
        tk.Label(keep_row, text=t("settings.backups.keep_range"), font=theme.font("caption"), background=c.surface,
                 foreground=c.text_muted).pack(side="left")
        self.auto_backup_button = Button(keep_row, theme, t("common.save"), command=self.save_auto_backup_keep)
        self.auto_backup_button.pack(side="left", padx=(theme.px(SPACE_M), 0))
        WrapLabel(backup, t("settings.backups.keep_note"), font=theme.font("caption"),
                  foreground=c.text_muted).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        tk.Frame(backup, height=1, background=c.border).pack(fill="x", pady=theme.px(SPACE_L))
        tk.Label(backup, text=t("settings.restore.title"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, anchor="w").pack(fill="x")
        WrapLabel(backup, t("settings.restore.description"), font=theme.font("body"),
                  foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        restore_row = tk.Frame(backup, background=c.surface)
        restore_row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.restore_button = Button(restore_row, theme, t("settings.restore.button"), icon="restore",
                                     variant="danger_subtle", command=app.restore_database)
        self.restore_button.pack(side="left")
        app.gate(self.restore_button, "restore")

        privacy = self._card(body, t("settings.privacy.title"), None)
        for icon, heading, text in PRIVACY_POINTS:
            self._point(privacy, icon, t(heading), t(text))
        backup_note = tk.Frame(privacy, background=c.surface)
        backup_note.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self._point(backup_note, "backup", t("settings.privacy.host_backups"), t("settings.privacy.host_backups_text"))
        Button(privacy, theme, t("settings.privacy.open_backups"), variant="link",
               command=app.open_connection_backups, anchor="w").pack(anchor="w", padx=(theme.px(30), 0))

        shortcuts = self._card(body, t("shortcut.dialog_title"), None)
        grid = tk.Frame(shortcuts, background=c.surface)
        grid.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.shortcut_rows = []
        for index, shortcut in enumerate(SHORTCUTS):  # one table for the keys and this list (v0.4.4 F3)
            tk.Label(grid, text=shortcut.keys, font=theme.font("mono"), background=c.surface_alt, foreground=c.text,
                     padx=theme.px(SPACE_S), pady=theme.px(1)).grid(row=index, column=0, sticky="w",
                                                                    pady=theme.px(3))
            label = WrapLabel(grid, t(shortcut.text), font=theme.font("body"), foreground=c.text_secondary)
            label.grid(row=index, column=1, sticky="we", padx=(theme.px(SPACE_M), 0))
            self.shortcut_rows.append(label)
        grid.columnconfigure(1, weight=1)

        about = self._card(body, t("settings.about.title"), None)
        tk.Label(about, text=t("settings.about.version", version=bio_ce.display_version(),
                               channel=release_channel(bio_ce.__version__)),
                 font=theme.font("body"), background=c.surface, foreground=c.text, anchor="w").pack(
            fill="x", pady=(theme.px(SPACE_XS), 0))
        WrapLabel(about, t("settings.about.copyright"), font=theme.font("caption"),
                  foreground=c.text_muted).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        about_row = tk.Frame(about, background=c.surface)
        about_row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.license_path = resource_path("LICENSE", "LICENSE")
        self.notices_path = resource_path("THIRD_PARTY_NOTICES", "docs/THIRD_PARTY_LICENSES.md")
        self.license_button = Button(about_row, theme, t("settings.about.view_license"), icon="document",
                                     command=lambda: self.view_file(t("settings.about.license_name"),
                                                                    self.license_path))
        self.license_button.pack(side="left")
        self.notices_button = Button(about_row, theme, t("settings.about.notices"),
                                     command=lambda: self.view_file(t("settings.about.notices"), self.notices_path))
        self.notices_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.license_button.set_enabled(self.license_path.is_file())
        self.notices_button.set_enabled(self.notices_path.is_file())
        tk.Frame(body, height=theme.px(SPACE_S), background=c.bg).pack()

    # Spaces --------------------------------------------------------------------------------------

    def _build_spaces_card(self, body: tk.Misc) -> None:
        theme, c = self.theme, self.colors
        card = self._card(body, t("settings.spaces.title"), t("settings.spaces.description"))
        self.spaces_list = tk.Frame(card, background=c.surface)
        self.spaces_list.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        row = tk.Frame(card, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.new_space_button = Button(row, theme, t("settings.spaces.new"), icon="add", command=self.new_space)
        self.new_space_button.pack(side="left")
        self.space_rows: dict[str, tk.Frame] = {}
        self.render_spaces()

    def _build_language_card(self, body: tk.Misc) -> None:
        """v0.4.4: the app language (auto = Setup's choice, then Windows). It applies on the next start (owner
        decision 2026-11-17, instead of redrawing every page at once); Restart now restarts BIO CE."""
        theme, c = self.theme, self.colors
        card = self._card(body, t("settings.language.title"), t("settings.language.note"))
        control = self.spaces_control()
        stored = control.ui_language() if control is not None and hasattr(control, "ui_language") else AUTO
        self.language_choice = tk.StringVar(master=self, value=stored)
        row = tk.Frame(card, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.language_buttons = {}
        for key, label in ((AUTO, t("settings.language.auto")), ("ko", NAMES["ko"]), ("en", NAMES["en"])):
            button = tk.Radiobutton(row, text=label, value=key, variable=self.language_choice,
                                    command=self.choose_language, font=theme.font("body"), background=c.surface,
                                    foreground=c.text, activebackground=c.surface, activeforeground=c.text,
                                    selectcolor=c.surface_alt, highlightthickness=0, borderwidth=0)
            button.pack(side="left", padx=(0, theme.px(SPACE_M)))
            self.language_buttons[key] = button
        self.restart_row = tk.Frame(card, background=c.surface)
        self.restart_note = WrapLabel(self.restart_row, t("settings.language.restart_note"), font=theme.font("body"),
                                      foreground=c.text_secondary)
        self.restart_button = Button(self.restart_row, theme, t("settings.language.restart_now"), variant="primary",
                                     command=self.app.restart)
        self.restart_button.pack(side="right")
        self.restart_note.pack(side="left", fill="x", expand=True)
        self._show_restart()

    def choose_language(self) -> None:
        control = self.spaces_control()
        choice = self.language_choice.get()
        if control is None or not hasattr(control, "set_ui_language"):
            return
        try:
            control.set_ui_language(choice)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", say(exc) or t("settings.language.not_saved"), title=t("settings.language.title"))
            return
        self._show_restart()

    def _show_restart(self) -> None:
        """The note and Restart now, while the chosen language is not the one the app shows."""
        differs = resolve(self.language_choice.get()) != language()
        if differs and not self.restart_row.winfo_manager():
            self.restart_row.pack(fill="x", pady=(self.theme.px(SPACE_M), 0))
        elif not differs and self.restart_row.winfo_manager():
            self.restart_row.pack_forget()

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
            WrapLabel(self.spaces_list, t("settings.spaces.unavailable"), font=theme.font("caption"),
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
            tk.Label(top, text=space_label(space), font=theme.font("body_strong"), background=c.surface_alt,
                     foreground=c.text, anchor="w").pack(side="left")
            folders = [(key, label) for space_id, key, label in links if space_id == space.space_id]
            if space.is_general:
                detail = t("settings.spaces.general_detail")
            else:
                detail = (t("settings.spaces.linked_folders", count=len(folders)) if folders
                          else t("settings.spaces.no_folder"))
                Button(top, theme, t("settings.spaces.archive"), variant="link",
                       command=lambda item=space: self.archive_space(item)).pack(side="right")
                Button(top, theme, t("settings.spaces.rename"), variant="link",
                       command=lambda item=space: self.rename_space(item)).pack(side="right")
                Button(top, theme, t("settings.spaces.link_folder"), variant="link",
                       command=lambda item=space: self.link_folder(item)).pack(side="right")
            tk.Label(inner, text=detail, font=theme.font("caption"), background=c.surface_alt,
                     foreground=c.text_muted, anchor="w").pack(fill="x")
            for key, label in folders:
                line = tk.Frame(inner, background=c.surface_alt)
                line.pack(fill="x", pady=(theme.px(2), 0))
                tk.Label(line, text=f"  {label}", font=theme.font("body"), background=c.surface_alt,
                         foreground=c.text_secondary, anchor="w").pack(side="left")
                Button(line, theme, t("settings.spaces.unlink"), variant="link",
                       command=lambda item=space, k=key: self.unlink_folder(item, k)).pack(side="right")
            self.space_rows[space.space_id] = frame
            if space.is_general:
                self._render_personal_row(control)

    def _render_personal_row(self, control) -> None:
        theme, c = self.theme, self.colors
        try:
            enabled = bool(control.personal_enabled())
        except Exception:  # noqa: BLE001
            return
        frame = tk.Frame(self.spaces_list, background=c.surface_alt, highlightthickness=1,
                         highlightbackground=c.border)
        frame.pack(fill="x", pady=(0, theme.px(SPACE_S)))
        inner = tk.Frame(frame, background=c.surface_alt)
        inner.pack(fill="x", padx=theme.px(SPACE_M), pady=theme.px(SPACE_S))
        top = tk.Frame(inner, background=c.surface_alt)
        top.pack(fill="x")
        tk.Label(top, text=t("space.personal"), font=theme.font("body_strong"), background=c.surface_alt,
                 foreground=c.text, anchor="w").pack(side="left")
        if enabled:
            Button(top, theme, t("settings.personal.turn_off"), variant="link",
                   command=self.turn_off_personal).pack(side="right")
            detail = t("settings.personal.on_detail")
        else:
            Button(top, theme, t("settings.personal.turn_on"), variant="link",
                   command=self.turn_on_personal).pack(side="right")
            detail = t("settings.personal.off_detail")
        WrapLabel(inner, text=detail, font=theme.font("caption"), background=c.surface_alt,
                  foreground=c.text_muted, max_width=theme.px(520)).pack(fill="x")
        self.space_rows["personal"] = frame

    def turn_on_personal(self) -> bool:
        if not self.app.confirm(
            title=t("settings.personal.on_title"),
            message=t("settings.personal.on_message"),
            points=(t("settings.personal.on_point_allow"), t("settings.personal.on_point_hooks"),
                    t("settings.personal.on_point_backups"), t("settings.personal.on_point_off")),
            confirm_text=t("settings.personal.on_confirm"),
        ):
            return False
        done = self.app.set_personal_enabled(True)
        self.render_spaces()
        return done

    def turn_off_personal(self) -> bool:
        if not self.app.confirm(
            title=t("settings.personal.off_title"),
            message=t("settings.personal.off_message"),
            points=(t("settings.personal.off_point"),),
            confirm_text=t("settings.personal.off_confirm"),
        ):
            return False
        done = self.app.set_personal_enabled(False)
        self.render_spaces()
        return done

    def _space_action(self, title: str, action) -> bool:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", say(exc) or t("settings.spaces.change_failed"), title=title)
            return False
        self.render_spaces()
        return True

    def new_space(self) -> None:
        control = self.spaces_control()
        name = self.app.ask_name(title=t("settings.spaces.new_title"), label=t("settings.spaces.name"),
                                 confirm_text=t("settings.spaces.create"), note=t("settings.spaces.new_note"))
        if control is None or not name:
            return
        if self._space_action(t("settings.spaces.not_created"), lambda: control.create_space(name)):
            self.app.notify("success", t("settings.spaces.created", name=name),
                            title=t("settings.spaces.created_title"))

    def rename_space(self, space) -> None:
        control = self.spaces_control()
        name = self.app.ask_name(title=t("settings.spaces.rename_title"), label=t("settings.spaces.name"),
                                 value=space.display_name, confirm_text=t("settings.spaces.rename"),
                                 note=t("settings.spaces.rename_note"))
        if control is None or not name or name == space.display_name:
            return
        self._space_action(t("settings.spaces.not_renamed"), lambda: control.rename_space(space.space_id, name))

    def archive_space(self, space) -> None:
        control = self.spaces_control()
        if control is None or not self.app.confirm(
            title=t("settings.spaces.archive_title", name=space.display_name),
            message=t("settings.spaces.archive_message"),
            quote=space.display_name,
            points=(t("settings.spaces.archive_point_kept"), t("settings.spaces.archive_point_general")),
            confirm_text=t("settings.spaces.archive_confirm"),
        ):
            return
        self._space_action(t("settings.spaces.not_archived"), lambda: control.archive_space(space.space_id))

    def link_folder(self, space) -> None:
        control = self.spaces_control()
        folder = self.app.ask_folder(title=t("settings.spaces.choose_folder", name=space.display_name))
        if control is None or not folder:
            return
        self._space_action(t("settings.spaces.not_linked"), lambda: control.link_folder(space.space_id, folder))

    def unlink_folder(self, space, key: str) -> None:
        control = self.spaces_control()
        if control is None:
            return
        self._space_action(t("settings.spaces.not_unlinked"), lambda: control.unlink_folder(space.space_id, key))

    # Inbox ---------------------------------------------------------------------------------------

    #: (setting, label key, unit key)
    INBOX_FIELDS = (
        ("inbox_expire_days", "settings.inbox.expire_label", "settings.inbox.expire_unit"),
        ("inbox_wait_days", "settings.inbox.wait_label", "settings.inbox.wait_unit"),
        ("file_content_limit", "settings.inbox.file_label", "settings.inbox.file_unit"),
    )

    def _build_inbox_card(self, body: tk.Misc) -> None:
        theme, c = self.theme, self.colors
        card = self._card(body, t("settings.inbox.title"), t("settings.inbox.description"))
        grid = tk.Frame(card, background=c.surface)
        grid.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.inbox_values: dict[str, tk.StringVar] = {}
        for row, (key, label, unit) in enumerate(self.INBOX_FIELDS):
            tk.Label(grid, text=t(label), font=theme.font("body"), background=c.surface, foreground=c.text,
                     anchor="w").grid(row=row, column=0, sticky="w", pady=theme.px(3))
            value = tk.StringVar(master=self)
            Field(grid, theme, textvariable=value, width=8).grid(row=row, column=1, sticky="w",
                                                                  padx=(theme.px(SPACE_M), theme.px(SPACE_S)))
            tk.Label(grid, text=t(unit), font=theme.font("caption"), background=c.surface, foreground=c.text_muted,
                     anchor="w").grid(row=row, column=2, sticky="w")
            self.inbox_values[key] = value
        Button(card, theme, t("settings.inbox.save"), command=self.save_inbox_settings).pack(
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
            self.app.notify("error", t("settings.inbox.save_failed", reason=say(exc)), title=t("settings.inbox.saved_title"))
            self.render_inbox_settings()
            return
        self.app.notify("success", t("settings.inbox.saved"), title=t("settings.inbox.saved_title"))
        self.render_inbox_settings()

    def render_auto_backup_keep(self) -> None:
        control = self.spaces_control()
        try:
            keep = control.auto_backup_keep() if control is not None else None
        except Exception:  # noqa: BLE001
            keep = None
        self.auto_backup_value.set("" if keep is None else str(keep))
        self.auto_backup_button.set_enabled(control is not None)

    def save_auto_backup_keep(self) -> int | None:
        control = self.spaces_control()
        if control is None:
            return None
        try:
            keep = control.set_auto_backup_keep(int(self.auto_backup_value.get().strip()))
        except (ValueError, TypeError):
            self.app.notify("error", t("settings.backups.keep_invalid"), title=t("settings.backups.keep_title"))
            self.render_auto_backup_keep()
            return None
        self.app.notify("success", t("settings.backups.keep_saved", count=keep), title=t("settings.backups.keep_title"))
        self.render_auto_backup_keep()
        return keep

    # Memory engine -------------------------------------------------------------------------------

    def _build_engine_card(self, body: tk.Misc) -> None:
        theme, c = self.theme, self.colors
        card = self._card(body, t("settings.engine.title"), t("settings.engine.description"))
        self.engine_banner_title = tk.Label(card, font=theme.font("body_strong"), background=c.surface,
                                            foreground=c.text, anchor="w")
        self.engine_banner_title.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.engine_banner_message = WrapLabel(card, font=theme.font("body"), foreground=c.text_secondary)
        self.engine_banner_message.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.engine_list = tk.Frame(card, background=c.surface)
        self.engine_list.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        self.engine_note = WrapLabel(card, say(SEPARATE_DATABASES_NOTE), font=theme.font("caption"),
                                     foreground=c.text_muted)
        self.engine_note.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        row = tk.Frame(card, background=c.surface)
        row.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.engine_check_button = Button(row, theme, t("settings.engine.check"), icon="refresh", variant="subtle",
                                          command=self.check_engines, tooltip=t("settings.engine.check_tooltip"))
        self.engine_check_button.pack(side="left")
        self.engine_rows: dict[str, EngineRowWidgets] = {}
        self.render_engines()

    def render_engines(self) -> None:
        theme, c = self.theme, self.colors
        shown = self.app.engine_banner()
        self.engine_banner_title.configure(text=say(shown.title),
                                           foreground=c.text if shown.connected else c.warning)
        # The separate-databases notice is shown once, below the list.
        message = "" if shown.message == SEPARATE_DATABASES_NOTE else shown.message
        self.engine_banner_message.configure(text=say(message))
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
            pill = Pill(top, theme, say(entry.state_text), _PILL_KIND.get(entry.tone, "neutral"))
            pill.pack(side="left", padx=(theme.px(SPACE_S), 0))
            if entry.active:
                Pill(top, theme, t("settings.engine.in_use"), "info").pack(side="left", padx=(theme.px(SPACE_XS), 0))
            # Engine switching is not enabled in this version: every choice button stays disabled.
            button = None
            if not entry.active:  # the active row already says "In use"
                button = Button(top, theme, t("settings.engine.use"), variant="subtle")
                button.pack(side="right")
                button.set_enabled(False)
                Tooltip(button, theme, t("settings.engine.switching_disabled"))
            if entry.detail:
                WrapLabel(inner, say(entry.detail), font=theme.font("caption"), foreground=c.text_muted,
                          background=c.surface_alt).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
            self.engine_rows[entry.engine_id] = EngineRowWidgets(entry.engine_id, entry.active, pill, button, frame)

    def check_engines(self) -> None:
        self.app.refresh_engine_status()
        self.render_engines()
        self.app.notify("info", say(self.app.engine_banner().title), title=t("settings.engine.checked"))

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
        self.render_auto_backup_keep()
        size = database_size(self.app.paths.user_database)
        parts = [t("settings.storage.active", count=count) if count is not None else t("settings.storage.no_count"),
                 t("settings.storage.on_disk", size=file_size(size))]
        self.storage_stats.configure(text=" · ".join(parts))

    def _copy_path(self) -> None:
        copy_to_clipboard(self, str(self.app.paths.user_database))
        self.app.notify("success", t("settings.storage.path_copied"))

    def view_file(self, title: str, path: Path) -> TextViewerDialog | None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            self.app.notify("error", t("settings.about.file_failed", name=path.name),
                            title=t("settings.about.file_failed_title"))
            return None
        if self.viewer is not None and self.viewer.winfo_exists():
            self.viewer.destroy()
        self.viewer = TextViewerDialog(self, self.theme, title, text).show()
        return self.viewer

    def focus_default(self) -> None:
        self.scroll.canvas.yview_moveto(0)
        self.focus_set()


__all__ = ["PRIVACY_POINTS", "SHORTCUTS", "SettingsPage", "database_size", "resource_path"]
