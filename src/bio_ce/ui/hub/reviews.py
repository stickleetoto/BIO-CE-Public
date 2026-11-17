# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The Reviews tab of the memory screen (v0.4.4 §2.3; moved from Connections "Needs your review").

What an AI host asked to change waits here; nothing changes before the user approves. A change shows the current
memory and the proposal side by side with the differences marked. When the two hardly share a topic
(``topic_overlap`` below ``TOPIC_THRESHOLD``) the proposal may be a different fact: a warning band says so and the
default button adds it as a new memory instead of overwriting (the same risk v0.4.3 blocked in imports).

Approve leaves an Undo notice (the memory gets its earlier text back as a new revision, or a memory the review
created is retracted); Reject waits eight seconds for Undo before it is recorded, like a delete.
"""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import re
import tkinter as tk

from bio_ce.core.models import MemoryNotFoundError
from bio_ce.curation import TOPIC_THRESHOLD, topic_overlap
from bio_ce.memory_policy import detect_secrets
from bio_ce.ui.dialogs import ReviewEditDialog
from bio_ce.ui.format import host_name, preview
from bio_ce.ui.hub.common import AutoText, control_of, in_space, space_label, when
from bio_ce.ui.hub.data import REVIEWS, HubItem
from bio_ce.ui.i18n import t
from bio_ce.ui.service_text import say
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import Button, Card, EmptyState, FlowFrame, Pill, ScrollFrame, WrapLabel

KIND_KEYS = {"create": "hub.review.kind_create", "update": "hub.review.kind_update",
             "retract": "hub.review.kind_retract"}
PENDING_KEYS = {"create": "hub.review.pending_create", "update": "hub.review.pending_update",
                "retract": "hub.review.pending_retract"}


@dataclass(frozen=True, slots=True)
class ReviewCard:
    review_id: int
    status_text: str
    buttons: tuple
    different_fact: bool = False
    default: str = ""


def word_diff(old: str, new: str) -> tuple[list, list]:
    """(old parts, new parts) as (text, tag) pairs: removed words tagged "del", added words "add"."""
    a, b = re.findall(r"\s+|\S+", old or ""), re.findall(r"\s+|\S+", new or "")
    left: list = []
    right: list = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            left.append(("".join(a[i1:i2]), None))
            right.append(("".join(b[j1:j2]), None))
            continue
        if i2 > i1:
            left.append(("".join(a[i1:i2]), "del"))
        if j2 > j1:
            right.append(("".join(b[j1:j2]), "add"))
    return left, right


def different_fact(current: str, proposed: str) -> bool:
    return topic_overlap(current, proposed) < TOPIC_THRESHOLD


class ReviewsView(tk.Frame):
    def __init__(self, master: tk.Misc, hub) -> None:
        theme, c = hub.theme, hub.colors
        super().__init__(master, background=c.bg)
        self.hub = hub
        self.app = hub.app
        self.theme = theme
        self.colors = c
        self.review_cards: list[ReviewCard] = []
        self.items: list[HubItem] = []
        WrapLabel(self, t("hub.review.intro"), font=theme.font("body"), foreground=c.text_secondary,
                  background=c.bg).pack(fill="x", pady=(0, theme.px(SPACE_M)))
        self.empty = EmptyState(self, theme, icon="check", title=t("hub.review.empty_title"),
                                message=t("hub.review.empty_message"))
        self.scroll = ScrollFrame(self, theme)

    @property
    def control(self):
        return control_of(self.app)

    def refresh(self, items: list[HubItem] | None = None) -> None:
        if items is None:
            items = self.hub.data.items(REVIEWS, self.hub.space_filter, self.hub.query.get())
        self.items = list(items)
        for child in self.scroll.body.winfo_children():
            child.destroy()
        self.review_cards = []
        if not self.items:
            self.scroll.pack_forget()
            self.empty.pack(fill="both", expand=True)
            return
        self.empty.pack_forget()
        self.scroll.pack(fill="both", expand=True)
        for item in self.items:
            self._card(item)

    def _current_memory(self, item: HubItem):
        review = item.record
        if review.kind not in ("update", "retract") or not review.memory_id:
            return None
        try:
            with in_space(self.app, item.space):
                return self.app.memory_engine().get(review.memory_id)
        except Exception:  # noqa: BLE001 - shown without the current text
            return None

    def _card(self, item: HubItem) -> None:
        theme, c = self.theme, self.colors
        review = item.record
        current = self._current_memory(item)
        proposed_text = f"{review.title}\n{review.content or ''}"
        warn = (review.kind == "update" and current is not None
                and different_fact(f"{current.title}\n{current.content or ''}", proposed_text))
        card = Card(self.scroll.body, theme, padding=SPACE_L)
        card.pack(fill="x", pady=(0, theme.px(SPACE_M)))
        if warn:
            band = tk.Frame(card.body, background=c.warning_bg)
            band.pack(fill="x", pady=(0, theme.px(SPACE_S)))
            tk.Label(band, text=t("hub.review.different_title"), font=theme.font("body_strong"),
                     background=c.warning_bg, foreground=c.warning, anchor="w").pack(
                fill="x", padx=theme.px(SPACE_M), pady=(theme.px(SPACE_S), 0))
            WrapLabel(band, t("hub.review.different_message"), font=theme.font("caption"), foreground=c.text,
                      background=c.warning_bg).pack(fill="x", padx=theme.px(SPACE_M), pady=(0, theme.px(SPACE_S)))
        head = tk.Frame(card.body, background=c.surface)
        head.pack(fill="x")
        Pill(head, theme, t(KIND_KEYS.get(review.kind, "hub.review.kind_update")),
             "warning" if review.kind != "create" else "info").pack(side="left", anchor="n")
        line = t("hub.review.line", host=host_name(review.host), when=when(review.created_at),
                 reason=say(review.review_reason), space=space_label(item.space))
        WrapLabel(head, line, font=theme.font("caption"), foreground=c.text_muted).pack(
            side="left", fill="x", expand=True, padx=(theme.px(SPACE_S), 0))
        if review.kind == "update" and current is not None:
            self._columns(card, current, review)
        else:
            tk.Label(card.body, text=review.title, font=theme.font("body_strong"), background=c.surface,
                     foreground=c.text, anchor="w", justify="left").pack(fill="x", pady=(theme.px(SPACE_S), 0))
            if review.content:
                WrapLabel(card.body, preview(review.content, 600), font=theme.font("body"),
                          foreground=c.text_secondary).pack(fill="x")
        status_text = t(PENDING_KEYS.get(review.kind, "hub.review.pending_update"))
        WrapLabel(card.body, status_text, font=theme.font("caption_strong"), foreground=c.warning).pack(
            fill="x", pady=(theme.px(SPACE_XS), 0))
        buttons = FlowFrame(card.body, gap=theme.px(SPACE_S), background=c.surface)
        buttons.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        made: list[Button] = []

        def add(text: str, variant: str, command) -> None:
            made.append(buttons.add(Button(buttons, theme, text, variant=variant, command=command)))

        if review.kind == "create":
            default = "approve"
            add(t("hub.review.add"), "primary", lambda: self.approve(item))
            add(t("hub.review.edit_add"), "secondary", lambda: self.approve(item, edit=True))
        elif review.kind == "retract":
            default = "approve"
            add(t("hub.review.retract"), "danger", lambda: self.approve(item))
        elif warn:
            default = "as_new"
            add(t("hub.review.add_new"), "primary", lambda: self.approve(item, as_new=True))
            add(t("hub.review.change_anyway"), "secondary", lambda: self.approve(item))
            add(t("hub.review.edit_approve"), "secondary", lambda: self.approve(item, edit=True))
        else:
            default = "approve"
            add(t("hub.review.change"), "primary", lambda: self.approve(item))
            add(t("hub.review.add_new"), "secondary", lambda: self.approve(item, as_new=True))
            add(t("hub.review.edit_approve"), "secondary", lambda: self.approve(item, edit=True))
        add(t("hub.review.reject"), "subtle", lambda: self.reject(item))
        for button in made:
            self.app.gate(button, "review")
        self.review_cards.append(ReviewCard(review.review_id, status_text, tuple(made), warn, default))

    def _columns(self, card, current, review) -> None:
        theme, c = self.theme, self.colors
        columns = tk.Frame(card.body, background=c.surface)
        columns.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        old_parts, new_parts = word_diff(f"{current.title}\n{current.content or ''}",
                                         f"{review.title}\n{review.content or ''}")
        for column, (label, parts) in enumerate(((t("hub.review.current"), old_parts),
                                                 (t("hub.review.proposed"), new_parts))):
            box = tk.Frame(columns, background=c.surface_alt, highlightthickness=1, highlightbackground=c.border)
            box.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else theme.px(SPACE_S), 0))
            columns.columnconfigure(column, weight=1, uniform="review")
            tk.Label(box, text=label, font=theme.font("caption_strong"), background=c.surface_alt,
                     foreground=c.text_muted, anchor="w").pack(fill="x", padx=theme.px(SPACE_S),
                                                               pady=(theme.px(SPACE_XS), 0))
            text = AutoText(box, theme, font="body", foreground=c.text_secondary, max_lines=40)
            text.tag_configure("del", foreground=c.danger, overstrike=True)
            text.tag_configure("add", foreground=c.success, underline=True)
            text.put(parts)
            text.pack(fill="x", padx=theme.px(SPACE_S), pady=(0, theme.px(SPACE_S)))

    # Actions ----------------------------------------------------------------------------------------------------

    def approve(self, item: HubItem, *, edit: bool = False, as_new: bool = False) -> bool:
        review = item.record
        control = self.control
        if control is None or not self.app.require_action("review"):
            return False
        title, content = review.title, review.content
        if edit:
            edited = ReviewEditDialog(self, self.theme, title=review.title, content=review.content or "",
                                      reason=say(review.review_reason)).ask()
            if edited is None:
                return False
            title, content = edited
        elif review.kind == "retract" and not self.app.confirm(
                title=t("hub.review.retract_title"),
                message=t("hub.review.retract_message", host=host_name(review.host)), quote=review.title,
                points=(t("hub.review.retract_point"),), confirm_text=t("hub.review.retract"), danger=True):
            return False
        before = self._current_memory(item) if review.kind == "update" and not as_new else None
        self.app.pending.flush()
        try:
            with in_space(self.app, item.space):
                if as_new:
                    revision = self._add_as_new(control, review, title, content or "")
                else:
                    revision = self.app.service.approve_review(control, review.review_id, title=title,
                                                               content=content)
        except Exception as exc:  # noqa: BLE001 - conflicts, secrets, or a stale request
            self.app.notify("warning", say(exc) or t("hub.review.failed"), title=t("hub.review.failed_title"))
            self.app.data_changed()
            return False
        self.app.data_changed()
        verb = {"create": "hub.review.saved", "update": "hub.review.updated",
                "retract": "hub.review.retracted"}[review.kind]
        if as_new:
            verb = "hub.review.saved"
        action = None
        if review.kind == "update" and before is not None and not as_new:
            action = (t("common.undo"), lambda: self.undo_update(item, before, revision))
        elif review.kind == "create" or as_new:
            action = (t("common.undo"), lambda: self.undo_create(item, revision))
        self.app.notify("success", f"“{preview(title, 60)}”" + (" " + t("hub.review.undo_note") if action else ""),
                        title=t(verb), action=action)
        return True

    def _add_as_new(self, control, review, title: str, content: str):
        """"Add as a new memory" for a proposed change: the memory it would replace stays as it is."""
        service = self.app.service
        if hasattr(service, "approve_review_as_new"):  # the storage side for this (asked of the lead, v0.4.4)
            return service.approve_review_as_new(control, review.review_id, title=title, content=content)
        if detect_secrets(title, content):  # the review's own rule (an AI proposed this text)
            raise ValueError(t("hub.review.secret"))
        engine = self.app.memory_engine()
        outcome = engine.create(title=title, content=content, source_ref=f"{review.host}:review-{review.review_id}")
        if not outcome.persisted:
            raise ValueError("; ".join(outcome.reasons) or t("hub.review.failed"))
        service.reject_review(control, review.review_id)  # closes the review; the current memory is untouched
        return engine.get(outcome.memory_id)

    def undo_update(self, item: HubItem, before, after) -> bool:
        """The memory gets the text it had before the approval back, as a new revision (History keeps both)."""
        try:
            with in_space(self.app, item.space):
                outcome = self.app.memory_engine().revise(after.memory_id, expected_revision_id=after.revision_id,
                                                          title=before.title, content=before.content or "",
                                                          source_ref=before.source_ref or "user-input")
        except Exception:  # noqa: BLE001
            outcome = None
        self.app.data_changed()
        if outcome is None or not outcome.persisted:
            self.app.notify("warning", t("hub.review.undo_failed"), title=t("hub.review.not_undone"))
            return False
        self.app.notify("success", t("hub.review.undo_update_done"), title=t("hub.review.undone"))
        return True

    def undo_create(self, item: HubItem, created) -> bool:
        """A memory the approval made is retracted (the allowed delete); nothing else changes."""
        try:
            with in_space(self.app, item.space):
                outcome = self.app.memory_engine().retract(created.memory_id,
                                                           expected_revision_id=created.revision_id)
        except (MemoryNotFoundError, Exception):  # noqa: BLE001
            outcome = None
        self.app.data_changed()
        if outcome is None or not outcome.persisted:
            self.app.notify("warning", t("hub.review.undo_failed"), title=t("hub.review.not_undone"))
            return False
        self.app.notify("success", t("hub.review.undo_create_done"), title=t("hub.review.undone"))
        return True

    def reject(self, item: HubItem) -> bool:
        review = item.record
        control = self.control
        if control is None or not self.app.require_action("review"):
            return False

        def run() -> None:
            try:
                with in_space(self.app, item.space):
                    self.app.service.reject_review(control, review.review_id)
            except Exception as exc:  # noqa: BLE001 - a stale card: the item was already handled
                self.app.notify("warning", say(exc), title=t("hub.review.reject_failed"))
            self.app.data_changed()

        self.app.pending.defer([item.key], run, message=t("hub.review.rejected", title=preview(review.title, 50)),
                               title=t("hub.review.rejected_title"), on_undo=self.hub.refresh)
        self.hub.refresh()
        return True


__all__ = ["KIND_KEYS", "ReviewCard", "ReviewsView", "different_fact", "word_diff"]
