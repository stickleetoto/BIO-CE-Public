# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Windows desktop memory manager backed by the BIO CE SQLite store.

This module owns data locations, settings, and the user-directed memory
service. The window itself lives in :mod:`bio_ce.ui`.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
from typing import Mapping
import uuid

from bio_ce.auto_memory import ReviewService
from bio_ce.control_store import ControlStore
from bio_ce.core.models import (
    MemoryRevision,
    MemoryScope,
    SearchHit,
    SourceProvenance,
)
from bio_ce.storage.backup import (
    BackupConflictError,
    create_backup,
    remove_sqlite_sidecars,
    stage_restore,
)
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from bio_ce.ui.app import BIOCEDesktop
from bio_ce.ui.dialogs import ask_privacy_consent
from bio_ce.ui.theme import Theme, app_icon, apply_window_chrome, enable_windows_dpi_awareness


PERSONAL_SCOPE = MemoryScope("bio-ce-personal", "default")
_SETTINGS_VERSION = 1
INSTANCE_MUTEX_NAME = "BIO-CE-Desktop-SingleInstance"
WINDOW_TITLE = "BIO Community Edition"
DATABASE_IN_USE = (
    "The database is in use by another program, such as another BIO CE window or a connected AI host. "
    "Close it and try again."
)


@dataclass(frozen=True, slots=True)
class AppDataPaths:
    """Separated locations for user data and the synthetic demo database."""

    root: Path
    user_database: Path
    demo_database: Path
    settings_file: Path

    @classmethod
    def under(cls, root: str | Path) -> "AppDataPaths":
        resolved = Path(root).expanduser().resolve()
        return cls(
            root=resolved,
            user_database=resolved / "data" / "memories.sqlite3",
            demo_database=resolved / "demo" / "demo.sqlite3",
            settings_file=resolved / "settings.json",
        )

    @classmethod
    def from_local_app_data(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AppDataPaths":
        values = os.environ if environ is None else environ
        local_app_data = values.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("Windows LOCALAPPDATA is not available")
        return cls.under(Path(local_app_data) / "BIO-CE")


class DesktopSettingsError(RuntimeError):
    """Local desktop settings exist but cannot be safely interpreted."""


def privacy_acknowledged(settings_file: str | Path) -> bool:
    path = Path(settings_file)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DesktopSettingsError("BIO CE settings could not be read") from exc
    if (
        not isinstance(data, dict)
        or data.get("settings_version") != _SETTINGS_VERSION
        or type(data.get("privacy_acknowledged")) is not bool
    ):
        raise DesktopSettingsError("BIO CE settings have an unsupported format")
    return data["privacy_acknowledged"]


def save_privacy_acknowledgement(settings_file: str | Path) -> None:
    path = Path(settings_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(
        {"settings_version": _SETTINGS_VERSION, "privacy_acknowledged": True},
        sort_keys=True,
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise DesktopSettingsError("BIO CE privacy setting could not be saved") from exc


class DesktopMemoryService:
    """Explicit user-directed memory operations over the real SQLite store."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()
        self.scope = PERSONAL_SCOPE
        self._store = SQLiteMemoryStore(self.database)

    def count(self) -> int:
        return self._store.count_current(self.scope)

    def list(self, *, limit: int = 100, offset: int = 0) -> tuple[MemoryRevision, ...]:
        return self._store.list_current(self.scope, limit=limit, offset=offset)

    def search(self, query: str, *, limit: int = 50) -> tuple[SearchHit, ...]:
        return self._store.search(self.scope, query, limit=limit)

    def read(self, memory_id: str) -> MemoryRevision:
        return self._store.read(self.scope, memory_id)

    def history(self, memory_id: str) -> tuple[MemoryRevision, ...]:
        return self._store.history(self.scope, memory_id)

    def add(self, *, title: str, content: str, source_ref: str) -> MemoryRevision:
        return self._store.add(
            self.scope,
            title=title,
            content=content,
            source=SourceProvenance("user-entered", source_ref),
        )

    def revise(
        self,
        current: MemoryRevision,
        *,
        title: str,
        content: str,
        source_ref: str,
    ) -> MemoryRevision:
        return self._store.revise(
            self.scope,
            current.memory_id,
            expected_revision_id=current.revision_id,
            title=title,
            content=content,
            source=SourceProvenance("user-entered", source_ref),
        )

    def retract(self, current: MemoryRevision) -> MemoryRevision:
        return self._store.retract(
            self.scope,
            current.memory_id,
            expected_revision_id=current.revision_id,
            source=SourceProvenance("user-requested-retraction", "bio-ce-desktop"),
        )

    def approve_review(
        self, control: ControlStore, review_id: int, *, title: str | None = None, content: str | None = None
    ) -> MemoryRevision:
        """Apply an AI host's queued proposal, optionally with the user's edits."""
        return ReviewService(self._store, control, self.scope).approve(review_id, title=title, content=content)

    def reject_review(self, control: ControlStore, review_id: int) -> None:
        ReviewService(self._store, control, self.scope).reject(review_id)

    def create_backup(self, destination: str | Path) -> Path:
        return create_backup(self.database, destination)

    def restore_backup(self, backup: str | Path) -> None:
        source = Path(backup).expanduser().resolve()
        if source == self.database:
            raise BackupConflictError("The active database cannot be restored from itself.")
        staged = stage_restore(source, self.database.parent)
        closed = False
        try:
            try:
                self._store.prepare_for_database_replacement()
            except RuntimeError as exc:
                raise BackupConflictError(DATABASE_IN_USE) from exc
            self._store.close()
            closed = True
            for suffix in ("-wal", "-shm"):
                if self.database.with_name(self.database.name + suffix).exists():
                    raise BackupConflictError(DATABASE_IN_USE)
            os.replace(staged, self.database)
            self._store = SQLiteMemoryStore(self.database)
            closed = False
        except Exception:
            if closed:
                self._store = SQLiteMemoryStore(self.database)
            raise
        finally:
            staged.unlink(missing_ok=True)
            remove_sqlite_sidecars(staged)

    def close(self) -> None:
        self._store.close()


def claim_single_instance(name: str = INSTANCE_MUTEX_NAME) -> int | None:
    """Hold a per-session named mutex; return None if another BIO CE window owns it.

    Only one desktop process may hold the personal database open, so a second
    launch hands focus to the running window instead. The returned handle must
    stay referenced for the life of the process. Non-Windows platforms return 0.
    """
    if os.name != "nt":
        return 0
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return 0
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return None
    return handle


def focus_existing_window(title: str = WINDOW_TITLE) -> bool:
    """Restore and raise the running BIO CE window, if one is visible."""
    if os.name != "nt":
        return False
    user32 = ctypes.WinDLL("user32")
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowW.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
    window = user32.FindWindowW("TkTopLevel", title)
    if not window:
        return False
    if user32.IsIconic(ctypes.c_void_p(window)):
        user32.ShowWindow(ctypes.c_void_p(window), 9)  # SW_RESTORE
    return bool(user32.SetForegroundWindow(ctypes.c_void_p(window)))


def run_desktop() -> int:
    """Start the Windows app after the user acknowledges the local data notice."""
    instance = claim_single_instance()
    if instance is None:
        focus_existing_window()
        return 0
    enable_windows_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    try:
        paths = AppDataPaths.from_local_app_data()
        acknowledged = privacy_acknowledged(paths.settings_file)
    except (RuntimeError, DesktopSettingsError) as exc:
        messagebox.showerror("BIO CE cannot start", str(exc), parent=root)
        root.destroy()
        return 2

    theme = Theme(root)
    root.title(WINDOW_TITLE)
    icon = app_icon(root, theme.colors)
    if icon is not None:
        root.iconphoto(True, icon)
    if not acknowledged:
        width, height = theme.px(760), theme.px(700)
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width, height = min(width, int(screen_w * 0.95)), min(height, int(screen_h * 0.9))
        root.geometry(f"{width}x{height}+{max(0, (screen_w - width) // 2)}+{max(0, (screen_h - height) // 3)}")
        if not ask_privacy_consent(root, theme):
            root.destroy()
            return 0
        root.withdraw()
        try:
            save_privacy_acknowledgement(paths.settings_file)
        except DesktopSettingsError as exc:
            messagebox.showerror("BIO CE cannot start", str(exc), parent=root)
            root.destroy()
            return 2

    try:
        service = DesktopMemoryService(paths.user_database)
    except Exception:
        messagebox.showerror(
            "BIO CE cannot start",
            "The personal memory database could not be opened. No data was imported from the demo database.",
            parent=root,
        )
        root.destroy()
        return 2
    BIOCEDesktop(root, service, paths, theme=theme)
    root.deiconify()
    if icon is not None:
        # Tk drops an icon set while the root was never mapped (the path taken
        # when the notice was already accepted), so apply it again once shown.
        root.update_idletasks()
        root.iconphoto(True, icon)
    apply_window_chrome(root, theme.colors)
    root.mainloop()
    return 0


__all__ = [
    "AppDataPaths",
    "BIOCEDesktop",
    "DesktopMemoryService",
    "DesktopSettingsError",
    "PERSONAL_SCOPE",
    "claim_single_instance",
    "focus_existing_window",
    "privacy_acknowledged",
    "run_desktop",
    "save_privacy_acknowledgement",
]
