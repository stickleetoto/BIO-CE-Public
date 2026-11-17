# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Filters and sort of the memory screen (v0.4.4 F4): where a memory came from (added here, imported, from an AI),
which AI host, how recently it changed, whether an import marked it sensitive, and the order. The space is the chip
row and the state the tabs, as before. The choice is remembered (``ControlStore.hub_view``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tkinter as tk
from tkinter import ttk

from bio_ce.ui.format import parse_timestamp
from bio_ce.ui.hub.common import control_of, in_space
from bio_ce.ui.hub.data import INBOX, MEMORIES, RETRACTED
from bio_ce.ui.i18n import t
from bio_ce.ui.theme import SPACE_S
from bio_ce.ui.widgets import FlowFrame

CHOICES = {"source": ("any", "added", "imported", "ai"), "host": ("any", "codex", "claude", "claude_desktop"),
           "period": ("any", "7d", "30d", "1y"), "sensitive": ("any", "only"), "sort": ("changed", "created", "title")}
DEFAULT = {key: values[0] for key, values in CHOICES.items()}
FILTERED_STATES = (MEMORIES, INBOX, RETRACTED)
_DAYS = {"7d": 7, "30d": 30, "1y": 365}
_AI_SOURCES = ("ai-auto-memory", "ai-suggested-user-approved", "ai-host-auto-memory")


def text_columns(text: str) -> int:
    """How many average-character columns ``text`` takes: Hangul and other wide (CJK) characters take two (a ttk
    box's width counts average Latin characters, so a Korean choice was cut off)."""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def source_group(source_type: str) -> str:
    if source_type == "user-imported":
        return "imported"
    if source_type in _AI_SOURCES or source_type.startswith("ai-"):
        return "ai"
    return "added"


def host_of(record) -> str | None:
    """The AI host a memory or inbox item came from: from its source reference ("codex:…") or its source's host."""
    metadata = getattr(getattr(record, "source", None), "metadata", None) or {}
    host = metadata.get("host") if isinstance(metadata, dict) else None
    if isinstance(host, str) and host in CHOICES["host"]:
        return host
    reference = str(getattr(record, "source_ref", "") or getattr(getattr(record, "source", None), "source_ref", ""))
    prefix = reference.split(":", 1)[0]
    return prefix if prefix in CHOICES["host"][1:] else None


def _source_type(record) -> str:
    return str(getattr(record, "source_type", "") or getattr(getattr(record, "source", None), "source_type", ""))


def is_filtered(view: dict) -> bool:
    return any(view.get(key, DEFAULT[key]) != DEFAULT[key] for key in ("source", "host", "period", "sensitive"))


def apply(items: list, view: dict, facts: dict[str, dict], *, now: datetime | None = None) -> list:
    """``items`` (newest change first) filtered and ordered by ``view``. ``facts``: memory id -> created_at and
    sensitive (only needed for those two)."""
    now = now or datetime.now(timezone.utc)
    source, host, period = view.get("source", "any"), view.get("host", "any"), view.get("period", "any")
    sensitive_only = view.get("sensitive") == "only"
    since = now - timedelta(days=_DAYS[period]) if period in _DAYS else None
    found = []
    for item in items:
        record = item.record.last if item.state == RETRACTED and hasattr(item.record, "last") else item.record
        if source != "any" and source_group(_source_type(record)) != source:
            continue
        if host != "any" and host_of(record) != host:
            continue
        if since is not None:
            changed = parse_timestamp(item.when)
            if changed is None or changed < since:
                continue
        if sensitive_only and not facts.get(item.item_id, {}).get("sensitive"):
            continue
        found.append(item)
    order = view.get("sort", "changed")
    if order == "title":
        found.sort(key=lambda item: (item.title or "").casefold())
    elif order == "created":
        found.sort(key=lambda item: facts.get(item.item_id, {}).get("created_at") or item.when or "", reverse=True)
    return found


def facts_for(app, items: list, view: dict) -> dict[str, dict]:
    """Created dates and sensitive marks, read only when the view needs them, per space of the items shown."""
    if view.get("sort") != "created" and view.get("sensitive") != "only":
        return {}
    if not hasattr(app.service, "memory_facts"):
        return {}
    facts: dict[str, dict] = {}
    for space in {id(item.space): item.space for item in items}.values():
        try:
            with in_space(app, space):
                facts.update(app.service.memory_facts())
        except Exception:  # noqa: BLE001 - without them the list keeps its default order
            continue
    return facts


class FilterBar(FlowFrame):
    """One row of drop-downs above the cards; ``on_change(view)`` runs on every choice."""

    def __init__(self, master: tk.Misc, app, on_change) -> None:
        theme = app.theme
        super().__init__(master, gap=theme.px(SPACE_S), background=theme.colors.bg)
        self.app, self.on_change = app, on_change
        self.view = self._saved_view()
        self.values: dict[str, tk.StringVar] = {}
        self.boxes: dict[str, ttk.Combobox] = {}
        for key in ("source", "host", "period", "sensitive", "sort"):
            # A label and its box wrap together (self-check 2026-11-17: "Sort" stayed on one line, its box went to
            # the next), and the box is wide enough for its longest choice in either language.
            pair = tk.Frame(self, background=theme.colors.bg)
            tk.Label(pair, text=t(f"hub.filter.{key}"), font=theme.font("caption_strong"), background=theme.colors.bg,
                     foreground=theme.colors.text_muted).pack(side="left", padx=(0, theme.px(4)))
            labels = [t(f"hub.filter.{key}.{value}") for value in CHOICES[key]]
            variable = tk.StringVar(master=self, value=t(f"hub.filter.{key}.{self.view[key]}"))
            box = ttk.Combobox(pair, textvariable=variable, state="readonly", values=labels, style="BIO.TCombobox",
                               width=max(text_columns(label) for label in labels) + 3)
            box.bind("<<ComboboxSelected>>", lambda _e, k=key: self._chosen(k))
            box.pack(side="left")
            self.add(pair)
            self.values[key], self.boxes[key] = variable, box
        self.clear_button = self.add(tk.Label(self, text=t("hub.filter.clear"), font=theme.font("caption"),
                                              background=theme.colors.bg, foreground=theme.colors.accent,
                                              cursor="hand2"))
        self.clear_button.bind("<Button-1>", lambda _e: self.clear())
        self._show_clear()

    def _saved_view(self) -> dict:
        control = control_of(self.app)
        try:
            return control.hub_view() if control is not None and hasattr(control, "hub_view") else dict(DEFAULT)
        except Exception:  # noqa: BLE001 - a damaged setting never breaks the screen
            return dict(DEFAULT)

    def _chosen(self, key: str) -> None:
        label = self.values[key].get()
        for value in CHOICES[key]:
            if t(f"hub.filter.{key}.{value}") == label:
                self.set(key, value)
                return

    def set(self, key: str, value: str) -> None:
        if value not in CHOICES[key]:
            raise ValueError(value)
        self.view = {**self.view, key: value}
        self.values[key].set(t(f"hub.filter.{key}.{value}"))
        control = control_of(self.app)
        if control is not None and hasattr(control, "set_hub_view"):
            try:
                control.set_hub_view(self.view)
            except Exception:  # noqa: BLE001 - the choice still applies now
                pass
        self._show_clear()
        self.on_change(self.view)

    def clear(self) -> None:
        for key in ("source", "host", "period", "sensitive"):
            self.view[key] = DEFAULT[key]
            self.values[key].set(t(f"hub.filter.{key}.{DEFAULT[key]}"))
        self.set("sort", self.view["sort"])

    def _show_clear(self) -> None:
        self.set_visible(self.clear_button, is_filtered(self.view))

