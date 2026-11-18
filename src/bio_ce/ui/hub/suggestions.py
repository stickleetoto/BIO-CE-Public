# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The Suggestions tab of the memory screen (v0.4.3 C, moved in v0.4.4): merge, keep, or update what is in the inbox.

BIO CE suggests; nothing changes until the user approves. Bulk approve and reject act only on the suggestions shown
(the space filter applies, K4) and say how many of each kind first. Approve and Reject both leave an Undo notice.
A merge draft is the most detailed item (v0.4.4 §9.1); sentences only the other items have are offered apart.
"""

from __future__ import annotations

from collections import Counter
import tkinter as tk
from tkinter import ttk

from bio_ce import curation
from bio_ce.curation import MERGE, PROMOTE, UPDATE_EXISTING, CurationError
from bio_ce.ui.format import format_timestamp, preview as short
from bio_ce.ui.hub.common import control_of, space_label
from bio_ce.ui.hub.data import ALL_SPACES
from bio_ce.ui.i18n import t
from bio_ce.ui.service_text import say
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS, SPACE_XXS
from bio_ce.ui.widgets import (
    Button,
    Card,
    EmptyState,
    FlowFrame,
    Pill,
    ScrollFrame,
    TextArea,
    WrapLabel,
)

ACTION_KEYS = {MERGE: "hub.sugg.merge", PROMOTE: "hub.sugg.promote", UPDATE_EXISTING: "hub.sugg.update"}


class SuggestionsView(tk.Frame):
    def __init__(self, master: tk.Misc, hub) -> None:
        theme, c = hub.theme, hub.colors
        super().__init__(master, background=c.bg)
        self.hub = hub
        self.app = hub.app
        self.theme = theme
        self.colors = c
        self.cards: dict[int, dict] = {}
        self.shown: list = []
        self._batches: list[tuple[str, str]] = []
        top = FlowFrame(self, gap=theme.px(SPACE_S), background=c.bg)
        top.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        self.top = top
        self.find_button = top.add(Button(top, theme, t("hub.sugg.find"), icon="refresh", command=self.find))
        self.filter = tk.StringVar(master=self, value=t("hub.sugg.all"))
        self.filter_box = top.add(ttk.Combobox(top, textvariable=self.filter, state="readonly", width=30,
                                               style="BIO.TCombobox", font=theme.font("body")))
        self.filter_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.approve_all = top.add(Button(top, theme, t("hub.sugg.approve_all"), variant="primary",
                                          command=self.approve_shown))
        self.reject_all = top.add(Button(top, theme, t("hub.sugg.reject_all"), variant="danger_subtle",
                                         command=self.reject_shown))
        for button in (self.find_button, self.approve_all, self.reject_all):
            self.app.gate(button, "review")
        # One line with "More" on the same line, the rest on request (POLISH §3.4); a row of its own made the list
        # run out of height in the smallest window.
        intro = tk.Frame(self, background=c.bg)
        intro.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        self.intro_full = WrapLabel(self, t("hub.sugg.intro"), font=theme.font("caption"),
                                    foreground=c.text_secondary, background=c.bg)
        self.intro_more = Button(intro, theme, t("hub.more"), icon="chevron_right", variant="link",
                                 command=lambda: self._show_intro(not self.intro_full.winfo_manager(), intro))
        self.intro_more.pack(side="right", anchor="n")
        WrapLabel(intro, t("hub.sugg.intro_short"), font=theme.font("body"), foreground=c.text_secondary,
                  background=c.bg).pack(side="left", fill="x", expand=True)
        self.empty = EmptyState(self, theme, icon="memories", title=t("hub.sugg.empty_title"),
                                message=t("hub.sugg.empty_message"))
        self.scroll = ScrollFrame(self, theme)

    def _show_intro(self, show: bool, row: tk.Frame) -> None:
        if show:
            self.intro_full.pack(fill="x", pady=(0, self.theme.px(SPACE_M)), after=row)
        else:
            self.intro_full.pack_forget()
        if self.intro_more.icon_label is not None:
            self.intro_more.icon_label.configure(text=self.theme.icon("chevron_down" if show else "chevron_right"))

    @property
    def control(self):
        return control_of(self.app)

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
        self.filter.set(next((text for key, text in self._batches if key == batch_id), t("hub.sugg.all")))
        self.refresh()

    # Data -------------------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        theme, c = self.theme, self.colors
        service, control = self.curation(), self.control
        try:
            batches = control.import_batches(limit=20) if control is not None else ()
        except Exception:  # noqa: BLE001
            batches = ()
        everything = t("hub.sugg.all")
        self._batches = [(batch["batch_id"], t("hub.sugg.from_import", when=format_timestamp(batch["created_at"])))
                         for batch in batches if batch["status"] != "undone"]
        labels = [everything] + [text for _key, text in self._batches]
        self.filter_box.configure(values=labels)
        if self.filter.get() not in labels:
            self.filter.set(everything)
        space_filter = self.hub.space_filter
        try:
            found = list(service.suggestions(batch_id=self.batch_filter())) if service is not None else []
        except Exception:  # noqa: BLE001
            found = []
        hidden = self.app.pending.hidden()
        self.shown = [s for s in found if (space_filter == ALL_SPACES or s.space_id == space_filter)
                      and f"suggestions:{s.proposal_id}" not in hidden]
        for child in self.scroll.body.winfo_children():
            child.destroy()
        self.cards = {}
        if not self.shown:
            self.scroll.pack_forget()
            self.empty.pack(fill="both", expand=True)
        else:
            self.empty.pack_forget()
            self.scroll.pack(fill="both", expand=True)
        spaces = {space.space_id: space for space in self.app.spaces()}
        for suggestion in self.shown:
            self._card(service, suggestion, spaces)
        allowed = self.app.allowed("review").enabled
        self.approve_all.set_enabled(bool(self.shown) and allowed)
        self.reject_all.set_enabled(bool(self.shown) and allowed)

    def _card(self, service, suggestion, spaces) -> None:
        theme, c = self.theme, self.colors
        card = Card(self.scroll.body, theme, padding=SPACE_L)
        card.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        head = tk.Frame(card.body, background=c.surface)
        head.pack(fill="x")
        Pill(head, theme, t(ACTION_KEYS[suggestion.action]),
             "info" if suggestion.action == MERGE else "success").pack(side="left")
        space = spaces.get(suggestion.space_id)
        name = space_label(space) if space is not None else suggestion.space_id
        tk.Label(head, text=f"{name} · {say(suggestion.reason)}", font=theme.font("caption"), background=c.surface,
                 foreground=c.text_muted).pack(side="left", padx=(theme.px(SPACE_S), 0))
        originals = service.originals(suggestion) if service is not None else []
        if suggestion.action == UPDATE_EXISTING and suggestion.target:
            WrapLabel(card.body, t("hub.sugg.update_note"), font=theme.font("caption"),
                      foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        sources = tk.Frame(card.body, background=c.surface)
        sources.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        for column, original in enumerate(originals):
            box = tk.Frame(sources, background=c.surface_alt, highlightthickness=1, highlightbackground=c.border)
            box.grid(row=0, column=column, sticky="nsew", padx=(0, theme.px(SPACE_XS)))
            sources.columnconfigure(column, weight=1, uniform="original")
            tk.Label(box, text=short(original.title, 40), font=theme.font("caption_strong"),
                     background=c.surface_alt, foreground=c.text, anchor="w").pack(
                fill="x", padx=theme.px(SPACE_S), pady=(theme.px(SPACE_XS), 0))
            WrapLabel(box, short(original.content or "", 200), font=theme.font("caption"),
                      foreground=c.text_secondary, background=c.surface_alt).pack(
                fill="x", padx=theme.px(SPACE_S), pady=(0, theme.px(SPACE_XS)))
        title_var = tk.StringVar(master=card, value=suggestion.draft_title)
        tk.Entry(card.body, textvariable=title_var, font=theme.font("body_strong"), background=c.surface_alt,
                 foreground=c.text, insertbackground=c.text, relief="flat").pack(fill="x", pady=(theme.px(SPACE_S), 0))
        text = TextArea(card.body, theme, font="body")
        text.text.configure(height=3)
        text.set(suggestion.draft_content)
        text.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        parts = {"card": card, "title": title_var, "text": text, "extras": {}}
        if suggestion.action == MERGE and originals:
            self._extras(card, originals, suggestion.draft_content, parts)
        buttons = tk.Frame(card.body, background=c.surface)
        buttons.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        made = [Button(buttons, theme, t("hub.sugg.approve"), variant="primary",
                       command=lambda s=suggestion: self.approve(s.proposal_id)),
                Button(buttons, theme, t("hub.sugg.approve_edited"),
                       command=lambda s=suggestion: self.approve(s.proposal_id, edited=True)),
                Button(buttons, theme, t("hub.sugg.reject"), variant="danger_subtle",
                       command=lambda s=suggestion: self.reject(s.proposal_id))]
        made[0].pack(side="left")
        made[1].pack(side="left", padx=(theme.px(SPACE_S), 0))
        made[2].pack(side="right")
        for button in made:
            self.app.gate(button, "review")
        self.cards[suggestion.proposal_id] = parts

    def _extras(self, card, originals, draft: str, parts: dict) -> None:
        """K11: what only the other items say, each with Add (appends it to the draft; not added by default)."""
        merge_extras = getattr(curation, "merge_extras", None)
        extras = merge_extras(originals, draft) if merge_extras is not None else []
        if not extras:
            return
        theme, c = self.theme, self.colors
        box = tk.Frame(card.body, background=c.surface)
        box.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        tk.Label(box, text=t("hub.sugg.extras"), font=theme.font("caption_strong"), background=c.surface,
                 foreground=c.text_muted, anchor="w").pack(fill="x")
        for sentence in extras:
            row = tk.Frame(box, background=c.surface)
            row.pack(fill="x", pady=(theme.px(SPACE_XXS), 0))
            button = Button(row, theme, t("hub.sugg.add_extra"), variant="link")
            button.pack(side="right", anchor="n")
            WrapLabel(row, sentence, font=theme.font("caption"), foreground=c.text_secondary).pack(
                side="left", fill="x", expand=True)
            button.set_command(lambda s=sentence, b=button: self.add_extra(parts, s, b))
            parts["extras"][sentence] = button

    def add_extra(self, parts: dict, sentence: str, button=None) -> None:
        text = parts["text"]
        current = text.get().rstrip()
        text.set(f"{current} {sentence}".strip() if current else sentence)
        if button is not None:
            button.set_enabled(False)

    # Actions ----------------------------------------------------------------------------------------------------

    def find(self) -> int:
        service = self.curation()
        if service is None or not self.app.require_action("review"):
            return 0
        try:
            added = service.find()
        except Exception:  # noqa: BLE001 - shown to the user
            self.app.notify("error", t("hub.sugg.find_failed"), title=t("hub.sugg.title"))
            return 0
        self.app.refresh_badges()
        self.hub.refresh()
        self.app.notify("success" if added else "info",
                        t("hub.sugg.found", count=added) if added else t("hub.sugg.none_found"),
                        title=t("hub.sugg.title"))
        return added

    def approve(self, proposal_id: int, *, edited: bool = False) -> bool:
        service = self.curation()
        if service is None or not self.app.require_action("review"):
            return False
        options = {}
        if edited and proposal_id in self.cards:
            parts = self.cards[proposal_id]
            options = {"title": parts["title"].get(), "content": parts["text"].get()}
        self.app.pending.flush()  # a waiting discard of these items runs first
        try:
            service.approve(proposal_id, **options)
        except CurationError as exc:
            self.app.notify("warning", say(exc), title=t("hub.sugg.not_approved"))
            self.hub.refresh()
            return False
        except Exception:  # noqa: BLE001 - shown to the user
            self.app.notify("error", t("hub.sugg.approve_failed"), title=t("hub.sugg.not_approved"))
            return False
        self.app.data_changed()
        self.app.notify("success", t("hub.sugg.approved"), title=t("hub.sugg.approved_title"),
                        action=(t("common.undo"), lambda: self.undo([proposal_id], ask=False)))
        return True

    def undo(self, proposal_ids: list[int], *, ask: bool = True) -> int:
        """Undo approved suggestions: the result gets its earlier text back (the undone version stays in History),
        a memory a suggestion created is retracted, and the inbox items come back unchanged."""
        service = self.curation()
        if service is None or not proposal_ids or not self.app.require_action("review"):
            return 0
        if ask and not self.app.confirm(
                title=t("hub.sugg.undo_title", count=len(proposal_ids)), message=t("hub.sugg.undo_message"),
                points=(t("hub.sugg.undo_point_history"), t("hub.sugg.undo_point_retract"),
                        t("hub.sugg.undo_point_again")),
                confirm_text=t("common.undo")):
            return 0
        done, refused = 0, []
        for proposal_id in proposal_ids:
            try:
                service.undo(proposal_id)
                done += 1
            except CurationError as exc:
                refused.append(say(exc))
            except Exception:  # noqa: BLE001 - shown to the user
                refused.append(t("hub.sugg.undo_failed"))
        self.app.data_changed()
        if refused:
            self.app.notify("warning", (t("hub.sugg.undid_some", count=done) + " " if done else "") + refused[0],
                            title=t("hub.sugg.not_undone"))
        else:
            self.app.notify("success", t("hub.sugg.undid", count=done), title=t("hub.sugg.undone_title"))
        return done

    def reject(self, proposal_id: int) -> bool:
        service = self.curation()
        if service is None or not self.app.require_action("review"):
            return False
        try:
            service.reject(proposal_id)
        except Exception:  # noqa: BLE001 - a stale card
            self.hub.refresh()
            return False
        self.app.refresh_badges()
        self.hub.refresh()
        self.app.notify("info", t("hub.sugg.rejected"), title=t("hub.sugg.rejected_title"),
                        action=(t("common.undo"), lambda: self.unreject([proposal_id])))
        return True

    def unreject(self, proposal_ids: list[int]) -> int:
        """Undo a rejection: the suggestion is waiting again (its status goes back to pending)."""
        control = self.control
        if control is None:
            return 0
        back = 0
        for proposal_id in proposal_ids:
            try:
                control.set_curation_proposal_status(int(proposal_id), "pending")
                back += 1
            except Exception:  # noqa: BLE001
                continue
        self.app.refresh_badges()
        self.hub.refresh()
        self.app.notify("success", t("hub.sugg.unrejected", count=back), title=t("hub.sugg.undone_title"))
        return back

    def _kinds(self) -> list[str]:
        counts = Counter(t(ACTION_KEYS[item.action]) for item in self.shown)
        return [f"{label}: {count}" for label, count in counts.items()]

    def approve_shown(self) -> dict | None:
        service = self.curation()
        if service is None or not self.shown or not self.app.require_action("review"):
            return None
        if not self.app.confirm(title=t("hub.sugg.approve_all_title", count=len(self.shown)),
                                message=t("hub.sugg.approve_all_message"), points=self._kinds(),
                                confirm_text=t("hub.sugg.approve_all_button")):
            return None
        self.app.pending.flush()
        outcome = service.approve_many([item.proposal_id for item in self.shown])
        self.app.data_changed()
        approved = list(outcome["ids"])
        message = (t("hub.sugg.approved_many_skipped", count=outcome["approved"], skipped=outcome["skipped"])
                   if outcome["skipped"] else t("hub.sugg.approved_many", count=outcome["approved"]))
        self.app.notify("success", message, title=t("hub.sugg.title"),
                        action=(t("hub.sugg.undo_all"), lambda: self.undo(approved, ask=False)) if approved else None)
        return outcome

    def reject_shown(self) -> int | None:
        service = self.curation()
        if service is None or not self.shown or not self.app.require_action("review"):
            return None
        if not self.app.confirm(title=t("hub.sugg.reject_all_title", count=len(self.shown)),
                                message=t("hub.sugg.reject_all_message"), points=self._kinds(),
                                confirm_text=t("hub.sugg.reject_all_button"), danger=True):
            return None
        ids = [item.proposal_id for item in self.shown]
        count = service.reject_many(ids)
        self.app.refresh_badges()
        self.hub.refresh()
        self.app.notify("info", t("hub.sugg.rejected_many", count=count), title=t("hub.sugg.rejected_title"),
                        action=(t("hub.sugg.undo_all"), lambda: self.unreject(ids)))
        return count


__all__ = ["ACTION_KEYS", "SuggestionsView"]
