# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Connections: register BIO CE's MCP server with Codex (CLI and desktop app) or Claude Code."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from tkinter import ttk
import os
from pathlib import Path
import tkinter as tk

from bio_ce import codex_options, memory_skill
from bio_ce.connections import (
    CodeModeResult,
    ConnectionResult,
    DiagnosticCheck,
    HostStatus,
    MCPConnectionConflict,
    MCPConnectionError,
    SkillResult,
    auto_memory_support,
)
from bio_ce.control_store import (
    MODE_AUTO_MEMORY,
    MODE_PAUSED,
    MODE_READ_ONLY,
    AuditEntry,
)
from bio_ce.server_registry import ServerRecord, end_idle, running
from bio_ce.ui.dialogs import TextViewerDialog
from bio_ce.ui.format import HOST_COMMANDS, HOSTS, host_name, preview, relative_time
from bio_ce.ui.hub.common import when
from bio_ce.ui.hub.data import REVIEWS
from bio_ce.ui.i18n import t
from bio_ce.ui.pages import Page
from bio_ce.ui.pages.dashboard import host_pill
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import Button, Card, Pill, ScrollFrame, WrapLabel, caption_label, section_label


class _Texts(Mapping):
    """A table of texts built when it is read, so it follows the app's language (v0.4.4 U5)."""

    def __init__(self, build: Callable[[], dict]) -> None:
        self._build = build

    def __getitem__(self, key):
        return self._build()[key]

    def __iter__(self) -> Iterator:
        return iter(self._build())

    def __len__(self) -> int:
        return len(self._build())


HOST_DESCRIPTIONS = _Texts(lambda: {
    "codex": t("connections.host.codex"),
    "claude": t("connections.host.claude"),
    "claude_desktop": t("connections.host.claude_desktop"),
})
DESKTOP = "claude_desktop"


def desktop_restart() -> str:
    return t("connections.desktop.restart")


def desktop_skill_note() -> str:
    return t("connections.skill.desktop_note")


def app_closed_note() -> str:
    return t("connections.app_closed_note")


SKILL_LABELS = _Texts(lambda: {
    memory_skill.ABSENT: t("connections.skill.absent"),
    memory_skill.CURRENT: t("connections.skill.current"),
    memory_skill.OUTDATED: t("connections.skill.outdated"),
    memory_skill.MODIFIED: t("connections.skill.modified"),
})
SKILL_ACTIONS = _Texts(lambda: {
    memory_skill.ABSENT: t("connections.action.install"),
    memory_skill.CURRENT: t("connections.action.remove"),
    memory_skill.OUTDATED: t("connections.action.update"),
    memory_skill.MODIFIED: t("connections.action.replace"),
})
CODE_MODE_LABELS = _Texts(lambda: {
    codex_options.APPLIED: t("connections.code_mode.applied"),
    codex_options.MISSING: t("connections.off"),
    codex_options.USER_SET: t("connections.code_mode.user_set"),
})
PROVIDER_EXAMPLES = _Texts(lambda: {
    "codex": t("connections.provider.codex"),
    "claude": t("connections.provider.claude"),
    "claude_desktop": t("connections.provider.claude_desktop"),
})
# The access modes as this screen shows them (control_store.MODE_LABELS keeps the English names for the service).
MODE_TEXTS = _Texts(lambda: {
    MODE_READ_ONLY: t("connections.mode.read_only"),
    MODE_AUTO_MEMORY: t("connections.mode.auto_memory"),
    MODE_PAUSED: t("connections.mode.paused"),
})
# v0.4.4 §9.2: "End idle servers…" ends only servers with no request for this long. It runs only when the user
# asks: whether a host starts a new server after one is ended (spike S-MCP) is not known yet, so nothing ends
# servers on its own.
IDLE_SERVER_SECONDS = 12 * 3600
_OUTCOME_STYLE = {
    "pass": ("success", "success"),
    "fail": ("error", "danger"),
    "info": ("info", "info"),
    "skip": ("dot", "text_muted"),
}


def settings_summary(settings: dict | None) -> str:
    """The space and saving settings a connection uses, for the Connect message ("Use all project spaces: on")."""
    settings = settings or {"all_projects": True, "save_mode": "curated"}
    projects = t("connections.summary.all") if settings.get("all_projects", True) \
        else t("connections.summary.general_only")
    saving = t("connections.summary.collect") if settings.get("save_mode") == "collect" \
        else t("connections.summary.curated")
    return t("connections.summary", projects=projects, saving=saving)


def host_message(host: str, status: HostStatus | None) -> str:
    name = host_name(host)
    command = HOST_COMMANDS[host]
    if status is None:
        return t("connections.status.unchecked", name=name)
    if not status.installed and host == DESKTOP:
        return t("connections.status.desktop_missing")
    if not status.installed:
        return t("connections.status.missing", command=command, name=name)
    if status.configuration_conflict:
        return t("connections.status.conflict", name=name)
    if status.connected and status.legacy:
        return t("connections.status.legacy", name=name)
    if status.connected and status.mode == MODE_AUTO_MEMORY:
        return t("connections.status.auto_memory", name=name)
    if status.connected and status.mode == MODE_PAUSED:
        return t("connections.status.paused", name=name)
    if status.connected:
        return t("connections.status.read_only", name=name)
    return t("connections.status.installed", name=name)


ACTIVITY_LABELS = _Texts(lambda: {
    "created": (t("connections.activity.created"), "success"),
    "updated": (t("connections.activity.updated"), "success"),
    "queued": (t("connections.activity.queued"), "info"),
    "duplicate": (t("connections.activity.duplicate"), "neutral"),
    "rejected": (t("connections.activity.rejected"), "warning"),
    "denied": (t("connections.activity.denied"), "warning"),
    "rate-limited": (t("connections.activity.rate_limited"), "warning"),
    "conflict": (t("connections.activity.conflict"), "warning"),
    "approved": (t("connections.activity.approved"), "success"),
    "rejected-by-user": (t("connections.activity.rejected_by_user"), "neutral"),
    "failed": (t("connections.activity.failed"), "danger"),
})


class HostCard(Card):
    def __init__(self, page: ConnectionsPage, master: tk.Misc, host: str) -> None:
        theme = page.theme
        super().__init__(master, theme, padding=SPACE_L + 4)
        c = theme.colors
        self.page = page
        self.host = host
        self.status: HostStatus | None = None
        self.busy = False
        body = self.body

        header = tk.Frame(body, background=c.surface)
        header.pack(fill="x")
        tile = tk.Frame(header, background=c.surface_alt, width=theme.px(40), height=theme.px(40))
        tile.pack(side="left", anchor="n")
        tile.pack_propagate(False)
        tk.Label(tile, text=theme.icon("terminal") or ">_", font=theme.icon_font("large") or theme.font("body_strong"),
                 background=c.surface_alt, foreground=c.text_secondary).place(relx=0.5, rely=0.5, anchor="center")
        names = tk.Frame(header, background=c.surface)
        names.pack(side="left", fill="x", expand=True, padx=(theme.px(SPACE_M + 2), 0))
        section_label(names, theme, host_name(host)).pack(fill="x")
        caption_label(names, theme, HOST_DESCRIPTIONS[host], muted=True).pack(fill="x")
        self.pill = Pill(header, theme, t("connections.checking"), "info")
        self.pill.pack(side="right", anchor="n")

        self.message = WrapLabel(body, font=theme.font("body"), foreground=c.text_secondary)
        self.message.pack(fill="x", pady=(theme.px(SPACE_M + 2), 0))

        # Being connected and the host's model being able to use Auto memory are shown separately.
        support = auto_memory_support(host)
        self.support = support
        capability = tk.Frame(body, background=c.surface)
        capability.pack(fill="x", pady=(theme.px(SPACE_S + 2), 0))
        self.capability = capability
        tk.Label(capability, text=t("connections.auto_support"), font=theme.font("caption_strong"),
                 background=c.surface, foreground=c.text_muted, anchor="w").pack(side="left")
        self.support_pill = Pill(capability, theme, support.summary,
                                 {"available": "success", "limited": "warning"}.get(support.level, "neutral"))
        self.support_pill.pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.support_detail = WrapLabel(body, support.detail, font=theme.font("caption"), foreground=c.text_muted)
        self.support_detail.pack(fill="x", pady=(theme.px(SPACE_XS), 0))

        self.access = tk.Frame(body, background=c.surface)
        modes = tk.Frame(self.access, background=c.surface)
        modes.pack(fill="x")
        tk.Label(modes, text=t("connections.row.access"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, width=12, anchor="w").pack(side="left")
        self.mode_buttons: dict[str, Button] = {}
        tips = {
            MODE_READ_ONLY: t("connections.mode.read_only_tip"),
            MODE_AUTO_MEMORY: t("connections.mode.auto_memory_tip"),
            MODE_PAUSED: t("connections.mode.paused_tip"),
        }
        for mode in (MODE_READ_ONLY, MODE_AUTO_MEMORY, MODE_PAUSED):
            button = Button(modes, theme, MODE_TEXTS[mode], tooltip=tips[mode],
                            command=lambda m=mode: page.set_mode(host, m))
            button.pack(side="left", padx=(0, theme.px(SPACE_XS)))
            self.mode_buttons[mode] = button
        spaces = tk.Frame(self.access, background=c.surface)
        spaces.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        tk.Label(spaces, text=t("connections.row.spaces"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, width=12, anchor="w").pack(side="left")
        self.spaces_label = tk.Label(spaces, text="", font=theme.font("body"), background=c.surface,
                                     foreground=c.text_secondary, anchor="w")
        self.spaces_label.pack(side="left")
        self.spaces_button = Button(spaces, theme, t("connections.spaces.use_general_only"), variant="link",
                                    command=lambda: page.toggle_projects(host))
        self.spaces_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.personal_row = tk.Frame(self.access, background=c.surface)
        tk.Label(self.personal_row, text=t("space.personal"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, width=12, anchor="w").pack(side="left")
        self.personal_label = tk.Label(self.personal_row, text="", font=theme.font("body"), background=c.surface,
                                       foreground=c.text_secondary, anchor="w")
        self.personal_label.pack(side="left")
        self.personal_button = Button(self.personal_row, theme, t("connections.personal.allow"), variant="link",
                                      command=lambda: page.change_personal(host))
        self.personal_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        saving = tk.Frame(self.access, background=c.surface)
        saving.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.saving_row = saving
        tk.Label(saving, text=t("connections.row.saving"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, width=12, anchor="w").pack(side="left")
        self.saving_label = tk.Label(saving, text="", font=theme.font("body"), background=c.surface,
                                     foreground=c.text_secondary, anchor="w")
        self.saving_label.pack(side="left")
        self.saving_button = Button(saving, theme, t("connections.saving.to_collect"), variant="link",
                                    command=lambda: page.toggle_save_mode(host))
        self.saving_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        hooks = tk.Frame(self.access, background=c.surface)
        if host != DESKTOP:
            hooks.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        tk.Label(hooks, text=t("connections.row.hooks"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, width=12, anchor="w").pack(side="left")
        self.hooks_label = tk.Label(hooks, text="", font=theme.font("body"), background=c.surface,
                                    foreground=c.text_secondary, anchor="w")
        self.hooks_label.pack(side="left")
        self.hooks_button = Button(hooks, theme, t("connections.action.install"), variant="link",
                                   command=lambda: page.toggle_hooks(host))
        self.hooks_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.code_mode_label: tk.Label | None = None
        self.code_mode_button: Button | None = None
        if host == "codex":
            code_mode = tk.Frame(self.access, background=c.surface)
            code_mode.pack(fill="x", pady=(theme.px(SPACE_S), 0))
            tk.Label(code_mode, text=t("connections.row.code_mode"), font=theme.font("body_strong"),
                     background=c.surface, foreground=c.text, width=12, anchor="w").pack(side="left")
            self.code_mode_label = tk.Label(code_mode, text="", font=theme.font("body"), background=c.surface,
                                            foreground=c.text_secondary, anchor="w")
            self.code_mode_label.pack(side="left")
            self.code_mode_button = Button(code_mode, theme, t("connections.action.apply"), variant="link",
                                           command=lambda: page.apply_code_mode(host))
        skill = tk.Frame(self.access, background=c.surface)
        skill.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        tk.Label(skill, text=t("connections.row.skill"), font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, width=12, anchor="w").pack(side="left")
        self.skill_label = tk.Label(skill, text="", font=theme.font("body"), background=c.surface,
                                    foreground=c.text_secondary, anchor="w")
        self.skill_label.pack(side="left")
        self.skill_button = Button(skill, theme, t("connections.action.install"), variant="link",
                                   command=lambda: page.toggle_skill(host))
        if host == DESKTOP:
            self.skill_button.set_text(t("connections.skill.save_zip"))
            self.skill_button.set_command(lambda: page.save_skill_zip(host))
        self.skill_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        Button(skill, theme, t("connections.skill.preview"), variant="link",
               command=lambda: page.preview_skill(host)).pack(
            side="left", padx=(theme.px(SPACE_XS), 0))
        # v0.4.4 §9.2: the BIO CE MCP servers this connection's host keeps running (one per conversation or session).
        self.servers_row = tk.Frame(self.access, background=c.surface)
        tk.Label(self.servers_row, text=t("connections.servers.label"), font=theme.font("body_strong"),
                 background=c.surface, foreground=c.text, width=12, anchor="w").pack(side="left")
        self.servers_label = tk.Label(self.servers_row, text="", font=theme.font("body"), background=c.surface,
                                      foreground=c.text_secondary, anchor="w")
        self.servers_label.pack(side="left")
        self.progress = ttk.Progressbar(body, mode="indeterminate", style="BIO.Horizontal.TProgressbar")

        actions = tk.Frame(body, background=c.surface)
        actions.pack(fill="x", pady=(theme.px(SPACE_L), 0))
        self.actions = actions
        self.primary = Button(actions, theme, t("connections.action.connect"), icon="connections", variant="primary",
                              command=lambda: page.connect_host(host))
        self.primary.pack(side="left")
        self.diagnose_button = Button(actions, theme, t("connections.action.diagnose"), icon="diagnostics",
                                      command=lambda: page.diagnose_host(host),
                                      tooltip=t("connections.action.diagnose_tip"))
        self.diagnose_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.results = tk.Frame(body, background=c.surface)
        self.checks: tuple[DiagnosticCheck, ...] = ()

    def apply(self, status: HostStatus | None) -> None:
        self.status = status
        self.support = auto_memory_support(self.host, status.code_mode if status is not None else None)
        self.support_detail.configure(text=self.support.detail)
        text, kind = host_pill(status)
        self.pill.set(text, kind)
        self.message.configure(text=host_message(self.host, status))
        managed = status is not None and status.connected and not status.legacy and status.connection_id
        if managed:
            self.access.pack(fill="x", pady=(self.page.theme.px(SPACE_M), 0), after=self.message)
            for mode, button in self.mode_buttons.items():
                button.set_variant("primary" if status.mode == mode else "secondary")
            settings = self.page.connection_settings(self.host) or {}
            all_projects = bool(settings.get("all_projects", True))
            self.spaces_label.configure(text=t("connections.spaces.all") if all_projects
                                        else t("connections.spaces.general_only"))
            self.spaces_button.set_text(t("connections.spaces.use_general_only") if all_projects
                                        else t("connections.spaces.use_all"))
            personal = self.page.personal_access(self.host)
            if personal is None:
                self.personal_row.pack_forget()
            else:
                self.personal_row.pack(fill="x", pady=(self.page.theme.px(SPACE_S), 0), before=self.saving_row)
                read, write = personal
                self.personal_label.configure(text=t("connections.personal.read_write") if write
                                              else t("connections.personal.read") if read else t("connections.off"))
                self.personal_button.set_text(t("connections.personal.change") if read
                                              else t("connections.personal.allow"))
            collect = settings.get("save_mode") == "collect"
            self.saving_label.configure(text=t("connections.saving.collect") if collect
                                        else t("connections.saving.curated"))
            self.saving_button.set_text(t("connections.saving.to_curated") if collect
                                        else t("connections.saving.to_collect"))
            self.hooks_label.configure(text=t("connections.hooks.on") if status.hooks_installed
                                       else t("connections.off"))
            self.hooks_button.set_text(t("connections.action.remove") if status.hooks_installed
                                       else t("connections.action.install"))
            if self.code_mode_label is not None and self.code_mode_button is not None:
                self.code_mode_label.configure(text=CODE_MODE_LABELS.get(status.code_mode or "",
                                                                         t("connections.unknown")))
                if status.code_mode == codex_options.MISSING:
                    self.code_mode_button.pack(side="left", padx=(self.page.theme.px(SPACE_S), 0))
                else:
                    self.code_mode_button.pack_forget()
            skill = status.skill or memory_skill.ABSENT
            if self.host == DESKTOP:
                self.skill_label.configure(text=t("connections.skill.desktop"))
            else:
                self.skill_label.configure(text=SKILL_LABELS.get(skill, t("connections.unknown")))
                self.skill_button.set_text(SKILL_ACTIONS.get(skill, t("connections.action.install")))
        else:
            self.access.pack_forget()
        if status is not None and status.connected and status.legacy:
            self.primary.set_text(t("connections.action.reconnect"))
            self.primary.set_variant("primary")
            self.primary.set_command(lambda: self.page.connect_host(self.host))
            self.primary.set_enabled(True)
        elif status is not None and status.connected:
            self.primary.set_text(t("connections.action.disconnect"))
            self.primary.set_variant("secondary")
            self.primary.set_command(lambda: self.page.disconnect_host(self.host))
            self.primary.set_enabled(True)
        else:
            self.primary.set_text(t("connections.action.connect"))
            self.primary.set_variant("primary")
            self.primary.set_command(lambda: self.page.connect_host(self.host))
            self.primary.set_enabled(status is not None and status.installed and not status.configuration_conflict)
        self.diagnose_button.set_enabled(True)

    def show_servers(self, records: list[ServerRecord]) -> None:
        """How many BIO CE servers run for this card's connection, and when the latest request came."""
        status = self.status
        if status is None or not status.connected or status.legacy or not status.connection_id:
            self.servers_row.pack_forget()
            return
        if records:
            servers = t("connections.servers.count", count=len(records))
            latest = max(record.last_request_at for record in records)
            text = t("connections.servers.last_request", servers=servers, when=when(latest)) if when(latest) \
                else servers
        else:
            text = t("connections.servers.none")
        self.servers_label.configure(text=text)
        self.servers_row.pack(fill="x", pady=(self.page.theme.px(SPACE_S), 0))

    def set_busy(self, label: str | None) -> None:
        self.busy = label is not None
        if label is not None:
            self.pill.set(label, "info")
            self.primary.set_enabled(False)
            self.diagnose_button.set_enabled(False)
            self.progress.pack(fill="x", pady=(self.page.theme.px(SPACE_M), 0), before=self.actions)
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def show_checks(self, checks: tuple[DiagnosticCheck, ...]) -> None:
        theme, c = self.page.theme, self.page.colors
        self.checks = checks
        for child in self.results.winfo_children():
            child.destroy()
        if not checks:
            self.results.pack_forget()
            return
        self.results.pack(fill="x", pady=(theme.px(SPACE_L), 0))
        tk.Frame(self.results, height=1, background=c.border).pack(fill="x", pady=(0, theme.px(SPACE_M)))
        tk.Label(self.results, text=t("connections.diagnostics"), font=theme.font("caption_strong"),
                 background=c.surface,
                 foreground=c.text_muted, anchor="w").pack(fill="x", pady=(0, theme.px(SPACE_XS)))
        for check in checks:
            icon, color_name = _OUTCOME_STYLE.get(check.outcome, ("info", "info"))
            row = tk.Frame(self.results, background=c.surface)
            row.pack(fill="x", pady=theme.px(3))
            tk.Label(row, text=theme.icon(icon) or check.outcome.upper(), font=theme.icon_font("small"),
                     background=c.surface, foreground=getattr(c, color_name), width=2).pack(
                side="left", anchor="n", pady=(theme.px(2), 0))
            column = tk.Frame(row, background=c.surface)
            column.pack(side="left", fill="x", expand=True, padx=(theme.px(SPACE_S), 0))
            tk.Label(column, text=check.name, font=theme.font("body_strong"), background=c.surface,
                     foreground=c.text, anchor="w").pack(fill="x")
            WrapLabel(column, check.detail, font=theme.font("caption"), foreground=c.text_secondary).pack(fill="x")


class ConnectionsPage(Page):
    key = "connections"
    nav_key = "connections"
    @property
    def title(self) -> str:  # type: ignore[override]
        return t("connections.title")

    @property
    def subtitle(self) -> str:  # type: ignore[override]
        return t("connections.subtitle")

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        Button(self.actions, theme, t("connections.refresh"), icon="refresh", command=self.refresh,
               tooltip=t("connections.refresh_tip")).pack(side="right")
        Button(self.actions, theme, t("connections.pause_all"), variant="danger_subtle", command=self.pause_all,
               tooltip=t("connections.pause_all_tip")).pack(
            side="right", padx=(0, theme.px(SPACE_S)))

        self.scroll = ScrollFrame(self, theme, max_width=960)
        self.scroll.pack(fill="both", expand=True)
        body = self.scroll.body

        callout = Card(body, theme, padding=SPACE_L, background=c.info_bg)
        callout.configure(highlightbackground=c.selection, highlightcolor=c.selection)
        callout.pack(fill="x")
        tk.Label(callout.body, text=theme.icon("lock"), font=theme.icon_font("normal"), background=c.info_bg,
                 foreground=c.info).pack(side="left", anchor="n", padx=(0, theme.px(SPACE_M)), pady=theme.px(2))
        column = tk.Frame(callout.body, background=c.info_bg)
        column.pack(side="left", fill="x", expand=True)
        tk.Label(column, text=t("connections.callout.title"), font=theme.font("body_strong"),
                 background=c.info_bg, foreground=c.text, anchor="w").pack(fill="x")
        WrapLabel(column, t("connections.callout.body"), font=theme.font("body"), foreground=c.text_secondary,
                  background=c.info_bg).pack(fill="x", pady=(theme.px(2), 0))
        WrapLabel(column, app_closed_note(), font=theme.font("body_strong"), foreground=c.text,
                  background=c.info_bg).pack(fill="x", pady=(theme.px(SPACE_S), 0))

        self.cards: dict[str, HostCard] = {}
        for host in HOSTS:
            card = HostCard(self, body, host)
            card.pack(fill="x", pady=(theme.px(SPACE_M), 0))
            self.cards[host] = card

        # v0.4.4: what hosts ask to change is reviewed on the memory screen (Memories → Reviews), not here.
        self.activity_card = Card(body, theme, padding=SPACE_L + 4)
        self.activity_card.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        activity_head = tk.Frame(self.activity_card.body, background=c.surface)
        activity_head.pack(fill="x")
        self.reviews_link = Button(activity_head, theme, t("connections.open_reviews"), variant="link",
                                   command=lambda: app.open_state(REVIEWS))
        self.reviews_link.pack(side="right")
        section_label(activity_head, theme, t("connections.activity.title")).pack(side="left")
        caption_label(self.activity_card.body, theme, t("connections.activity.note"), muted=True).pack(
            fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_S)))
        self.activity_list = tk.Frame(self.activity_card.body, background=c.surface)
        self.activity_list.pack(fill="x")

        # v0.4.4 §9.2: the running BIO CE MCP servers of all connections, and ending the long-idle ones on request.
        servers = Card(body, theme, padding=SPACE_L + 4)
        servers.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        servers_row = tk.Frame(servers.body, background=c.surface)
        servers_row.pack(fill="x")
        servers_column = tk.Frame(servers_row, background=c.surface)
        servers_column.pack(side="left", fill="x", expand=True)
        section_label(servers_column, theme, t("connections.servers.title")).pack(fill="x")
        WrapLabel(servers_column, t("connections.servers.note"), font=theme.font("body"),
                  foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.servers_total = tk.Label(servers_column, text="", font=theme.font("body_strong"), background=c.surface,
                                      foreground=c.text, anchor="w")
        self.servers_total.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.end_idle_button = Button(servers_row, theme, t("connections.servers.end_idle"),
                                      command=self.end_idle_servers)
        self.end_idle_button.pack(side="right", anchor="n", padx=(theme.px(SPACE_L), 0))

        backups = Card(body, theme, padding=SPACE_L + 4)
        backups.pack(fill="x", pady=(theme.px(SPACE_M), theme.px(SPACE_S)))
        row = tk.Frame(backups.body, background=c.surface)
        row.pack(fill="x")
        column = tk.Frame(row, background=c.surface)
        column.pack(side="left", fill="x", expand=True)
        section_label(column, theme, t("connections.backups.title")).pack(fill="x")
        WrapLabel(column, t("connections.backups.note"), font=theme.font("body"),
                  foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        Button(row, theme, t("connections.backups.open"), icon="folder", command=app.open_connection_backups).pack(
            side="right", anchor="n", padx=(theme.px(SPACE_L), 0))

    def refresh(self) -> None:
        super().refresh()
        statuses = self.app.host_statuses(refresh=True)
        for host, card in self.cards.items():
            if not card.busy:
                card.apply(statuses.get(host))
        self.refresh_activity()
        self.refresh_servers()

    def on_show(self) -> None:
        was_stale = self.stale
        super().on_show()
        if not was_stale:
            self.refresh_servers()  # the count changes without the page knowing; reading it doesn't ask the hosts

    @property
    def control(self):
        return getattr(self.app.connection_manager, "control", None)

    # BIO CE servers (v0.4.4 §9.2) -----------------------------------------

    def data_folder(self) -> Path:
        """Where the servers keep their records: the folder of the user database, as the MCP server sees it."""
        return Path(self.app.paths.user_database).parent

    def _servers(self) -> list[ServerRecord]:
        try:
            return running(self.data_folder())
        except OSError:
            return []

    def server_counts(self) -> tuple[dict[str | None, int], int]:
        """Running BIO CE servers per connection ID, and in total."""
        counts: dict[str | None, int] = {}
        records = self._servers()
        for record in records:
            counts[record.connection_id] = counts.get(record.connection_id, 0) + 1
        return counts, len(records)

    def refresh_servers(self) -> None:
        records = self._servers()
        for card in self.cards.values():
            connection = card.status.connection_id if card.status is not None else None
            card.show_servers([record for record in records if connection and record.connection_id == connection])
        self.servers_total.configure(text=t("connections.servers.total", count=len(records)) if records
                                     else t("connections.servers.none"))

    def end_idle_servers(self) -> list[int]:
        """End the BIO CE servers with no request for IDLE_SERVER_SECONDS, after the user confirms. Returns their
        process IDs. Only on the user's request: nothing calls this on its own (v0.4.4)."""
        hours = IDLE_SERVER_SECONDS // 3600
        idle = [record for record in self._servers()
                if record.pid != os.getpid() and record.idle_seconds() >= IDLE_SERVER_SECONDS]
        if not idle:
            self.refresh_servers()
            self.app.notify("info", t("connections.servers.none_idle", hours=hours))
            return []
        if not self.app.confirm(
            title=t("connections.servers.end_title", count=len(idle)),
            message=t("connections.servers.end_message", hours=hours),
            points=(t("connections.servers.end_point_fail"), t("connections.servers.end_point_keep", hours=hours)),
            confirm_text=t("connections.servers.end_confirm"),
            danger=True,
        ):
            return []
        try:
            ended = end_idle(self.data_folder(), IDLE_SERVER_SECONDS)
        except OSError:
            self.refresh_servers()
            self.app.notify("error", t("connections.servers.end_failed"), title=t("connections.servers.ended_title"))
            return []
        self.refresh_servers()
        self.app.notify("success", t("connections.servers.ended", count=len(ended)),
                        title=t("connections.servers.ended_title"))
        return ended

    def refresh_activity(self) -> None:
        theme, c = self.theme, self.colors
        for child in self.activity_list.winfo_children():
            child.destroy()
        control = self.control
        activity: tuple[AuditEntry, ...] = control.recent_activity(limit=15) if control is not None else ()
        try:
            waiting = int(control.pending_review_count()) if control is not None else 0
        except Exception:  # noqa: BLE001
            waiting = 0
        self.reviews_link.set_text(t("connections.open_reviews_count", count=waiting) if waiting
                                   else t("connections.open_reviews"))
        refresh_badges = getattr(self.app, "refresh_badges", None)
        if refresh_badges is not None:
            refresh_badges()
        if not activity:
            caption_label(self.activity_list, theme, t("connections.activity.none"), muted=True).pack(fill="x")
        for entry in activity:
            label, kind = ACTIVITY_LABELS.get(entry.outcome, (entry.outcome, "neutral"))
            row = tk.Frame(self.activity_list, background=c.surface)
            row.pack(fill="x", pady=theme.px(2))
            Pill(row, theme, label, kind).pack(side="left", anchor="n")
            text = f"{host_name(entry.host)} · {entry.action.replace('-', ' ')}"
            if entry.title:
                text += f" · “{preview(entry.title, 60)}”"
            reason = entry.detail.get("decision") or entry.detail.get("reason") or ""
            link = entry.memory_id if entry.outcome in ("created", "updated", "approved", "duplicate") else None
            widget = Button(row, theme, text, variant="link" if link else "subtle",
                            command=(lambda m=link: self.app.open_memory(m)) if link else None)
            widget.pack(side="left", padx=(theme.px(SPACE_S), 0))
            if reason:
                tk.Label(row, text=preview(reason, 70), font=theme.font("caption"), background=c.surface,
                         foreground=c.text_muted).pack(side="left", padx=(theme.px(SPACE_S), 0))
            tk.Label(row, text=relative_time(entry.recorded_at), font=theme.font("caption"), background=c.surface,
                     foreground=c.text_muted).pack(side="right")

    def focus_default(self) -> None:
        self.focus_set()

    # Actions --------------------------------------------------------------

    def connect_desktop(self) -> None:
        host, name = DESKTOP, host_name(DESKTOP)
        manager = self.app.connection_manager
        path = manager.desktop_config_path() if hasattr(manager, "desktop_config_path") else None
        if not self.app.confirm(
            title=t("connections.desktop.title", name=name),
            message=t("connections.desktop.message"),
            points=(
                t("connections.desktop.settings_file", path=path) if path
                else t("connections.desktop.settings_file_found"),
                t("connections.desktop.point_backup"),
                t("connections.desktop.point_read", provider=PROVIDER_EXAMPLES[host]),
                t("connections.desktop.point_auto_off"),
                t("connections.desktop.point_check"),
                desktop_restart(),
            ),
            confirm_text=t("connections.action.connect"),
        ):
            return
        card = self.cards[host]
        card.set_busy(t("connections.connecting"))
        card.show_checks(())
        self.app.run_task(lambda: (manager.connect(host, approved=True), None),
                          lambda outcome: self._connected(host, *outcome),
                          lambda error: self._failed(host, error, "connect"))

    def save_skill_zip(self, host: str = DESKTOP) -> Path | None:
        """Save the memory skill as a ZIP for the user to upload in Claude (BIO CE never uploads it)."""
        manager = self.app.connection_manager
        if not self.app.confirm(title=t("connections.skill.zip_title"), message=desktop_skill_note(),
                                points=(t("connections.skill.zip_point"),),
                                confirm_text=t("connections.skill.zip_confirm")):
            return None
        target = self.app.ask_save_path(title=t("connections.skill.zip_save_title"), defaultextension=".zip",
                                        initialfile="bio-ce-memory.zip", filetypes=(("ZIP", "*.zip"),))
        if not target:
            return None
        try:
            with open(target, "xb") as handle:
                handle.write(manager.skill_zip(host))
        except FileExistsError:
            self.app.notify("warning", t("connections.skill.zip_exists"), title=t("connections.skill.not_saved"))
            return None
        except (OSError, MCPConnectionError):
            self.app.notify("error", t("connections.skill.zip_failed"), title=t("connections.skill.not_saved"))
            return None
        self.app.notify("success", t("connections.skill.zip_saved"), title=t("connections.skill.zip_saved_title"),
                        action=(t("connections.skill.show_in_folder"), lambda: self.app.reveal_file(Path(target))))
        return Path(target)

    def connect_host(self, host: str) -> None:
        if host == DESKTOP:
            self.connect_desktop()
            return
        name = host_name(host)
        manager = self.app.connection_manager
        skill_path = manager.memory_skill_path(host)
        options = [("skill", t("connections.skill.connect_option", name=name, path=skill_path), True)]
        if host == "codex":
            options.append(("agents", t("connections.skill.agents_option",
                                        path=str(skill_path.parents[2] / "AGENTS.md")), False))
        code_mode_point = (t("connections.code_mode.connect_point"),) if host == "codex" else ()
        choices: dict[str, bool] = {key: default for key, _label, default in options}
        if not self.app.confirm(
            title=t("connections.connect.title", name=name),
            message=t("connections.connect.message", name=name),
            points=(
                t("connections.connect.point_read", name=name),
                t("connections.connect.point_provider", name=name, provider=PROVIDER_EXAMPLES[host]),
                t("connections.connect.point_auto_off"),
                t("connections.connect.point_backup"),
                t("connections.connect.point_check"),
                *code_mode_point,
            ),
            confirm_text=t("connections.action.connect"),
            options=options,
            choices=choices,
            links=((t("connections.skill.preview_link"), lambda dialog: self._show_skill(host, dialog)),),
        ):
            return
        card = self.cards[host]
        card.set_busy(t("connections.connecting"))
        card.show_checks(())

        def work():
            result = manager.connect(host, approved=True)
            skill = None
            if choices.get("skill") or choices.get("agents"):
                try:
                    skill = manager.install_memory_skill(host, approved=True, agents_md=bool(choices.get("agents")))
                except MCPConnectionError as exc:
                    skill = exc
            return result, skill

        self.app.run_task(
            work,
            lambda outcome: self._connected(host, *outcome),
            lambda error: self._failed(host, error, "connect"),
        )

    def disconnect_host(self, host: str) -> None:
        name = host_name(host)
        status = self.cards[host].status
        skill = (status.skill if status is not None else None) or memory_skill.ABSENT
        options = []
        if skill != memory_skill.ABSENT:
            edited = skill == memory_skill.MODIFIED
            options.append(("remove_skill", t("connections.disconnect.remove_skill_edited") if edited
                            else t("connections.disconnect.remove_skill"), not edited))
        choices: dict[str, bool] = {key: default for key, _label, default in options}
        if not self.app.confirm(
            title=t("connections.disconnect.title", name=name),
            message=t("connections.disconnect.message", name=name),
            points=(t("connections.disconnect.point_backup"),
                    t("connections.disconnect.point_memories")),
            confirm_text=t("connections.action.disconnect"),
            options=options,
            choices=choices,
        ):
            return
        card = self.cards[host]
        card.set_busy(t("connections.disconnecting"))
        card.show_checks(())
        remove_skill = bool(choices.get("remove_skill"))
        self.app.run_task(
            lambda: self.app.connection_manager.disconnect(
                host, approved=True, remove_skill=remove_skill,
                remove_modified_skill=remove_skill and skill == memory_skill.MODIFIED),
            lambda result: self._disconnected(host, result),
            lambda error: self._failed(host, error, "disconnect"),
        )

    def set_mode(self, host: str, mode: str) -> None:
        name = host_name(host)
        status = self.cards[host].status
        if status is not None and status.mode == mode:
            return
        if mode == MODE_AUTO_MEMORY and not self.app.confirm(
            title=t("connections.auto.title", name=name),
            message=t("connections.auto.message", name=name),
            points=(
                *((t("connections.auto.point_support", name=name, detail=auto_memory_support(host).detail),)
                  if auto_memory_support(host).level != "available" else ()),
                t("connections.auto.point_what"),
                t("connections.auto.point_refused"),
                t("connections.auto.point_approval", name=name),
                t("connections.auto.point_provider", name=name),
                t("connections.auto.point_back"),
            ),
            confirm_text=t("connections.auto.confirm"),
        ):
            return
        try:
            self.app.connection_manager.set_mode(host, mode)
        except MCPConnectionError as exc:
            self.app.notify("error", str(exc), title=t("connections.auto.failed_title", name=name))
            return
        self.app.hosts_changed()
        self.app.notify("success", host_message(host, self.app.host_statuses(refresh=False).get(host)),
                        title=t("connections.mode.changed_title", name=name, mode=MODE_TEXTS[mode]))

    def connection_settings(self, host: str) -> dict | None:
        manager = self.app.connection_manager
        if not hasattr(manager, "connection_settings"):
            return None
        try:
            return manager.connection_settings(host)
        except Exception:  # noqa: BLE001 - a settings read must never break the page
            return None

    def personal_access(self, host: str) -> tuple[bool, bool] | None:
        """This host's Personal access, or None when Personal is off or the host is not connected."""
        manager = self.app.connection_manager
        if not hasattr(manager, "personal_access") or not self.app.personal_enabled():
            return None
        try:
            return manager.personal_access(host)
        except Exception:  # noqa: BLE001 - a settings read must never break the page
            return None

    def change_personal(self, host: str) -> None:
        """Allow, narrow, or remove one host's Personal access. Allowing needs the transfer consent."""
        name = host_name(host)
        current = self.personal_access(host)
        if current is None:
            self.app.notify("info", t("connections.personal.off_message"), title=t("connections.personal.off_title"))
            return
        choice = self.app.ask_choice(
            title=t("connections.personal.title", name=name),
            message=t("connections.personal.message", name=name),
            choices=[("read", t("connections.personal.read"), t("connections.personal.read_detail", name=name)),
                     ("write", t("connections.personal.read_write"),
                      t("connections.personal.write_detail", name=name)),
                     ("off", t("connections.off"), t("connections.personal.off_detail", name=name))],
            confirm_text=t("connections.personal.continue"))
        if choice is None:
            return
        read, write = choice in ("read", "write"), choice == "write"
        if read and not current[0]:
            choices: dict[str, bool] = {}
            accepted = self.app.confirm(
                title=t("connections.personal.allow_title", name=name),
                message=t("connections.personal.allow_message", name=name, provider=PROVIDER_EXAMPLES[host]),
                points=(t("connections.personal.point_hooks"),
                        t("connections.personal.point_off")),
                options=(("consent", t("connections.personal.consent"), False),),
                choices=choices, confirm_text=t("connections.personal.allow_confirm"))
            if not accepted or not choices.get("consent"):
                if accepted:
                    self.app.notify("info", t("connections.personal.not_ticked"),
                                    title=t("connections.personal.title", name=name))
                return
        try:
            self.app.connection_manager.set_personal_access(host, can_read=read, can_write=write)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", str(exc) or t("connections.setting_failed"),
                            title=t("connections.personal.title", name=name))
            return
        self.app.notify("success", {"read": t("connections.personal.now_read", name=name),
                                    "write": t("connections.personal.now_write", name=name),
                                    "off": t("connections.personal.now_off", name=name)}[choice],
                        title=t("connections.personal.title", name=name))
        self.app.hosts_changed()

    def toggle_projects(self, host: str) -> None:
        """All project spaces on or off for one host. General access always follows the Access mode."""
        current = self.connection_settings(host) or {"all_projects": True}
        wanted = not current.get("all_projects", True)
        name = host_name(host)
        try:
            self.app.connection_manager.set_connection_settings(host, all_projects=wanted)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", str(exc) or t("connections.setting_failed"),
                            title=t("connections.spaces.title", name=name))
            return
        self.app.notify("success", t("connections.spaces.now_all", name=name) if wanted else
                        t("connections.spaces.now_general", name=name), title=t("connections.spaces.title", name=name))
        self.app.hosts_changed()

    def toggle_save_mode(self, host: str) -> None:
        """Curated (default) or Collect for one host, after the user confirms what changes."""
        current = (self.connection_settings(host) or {}).get("save_mode", "curated")
        wanted = "curated" if current == "collect" else "collect"
        name = host_name(host)
        if wanted == "collect":
            points = (
                t("connections.saving.collect_point_what", name=name),
                t("connections.saving.collect_point_use"),
                t("connections.saving.collect_point_cleanup"),
                t("connections.saving.collect_point_review"),
                t("connections.saving.collect_point_skill"),
            )
            title = t("connections.saving.collect_title", name=name)
            message, confirm = t("connections.saving.collect_message"), t("connections.saving.to_collect")
            done = t("connections.saving.now_collect", name=name)
        else:
            points = (t("connections.saving.curated_point_what"), t("connections.saving.curated_point_inbox"),
                      t("connections.saving.curated_point_skill"))
            title = t("connections.saving.curated_title", name=name)
            message, confirm = t("connections.saving.curated_message"), t("connections.saving.to_curated")
            done = t("connections.saving.now_curated", name=name)
        if not self.app.confirm(title=title, message=message, points=points, confirm_text=confirm):
            return
        try:
            self.app.connection_manager.set_connection_settings(host, save_mode=wanted)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", str(exc) or t("connections.setting_failed"),
                            title=t("connections.saving.title", name=name))
            return
        self.app.notify("success", done, title=t("connections.saving.title", name=name))
        self._rewrite_skill_for_mode(host)
        self.app.hosts_changed()

    def _rewrite_skill_for_mode(self, host: str) -> None:
        """The managed skill follows the saving mode. An edited skill is replaced only if the user says so."""
        status = self.cards[host].status
        state = (status.skill if status is not None else None) or memory_skill.ABSENT
        if state == memory_skill.ABSENT:
            return
        name = host_name(host)
        replacing = state == memory_skill.MODIFIED
        if replacing and not self.app.confirm(
            title=t("connections.skill.replace_title", name=name),
            message=t("connections.skill.rewrite_message"),
            points=(t("connections.skill.point_edited_backup"),
                    t("connections.skill.point_keep")),
            confirm_text=t("connections.action.replace"), cancel_text=t("connections.skill.keep_mine"), danger=True,
        ):
            return
        agents = status is not None and status.agents_block not in (None, memory_skill.ABSENT)
        manager = self.app.connection_manager
        self.cards[host].set_busy(t("connections.skill.updating"))
        self.app.run_task(lambda: manager.install_memory_skill(host, approved=True, replace_modified=replacing,
                                                               agents_md=agents),
                          lambda results: self._skill_done(host, results),
                          lambda error: self._failed(host, error, "skill"))

    def toggle_hooks(self, host: str) -> None:
        name = host_name(host)
        status = self.cards[host].status
        installing = not (status is not None and status.hooks_installed)
        if installing:
            backup = t("connections.hooks.point_backup_codex") if host == "codex" \
                else t("connections.hooks.point_backup")
            if not self.app.confirm(
                title=t("connections.hooks.add_title", name=name),
                message=t("connections.hooks.add_message", name=name),
                points=(
                    t("connections.hooks.point_start"),
                    t("connections.hooks.point_prompt"),
                    t("connections.hooks.point_silent"),
                    backup,
                ),
                confirm_text=t("connections.hooks.add_confirm"),
            ):
                return
        card = self.cards[host]
        card.set_busy(t("connections.hooks.updating"))
        manager = self.app.connection_manager
        self.app.run_task(
            (lambda: manager.install_hooks(host, approved=True)) if installing
            else (lambda: manager.remove_hooks(host, approved=True)),
            lambda _result: self._hooks_done(host, installing),
            lambda error: self._failed(host, error, "hooks"),
        )

    def apply_code_mode(self, host: str) -> None:
        if not self.app.confirm(
            title=t("connections.code_mode.title"),
            message=t("connections.code_mode.message"),
            points=(
                t("connections.code_mode.point_version"),
                t("connections.code_mode.point_backup"),
                t("connections.code_mode.point_other"),
            ),
            confirm_text=t("connections.action.apply"),
        ):
            return
        card = self.cards[host]
        card.set_busy(t("connections.code_mode.updating"))
        self.app.run_task(
            lambda: self.app.connection_manager.apply_codex_code_mode(approved=True),
            lambda result: self._code_mode_done(host, result),
            lambda error: self._failed(host, error, "code_mode"),
        )

    def _code_mode_done(self, host: str, result: CodeModeResult) -> None:
        self._finish(host)
        kind = "success" if result.state in ("applied", "already_applied") else "warning"
        self.app.notify(kind, result.detail, title=t("connections.code_mode.done_title"))

    def _show_skill(self, host: str, parent: tk.Misc | None = None) -> None:
        path = self.app.connection_manager.memory_skill_path(host)
        mode = (self.connection_settings(host) or {}).get("save_mode", memory_skill.CURATED)
        body = t("connections.skill.location", path=path) + "\n\n" + memory_skill.render(mode=mode)
        TextViewerDialog(parent or self, self.theme, t("connections.skill.viewer_title"), body).show(
            modal=parent is not None)

    def preview_skill(self, host: str) -> None:
        self._show_skill(host)

    def toggle_skill(self, host: str) -> None:
        name = host_name(host)
        status = self.cards[host].status
        state = (status.skill if status is not None else None) or memory_skill.ABSENT
        manager = self.app.connection_manager
        path = manager.memory_skill_path(host)
        if state == memory_skill.CURRENT:
            if not self.app.confirm(
                title=t("connections.skill.remove_title", name=name),
                message=t("connections.skill.remove_message", path=path),
                points=(t("connections.skill.point_backup_kept"), t("connections.skill.point_stays")),
                confirm_text=t("connections.action.remove"),
            ):
                return
            work = lambda: manager.remove_memory_skill(host, approved=True)
        else:
            replacing = state == memory_skill.MODIFIED
            if replacing:
                title = t("connections.skill.replace_title", name=name)
            elif state == memory_skill.OUTDATED:
                title = t("connections.skill.update_title", name=name)
            else:
                title = t("connections.skill.install_title", name=name)
            if not self.app.confirm(
                title=title,
                message=t("connections.skill.install_message", name=name, path=path),
                points=((t("connections.skill.point_edited_backup"),) if replacing else ())
                + (t("connections.skill.point_server"),),
                confirm_text=t("connections.action.replace") if replacing else t("connections.action.install"),
                danger=replacing,
                links=((t("connections.skill.preview_link"), lambda dialog: self._show_skill(host, dialog)),),
            ):
                return
            work = lambda: manager.install_memory_skill(host, approved=True, replace_modified=replacing)
        card = self.cards[host]
        card.set_busy(t("connections.skill.updating"))
        self.app.run_task(work, lambda results: self._skill_done(host, results),
                          lambda error: self._failed(host, error, "skill"))

    def _skill_done(self, host: str, results) -> None:
        self._finish(host)
        self.app.notify("success", _skill_message(host_name(host), results[0]), title=t("connections.row.skill"))

    def _hooks_done(self, host: str, installed: bool) -> None:
        self._finish(host)
        name = host_name(host)
        if installed:
            message = t("connections.hooks.added_codex", name=name) if host == "codex" \
                else t("connections.hooks.added", name=name)
        else:
            message = t("connections.hooks.removed", name=name)
        self.app.notify("success", message, title=t("connections.hooks.updated_title"))

    def pause_all(self) -> None:
        control = self.control
        if control is None or not self.app.confirm(
            title=t("connections.pause.title"),
            message=t("connections.pause.message"),
            points=(t("connections.pause.point_sessions"), t("connections.pause.point_nothing")),
            confirm_text=t("connections.pause.confirm"),
            danger=True,
        ):
            return
        count = control.pause_all()
        self.app.hosts_changed()
        self.app.notify("success", t("connections.pause.done", count=count), title=t("connections.pause.done_title"))

    def diagnose_host(self, host: str) -> None:
        card = self.cards[host]
        card.set_busy(t("connections.checking"))
        self.app.run_task(
            lambda: self.app.connection_manager.diagnose(host),
            lambda checks: self._diagnosed(host, checks),
            lambda error: self._failed(host, error, "diagnose"),
        )

    def _finish(self, host: str) -> None:
        self.cards[host].set_busy(None)
        self.app.hosts_changed()

    def _connected(self, host: str, result: ConnectionResult, skill=None) -> None:
        self._finish(host)
        name = host_name(host)
        if result.already_configured:
            message = t("connections.connected.again", name=name)
        else:
            message = t("connections.connected.now", name=name)
            if result.backup_file is not None:
                message += " " + t("connections.connected.backup")
        message += " " + settings_summary(self.connection_settings(host))
        if result.code_mode is not None:
            message += " " + result.code_mode.detail
        if isinstance(skill, BaseException):
            message += " " + t("connections.connected.skill_failed", error=str(skill))
        elif skill is not None:
            message += " " + _skill_message(name, skill[0])
        if host == DESKTOP:
            message += " " + desktop_restart() + " " + desktop_skill_note()
        message += " " + app_closed_note()
        self.app.notify("success", message, title=t("connections.connected.title", name=name))

    def _disconnected(self, host: str, result: ConnectionResult) -> None:
        self._finish(host)
        name = host_name(host)
        if result.backup_file is not None:
            self.app.notify("success", t("connections.disconnected.backup", name=name)
                            + (" " + desktop_restart() if host == DESKTOP else ""),
                            title=t("connections.disconnected.title", name=name))
        else:
            self.app.notify("info", t("connections.disconnected.already", name=name),
                            title=t("connections.disconnected.title", name=name))

    def _diagnosed(self, host: str, checks: tuple[DiagnosticCheck, ...]) -> None:
        self._finish(host)
        card = self.cards[host]
        card.show_checks(checks)
        self.update_idletasks()
        self.scroll.scroll_to_widget(card.results)
        failures = [check for check in checks if check.outcome == "fail"]
        name = host_name(host)
        if failures:
            self.app.notify("warning", t("connections.diagnose.attention", count=len(failures)),
                            title=t("connections.diagnose.title", name=name))
        else:
            self.app.notify("success", t("connections.diagnose.passed"),
                            title=t("connections.diagnose.passed_title", name=name))

    def _failed(self, host: str, error: BaseException, action: str) -> None:
        self._finish(host)
        name = host_name(host)
        titles = {"connect": t("connections.failed.connect", name=name),
                  "disconnect": t("connections.failed.disconnect", name=name),
                  "diagnose": t("connections.failed.diagnose", name=name),
                  "hooks": t("connections.failed.hooks", name=name),
                  "code_mode": t("connections.failed.code_mode"), "skill": t("connections.failed.skill")}
        if isinstance(error, MCPConnectionConflict):
            message = t("connections.failed.conflict", error=error)
            kind = "warning"
        elif isinstance(error, MCPConnectionError):
            message = str(error)
            kind = "error"
        else:
            message = t("connections.failed.other", name=name)
            kind = "error"
        self.app.notify(kind, message, title=titles[action])


def _skill_message(name: str, result: SkillResult) -> str:
    return {
        "installed": t("connections.skill.result.installed", name=name),
        "updated": t("connections.skill.result.updated", name=name),
        "unchanged": t("connections.skill.result.unchanged", name=name),
        "kept_modified": t("connections.skill.result.kept_modified", name=name),
        "removed": t("connections.skill.result.removed", name=name),
        "absent": t("connections.skill.result.absent", name=name),
    }.get(result.state, t("connections.skill.result.other", state=result.state))


__all__ = ["ConnectionsPage", "HostCard", "app_closed_note", "host_message", "settings_summary"]
