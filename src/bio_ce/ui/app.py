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
from bio_ce.engine.community import COMMUNITY_ENGINE_ID, CommunityEngineAdapter
from bio_ce.engine.contract import (
    Capability,
    EngineBackend,
    EngineState,
    EngineStatus,
    EngineUnavailable,
    MemoryView,
)
from bio_ce.engine.external import ExternalEngineAdapter
from bio_ce.engine.presentation import ActionState, EngineBanner, action_states, banner, engine_name
from bio_ce.engine.switching import DEFAULT_SELECTION, EngineSelection, SwitchPhase
from bio_ce.storage.backup import PAIR_MATCHED, BackupError, pair_path
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.exporter import SOURCE_KINDS, SOURCE_LABELS, UNENCRYPTED_NOTICE, ExportOptions, ExportRefused, write_export
from bio_ce.ui.dialogs import ChoiceDialog, ConfirmDialog, ExportDialog, NameDialog, ReviewEditDialog
from bio_ce.ui.format import HOSTS
from bio_ce.ui.i18n import resolve, set_language, t
from bio_ce.ui.pending import PendingDeletes
from bio_ce.ui.hub.common import space_label
from bio_ce.ui.hub.data import ALL_SPACES, INBOX, SUGGESTIONS
from bio_ce.ui.hub.page import HubPage
from bio_ce.ui.pages import Page
from bio_ce.ui.pages.connections import ConnectionsPage
from bio_ce.ui.pages.dashboard import DashboardPage
from bio_ce.ui.pages.importing import ImportPage
from bio_ce.ui.pages.settings import SettingsPage
from bio_ce.ui.tasks import TaskRunner
from bio_ce.ui.theme import (
    CENTER_FROM,
    CONTENT_MAX_WIDTH,
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
from bio_ce.ui.widgets import InfoBar, NavItem, SearchBox, Tooltip, WrapLabel, install_mousewheel

if TYPE_CHECKING:
    from bio_ce.desktop import AppDataPaths, DesktopMemoryService


NAVIGATION = (  # (page, text key, icon, shortcut)
    ("dashboard", "nav.dashboard", "dashboard", "Ctrl+1"),
    ("memories", "nav.memories", "memories", "Ctrl+2"),
    ("connections", "nav.connections", "connections", "Ctrl+3"),
    ("settings", "nav.settings", "settings", "Ctrl+4"),
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
        engine: EngineBackend | None = None,
        engines: dict[str, EngineBackend] | None = None,
        engine_selection: EngineSelection | None = None,
    ) -> None:
        self.root = root
        self.service = service
        # The memory engine this window uses. Community is the default; any other engine must be passed in
        # explicitly together with its selection. This version never switches engines on its own.
        self.engine: EngineBackend = engine if engine is not None else CommunityEngineAdapter(service)
        registry: dict[str, EngineBackend] = {COMMUNITY_ENGINE_ID: self.engine if self.engine.engine_id ==
                                              COMMUNITY_ENGINE_ID else CommunityEngineAdapter(service)}
        registry.update(engines or {})
        registry[self.engine.engine_id] = self.engine
        registry.setdefault("core", ExternalEngineAdapter("core", None))  # reported as not installed
        self.engines = registry
        self.engine_selection = engine_selection or (
            DEFAULT_SELECTION if self.engine.engine_id == COMMUNITY_ENGINE_ID
            else EngineSelection(SwitchPhase.ACTIVE, self.engine.engine_id, 0))
        self.engine_status: EngineStatus | None = None
        self._engine_statuses: dict[str, EngineStatus] = {}
        self._actions: dict[str, ActionState] = {}
        self.paths = paths
        self.connection_manager = connection_manager or MCPConnectionManager(service.database, paths.root)
        control = getattr(self.connection_manager, "control", None)
        try:  # before any screen is built: the app's text language (v0.4.4)
            set_language(resolve(control.ui_language() if control is not None else None))
        except Exception:  # noqa: BLE001 - an unreadable setting: same as Windows
            set_language(resolve(None))
        self.theme = theme or Theme(root)
        self.tasks = TaskRunner(root)
        self.pending = PendingDeletes(self)  # v0.4.4: deletes wait a few seconds for Undo
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
        self.refresh_engine_status()

        self.main = tk.Frame(root, background=c.bg)
        self.main.pack(side="left", fill="both", expand=True)
        gutter = self.theme.px(SPACE_XXL)
        header = tk.Frame(self.main, background=c.bg)
        header.pack(fill="x", padx=gutter, pady=(self.theme.px(SPACE_XL + 4), self.theme.px(SPACE_L + 4)))
        # The page's buttons are packed first: when the header is too narrow the title text is shortened, never a
        # button (a cut-off button ignores clicks).
        self.header_actions = tk.Frame(header, background=c.bg)
        self.header_actions.pack(side="right", anchor="s")
        # v0.4.4 F1: a search above every page; Enter shows the results on the memory screen (which has its own
        # search box in the same place, so this one hides there).
        self.header_query = tk.StringVar(master=root)
        self.header_search = SearchBox(header, self.theme, self.header_query, t("search.everywhere"))
        self.header_search.entry.configure(width=30)
        self.header_search.entry.bind("<Return>", lambda _e: (self._search_from_header(), "break")[1])
        self.header_search.entry.bind("<KP_Enter>", lambda _e: (self._search_from_header(), "break")[1])
        header.bind("<Configure>", self._fit_header_search, add="+")  # shown by _fit_header_search
        titles = tk.Frame(header, background=c.bg)
        self._header_titles = titles
        titles.pack(side="left", fill="x", expand=True)
        self.header_title = tk.Label(titles, font=self.theme.font("display"), background=c.bg,
                                     foreground=c.text, anchor="w")
        self.header_title.pack(fill="x")
        self.header_subtitle = WrapLabel(titles, font=self.theme.font("body"), background=c.bg,
                                         foreground=c.text_secondary)
        self.header_subtitle.pack(fill="x", pady=(self.theme.px(2), 0))

        self.page_host = tk.Frame(self.main, background=c.bg)
        self.page_host.pack(fill="both", expand=True, padx=gutter, pady=(0, self.theme.px(SPACE_XL)))
        self.infobar = InfoBar(self.main, self.theme, before=self.page_host,
                               pack_options={"fill": "x", "padx": gutter, "pady": (0, self.theme.px(SPACE_L))})
        self._header, self._gutter, self._side_pad = header, gutter, gutter
        self.main.bind("<Configure>", self._center_content, add="+")

        self.dashboard = DashboardPage(self, self.page_host)
        self._space_id = "general"
        self._maintenance_after: str | None = None
        # v0.4.4: one memory screen for memories, the inbox, suggestions, and reviews (design §2.2). The add / edit
        # form lives in its drawer; Import is still a page of its own, opened from there and from the dashboard.
        self.memories = HubPage(self, self.page_host)
        self.editor = self.memories.drawer.editor
        self.suggestions = self.memories.suggestions
        self.importer = ImportPage(self, self.page_host)
        self.connections = ConnectionsPage(self, self.page_host)
        self.settings = SettingsPage(self, self.page_host)
        self.pages: dict[str, Page] = {
            "dashboard": self.dashboard,
            "memories": self.memories,
            "connections": self.connections,
            "settings": self.settings,
        }
        self._routes: dict[str, Page] = dict(self.pages, **{"import": self.importer})

        self._bind_shortcuts()
        root.bind("<Configure>", self._on_resize, add="+")
        self.host_statuses(refresh=True)
        self.show_page("dashboard")
        self._apply_compact(root.winfo_width() < self.theme.px(SIDEBAR_COMPACT_BELOW))
        apply_window_chrome(root, c)
        self._maintenance_after = root.after(5000, self.inbox_maintenance)

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
        tk.Label(self.brand_text, text=t("app.edition"), font=theme.font("caption"), background=c.sidebar,
                 foreground=c.text_muted, anchor="w").pack(fill="x")

        self.nav: dict[str, NavItem] = {}
        for key, label, icon, shortcut in NAVIGATION:
            item = NavItem(self.sidebar, theme, t(label), icon, lambda target=key: self.show_page(target),
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
        tk.Label(self.sidebar_footer_text, text=t("app.local_only"), font=theme.font("caption_strong"),
                 background=c.sidebar, foreground=c.text_secondary, anchor="w").pack(fill="x")
        tk.Label(self.sidebar_footer_text, text=t("app.you_control"), font=theme.font("caption"),
                 background=c.sidebar, foreground=c.text_muted, anchor="w").pack(fill="x")
        self.engine_label = tk.Label(self.sidebar_footer_text, text="", font=theme.font("caption"),
                                     background=c.sidebar, foreground=c.text_muted, anchor="w", justify="left")
        self.engine_label.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        tk.Label(self.sidebar_footer_text, text=t("app.version", version=bio_ce.display_version()), font=theme.font("caption"),
                 background=c.sidebar, foreground=c.text_muted, anchor="w").pack(fill="x", pady=(theme.px(SPACE_S), 0))

    def _on_resize(self, event) -> None:
        if event.widget is self.root:
            self._apply_compact(int(event.width) < self.theme.px(SIDEBAR_COMPACT_BELOW))

    def content_side_pad(self, main_width: int, window_width: int) -> int:
        """The space left and right of the pages: the gutter, or more on a big window (§3.3), so the content is at
        most CONTENT_MAX_WIDTH wide and centred."""
        if window_width < self.theme.px(CENTER_FROM):
            return self._gutter
        return max(self._gutter, (main_width - self.theme.px(CONTENT_MAX_WIDTH) + 1) // 2)  # rounded up: never wider

    def _center_content(self, event) -> None:
        if event.widget is not self.main:
            return
        pad = self.content_side_pad(int(event.width), self.root.winfo_width())
        if pad == self._side_pad:
            return
        self._side_pad = pad
        self._header.pack_configure(padx=pad)
        self.page_host.pack_configure(padx=pad)
        self.infobar.set_pack_padx(pad)

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
        if self.current is self.memories and not self.memories.confirm_leave():
            return False
        self.pending.flush()  # leaving the page: a delete waiting for Undo runs now
        if self.current is not None:
            self.current.pack_forget()
            self.current.actions.pack_forget()
        self.infobar.hide()
        self.current = target
        target.pack(fill="both", expand=True)
        target.actions.pack(side="right")
        self._fit_header_search()
        for nav_key, item in self.nav.items():
            item.set_selected(nav_key == target.nav_key)
        self.refresh_badges()
        self.refresh_header()
        target.on_show()
        target.focus_default()
        return True

    def _fit_header_search(self, _event=None) -> None:
        """The search above the page only where the header has room for it beside the title and the page's
        buttons (a title is never cut for it), and never on the memory screen, which has its own."""
        try:
            # The title must fit; the subtitle wraps under it, so it doesn't count.
            free = (self.header_search.master.winfo_width() - self.header_title.winfo_reqwidth()
                    - self.header_actions.winfo_reqwidth() - 2 * self.theme.px(SPACE_M))
        except tk.TclError:
            return
        show = self.current is not self.memories and free >= self.header_search.winfo_reqwidth()
        if show and not self.header_search.winfo_manager():
            self.header_search.pack(side="right", anchor="s", padx=(0, self.theme.px(SPACE_M)),
                                    before=self._header_titles)
        elif not show and self.header_search.winfo_manager():
            self.header_search.pack_forget()

    def _search_from_header(self) -> None:
        query = self.header_query.get().strip()
        self.header_query.set("")
        self.open_search(query)

    def focus_search(self) -> None:
        """Ctrl+F and / (v0.4.4 F1): the memory screen's search there, the search above the page elsewhere."""
        if self.current is not self.memories and self.header_search.winfo_manager():
            self.header_search.focus_set()
        elif self.current is self.memories:
            self.memories.search.focus_set()
            self.memories.search.entry.icursor(tk.END)
        else:  # no room for the search above this page: the memory screen's search
            self.open_search(self.memories.query.get())

    def show_shortcuts(self):
        from bio_ce.ui.dialogs import ShortcutsDialog
        return ShortcutsDialog(self.root, self.theme).show()

    def typing(self) -> bool:
        """True while a text box has the keyboard focus (single-letter keys then type, they don't act)."""
        from bio_ce.ui.hub.keys import TYPING_CLASSES
        try:
            widget = self.root.focus_get() or self.root.focus_lastfor()
        except (KeyError, tk.TclError):
            return False
        return widget is not None and widget.winfo_class() in TYPING_CLASSES

    def refresh_header(self) -> None:
        if self.current is None:
            return
        title, subtitle = self.current.heading()
        self.header_title.configure(text=title)
        self.header_subtitle.configure(text=subtitle)

    def refresh_current(self) -> None:
        if self.current is self.memories and self.memories.drawer.editing:
            return  # the form keeps the user's text
        if self.current is self.connections:
            self.connections.refresh()
            return
        self.host_statuses(refresh=True)
        self.refresh_engine_status()
        if self.current is not None:
            self.current.refresh()

    def open_search(self, query: str) -> None:
        if self.show_page("memories"):
            if self.memories.query.get() != query:
                self.memories.query.set(query)
            self.memories.refresh()
            self.memories.search.focus_set()
            self.memories.search.entry.icursor(tk.END)

    def open_memory(self, memory_id: str) -> None:
        if self.show_page("memories"):
            self.memories.open_memory(memory_id)

    def open_state(self, state: str, *, batch_id: str | None = None) -> None:
        """The memory screen on one of its tabs (memories, inbox, suggestions, reviews)."""
        if self.show_page("memories"):
            self.memories.show_state(state)
            if state == SUGGESTIONS and batch_id is not None:
                self.suggestions.show_batch(batch_id)

    def _bind_shortcuts(self) -> None:
        # The table in bio_ce.ui.shortcuts lists every key; the memory screen binds its own (hub/keys.py).
        root = self.root
        for index, (key, *_rest) in enumerate(NAVIGATION, start=1):
            root.bind(f"<Control-Key-{index}>", lambda _e, target=key: self._shortcut(lambda: self.show_page(target)))
        root.bind("<Control-n>", lambda _e: self._shortcut(self.start_new_memory))
        root.bind("<Control-f>", lambda _e: self._shortcut(self.focus_search))
        root.bind("<slash>", lambda _e: None if self.typing() else self._shortcut(self.focus_search))
        root.bind("<question>", lambda _e: None if self.typing() else self._shortcut(self.show_shortcuts))
        root.bind("<F5>", lambda _e: self._shortcut(self.refresh_current))

    def _shortcut(self, action: Callable[[], Any] | None) -> str:
        if action is not None and self.root.grab_current() is None:
            action()
        return "break"

    # Memory engine ----------------------------------------------------------

    def refresh_engine_status(self) -> None:
        """Re-read every engine's status and recompute which actions the active engine allows."""
        statuses: dict[str, EngineStatus] = {}
        for engine_id, backend in self.engines.items():
            try:
                statuses[engine_id] = backend.status()
            except Exception:
                statuses[engine_id] = EngineStatus(engine_id, EngineState.ERROR,
                                                   "The engine status could not be read.")
        self._engine_statuses = statuses
        binding = self.engine_selection.binding
        self.engine_status = statuses.get(binding.engine_id) if binding is not None else None
        support = ({capability: self.engine.support(capability) for capability in Capability}
                   if binding is not None and binding.engine_id == self.engine.engine_id else {})
        self._actions = action_states(self.engine_selection, self.engine_status, support)
        if hasattr(self, "engine_label"):
            c = self.theme.colors
            self.engine_label.configure(text=self._engine_label_text(),
                                        foreground=c.text_muted if self.engine_banner().connected else c.warning)

    def _engine_label_text(self) -> str:
        binding = self.engine_selection.binding
        if binding is None:
            return t("app.engine.none")
        name = engine_name(binding.engine_id, self.engine_status)
        if self.engine_status is None or not self.engine_status.ready:
            state = self.engine_status.state.value.replace("_", " ") if self.engine_status else "error"
            return f"{name}: {state}"
        return t("app.engine.name", name=name)

    def engine_statuses(self) -> tuple[EngineStatus, ...]:
        return tuple(self._engine_statuses.values())

    def engine_banner(self) -> EngineBanner:
        return banner(self.engine_selection, self.engine_status)

    def allowed(self, action: str) -> ActionState:
        return self._actions.get(action, ActionState(action, False, t("app.not_available")))

    def require_action(self, action: str) -> bool:
        """True when the active engine allows ``action``; otherwise tell the user why not."""
        state = self.allowed(action)
        if not state.enabled:
            self.notify("warning", state.note or t("app.not_available"), title=t("app.not_available_title"))
        return state.enabled

    def gate(self, button, action: str) -> None:
        """Disable ``button`` when the active engine does not allow ``action``; Community allows all."""
        state = self.allowed(action)
        if not state.enabled:
            button.set_enabled(False)
            Tooltip(button, self.theme, state.note)

    def memory_engine(self) -> EngineBackend:
        """The engine for reads and writes now, or :class:`EngineUnavailable`. Never another engine."""
        if self.engine_selection.binding is None:
            raise EngineUnavailable("No memory engine is connected.")
        if self.engine_status is None or not self.engine_status.ready:
            raise EngineUnavailable("The memory engine is unavailable.")
        return self.engine

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

    def ask_folder(self, **options: Any) -> str:
        return filedialog.askdirectory(parent=self.root, mustexist=True, **options)

    def ask_name(self, **options: Any) -> str | None:
        return NameDialog(self.root, self.theme, **options).ask()

    def ask_choice(self, **options: Any) -> str | None:
        return ChoiceDialog(self.root, self.theme, **options).ask()

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
            for host in HOSTS:
                try:
                    statuses[host] = self.connection_manager.status(host)
                except Exception:
                    statuses[host] = None
            self._host_statuses = statuses
        return dict(self._host_statuses)

    def data_changed(self, select: str | None = None) -> None:
        """Mark pages stale after a write and refresh the visible one."""
        # Connections too: an import makes reviews and Undo import closes them; its list stayed at 3 while the
        # badge said 1 (GUI check, 2026-11-16).
        connections = self.pages.get("connections")
        for page in (self.dashboard, self.memories, self.settings, self.importer, connections):
            if page is not None:
                page.stale = True
        self.refresh_badges()
        if self.current in (self.dashboard, self.memories, self.settings, connections):
            if self.current is self.memories:
                self.memories.refresh(select=select)
            else:
                self.current.refresh()

    def pending_review_count(self) -> int | None:
        """Review items waiting for the user, or None when the control database cannot be read."""
        control = getattr(self.connection_manager, "control", None)
        if control is None:
            return None
        try:
            return int(control.pending_review_count())
        except Exception:  # noqa: BLE001 - a count must never break the window
            return None

    def pending_cleanup_count(self) -> int | None:
        """Inbox items to sort: proposed discards plus sorting suggestions; None when the control file can't be read."""
        control = getattr(self.connection_manager, "control", None)
        if control is None:
            return None
        try:
            return int(control.pending_cleanup_count()) + int(control.pending_proposal_count())
        except Exception:  # noqa: BLE001 - a count must never break the window
            return None

    def connection_problem(self) -> bool:
        """A host whose settings need attention (a conflicting entry); shown as "!" on Connections."""
        return any(status is not None and status.configuration_conflict
                   for status in self._host_statuses.values())

    def refresh_badges(self) -> None:
        """v0.4.4 owner decision Q1: the only number is what waits for the user's decision, the review queue, on
        Memories (where the reviews are now). Suggestions and discard proposals show in the memory screen's tabs."""
        reviews = self.pending_review_count()
        if "memories" in self.nav:
            self.nav["memories"].set_badge(reviews or 0)
        if "connections" in self.nav:
            self.nav["connections"].set_alert(self.connection_problem())
        dashboard = getattr(self, "dashboard", None)
        if dashboard is not None:
            dashboard.show_review_count(reviews)

    # Spaces and the inbox -------------------------------------------------

    def spaces(self) -> tuple:
        """General, then Personal while it is on, then the project spaces."""
        control = getattr(self.connection_manager, "control", None)
        if control is None:
            return ()
        try:
            spaces = control.spaces()
            personal = (PERSONAL_SPACE,) if control.personal_enabled() else ()
        except Exception:  # noqa: BLE001
            return ()
        general = tuple(space for space in spaces if space.is_general)
        return general + personal + tuple(space for space in spaces if not space.is_general)

    def personal_enabled(self) -> bool:
        control = getattr(self.connection_manager, "control", None)
        try:
            return bool(control is not None and control.personal_enabled())
        except Exception:  # noqa: BLE001
            return False

    def set_personal_enabled(self, enabled: bool) -> bool:
        """Turn Personal on or off. Off keeps its memories, removes every host's access, and shows General."""
        control = getattr(self.connection_manager, "control", None)
        if control is None:
            return False
        try:
            control.set_personal_enabled(enabled)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.notify("error", str(exc) or t("app.personal_failed"), title=t("space.personal"))
            return False
        if not enabled and self._space_id == PERSONAL_SPACE.space_id:
            general = next((space for space in self.spaces() if space.is_general), None)
            self._space_id = "general"
            if general is not None:
                self.service.use_space(general.curated)
        if not enabled:
            drawer = self.memories.drawer
            shown = drawer.item.space if drawer.item is not None else drawer.editor.space
            if shown is not None and shown.is_personal:
                self.memories.close_drawer(force=True)
            if self.memories.space_filter == PERSONAL_SPACE.space_id:
                self.memories.space_filter = "general"
        self.data_changed()
        self.hosts_changed()
        return True

    def ask_export(self) -> dict | None:
        return ExportDialog(self.root, self.theme, spaces=self.spaces(), current=self._space_id,
                            sources=[(key, SOURCE_LABELS[key]) for key in SOURCE_KINDS]).ask()

    def export_memories(self) -> Path | None:
        """Export chosen memories as a "[date] - memory" .md file. Never overwrites; warns about Personal."""
        if not self.require_action("browse"):
            return None
        chosen = self.ask_export()
        if not chosen:
            return None
        options = ExportOptions(**chosen)
        personal = "personal" in options.space_ids
        if personal and not self.confirm(
            title=t("hub.selection.personal_title"),
            message=t("hub.selection.personal_message"),
            points=(t("app.unencrypted"),), confirm_text=t("hub.selection.personal_button")):
            return None
        try:
            result = self.service.export_text(self.spaces(), options, personal_allowed=personal and
                                              self.personal_enabled())
        except ExportRefused as exc:
            self.notify("warning", str(exc), title=t("hub.selection.not_exported"))
            return None
        except Exception:  # noqa: BLE001 - shown to the user
            self.notify("error", t("app.export.read_failed"), title=t("hub.selection.not_exported"))
            return None
        from datetime import date as _date
        path = self.ask_save_path(title=t("app.export.title"), defaultextension=".md",
                                  initialfile=f"bio-ce-export-{_date.today().isoformat()}.md",
                                  filetypes=((t("hub.selection.file_type"), "*.md"),))
        if not path:
            return None
        try:
            written = write_export(path, result.text)
        except ExportRefused as exc:
            self.notify("warning", str(exc), title=t("hub.selection.not_exported"))
            return None
        except OSError:
            self.notify("error", t("app.export.write_failed"), title=t("hub.selection.not_exported"))
            return None
        self.notify("success", t("hub.selection.exported", count=result.count) + " " + t("app.unencrypted"),
                    title=t("hub.selection.exported_title"),
                    action=(t("hub.selection.show_folder"), lambda: self.reveal_file(written)))
        return written

    def move_memories(self, memory_ids: list[str], target, *, inbox: bool = False, source=None,
                      notify: bool = True) -> int | None:
        """Move memories (or inbox items) of ``source`` (a Space; default the shown one) to ``target`` after an
        automatic backup. The memory screen's notice adds an Undo that moves them back the same way."""
        control = getattr(self.connection_manager, "control", None)
        if control is None or not memory_ids or not self.require_action("edit"):
            return None
        if target.is_personal and not self.personal_enabled():
            self.notify("warning", t("hub.move.personal_off"), title=t("hub.move.personal_off_title"))
            return None
        self.pending.flush()  # a waiting delete of these runs first, in the space it was made in
        before = self.service.scope
        try:
            if source is not None:
                self.service.use_space(source.curated)
            result = self.service.move_memories(control, memory_ids, target.curated, inbox=inbox)
        except Exception:  # noqa: BLE001 - shown to the user
            self.notify("error", t("hub.move.failed"), title=t("hub.move.failed_title"))
            return None
        finally:
            self.service.use_space(before)
        self.memories.close_drawer_for(memory_ids)
        self.data_changed()
        moved = int(result.get("moved", 0))
        if notify:
            self.notify("success", t("hub.move.done", count=moved, space=space_label(target)), title=t("hub.move.title"))
        return moved

    def current_space(self):
        return next((space for space in self.spaces() if space.space_id == self._space_id), None)

    def set_space(self, space_id: str, *, refresh: bool = True) -> None:
        """Show one space on the memory screen (its space chip); new memories go there too."""
        space = next((item for item in self.spaces() if item.space_id == space_id), None)
        if space is None or not self.require_action("browse"):
            return
        if refresh and self.memories.space_filter != space_id:
            if self.memories.drawer_open and not self.memories.close_drawer():
                return
            self.memories.space_filter = space_id
            self.memories.stale = True
        if space_id == self._space_id and not refresh:
            return
        self._space_id = space_id
        self.service.use_space(space.curated)
        if refresh:
            self.data_changed()

    def inbox_count_all(self) -> int:
        """Inbox items of every space (the dashboard's count line)."""
        try:
            return len(self.memories.data.items(INBOX, ALL_SPACES))
        except Exception:  # noqa: BLE001
            return 0

    def cleanup_proposals(self) -> tuple:
        control = getattr(self.connection_manager, "control", None)
        if control is None:
            return ()
        try:
            return control.curation_items()
        except Exception:  # noqa: BLE001
            return ()

    def edit_before_saving(self, *, title: str, content: str, reason: str) -> tuple[str, str] | None:
        return ReviewEditDialog(self.root, self.theme, title=title, content=content, reason=reason).ask()

    def inbox_maintenance(self) -> None:
        """Daily inbox pass (expiry proposals, due discards); every two minutes while a clean-up waits."""
        self._maintenance_after = None
        control = getattr(self.connection_manager, "control", None) if self.allowed("review").enabled else None
        delay = 24 * 60 * 60 * 1000
        if control is not None:
            try:
                result = self.service.run_inbox_expiry(control)
            except Exception:  # noqa: BLE001 - retried on the next pass
                result = None
            if result is not None:
                if result.proposed and not self._notice_busy():
                    self.notify("info", t("hub.cleanup.proposed", count=result.proposed),
                                title=t("hub.cleanup.proposed_title"),
                                action=(t("hub.open_inbox"), lambda: self.open_state(INBOX)))
                if result.proposed or result.discarded:
                    self.data_changed()
                if result.waiting_cleanup:
                    delay = 2 * 60 * 1000
            # The "Open suggestions" notice never showed (every caller was quiet; inventory §13 item 1): the daily
            # pass now says so, unless another notice (an Undo, a result) is on screen.
            self.find_suggestions(quiet=self._notice_busy())
        try:
            self._maintenance_after = self.root.after(delay, self.inbox_maintenance)
        except tk.TclError:
            pass

    def find_suggestions(self, *, batch_id: str | None = None, quiet: bool = False) -> int:
        """Look for sorting suggestions (daily, after an import, or on request); never fails the caller."""
        control = getattr(self.connection_manager, "control", None)
        if control is None or not self.allowed("review").enabled:
            return 0
        try:
            added = self.service.curation(control, self.spaces()).find(batch_id=batch_id)
        except Exception:  # noqa: BLE001 - tried again on the next pass
            return 0
        if added:
            self.refresh_badges()
            self.memories.stale = True
            if self.current is self.memories:
                self.memories.refresh()
            if not quiet:
                self.notify("info", t("hub.sugg.waiting", count=added), title=t("hub.sugg.title"),
                            action=(t("hub.open_suggestions"), lambda: self.open_state(SUGGESTIONS)))
        return added

    def _notice_busy(self) -> bool:
        """A notice is on screen (for example an Undo); background news must not replace it."""
        return bool(self.infobar.visible or self.pending.hidden())

    def schedule_cleanup_retry(self) -> None:
        if self._maintenance_after is not None:
            try:
                self.root.after_cancel(self._maintenance_after)
            except tk.TclError:
                pass
        self._maintenance_after = self.root.after(2 * 60 * 1000, self.inbox_maintenance)

    def hosts_changed(self) -> None:
        self.refresh_badges()
        self.host_statuses(refresh=True)
        self.dashboard.stale = True
        for host, card in self.connections.cards.items():
            if not card.busy:
                card.apply(self._host_statuses.get(host))
        if self.current is self.dashboard:
            self.dashboard.refresh()

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
    def selected(self) -> MemoryView | None:
        return self.memories.selected

    @property
    def editing(self) -> MemoryView | None:
        return self.editor.editing

    def start_new_memory(self) -> None:
        """Ctrl+N and every Add button: the add form in the memory screen's drawer (the editor page is gone)."""
        self.memories.new_memory()

    def start_edit_memory(self) -> None:
        drawer = self.memories.drawer
        if drawer.record is None or drawer.mode != "memories":
            self.notify("info", t("hub.select_first"))
            return
        if self.require_action("edit"):
            drawer.start_edit()

    def save_memory(self) -> MemoryView | None:
        return self.editor.save_memory()

    def cancel_edit(self) -> None:
        self.editor.cancel_edit()

    def retract_selected(self) -> bool:
        """Delete the memory open in the drawer (or the selected cards): it waits for Undo (v0.4.4 §3.2)."""
        items = self.memories.chosen_items() or ([self.memories.drawer.item] if self.memories.drawer.item else [])
        return self.memories.delete_items(items)

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
            self.notify("error", t("app.folder.data_failed"), title=t("app.folder.unavailable"))

    def open_connection_backups(self) -> None:
        folder = self.paths.root / "connections" / "backups"
        if not folder.is_dir():
            self.notify("info", t("app.folder.no_backups"))
            return
        if not self.open_path(folder):
            self.notify("error", t("app.folder.backups_failed"), title=t("app.folder.unavailable"))

    def backup_database(self) -> Path | None:
        if not self.require_action("backup"):
            return None
        destination = self.ask_save_path(
            title=t("app.backup.save_title"),
            defaultextension=".sqlite3",
            initialfile="bio-ce-backup.sqlite3",
            filetypes=((t("app.backup.file_type"), "*.sqlite3"), (t("app.all_files"), "*.*")),
        )
        if not destination:
            return None
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            created = self.service.create_backup(destination)
        except BackupError as exc:
            self.notify("error", str(exc), title=t("app.backup.not_created"))
            return None
        except Exception:
            self.notify("error", t("app.backup.write_failed"), title=t("app.backup.not_created"))
            return None
        finally:
            self.root.configure(cursor="")
        pair = pair_path(created)
        saved = (t("app.backup.saved_pair", name=created.name, pair=pair.name, folder=created.parent)
                 if pair.exists() else t("app.backup.saved_one", path=created))
        self.notify("success", saved, title=t("app.backup.created"),
                    action=(t("hub.selection.show_folder"), lambda: self.reveal_file(created)))
        return created

    def restore_database(self) -> bool:
        if not self.require_action("restore"):
            return False
        source = self.ask_open_path(
            title=t("app.restore.choose"),
            filetypes=((t("app.backup.file_type"), "*.sqlite3"), (t("app.all_files"), "*.*")),
        )
        if not source:
            return False
        if not self.confirm(
            title=t("app.restore.title"),
            message=t("app.restore.message"),
            quote=Path(source).name,
            points=(t("app.restore.point_check"), t("app.restore.point_connections"), t("app.restore.point_close"),
                    t("app.restore.point_safety")),
            confirm_text=t("app.restore.button"),
            danger=True,
        ):
            return False
        if not self.memories.confirm_leave():
            return False
        self.pending.flush()  # a waiting delete runs on the memories it was made for, before they are replaced
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            report = self.service.restore_backup(source, control=getattr(self.connection_manager, "control", None))
        except BackupError as exc:
            self.notify("error", f"{exc} " + t("app.restore.unchanged"), title=t("app.restore.failed"))
            return False
        except Exception:
            self.notify("error", t("app.restore.replace_failed"), title=t("app.restore.failed"))
            return False
        finally:
            self.root.configure(cursor="")
        self.memories.query.set("")
        self.memories.close_drawer(force=True)
        self.data_changed()
        self.refresh_badges()
        message = t("app.restore.done")
        if report.get("pair") != PAIR_MATCHED:
            message += " " + t("app.restore.memories_only")
        restored = [name for name in report.get("restored_spaces", ()) if name.startswith("project:")]
        if restored:
            message += " " + t("app.restore.spaces_back", count=len(restored))
        if report.get("reviews_failed"):
            message += " " + t("app.restore.reviews_closed", count=report["reviews_failed"])
        self.notify("success", message, title=t("app.restore.restored"))
        return True

    def close(self) -> None:
        if self.tasks.busy:
            self.notify("warning", t("app.close.busy"), title=t("app.close.wait"))
            return
        if not self.memories.confirm_leave():
            return
        try:
            self.pending.flush()  # a delete waiting for Undo runs before the app closes
        except Exception:  # noqa: BLE001 - closing must go on; the delete reports its own failure
            pass
        for backend in self.engines.values():
            try:
                backend.close()  # the Community adapter leaves the service to the line below
            except Exception:
                pass
        if self._maintenance_after is not None:
            try:
                self.root.after_cancel(self._maintenance_after)
            except tk.TclError:
                pass
        self.service.close()
        closer = getattr(self.connection_manager, "close", None)
        if callable(closer):
            closer()
        self.root.destroy()


__all__ = ["BIOCEDesktop", "NAVIGATION"]
