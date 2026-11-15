# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Sorting suggestions for the inbox (v0.4.3 C): merge, keep as a memory, update a memory.

BIO CE suggests; nothing changes until the user approves. Bulk approve and reject act only on the suggestions shown
and say how many of each kind first.
"""

from __future__ import annotations

from collections import Counter
import tkinter as tk
from tkinter import ttk

from bio_ce.curation import ACTION_LABELS, MERGE, UPDATE_EXISTING, CurationError
from bio_ce.ui.format import format_timestamp, plural, preview as short
from bio_ce.ui.pages import Page
from bio_ce.ui.pages.inbox import SpaceBar
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import Button, Card, EmptyState, FlowFrame, Pill, ScrollFrame, TextArea, WrapLabel, section_label

ALL = "All suggestions"


class SuggestionsPage(Page):
    key = "suggestions"
    nav_key = "memories"
    title = "Memories"
    subtitle = "Suggestions: merge, keep, or update what is in the inbox"

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        self.cards: dict[int, dict] = {}
        self.shown: list = []
        Button(self.actions, theme, "Back to inbox", variant="subtle",
               command=lambda: app.show_page("inbox")).pack(side="right")
        self.space_bar = SpaceBar(self, app, active="suggestions")
        self.space_bar.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        top = FlowFrame(self, gap=theme.px(SPACE_S), background=c.bg)
        top.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        self.find_button = top.add(Button(top, theme, "Find suggestions", icon="refresh", command=self.find))
        self.filter = tk.StringVar(master=self, value=ALL)
        self.filter_box = top.add(ttk.Combobox(top, textvariable=self.filter, state="readonly", width=34,
                                               style="BIO.TCombobox", font=theme.font("body")))
        self.filter_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.approve_all = top.add(Button(top, theme, "Approve all shown…", variant="primary",
                                          command=self.approve_shown))
        self.reject_all = top.add(Button(top, theme, "Reject all shown…", variant="danger_subtle",
                                         command=self.reject_shown))
        for button in (self.find_button, self.approve_all, self.reject_all):
            app.gate(button, "review")
        WrapLabel(self, "BIO CE compares what is in the inbox and suggests merging repeats, keeping items your hosts "
                  "keep using, and updating memories an item adds to. It never calls an AI model, and nothing "
                  "changes until you approve.", font=theme.font("body"), foreground=c.text_secondary,
                  background=c.bg).pack(fill="x", pady=(0, theme.px(SPACE_M)))
        self.empty = EmptyState(self, theme, icon="memories", title="No suggestions",
                                message="Nothing to sort right now. BIO CE looks again every day and after imports.")
        self.scroll = ScrollFrame(self, theme)
        self._batches: list[tuple[str, str]] = []

    @property
    def control(self):
        return getattr(self.app.connection_manager, "control", None)

    def curation(self):
        control = self.control
        if control is None:
            return None
        return self.app.service.curation(control, self.app.spaces())

    def batch_filter(self) -> str | None:
        label = self.filter.get()
        return next((batch_id for batch_id, text in self._batches if text == label), None)

    def show_batch(self, batch_id: str | None) -> None:
        self.refresh()
        label = next((text for key, text in self._batches if key == batch_id), ALL)
        self.filter.set(label)
        self.refresh()

    # Data -----------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        super().refresh()
        self.space_bar.refresh()
        theme, c = self.theme, self.colors
        service, control = self.curation(), self.control
        try:
            batches = control.import_batches(limit=20) if control is not None else ()
        except Exception:  # noqa: BLE001
            batches = ()
        self._batches = [(batch["batch_id"], f"From the import of {format_timestamp(batch['created_at'])}")
                         for batch in batches if batch["status"] != "undone"]
        self.filter_box.configure(values=[ALL] + [text for _key, text in self._batches])
        if self.filter.get() not in [ALL] + [text for _key, text in self._batches]:
            self.filter.set(ALL)
        try:
            self.shown = list(service.suggestions(batch_id=self.batch_filter())) if service is not None else []
        except Exception:  # noqa: BLE001
            self.shown = []
        for child in self.scroll.body.winfo_children():
            child.destroy()
        self.cards = {}
        if not self.shown:
            self.scroll.pack_forget()
            self.empty.pack(fill="both", expand=True)
        else:
            self.empty.pack_forget()
            self.scroll.pack(fill="both", expand=True)
        names = {space.space_id: space.display_name for space in self.app.spaces()}
        for suggestion in self.shown:
            card = Card(self.scroll.body, theme, padding=SPACE_L)
            card.pack(fill="x", pady=(0, theme.px(SPACE_M)))
            head = tk.Frame(card.body, background=c.surface)
            head.pack(fill="x")
            Pill(head, theme, ACTION_LABELS[suggestion.action],
                 "info" if suggestion.action == MERGE else "success").pack(side="left")
            tk.Label(head, text=f"{names.get(suggestion.space_id, suggestion.space_id)} · {suggestion.reason}",
                     font=theme.font("caption"), background=c.surface, foreground=c.text_muted).pack(
                side="left", padx=(theme.px(SPACE_S), 0))
            originals = service.originals(suggestion) if service is not None else []
            if suggestion.action == UPDATE_EXISTING and suggestion.target:
                WrapLabel(card.body, "Updates your memory with what the inbox item adds. You can edit the text first.",
                          font=theme.font("caption"), foreground=c.text_secondary).pack(
                    fill="x", pady=(theme.px(SPACE_XS), 0))
            sources = tk.Frame(card.body, background=c.surface)
            sources.pack(fill="x", pady=(theme.px(SPACE_S), 0))
            for column, original in enumerate(originals):
                box = tk.Frame(sources, background=c.surface_alt, highlightthickness=1, highlightbackground=c.border)
                box.grid(row=0, column=column, sticky="nsew", padx=(0, theme.px(SPACE_XS)))
                sources.columnconfigure(column, weight=1)
                tk.Label(box, text=short(original.title, 40), font=theme.font("caption_strong"),
                         background=c.surface_alt, foreground=c.text, anchor="w").pack(
                    fill="x", padx=theme.px(SPACE_S), pady=(theme.px(SPACE_XS), 0))
                WrapLabel(box, short(original.content or "", 200), font=theme.font("caption"),
                          foreground=c.text_secondary, background=c.surface_alt).pack(
                    fill="x", padx=theme.px(SPACE_S), pady=(0, theme.px(SPACE_XS)))
            title_var = tk.StringVar(master=card, value=suggestion.draft_title)
            tk.Entry(card.body, textvariable=title_var, font=theme.font("body_strong"), background=c.surface_alt,
                     foreground=c.text, insertbackground=c.text, relief="flat").pack(
                fill="x", pady=(theme.px(SPACE_S), 0))
            text = TextArea(card.body, theme, font="body")
            text.text.configure(height=3)
            text.set(suggestion.draft_content)
            text.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
            buttons = tk.Frame(card.body, background=c.surface)
            buttons.pack(fill="x", pady=(theme.px(SPACE_S), 0))
            Button(buttons, theme, "Approve", variant="primary",
                   command=lambda s=suggestion: self.approve(s.proposal_id)).pack(side="left")
            Button(buttons, theme, "Approve as edited", command=lambda s=suggestion: self.approve(
                s.proposal_id, edited=True)).pack(side="left", padx=(theme.px(SPACE_S), 0))
            Button(buttons, theme, "Reject", variant="danger_subtle",
                   command=lambda s=suggestion: self.reject(s.proposal_id)).pack(side="right")
            self.cards[suggestion.proposal_id] = {"card": card, "title": title_var, "text": text}
        self.approve_all.set_enabled(bool(self.shown) and self.app.allowed("review").enabled)
        self.reject_all.set_enabled(bool(self.shown) and self.app.allowed("review").enabled)

    # Actions --------------------------------------------------------------------------------------------

    def find(self) -> int:
        service = self.curation()
        if service is None or not self.app.require_action("review"):
            return 0
        try:
            added = service.find()
        except Exception:  # noqa: BLE001 - shown to the user
            self.app.notify("error", "BIO CE couldn't look for suggestions. Nothing was changed.",
                            title="Suggestions")
            return 0
        self.app.refresh_badges()
        self.refresh()
        self.app.notify("info" if not added else "success",
                        f"{plural(added, 'new suggestion')}." if added else "No new suggestions.",
                        title="Suggestions")
        return added

    def approve(self, proposal_id: int, *, edited: bool = False) -> bool:
        service = self.curation()
        if service is None or not self.app.require_action("review"):
            return False
        options = {}
        if edited and proposal_id in self.cards:
            parts = self.cards[proposal_id]
            options = {"title": parts["title"].get(), "content": parts["text"].get()}
        try:
            service.approve(proposal_id, **options)
        except CurationError as exc:
            self.app.notify("warning", str(exc), title="Not approved")
            self.refresh()
            return False
        except Exception:  # noqa: BLE001 - shown to the user
            self.app.notify("error", "BIO CE couldn't carry out this suggestion. Nothing was changed.",
                            title="Not approved")
            return False
        self.app.data_changed()
        self.refresh()
        return True

    def reject(self, proposal_id: int) -> bool:
        service = self.curation()
        if service is None:
            return False
        try:
            service.reject(proposal_id)
        except Exception:  # noqa: BLE001
            self.refresh()
            return False
        self.app.refresh_badges()
        self.refresh()
        return True

    def _kinds(self) -> list[str]:
        counts = Counter(ACTION_LABELS[item.action] for item in self.shown)
        return [f"{label}: {count}" for label, count in counts.items()]

    def approve_shown(self) -> dict | None:
        service = self.curation()
        if service is None or not self.shown or not self.app.require_action("review"):
            return None
        if not self.app.confirm(
            title=f"Approve {plural(len(self.shown), 'suggestion')}?",
            message="Each is carried out as shown here, without your edits. Suggestions whose items changed are "
                    "skipped.",
            points=self._kinds(), confirm_text="Approve all"):
            return None
        outcome = service.approve_many([item.proposal_id for item in self.shown])
        self.app.data_changed()
        self.refresh()
        self.app.notify("success", f"Approved {outcome['approved']}"
                        + (f"; skipped {outcome['skipped']} that changed" if outcome["skipped"] else "") + ".",
                        title="Suggestions")
        return outcome

    def reject_shown(self) -> int | None:
        service = self.curation()
        if service is None or not self.shown:
            return None
        if not self.app.confirm(
            title=f"Reject {plural(len(self.shown), 'suggestion')}?",
            message="The inbox items stay as they are. BIO CE won't suggest the same groups again.",
            points=self._kinds(), confirm_text="Reject all", danger=True):
            return None
        count = service.reject_many([item.proposal_id for item in self.shown])
        self.app.refresh_badges()
        self.refresh()
        return count


__all__ = ["SuggestionsPage"]
