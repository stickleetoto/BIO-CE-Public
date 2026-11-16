# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""What the unified memory screen lists (v0.4.4 §2.2): memories, inbox items, suggestions, and reviews, from one
space or all of them, as one kind of item. Reads only; the actions are in ``bio_ce.ui.hub.actions``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MEMORIES = "memories"
INBOX = "inbox"
SUGGESTIONS = "suggestions"
REVIEWS = "reviews"
STATES = (MEMORIES, INBOX, SUGGESTIONS, REVIEWS)
ALL_SPACES = "all"
PER_SPACE_LIMIT = 500


@dataclass(frozen=True)
class HubItem:
    state: str
    key: str  # unique on the screen: "<state>:<id>"
    item_id: str  # memory id, inbox item id, suggestion id, or review id (as text)
    space: Any  # a Space, or None when it can't be told (a review of a removed space)
    title: str
    text: str
    when: str  # timestamp (ISO) for sorting and "3 days ago"
    record: Any = field(compare=False, default=None)


def _space_of_scope(spaces, project: str | None, namespace: str | None):
    for space in spaces:
        if space.curated.project == project and namespace in (space.curated.namespace, space.inbox.namespace):
            return space
    return None


def _matches(item: HubItem, words: list[str]) -> bool:
    if not words:
        return True
    haystack = f"{item.title}\n{item.text}".casefold()
    return all(word in haystack for word in words)


class HubData:
    """Collects the items for one state and a space filter. ``app`` is the desktop app."""

    def __init__(self, app) -> None:
        self.app = app

    def spaces(self, space_filter: str) -> list:
        spaces = list(self.app.spaces())
        return spaces if space_filter == ALL_SPACES else [s for s in spaces if s.space_id == space_filter]

    def counts(self, space_filter: str) -> dict[str, int]:
        return {state: len(self.items(state, space_filter)) for state in STATES}

    def items(self, state: str, space_filter: str, query: str = "") -> list[HubItem]:
        words = [word for word in query.casefold().split() if word]
        hidden = self.app.pending.hidden()
        found = {MEMORIES: self._memories, INBOX: self._inbox, SUGGESTIONS: self._suggestions,
                 REVIEWS: self._reviews}[state](space_filter)
        found = [item for item in found if item.item_id not in hidden and _matches(item, words)]
        return sorted(found, key=lambda item: item.when or "", reverse=True)

    # Each state --------------------------------------------------------------------------------------------

    def _each_space(self, space_filter: str, read):
        """Run ``read(space)`` with the service switched to each space; the shown space is restored after."""
        service = self.app.service
        before = service.scope
        try:
            results = []
            for space in self.spaces(space_filter):
                service.use_space(space.curated)
                results.extend(read(space))
            return results
        finally:
            service.use_space(before)

    def _memories(self, space_filter: str) -> list[HubItem]:
        try:
            engine = self.app.memory_engine()
        except Exception:  # noqa: BLE001 - the screen shows the engine notice instead
            return []

        def read(space):
            return [HubItem(MEMORIES, f"{MEMORIES}:{view.memory_id}", view.memory_id, space, view.title,
                            view.content or "", view.recorded_at, view)
                    for view in engine.list(limit=PER_SPACE_LIMIT)]

        return self._each_space(space_filter, read)

    def _inbox(self, space_filter: str) -> list[HubItem]:
        def read(space):
            return [HubItem(INBOX, f"{INBOX}:{item.memory_id}", item.memory_id, space, item.title,
                            item.content or "", item.recorded_at, item)
                    for item in self.app.service.inbox()]

        return self._each_space(space_filter, read)

    def _suggestions(self, space_filter: str) -> list[HubItem]:
        control = getattr(self.app.connection_manager, "control", None)
        if control is None:
            return []
        spaces = {space.space_id: space for space in self.spaces(space_filter)}
        try:
            suggestions = self.app.service.curation(control, self.app.spaces()).suggestions()
        except Exception:  # noqa: BLE001
            return []
        return [HubItem(SUGGESTIONS, f"{SUGGESTIONS}:{s.proposal_id}", str(s.proposal_id), spaces[s.space_id],
                        s.draft_title, s.draft_content, s.run_at, s)
                for s in suggestions if s.space_id in spaces]

    def _reviews(self, space_filter: str) -> list[HubItem]:
        control = getattr(self.app.connection_manager, "control", None)
        if control is None:
            return []
        all_spaces = list(self.app.spaces())
        wanted = {space.space_id for space in self.spaces(space_filter)}
        items = []
        for review in control.reviews(limit=200):
            meta = dict(review.metadata or {})
            space = _space_of_scope(all_spaces, meta.get("project"), meta.get("namespace"))
            if space is None:
                space = next((s for s in all_spaces if s.is_general), None)  # older reviews: General
            if space_filter != ALL_SPACES and (space is None or space.space_id not in wanted):
                continue
            items.append(HubItem(REVIEWS, f"{REVIEWS}:{review.review_id}", str(review.review_id), space,
                                 review.title, review.content or "", review.created_at, review))
        return items


__all__ = ["ALL_SPACES", "HubData", "HubItem", "INBOX", "MEMORIES", "REVIEWS", "STATES", "SUGGESTIONS"]
