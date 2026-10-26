# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Application shell: sidebar navigation, page header, notifications, routing."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Any, Callable
import tkinter as tk
from tkinter import filedialog

import bio_ce
from bio_ce.connections import HostStatus, MCPConnectionManager
from bio_ce.core.models import MemoryRevision
from bio_ce.storage.backup import BackupError
from bio_ce.ui.dialogs import ConfirmDialog
from bio_ce.ui.format import preview
from bio_ce.ui.pages import Page
from bio_ce.ui.pages.connections import ConnectionsPage
from bio_ce.ui.pages.dashboard import DashboardPage
from bio_ce.ui.pages.editor import EditorPage
from bio_ce.ui.pages.memories import MemoriesPage
from bio_ce.ui.pages.settings import SettingsPage
from bio_ce.ui.tasks import TaskRunner
from bio_ce.ui.theme import (
    SIDEBAR_COMPACT_BELOW,
    SIDEBAR_COMPACT_WIDTH,
    SIDEBAR_WIDTH,
    SPACE_L,
    SPACE_M,
    SPACE_S,
    SPACE_XL,
    SPACE_XXL,
    Theme,
    app_icon,
    apply_window_chrome,
)
from bio_ce.ui.widgets import InfoBar, NavItem, install_mousewheel

if TYPE_CHECKING:
    from bio_ce.desktop import AppDataPaths, DesktopMemoryService


NAVIGATION = (
    ("dashboard", "Dashboard", "dashboard", "Ctrl+1"),
    ("memories", "Memories", "memories", "Ctrl+2"),
    ("connections", "Connections", "connections", "Ctrl+3"),
    ("settings", "Settings", "settings", "Ctrl+4"),
)
DEFAULT_SIZE = (1200, 780)
MINIMUM_SIZE = (860, 560)


class BIOCEDesktop:
    """Desktop memory manager. Every write requires an explicit user action."""

    def __init__(
        self,
        root: tk.Tk,
        service: "DesktopMemoryService",
        paths: "AppDataPaths",
        connection_manager: MCPConnectionManager | None = None,
        *,
        theme: Theme | None = None,
    ) -> None:
        self.root = root
        self.service = service
        self.paths = paths
        self.connection_manager = connection_manager or MCPConnectionManager(service.database, paths.root)
        self.theme = theme or Theme(root)
        self.tasks = TaskRunner(root)
        self._host_statuses: dict[str, HostStatus | None] = {}
        self._compact: bool | None = None
        self.current: Page | None = None
        c = self.theme.colors

        root.title("BIO Community Edition")
        self._icon = app_icon(root, c)
        if self._icon is not None:
            root.iconphoto(True, self._icon)
        self._size_window()
        root.protocol("WM_DELETE_WINDOW", self.close)
        install_mousewheel(root)

        self.sidebar = tk.Frame(root, background=c.sidebar, width=self.theme.px(SIDEBAR_WIDTH))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(root, width=1, background=c.border).pack(side="left", fill="y")
        self._build_sidebar()

        self.main = tk.Frame(root, background=c.bg)
        self.main.pack(side="left", fill="both", expand=True)
        gutter = self.theme.px(SPACE_XXL)
        header = tk.Frame(self.main, background=c.bg)
        header.pack(fill="x", padx=gutter, pady=(self.theme.px(SPACE_XL + 4), self.theme.px(SPACE_L + 4)))
        titles = tk.Frame(header, background=c.bg)
        titles.pack(side="left", fill="x", expand=True)
        self.header_title = tk.Label(titles, font=self.theme.font("display"), background=c.bg,
                                     foreground=c.text, anchor="w")
        self.header_title.pack(fill="x")
        self.header_subtitle = tk.Label(titles, font=self.theme.font("body"), background=c.bg,
                                        foreground=c.text_secondary, anchor="w")
        self.header_subtitle.pack(fill="x", pady=(self.theme.px(2), 0))
        self.header_actions = tk.Frame(header, background=c.bg)
        self.header_actions.pack(side="right", anchor="s")

        self.page_host = tk.Frame(self.main, background=c.bg)
        self.page_host.pack(fill="both", expand=True, padx=gutter, pady=(0, self.theme.px(SPACE_XL)))
        self.infobar = InfoBar(self.main, self.theme, before=self.page_host,
                               pack_options={"fill": "x", "padx": gutter, "pady": (0, self.theme.px(SPACE_L))})

        self.dashboard = DashboardPage(self, self.page_host)
        self.memories = MemoriesPage(self, self.page_host)
        self.editor = EditorPage(self, self.page_host)
        self.connections = ConnectionsPage(self, self.page_host)
        self.settings = SettingsPage(self, self.page_host)
        self.pages: dict[str, Page] = {
            "dashboard": self.dashboard,
            "memories": self.memories,
            "connections": self.connections,
            "settings": self.settings,
        }
        self._routes: dict[str, Page] = dict(self.pages, editor=self.editor)

        self._bind_shortcuts()
        root.bind("<Configure>", self._on_resize, add="+")
        self.host_statuses(refresh=True)
        self.show_page("dashboard")
        self._apply_compact(root.winfo_width() < self.theme.px(SIDEBAR_COMPACT_BELOW))
        apply_window_chrome(root, c)

    # Layout ---------------------------------------------------------------

    def _size_window(self) -> None:
        theme, root = self.theme, self.root
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width = min(theme.px(DEFAULT_SIZE[0]), int(screen_w * 0.9))
        height = min(theme.px(DEFAULT_SIZE[1]), int(screen_h * 0.85))
        root.minsize(min(theme.px(MINIMUM_SIZE[0]), int(screen_w * 0.95)),
                     min(theme.px(MINIMUM_SIZE[1]), int(screen_h * 0.85)))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_sidebar(self) -> None:
        theme, c = self.theme, self.theme.colors
        brand = tk.Frame(self.sidebar, background=c.sidebar)
        brand.pack(fill="x", padx=theme.px(SPACE_M + 2), pady=(theme.px(SPACE_XL - 2), theme.px(SPACE_XL)))
        mark = tk.Frame(brand, background=c.accent, width=theme.px(28), height=theme.px(28))
        mark.pack(side="left")
        mark.pack_propagate(False)
        tk.Label(mark, text=theme.icon("memories") or "B", font=theme.icon_font("small") or theme.font("caption"),
                 background=c.accent, foreground=c.on_accent).place(relx=0.5, rely=0.5, anchor="center")
        self.brand_text = tk.Frame(brand, background=c.sidebar)
        self.brand_text.pack(side="left", padx=(theme.px(SPACE_M - 2), 0))
        tk.Label(self.brand_text, text="BIO CE", font=theme.font("brand"), background=c.sidebar,
                 foreground=c.text, anchor="w").pack(fill="x")
        tk.Label(self.brand_text, text="Community Edition", font=theme.font("caption"), background=c.sidebar,
                 foreground=c.text_muted, anchor="w").pack(fill="x")

        self.nav: dict[str, NavItem] = {}
        for key, label, icon, shortcut in NAVIGATION:
            item = NavItem(self.sidebar, theme, label, icon, lambda target=key: self.show_page(target),
                           shortcut=shortcut)
            item.pack(fill="x", padx=theme.px(SPACE_S), pady=theme.px(1))
            self.nav[key] = item

        footer = tk.Frame(self.sidebar, background=c.sidebar)
        footer.pack(side="bottom", fill="x", padx=theme.px(SPACE_L), pady=theme.px(SPACE_L))
        row = tk.Frame(footer, background=c.sidebar)
        row.pack(fill="x")
        tk.Label(row, text=theme.icon("shield"), font=theme.icon_font("small"), background=c.sidebar,
                 foreground=c.success).pack(side="left", anchor="n", pady=(theme.px(2), 0))
        self.sidebar_footer_text = tk.Frame(row, background=c.sidebar)
        self.sidebar_footer_text.pack(side="left", fill="x", padx=(theme.px(SPACE_S), 0))
        tk.Label(self.sidebar_footer_text, text="Local only", font=theme.font("caption_strong"),
                 background=c.sidebar, foreground=c.text_secondary, anchor="w").pack(fill="x")
        tk.Label(self.sidebar_footer_text, text="You control AI access", font=theme.font("caption"),
                 background=c.sidebar, foreground=c.text_muted, anchor="w").pack(fill="x")
        tk.Label(self.sidebar_footer_text, text=f"Version {bio_ce.__version__}", font=theme.font("caption"),
                 background=c.sidebar, foreground=c.text_muted, anchor="w").pack(fill="x", pady=(theme.px(SPACE_S), 0))

    def _on_resize(self, event) -> None:
        if event.widget is self.root:
            self._apply_compact(int(event.width) < self.theme.px(SIDEBAR_COMPACT_BELOW))

    def _apply_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        width = SIDEBAR_COMPACT_WIDTH if compact else SIDEBAR_WIDTH
        self.sidebar.configure(width=self.theme.px(width))
        for item in self.nav.values():
            item.set_compact(compact)
        for frame in (self.brand_text, self.sidebar_footer_text):
            if compact:
                frame.pack_forget()
            elif not frame.winfo_manager():
                frame.pack(side="left", fill="x", padx=(self.theme.px(SPACE_S if frame is self.sidebar_footer_text
                                                                       else SPACE_M - 2), 0))

    @property
    def compact(self) -> bool:
        return bool(self._compact)

    # Navigation -----------------------------------------------------------

    def show_page(self, key: str) -> bool:
        target = self._routes[key]
        if self.current is target:
            target.focus_default()
            return True
        if self.current is self.editor and not self.editor.confirm_leave():
            return False
        if self.current is not None:
            self.current.pack_forget()
            self.current.actions.pack_forget()
        self.infobar.hide()
        self.current = target
        target.pack(fill="both", expand=True)
        target.actions.pack(side="right")
        for nav_key, item in self.nav.items():
            item.set_selected(nav_key == target.nav_key)
        self.refresh_header()
        target.on_show()
        target.focus_default()
        return True

    def refresh_header(self) -> None:
        if self.current is None:
            return
        title, subtitle = self.current.heading()
        self.header_title.configure(text=title)
        self.header_subtitle.configure(text=subtitle)

    def refresh_current(self) -> None:
        if self.current is self.editor:
            return
        if self.current is self.connections:
            self.connections.refresh()
            return
        self.host_statuses(refresh=True)
        if self.current is not None:
            self.current.refresh()

    def open_search(self, query: str) -> None:
        if self.show_page("memories"):
            self.memories.query.set(query)
            self.memories.refresh()
            self.memories.search.focus_set()
            self.memories.search.entry.icursor(tk.END)

    def open_memory(self, memory_id: str) -> None:
        if self.show_page("memories"):
            if self.memories.query.get():
                self.memories.query.set("")
            self.memories.refresh(select=memory_id)
            self.memories.tree.focus_set()

    def _bind_shortcuts(self) -> None:
        root = self.root
        for index, (key, *_rest) in enumerate(NAVIGATION, start=1):
            root.bind(f"<Control-Key-{index}>", lambda _e, target=key: self._shortcut(lambda: self.show_page(target)))
        root.bind("<Control-n>", lambda _e: self._shortcut(self.start_new_memory))
        root.bind("<Control-f>", lambda _e: self._shortcut(lambda: self.open_search(self.memories.query.get())))
        root.bind("<Control-s>", lambda _e: self._shortcut(self.save_memory if self.current is self.editor else None))
        root.bind("<Control-e>", lambda _e: self._shortcut(self.start_edit_memory if self.current is self.memories
                                                           else None))
        root.bind("<Control-h>", lambda _e: self._shortcut(self.show_history if self.current is self.memories
                                                           else None))
        root.bind("<F5>", lambda _e: self._shortcut(self.refresh_current))
        root.bind("<Escape>", lambda _e: self._shortcut(self.cancel_edit if self.current is self.editor else None),
                  add="+")

    def _shortcut(self, action: Callable[[], Any] | None) -> str:
        if action is not None and self.root.grab_current() is None:
            action()
        return "break"

    # Shared services ------------------------------------------------------

    def notify(self, kind: str, message: str, *, title: str = "",
               action: tuple[str, Callable[[], object]] | None = None) -> None:
        self.infobar.show(kind, message, title=title, action=action)

    def confirm(self, **options: Any) -> bool:
        return ConfirmDialog(self.root, self.theme, **options).ask()

    def ask_save_path(self, **options: Any) -> str:
        return filedialog.asksaveasfilename(parent=self.root, **options)

    def ask_open_path(self, **options: Any) -> str:
        return filedialog.askopenfilename(parent=self.root, **options)

    def open_path(self, path: Path) -> bool:
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False
        return True

    def reveal_file(self, path: Path) -> None:
        try:
            subprocess.Popen(["explorer.exe", f"/select,{path}"])
        except OSError:
            self.open_path(path.parent)

    def run_task(self, work: Callable[[], Any], on_success: Callable[[Any], None],
                 on_error: Callable[[BaseException], None]) -> None:
        self.tasks.submit(work, on_success, on_error)

    def host_statuses(self, *, refresh: bool) -> dict[str, HostStatus | None]:
        if refresh or not self._host_statuses:
            statuses: dict[str, HostStatus | None] = {}
            for host in ("codex", "claude"):
                try:
                    statuses[host] = self.connection_manager.status(host)
                except Exception:
                    statuses[host] = None
            self._host_statuses = statuses
        return dict(self._host_statuses)

    def data_changed(self, select: str | None = None) -> None:
        """Mark pages stale after a write and refresh the visible one."""
        for page in (self.dashboard, self.memories, self.settings):
            page.stale = True
        if self.current in (self.dashboard, self.memories, self.settings):
            if self.current is self.memories:
                self.memories.refresh(select=select)
            else:
                self.current.refresh()

    def hosts_changed(self) -> None:
        self.host_statuses(refresh=True)
        self.dashboard.stale = True
        for host, card in self.connections.cards.items():
            if not card.busy:
                card.apply(self._host_statuses.get(host))
        if self.current is self.dashboard:
            self.dashboard.refresh()

    def memory_saved(self, saved: MemoryRevision, *, created: bool) -> None:
        self.memories.query.set("")
        self.show_page("memories")
        self.data_changed(select=saved.memory_id)
        self.memories.tree.focus_set()
        title = "Memory saved" if created else f"Saved revision {saved.revision_number}"
        self.notify("success", f"“{preview(saved.title, 60)}” is stored on this PC.", title=title)

    # Compatibility API (used by tests and older callers) -------------------

    @property
    def title_value(self) -> tk.StringVar:
        return self.editor.title_value

    @property
    def source_value(self) -> tk.StringVar:
        return self.editor.source_value

    @property
    def content_value(self) -> tk.Text:
        return self.editor.content.text

    @property
    def query(self) -> tk.StringVar:
        return self.memories.query

    @property
    def selected(self) -> MemoryRevision | None:
        return self.memories.selected

    @property
    def editing(self) -> MemoryRevision | None:
        return self.editor.editing

    @property
    def memory_table(self):
        return self.memories.tree

    def start_new_memory(self) -> None:
        if self.current is self.editor and self.editor.editing is None:
            self.editor.focus_default()
            return
        if self.current is self.editor and not self.editor.confirm_leave():
            return
        self.editor.load(None)
        self.show_page("editor")

    def start_edit_memory(self) -> None:
        record = self.memories.selected
        if record is None:
            self.notify("info", "Select a memory in the list first.")
            return
        self.editor.load(record)
        self.show_page("editor")

    def save_memory(self) -> MemoryRevision | None:
        return self.editor.save_memory()

    def cancel_edit(self) -> None:
        self.editor.cancel_edit()

    def retract_selected(self) -> None:
        self.memories.retract_selected()

    def show_history(self):
        return self.memories.show_history()

    def refresh_memories(self) -> None:
        self.memories.refresh()

    def refresh_home(self) -> None:
        self.dashboard.refresh()

    def refresh_connections(self) -> None:
        self.connections.refresh()

    def connect_host(self, host: str) -> None:
        self.connections.connect_host(host)

    def disconnect_host(self, host: str) -> None:
        self.connections.disconnect_host(host)

    def diagnose_host(self, host: str) -> None:
        self.connections.diagnose_host(host)

    def open_data_folder(self) -> None:
        if not self.open_path(self.paths.user_database.parent):
            self.notify("error", "BIO CE couldn't open the data folder in File Explorer.", title="Folder unavailable")

    def open_connection_backups(self) -> None:
        folder = self.paths.root / "connections" / "backups"
        if not folder.is_dir():
            self.notify("info", "There are no settings backups yet. BIO CE creates one each time you connect or "
                        "disconnect a host.")
            return
        if not self.open_path(folder):
            self.notify("error", "BIO CE couldn't open the backups folder in File Explorer.",
                        title="Folder unavailable")

    def backup_database(self) -> Path | None:
        destination = self.ask_save_path(
            title="Save BIO CE backup",
            defaultextension=".sqlite3",
            initialfile="bio-ce-backup.sqlite3",
            filetypes=(("BIO CE backup", "*.sqlite3"), ("All files", "*.*")),
        )
        if not destination:
            return None
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            created = self.service.create_backup(destination)
        except BackupError as exc:
            self.notify("error", str(exc), title="Backup not created")
            return None
        except Exception:
            self.notify("error", "BIO CE couldn't write the backup file. Check that the folder exists and you can "
                        "save files there.", title="Backup not created")
            return None
        finally:
            self.root.configure(cursor="")
        self.notify("success", f"Saved to {created}. Keep this file private; it contains your memories.",
                    title="Backup created", action=("Show in folder", lambda: self.reveal_file(created)))
        return created

    def restore_database(self) -> bool:
        source = self.ask_open_path(
            title="Choose a BIO CE backup to restore",
            filetypes=(("BIO CE backup", "*.sqlite3"), ("All files", "*.*")),
        )
        if not source:
            return False
        if not self.confirm(
            title="Replace all current memories?",
            message="Every memory currently in BIO CE will be replaced by the contents of this backup.",
            quote=Path(source).name,
            points=(
                "BIO CE checks the backup before changing anything. If the check fails, nothing is replaced.",
                "Close connected AI hosts first; BIO CE can't restore while another program is reading the database.",
                "If you want to keep your current memories, cancel and create a backup first.",
            ),
            confirm_text="Replace memories",
            danger=True,
        ):
            return False
        if self.current is self.editor and not self.editor.confirm_leave():
            return False
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            self.service.restore_backup(source)
        except BackupError as exc:
            self.notify("error", f"{exc} Your current memories were not changed.", title="Restore failed")
            return False
        except Exception:
            self.notify("error", "BIO CE couldn't replace the database. Your current memories and the backup file "
                        "were kept.", title="Restore failed")
            return False
        finally:
            self.root.configure(cursor="")
        self.memories.query.set("")
        self.memories.selected = None
        self.data_changed()
        self.notify("success", "The backup is now your active memory database.", title="Backup restored")
        return True

    def close(self) -> None:
        if self.tasks.busy:
            self.notify("warning", "A host connection change is still running. Wait for it to finish, then close "
                        "BIO CE.", title="Please wait")
            return
        if self.current is self.editor and not self.editor.confirm_leave():
            return
        self.service.close()
        closer = getattr(self.connection_manager, "close", None)
        if callable(closer):
            closer()
        self.root.destroy()


__all__ = ["BIOCEDesktop", "NAVIGATION"]
