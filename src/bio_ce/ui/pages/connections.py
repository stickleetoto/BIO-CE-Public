# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Connections: register BIO CE's read-only MCP server with Codex CLI or Claude Code."""

from __future__ import annotations

from tkinter import ttk
import tkinter as tk

from bio_ce.connections import (
    ConnectionResult,
    DiagnosticCheck,
    HostStatus,
    MCPConnectionConflict,
    MCPConnectionError,
    auto_memory_support,
)
from bio_ce.control_store import (
    MODE_AUTO_MEMORY,
    MODE_LABELS,
    MODE_PAUSED,
    MODE_READ_ONLY,
    AuditEntry,
    ReviewItem,
)
from bio_ce.ui.dialogs import ReviewEditDialog
from bio_ce.ui.format import HOST_COMMANDS, host_name, preview, relative_time
from bio_ce.ui.pages import Page
from bio_ce.ui.pages.dashboard import host_pill
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import Button, Card, Pill, ScrollFrame, WrapLabel, caption_label, section_label


HOST_DESCRIPTIONS = {
    "codex": "OpenAI’s command-line coding agent",
    "claude": "Anthropic’s command-line coding agent",
}
PROVIDER_EXAMPLES = {
    "codex": "usually OpenAI, or another provider you configured in Codex",
    "claude": "usually Anthropic, or the cloud provider you configured in Claude Code",
}
_OUTCOME_STYLE = {
    "pass": ("success", "success"),
    "fail": ("error", "danger"),
    "info": ("info", "info"),
    "skip": ("dot", "text_muted"),
}


def host_message(host: str, status: HostStatus | None) -> str:
    name = host_name(host)
    command = HOST_COMMANDS[host]
    if status is None:
        return f"BIO CE couldn't check {name}. Select Refresh to try again."
    if not status.installed:
        return (f"BIO CE looks for the “{command}” command and didn't find it. Install {name}, confirm that "
                f"“{command} --version” works in a new terminal, then select Refresh.")
    if status.configuration_conflict:
        return (f"{name} already has a different MCP server named “bio-ce”, or its settings file can't be "
                "read. BIO CE won't change it. Run diagnostics for details.")
    if status.connected and status.legacy:
        return (f"{name} was connected by BIO CE v0.2: it can only search and read, and BIO CE can't pause or "
                "revoke it. Select Reconnect to manage its access.")
    if status.connected and status.mode == MODE_AUTO_MEMORY:
        return (f"{name} can search and read your memories and save or update lasting ones under BIO CE’s rules. "
                "Uncertain changes and retractions wait for your review.")
    if status.connected and status.mode == MODE_PAUSED:
        return f"{name}’s access is paused. It can’t read or change memories until you choose another mode."
    if status.connected:
        return f"{name} can search and read your memories. Auto memory is off."
    return f"{name} is installed. Connect it to let it search and read your memories."


ACTIVITY_LABELS = {
    "created": ("Saved", "success"),
    "updated": ("Updated", "success"),
    "queued": ("Sent to review", "info"),
    "duplicate": ("Already stored", "neutral"),
    "rejected": ("Refused", "warning"),
    "denied": ("Blocked (no permission)", "warning"),
    "rate-limited": ("Paused (too many changes)", "warning"),
    "conflict": ("Changed meanwhile", "warning"),
    "approved": ("Approved by you", "success"),
    "rejected-by-user": ("Rejected by you", "neutral"),
    "failed": ("Couldn't apply", "danger"),
}
REVIEW_KIND_LABELS = {"create": "New memory", "update": "Change", "retract": "Retraction request"}


class HostCard(Card):
    def __init__(self, page: "ConnectionsPage", master: tk.Misc, host: str) -> None:
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
        self.pill = Pill(header, theme, "Checking…", "info")
        self.pill.pack(side="right", anchor="n")

        self.message = WrapLabel(body, font=theme.font("body"), foreground=c.text_secondary)
        self.message.pack(fill="x", pady=(theme.px(SPACE_M + 2), 0))

        # Being connected and the host's model being able to use Auto memory are shown separately.
        support = auto_memory_support(host)
        self.support = support
        capability = tk.Frame(body, background=c.surface)
        capability.pack(fill="x", pady=(theme.px(SPACE_S + 2), 0))
        self.capability = capability
        tk.Label(capability, text="Auto memory in this host", font=theme.font("caption_strong"),
                 background=c.surface, foreground=c.text_muted, anchor="w").pack(side="left")
        self.support_pill = Pill(capability, theme, support.summary,
                                 {"available": "success", "limited": "warning"}.get(support.level, "neutral"))
        self.support_pill.pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.support_detail = WrapLabel(body, support.detail, font=theme.font("caption"), foreground=c.text_muted)
        self.support_detail.pack(fill="x", pady=(theme.px(SPACE_XS), 0))

        self.access = tk.Frame(body, background=c.surface)
        modes = tk.Frame(self.access, background=c.surface)
        modes.pack(fill="x")
        tk.Label(modes, text="Access", font=theme.font("body_strong"), background=c.surface, foreground=c.text,
                 width=12, anchor="w").pack(side="left")
        self.mode_buttons: dict[str, Button] = {}
        tips = {
            MODE_READ_ONLY: "Search and read only",
            MODE_AUTO_MEMORY: "Also save and update lasting memories under BIO CE's rules",
            MODE_PAUSED: "No reading or changes until you resume",
        }
        for mode in (MODE_READ_ONLY, MODE_AUTO_MEMORY, MODE_PAUSED):
            button = Button(modes, theme, MODE_LABELS[mode], tooltip=tips[mode],
                            command=lambda m=mode: page.set_mode(host, m))
            button.pack(side="left", padx=(0, theme.px(SPACE_XS)))
            self.mode_buttons[mode] = button
        hooks = tk.Frame(self.access, background=c.surface)
        hooks.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        tk.Label(hooks, text="Session hooks", font=theme.font("body_strong"), background=c.surface,
                 foreground=c.text, width=12, anchor="w").pack(side="left")
        self.hooks_label = tk.Label(hooks, text="", font=theme.font("body"), background=c.surface,
                                    foreground=c.text_secondary, anchor="w")
        self.hooks_label.pack(side="left")
        self.hooks_button = Button(hooks, theme, "Install", variant="link", command=lambda: page.toggle_hooks(host))
        self.hooks_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.progress = ttk.Progressbar(body, mode="indeterminate", style="BIO.Horizontal.TProgressbar")

        actions = tk.Frame(body, background=c.surface)
        actions.pack(fill="x", pady=(theme.px(SPACE_L), 0))
        self.actions = actions
        self.primary = Button(actions, theme, "Connect", icon="connections", variant="primary",
                              command=lambda: page.connect_host(host))
        self.primary.pack(side="left")
        self.diagnose_button = Button(actions, theme, "Run diagnostics", icon="diagnostics",
                                      command=lambda: page.diagnose_host(host),
                                      tooltip="Check the setup without changing anything")
        self.diagnose_button.pack(side="left", padx=(theme.px(SPACE_S), 0))
        self.results = tk.Frame(body, background=c.surface)
        self.checks: tuple[DiagnosticCheck, ...] = ()

    def apply(self, status: HostStatus | None) -> None:
        self.status = status
        text, kind = host_pill(status)
        self.pill.set(text, kind)
        self.message.configure(text=host_message(self.host, status))
        managed = status is not None and status.connected and not status.legacy and status.connection_id
        if managed:
            self.access.pack(fill="x", pady=(self.page.theme.px(SPACE_M), 0), after=self.message)
            for mode, button in self.mode_buttons.items():
                button.set_variant("primary" if status.mode == mode else "secondary")
            self.hooks_label.configure(text="On: recalls memories at session start and per prompt"
                                       if status.hooks_installed else "Off")
            self.hooks_button.set_text("Remove" if status.hooks_installed else "Install")
        else:
            self.access.pack_forget()
        if status is not None and status.connected and status.legacy:
            self.primary.set_text("Reconnect")
            self.primary.set_variant("primary")
            self.primary.set_command(lambda: self.page.connect_host(self.host))
            self.primary.set_enabled(True)
        elif status is not None and status.connected:
            self.primary.set_text("Disconnect")
            self.primary.set_variant("secondary")
            self.primary.set_command(lambda: self.page.disconnect_host(self.host))
            self.primary.set_enabled(True)
        else:
            self.primary.set_text("Connect")
            self.primary.set_variant("primary")
            self.primary.set_command(lambda: self.page.connect_host(self.host))
            self.primary.set_enabled(status is not None and status.installed and not status.configuration_conflict)
        self.diagnose_button.set_enabled(True)

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
        tk.Label(self.results, text="Diagnostics", font=theme.font("caption_strong"), background=c.surface,
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
    title = "AI connections"
    subtitle = "Let AI coding tools use and grow your memories"

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        Button(self.actions, theme, "Refresh", icon="refresh", command=self.refresh,
               tooltip="Check the hosts again (F5)").pack(side="right")
        Button(self.actions, theme, "Pause all AI access", variant="danger_subtle", command=self.pause_all,
               tooltip="Stop every connected host from reading or changing memories").pack(
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
        tk.Label(column, text="Read only unless you allow more", font=theme.font("body_strong"),
                 background=c.info_bg, foreground=c.text, anchor="w").pack(fill="x")
        WrapLabel(column, "A connected host can search and read your memories. With Auto memory on, it can also save "
                  "and update lasting ones; BIO CE refuses secrets and anything taken from documents, and keeps "
                  "uncertain changes and every retraction for your review. BIO CE changes a host’s settings only "
                  "after you confirm, and never calls an AI model itself. Memories a host reads become part of that "
                  "conversation and "
                  "may be sent to the host’s AI model provider (for example OpenAI for Codex CLI or Anthropic for "
                  "Claude Code) under that provider’s terms.", font=theme.font("body"), foreground=c.text_secondary,
                  background=c.info_bg).pack(fill="x", pady=(theme.px(2), 0))

        self.cards: dict[str, HostCard] = {}
        for host in ("codex", "claude"):
            card = HostCard(self, body, host)
            card.pack(fill="x", pady=(theme.px(SPACE_M), 0))
            self.cards[host] = card

        self.review_card = Card(body, theme, padding=SPACE_L + 4)
        self.review_card.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        review_head = tk.Frame(self.review_card.body, background=c.surface)
        review_head.pack(fill="x")
        section_label(review_head, theme, "Needs your review").pack(side="left")
        self.review_pill = Pill(review_head, theme, "0", "neutral")
        self.review_pill.pack(side="left", padx=(theme.px(SPACE_S), 0))
        caption_label(self.review_card.body, theme, "Changes an AI host proposed that BIO CE won't make on its own: "
                      "uncertain or conflicting facts, and every retraction.", muted=True).pack(
            fill="x", pady=(theme.px(SPACE_XS), theme.px(SPACE_S)))
        self.review_list = tk.Frame(self.review_card.body, background=c.surface)
        self.review_list.pack(fill="x")

        self.activity_card = Card(body, theme, padding=SPACE_L + 4)
        self.activity_card.pack(fill="x", pady=(theme.px(SPACE_M), 0))
        section_label(self.activity_card.body, theme, "Recent AI activity").pack(fill="x")
        caption_label(self.activity_card.body, theme, "What hosts saved, updated, or tried to save. Select an "
                      "entry to open the memory.", muted=True).pack(fill="x", pady=(theme.px(SPACE_XS),
                                                                                     theme.px(SPACE_S)))
        self.activity_list = tk.Frame(self.activity_card.body, background=c.surface)
        self.activity_list.pack(fill="x")

        backups = Card(body, theme, padding=SPACE_L + 4)
        backups.pack(fill="x", pady=(theme.px(SPACE_M), theme.px(SPACE_S)))
        row = tk.Frame(backups.body, background=c.surface)
        row.pack(fill="x")
        column = tk.Frame(row, background=c.surface)
        column.pack(side="left", fill="x", expand=True)
        section_label(column, theme, "Settings backups").pack(fill="x")
        WrapLabel(column, "Before connecting or disconnecting, BIO CE copies the host’s MCP settings to your BIO CE "
                  "folder. These copies can contain settings or environment values for other servers and are not "
                  "encrypted. Delete them when you no longer need them.", font=theme.font("body"),
                  foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        Button(row, theme, "Open folder", icon="folder", command=app.open_connection_backups).pack(
            side="right", anchor="n", padx=(theme.px(SPACE_L), 0))

    def refresh(self) -> None:
        super().refresh()
        statuses = self.app.host_statuses(refresh=True)
        for host, card in self.cards.items():
            if not card.busy:
                card.apply(statuses.get(host))
        self.refresh_activity()

    @property
    def control(self):
        return getattr(self.app.connection_manager, "control", None)

    def refresh_activity(self) -> None:
        theme, c = self.theme, self.colors
        for frame in (self.review_list, self.activity_list):
            for child in frame.winfo_children():
                child.destroy()
        control = self.control
        reviews: tuple[ReviewItem, ...] = control.reviews(limit=50) if control is not None else ()
        activity: tuple[AuditEntry, ...] = control.recent_activity(limit=15) if control is not None else ()
        self.review_pill.set(str(len(reviews)), "warning" if reviews else "neutral")
        if not reviews:
            caption_label(self.review_list, theme, "Nothing to review.", muted=True).pack(fill="x")
        for item in reviews:
            self._review_row(item)
        if not activity:
            caption_label(self.activity_list, theme, "No AI activity yet.", muted=True).pack(fill="x")
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

    def _review_row(self, item: ReviewItem) -> None:
        theme, c = self.theme, self.colors
        box = tk.Frame(self.review_list, background=c.surface_alt, highlightthickness=1,
                       highlightbackground=c.border)
        box.pack(fill="x", pady=(0, theme.px(SPACE_S)))
        inner = tk.Frame(box, background=c.surface_alt)
        inner.pack(fill="x", padx=theme.px(SPACE_M), pady=theme.px(SPACE_S))
        top = tk.Frame(inner, background=c.surface_alt)
        top.pack(fill="x")
        Pill(top, theme, REVIEW_KIND_LABELS.get(item.kind, item.kind), "info").pack(side="left")
        tk.Label(top, text=f"{host_name(item.host)} · {relative_time(item.created_at)}", font=theme.font("caption"),
                 background=c.surface_alt, foreground=c.text_muted).pack(side="left", padx=(theme.px(SPACE_S), 0))
        tk.Label(inner, text=item.title, font=theme.font("body_strong"), background=c.surface_alt,
                 foreground=c.text, anchor="w", justify="left").pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        if item.content:
            WrapLabel(inner, preview(item.content, 400), font=theme.font("body"), foreground=c.text_secondary,
                      background=c.surface_alt).pack(fill="x")
        WrapLabel(inner, f"Why it needs you: {item.review_reason}", font=theme.font("caption"),
                  foreground=c.text_muted, background=c.surface_alt).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        buttons = tk.Frame(inner, background=c.surface_alt)
        buttons.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        approve_text = "Retract memory" if item.kind == "retract" else "Approve"
        Button(buttons, theme, approve_text, variant="danger" if item.kind == "retract" else "primary",
               command=lambda: self.approve_review(item)).pack(side="left")
        if item.kind != "retract":
            Button(buttons, theme, "Edit and approve…",
                   command=lambda: self.approve_review(item, edit=True)).pack(side="left",
                                                                            padx=(theme.px(SPACE_S), 0))
        Button(buttons, theme, "Reject", command=lambda: self.reject_review(item)).pack(
            side="left", padx=(theme.px(SPACE_S), 0))

    def focus_default(self) -> None:
        self.focus_set()

    # Actions --------------------------------------------------------------

    def connect_host(self, host: str) -> None:
        name = host_name(host)
        if not self.app.confirm(
            title=f"Connect {name}?",
            message=f"BIO CE will use {name}’s own command to add one MCP server entry named “bio-ce” "
                    "to your user settings.",
            points=(
                f"{name} will be able to search and read active memories in your personal store. It can't add, "
                "edit, or retract them.",
                f"Memories {name} reads become part of your conversation and may be sent to the AI model provider "
                f"{name} uses ({PROVIDER_EXAMPLES[host]}). BIO CE can't control what happens to them there.",
                "Auto memory stays off: the host can only search and read until you turn it on.",
                "Your current MCP settings are backed up first. The backup can contain settings or environment "
                "values for other servers and is stored locally without encryption.",
                "BIO CE then runs a local read-only check against your database. No AI model is called and no "
                "memory is written.",
            ),
            confirm_text="Connect",
        ):
            return
        card = self.cards[host]
        card.set_busy("Connecting…")
        card.show_checks(())
        self.app.run_task(
            lambda: self.app.connection_manager.connect(host, approved=True),
            lambda result: self._connected(host, result),
            lambda error: self._failed(host, error, "connect"),
        )

    def disconnect_host(self, host: str) -> None:
        name = host_name(host)
        if not self.app.confirm(
            title=f"Disconnect {name}?",
            message=f"BIO CE will remove only its own “bio-ce” entry from {name}. Other MCP servers stay "
                    "as they are.",
            points=("The current MCP settings are backed up first.",
                    "Your memories are not changed. You can connect again at any time."),
            confirm_text="Disconnect",
        ):
            return
        card = self.cards[host]
        card.set_busy("Disconnecting…")
        card.show_checks(())
        self.app.run_task(
            lambda: self.app.connection_manager.disconnect(host, approved=True),
            lambda result: self._disconnected(host, result),
            lambda error: self._failed(host, error, "disconnect"),
        )

    def set_mode(self, host: str, mode: str) -> None:
        name = host_name(host)
        status = self.cards[host].status
        if status is not None and status.mode == mode:
            return
        if mode == MODE_AUTO_MEMORY and not self.app.confirm(
            title=f"Turn on Auto memory for {name}?",
            message=f"{name} will be able to save and update memories on its own while you work.",
            points=(
                *((f"{name} may not use Auto memory on its own. {auto_memory_support(host).detail}",)
                  if auto_memory_support(host).level != "available" else ()),
                "It may store lasting preferences, confirmed decisions, project goals, and clear corrections that "
                "you state. You can review, edit, and retract them here and on the Memories page.",
                "BIO CE refuses passwords, tokens, keys, and anything taken from files, web pages, or tool output. "
                "Uncertain or conflicting changes and every retraction wait for your review.",
                f"So that saving doesn't interrupt you, BIO CE lets {name} run BIO CE's own memory tools without "
                "asking each time. All other tools keep their current approval settings. Your settings file is "
                "backed up first.",
                f"Memories {name} reads or writes are part of your conversation and may be sent to its AI model "
                "provider.",
                "You can switch back to Read only or Paused at any time; running sessions follow on their next "
                "request.",
            ),
            confirm_text="Turn on Auto memory",
        ):
            return
        try:
            self.app.connection_manager.set_mode(host, mode)
        except MCPConnectionError as exc:
            self.app.notify("error", str(exc), title=f"Couldn't change {name}")
            return
        self.app.hosts_changed()
        self.app.notify("success", host_message(host, self.app.host_statuses(refresh=False).get(host)),
                        title=f"{name}: {MODE_LABELS[mode]}")

    def toggle_hooks(self, host: str) -> None:
        name = host_name(host)
        status = self.cards[host].status
        installing = not (status is not None and status.hooks_installed)
        if installing:
            trust = (" Codex runs new hooks only after you trust them: open Codex and use /hooks to review and "
                     "approve the two BIO CE entries." if host == "codex" else "")
            if not self.app.confirm(
                title=f"Add BIO CE session hooks to {name}?",
                message=f"BIO CE will add two hooks to {name}’s user settings so it can recall memories without "
                        "being asked.",
                points=(
                    "At session start, BIO CE adds its memory rules and memories related to the working folder.",
                    "With each message you send, BIO CE looks up memories that share words with it. Your message "
                    "is not stored or logged.",
                    "The hooks never save anything themselves and stay silent while access is paused.",
                    "Your current settings file is backed up first." + trust,
                ),
                confirm_text="Add hooks",
            ):
                return
        card = self.cards[host]
        card.set_busy("Updating hooks…")
        manager = self.app.connection_manager
        self.app.run_task(
            (lambda: manager.install_hooks(host, approved=True)) if installing
            else (lambda: manager.remove_hooks(host, approved=True)),
            lambda _result: self._hooks_done(host, installing),
            lambda error: self._failed(host, error, "hooks"),
        )

    def _hooks_done(self, host: str, installed: bool) -> None:
        self._finish(host)
        name = host_name(host)
        if installed:
            message = f"{name} will recall BIO CE memories in new sessions."
            if host == "codex":
                message += " Open Codex and approve the BIO CE hooks with /hooks."
        else:
            message = f"BIO CE removed its hooks from {name}."
        self.app.notify("success", message, title="Session hooks updated")

    def pause_all(self) -> None:
        control = self.control
        if control is None or not self.app.confirm(
            title="Pause all AI access?",
            message="Every connected host loses access to your memories until you choose a mode again.",
            points=("Running sessions are refused on their next request.", "Nothing is deleted or disconnected."),
            confirm_text="Pause all",
            danger=True,
        ):
            return
        count = control.pause_all()
        self.app.hosts_changed()
        self.app.notify("success", f"Paused {count} connection{'s' if count != 1 else ''}.", title="AI access paused")

    def approve_review(self, item: ReviewItem, *, edit: bool = False) -> None:
        title, content = item.title, item.content
        if edit:
            edited = ReviewEditDialog(self, self.theme, title=item.title, content=item.content or "",
                                      reason=item.review_reason).ask()
            if edited is None:
                return
            title, content = edited
        elif item.kind == "retract" and not self.app.confirm(
            title="Retract this memory?",
            message=f"{host_name(item.host)} asked to retract it. BIO CE and AI hosts will no longer find or read it.",
            quote=item.title,
            points=("Earlier revisions stay inside the database file. Retraction is not a secure erase.",),
            confirm_text="Retract memory",
            danger=True,
        ):
            return
        try:
            revision = self.app.service.approve_review(self.control, item.review_id, title=title, content=content)
        except Exception as exc:  # conflicts, secrets, or a stale request
            self.app.notify("warning", str(exc), title="Couldn't apply the change")
            self.refresh_activity()
            return
        self.app.data_changed(select=None if item.kind == "retract" else revision.memory_id)
        self.refresh_activity()
        verb = {"create": "Saved", "update": "Updated", "retract": "Retracted"}[item.kind]
        self.app.notify("success", f"“{preview(title, 60)}”", title=f"{verb} after your review")

    def reject_review(self, item: ReviewItem) -> None:
        self.app.service.reject_review(self.control, item.review_id)
        self.refresh_activity()
        self.app.notify("info", "Nothing was changed.", title="Suggestion rejected")

    def diagnose_host(self, host: str) -> None:
        card = self.cards[host]
        card.set_busy("Checking…")
        self.app.run_task(
            lambda: self.app.connection_manager.diagnose(host),
            lambda checks: self._diagnosed(host, checks),
            lambda error: self._failed(host, error, "diagnose"),
        )

    def _finish(self, host: str) -> None:
        self.cards[host].set_busy(None)
        self.app.hosts_changed()

    def _connected(self, host: str, result: ConnectionResult) -> None:
        self._finish(host)
        name = host_name(host)
        if result.already_configured:
            message = f"{name} was already connected. BIO CE verified the read-only server again."
        else:
            message = f"{name} can now search and read your memories."
            if result.backup_file is not None:
                message += " A backup of its previous MCP settings was saved."
        self.app.notify("success", message, title=f"{name} connected")

    def _disconnected(self, host: str, result: ConnectionResult) -> None:
        self._finish(host)
        name = host_name(host)
        if result.backup_file is not None:
            self.app.notify("success", f"BIO CE removed its entry from {name}. A backup of the previous MCP settings "
                            "was saved.", title=f"{name} disconnected")
        else:
            self.app.notify("info", f"{name} was already disconnected.", title=f"{name} disconnected")

    def _diagnosed(self, host: str, checks: tuple[DiagnosticCheck, ...]) -> None:
        self._finish(host)
        card = self.cards[host]
        card.show_checks(checks)
        self.update_idletasks()
        self.scroll.scroll_to_widget(card.results)
        failures = [check for check in checks if check.outcome == "fail"]
        name = host_name(host)
        if failures:
            self.app.notify("warning", f"{len(failures)} check{'s' if len(failures) != 1 else ''} need attention. "
                            "See the details under the host.", title=f"{name} diagnostics")
        else:
            self.app.notify("success", "Everything BIO CE can check locally looks right.",
                            title=f"{name} diagnostics passed")

    def _failed(self, host: str, error: BaseException, action: str) -> None:
        self._finish(host)
        name = host_name(host)
        titles = {"connect": f"Couldn't connect {name}", "disconnect": f"Couldn't disconnect {name}",
                  "diagnose": f"Couldn't check {name}", "hooks": f"Couldn't update {name}'s hooks"}
        if isinstance(error, MCPConnectionConflict):
            message = f"{error} Nothing was changed."
            kind = "warning"
        elif isinstance(error, MCPConnectionError):
            message = str(error)
            kind = "error"
        else:
            message = (f"BIO CE couldn't finish talking to {name}. Check that {name} works in a terminal, then try "
                       "again. Run diagnostics for details.")
            kind = "error"
        self.app.notify(kind, message, title=titles[action])


__all__ = ["ConnectionsPage", "HostCard", "host_message"]
