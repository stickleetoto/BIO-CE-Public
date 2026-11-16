# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Sorting suggestions for the inbox (v0.4.3 C): merge, promote, and update an existing memory.

Suggestions are made by local rules only (no AI model) and nothing changes until the user approves:

| Suggestion        | Rule                                                                         |
|-------------------|------------------------------------------------------------------------------|
| merge             | inbox items of one space with similarity >= 0.6, at most 8 per group           |
| update_existing   | an inbox item 0.45-0.82 similar to a curated memory of the same space        |
| promote           | (a) 7+ days in the inbox and used 2+ times, (b) the same text on 2+ different days, |
|                   | (c) the user chose "review, then promote" for an import                      |

A suggestion whose items changed or disappeared is stale and can't be approved. A rejected group (same items, same
kind: the signature) is never suggested again. Dates move as they are: a claimed date never becomes a confirmed one.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Iterable

from bio_ce.control_store import ControlStore, ControlStoreError
from bio_ce.core.models import MemoryNotFoundError, MemoryRevision, MemoryScope, SourceProvenance
from bio_ce.memory_policy import DUPLICATE_THRESHOLD, detect_secrets, normalize, similarity
from bio_ce.spaces import Space
from bio_ce.inbox import kept_scope
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


MERGE = "merge"
PROMOTE = "promote"
UPDATE_EXISTING = "update_existing"
ACTIONS = (MERGE, PROMOTE, UPDATE_EXISTING)
MERGE_THRESHOLD = 0.6
MERGE_LIMIT = 8
UPDATE_LOW = 0.45
# Character similarity alone counts shared openings and endings ("사용자는 … 선호한다"), so two different facts
# scored 0.6-0.75. A merge or an update also needs this share of the shorter text's distinctive content in common.
TOPIC_THRESHOLD = 0.6
PROMOTE_DAYS = 7
PROMOTE_USES = 2
DESKTOP_HOST = "bio-ce-desktop"
# Metadata that moves with an item when it is merged or promoted (12.1: dates move unchanged).
CARRIED = ("import_source", "batch_id", "imported_at", "claimed_date", "claimed_date_precision", "claimed_date_text",
           "said_at", "said_at_precision", "said_at_confirmed", "section", "sensitive", "host", "guess")
ACTION_LABELS = {MERGE: "Merge", PROMOTE: "Keep as a memory", UPDATE_EXISTING: "Update a memory"}


class CurationError(RuntimeError):
    """A suggestion can't be carried out (stale, or the text needs the user's attention)."""


@dataclass(frozen=True, slots=True)
class Suggestion:
    proposal_id: int
    run_at: str
    action: str
    space_id: str
    items: tuple[tuple[str, str], ...]  # (memory_id, revision_id) of the inbox items, newest first
    target: tuple[str, str] | None  # (memory_id, revision_id) of the curated memory for update_existing
    draft_title: str
    draft_content: str
    status: str
    reason: str
    batch_id: str | None

    @property
    def memory_ids(self) -> tuple[str, ...]:
        return tuple(memory_id for memory_id, _revision in self.items)


def signature(action: str, memory_ids: Iterable[str], target: str | None = None) -> str:
    key = json.dumps([action, sorted(memory_ids), target or ""])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def merge_draft(revisions: list[MemoryRevision]) -> tuple[str, str]:
    """The newest item's sentences, then sentences found only in the others; repeated sentences once."""
    ordered = sorted(revisions, key=lambda revision: revision.recorded_at, reverse=True)
    sentences: list[str] = []
    seen: set[str] = set()
    for revision in ordered:
        for sentence in _sentences(revision.content or ""):
            key = normalize(sentence)
            if key and key not in seen and not any(key in other or other in key for other in seen):
                seen.add(key)
                sentences.append(sentence)
    return ordered[0].title, " ".join(sentences)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?。])\s+|\n+", text) if part.strip()]


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class CurationService:
    """Finds and carries out sorting suggestions. The desktop app is the only writer."""

    def __init__(self, store: SQLiteMemoryStore, control: ControlStore, spaces: Iterable[Space], *,
                 merge_threshold: float = MERGE_THRESHOLD) -> None:
        self.store = store
        self.control = control
        self.spaces = {space.space_id: space for space in spaces}
        self.merge_threshold = merge_threshold

    # Finding ------------------------------------------------------------------------------------------------

    def find(self, *, now: datetime | None = None, batch_id: str | None = None) -> int:
        """Add new suggestions for every space (or only the items of one import); returns how many are new."""
        now = now or datetime.now(timezone.utc)
        self.mark_stale()
        only = None
        if batch_id is not None:
            only = {memory_id for _key, memory_id in self.control.import_batch(batch_id)["memory_ids"]}
        usage = self.control.inbox_usage()
        busy = {memory_id for suggestion in self.suggestions() for memory_id in suggestion.memory_ids}
        added = 0
        for space in self.spaces.values():
            items = [revision for revision in self._inbox(space) if only is None or revision.memory_id in only]
            for action, group, target, reason in self._rules(space, items, usage, now):
                ids = [revision.memory_id for revision in group]
                if busy & set(ids):
                    continue
                if self._add(space, action, group, target, reason, batch_id):
                    busy |= set(ids)
                    added += 1
        return added

    def promote_batch(self, batch_id: str) -> int:
        """Rule (c): the user chose "review, then promote" for an import. One suggestion per item still waiting."""
        ids = {memory_id for _key, memory_id in self.control.import_batch(batch_id)["memory_ids"]}
        busy = {memory_id for suggestion in self.suggestions() for memory_id in suggestion.memory_ids}
        added = 0
        for space in self.spaces.values():
            for revision in self._inbox(space):
                if revision.memory_id in ids and revision.memory_id not in busy:
                    if self._add(space, PROMOTE, [revision], None, "you chose to review this import and keep it",
                                 batch_id):
                        added += 1
        return added

    def _inbox(self, space: Space) -> list[MemoryRevision]:
        items: list[MemoryRevision] = []
        while True:
            page = self.store.list_current(space.inbox, limit=500, offset=len(items))
            items.extend(page)
            if len(page) < 500:
                return items

    def _rules(self, space: Space, items: list[MemoryRevision], usage: dict, now: datetime):
        by_id = {item.memory_id: item for item in items}
        text = {item.memory_id: f"{item.title}\n{item.content or ''}" for item in items}
        parent = {item.memory_id: item.memory_id for item in items}
        closeness: dict[tuple[str, str], float] = {}
        common = _common_words(text.values())

        def find(node: str) -> str:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for item in items:
            for hit in self.store.search(space.inbox, _keywords(text[item.memory_id]), limit=6):
                other = hit.memory_id
                if other == item.memory_id or other not in by_id:
                    continue
                pair = tuple(sorted((item.memory_id, other)))
                if pair in closeness:
                    continue
                closeness[pair] = similarity(text[item.memory_id], text[other])
                if closeness[pair] >= self.merge_threshold and topic_overlap(
                        text[item.memory_id], text[other], common) >= TOPIC_THRESHOLD:
                    a, b = find(pair[0]), find(pair[1])
                    if a != b:
                        parent[b] = a
        groups: dict[str, list[MemoryRevision]] = defaultdict(list)
        for item in items:
            groups[find(item.memory_id)].append(item)
        grouped: set[str] = set()
        for members in groups.values():
            if len(members) < 2:
                continue
            members = sorted(members, key=lambda revision: revision.recorded_at, reverse=True)[:MERGE_LIMIT]
            grouped |= {member.memory_id for member in members}
            days = {member.recorded_at[:10] for member in members}
            same = all(closeness.get(tuple(sorted((members[0].memory_id, m.memory_id))), 1.0) >= DUPLICATE_THRESHOLD
                       for m in members[1:])
            if same and len(days) >= 2:
                yield PROMOTE, members, None, "the same thing was saved on different days"
            else:
                yield MERGE, members, None, "these items say nearly the same"
        for item in items:
            if item.memory_id in grouped:
                continue
            target, score = self._closest_curated(space, text[item.memory_id])
            if target is not None and UPDATE_LOW <= score < DUPLICATE_THRESHOLD and topic_overlap(
                    text[item.memory_id], f"{target.title}\n{target.content or ''}", common) >= TOPIC_THRESHOLD:
                yield UPDATE_EXISTING, [item], target, "it may add to or change a memory you have"
                continue
            row = usage.get(item.memory_id, {})
            first = _parse(row.get("first_seen")) or _parse(item.recorded_at)
            if first is not None and now - first >= timedelta(days=PROMOTE_DAYS) and int(row.get("hit_count") or 0) \
                    >= PROMOTE_USES:
                yield PROMOTE, [item], None, "your AI hosts used it again and again"

    def _closest_curated(self, space: Space, text: str) -> tuple[MemoryRevision | None, float]:
        best, best_score = None, 0.0
        for hit in self.store.search(space.curated, _keywords(text), limit=5):
            try:
                revision = self.store.read(space.curated, hit.memory_id)
            except MemoryNotFoundError:
                continue
            score = similarity(text, f"{revision.title}\n{revision.content or ''}")
            if score > best_score:
                best, best_score = revision, score
        return best, best_score

    def _add(self, space: Space, action: str, group: list[MemoryRevision], target: MemoryRevision | None,
             reason: str, batch_id: str | None) -> bool:
        if action == MERGE:
            title, content = merge_draft(group)
        elif action == UPDATE_EXISTING and target is not None:
            title = target.title
            content = " ".join(dict.fromkeys(_sentences(target.content or "") + _sentences(group[0].content or "")))
        else:
            title, content = group[0].title, group[0].content or ""
        return self.control.add_curation_proposal(
            action=action, space_id=space.space_id,
            items=[(revision.memory_id, revision.revision_id) for revision in group],
            target=(target.memory_id, target.revision_id) if target is not None else None,
            draft_title=title, draft_content=content, reason=reason, batch_id=batch_id,
            signature=signature(action, [revision.memory_id for revision in group],
                                target.memory_id if target is not None else None))

    # Reading ------------------------------------------------------------------------------------------------

    def suggestions(self, *, batch_id: str | None = None) -> tuple[Suggestion, ...]:
        rows = self.control.curation_proposals()
        found = tuple(_suggestion(row) for row in rows)
        if batch_id is None:
            return found
        ids = {memory_id for _key, memory_id in self.control.import_batch(batch_id)["memory_ids"]}
        return tuple(item for item in found if item.batch_id == batch_id or set(item.memory_ids) & ids)

    def originals(self, suggestion: Suggestion) -> list[MemoryRevision]:
        space = self.spaces.get(suggestion.space_id)
        result = []
        for memory_id, _revision in suggestion.items:
            try:
                result.append(self.store.read(space.inbox, memory_id))
            except (MemoryNotFoundError, AttributeError):
                continue
        return result

    def mark_stale(self) -> int:
        """Suggestions whose items or target changed or disappeared can't be approved any more."""
        count = 0
        for suggestion in self.suggestions():
            if not self._current(suggestion):
                self.control.set_curation_proposal_status(suggestion.proposal_id, "stale")
                count += 1
        return count

    def _current(self, suggestion: Suggestion) -> bool:
        space = self.spaces.get(suggestion.space_id)
        if space is None:
            return False
        try:
            for memory_id, revision_id in suggestion.items:
                if self.store.read(space.inbox, memory_id).revision_id != revision_id:
                    return False
            if suggestion.target is not None:
                memory_id, revision_id = suggestion.target
                if self.store.read(space.curated, memory_id).revision_id != revision_id:
                    return False
        except MemoryNotFoundError:
            return False
        return True

    # Deciding -----------------------------------------------------------------------------------------------

    def approve(self, proposal_id: int, *, title: str | None = None, content: str | None = None) -> MemoryRevision:
        suggestion = self._pending(proposal_id)
        if not self._current(suggestion):
            self.control.set_curation_proposal_status(proposal_id, "stale")
            raise CurationError("These items changed since BIO CE suggested this. Nothing was changed.")
        space = self.spaces[suggestion.space_id]
        title = " ".join((title if title is not None else suggestion.draft_title).split())
        content = (content if content is not None else suggestion.draft_content).strip()
        if not title or not content:
            raise CurationError("Title and text can't be empty.")
        if detect_secrets(title, content):
            raise CurationError("This text contains a password, token, or key, so BIO CE won't store it.")
        originals = self.originals(suggestion)
        newest = originals[0]
        carried = {key: newest.source.metadata[key] for key in CARRIED if key in newest.source.metadata}
        ids = [revision.memory_id for revision in originals]
        # The result names its suggestion, and the items it used are kept aside, never deleted: see undo().
        used = ids[1:] if suggestion.action == MERGE else ids
        before = newest if suggestion.action == MERGE else (
            self.store.read(space.curated, suggestion.target[0]) if suggestion.action == UPDATE_EXISTING
            and suggestion.target is not None else None)
        earlier_kept = list(before.source.metadata.get("kept") or ()) if before is not None else []
        mark = {"suggestion": int(proposal_id), "kept": sorted(set(earlier_kept) | set(used))}
        if suggestion.action == MERGE:
            source = SourceProvenance(newest.source.source_type, newest.source.source_ref,
                                      {**newest.source.metadata, "merged_from": ids[1:], "stage": "inbox", **mark})
            revision = self.store.revise(space.inbox, newest.memory_id, expected_revision_id=newest.revision_id,
                                         title=title, content=content, source=source)
            self.store.move(space.inbox, kept_scope(space.inbox), ids[1:])
        elif suggestion.action == UPDATE_EXISTING:
            memory_id, revision_id = suggestion.target  # type: ignore[misc]
            source = SourceProvenance("user-entered", "bio-ce-curation", {**carried, "from_inbox": ids, **mark})
            revision = self.store.revise(space.curated, memory_id, expected_revision_id=revision_id, title=title,
                                         content=content, source=source)
            self.store.move(space.inbox, kept_scope(space.inbox), ids)
        else:
            for hit in self.store.search(space.curated, _keywords(f"{title}\n{content}"), limit=5):
                existing = self.store.read(space.curated, hit.memory_id)
                if similarity(f"{title}\n{content}", f"{existing.title}\n{existing.content or ''}") >= \
                        DUPLICATE_THRESHOLD:
                    self.control.set_curation_proposal_status(proposal_id, "stale")
                    raise CurationError(f"Your memories already have this (“{existing.title}”). Discard the inbox "
                                        "item instead.")
            source = SourceProvenance("user-entered", "bio-ce-curation", {**carried, "from_inbox": ids, **mark})
            revision = self.store.add(space.curated, title=title, content=content, source=source)
            self.store.move(space.inbox, kept_scope(space.inbox), ids)
        self.control.set_curation_proposal_status(proposal_id, "approved")
        self.control.record(host=DESKTOP_HOST, connection_id=None, action=f"suggestion-{suggestion.action}",
                            outcome="approved", memory_id=revision.memory_id, revision_id=revision.revision_id,
                            detail={"items": len(ids), "space": suggestion.space_id})
        return revision

    # Undoing -----------------------------------------------------------------------------------------------

    def result_of(self, scope: MemoryScope, memory_id: str) -> int | None:
        """The approved suggestion whose result ``memory_id`` still is (not edited since), or None."""
        try:
            current = self.store.read(scope, memory_id)
        except MemoryNotFoundError:
            return None
        proposal_id = current.source.metadata.get("suggestion")
        if not isinstance(proposal_id, int):
            return None
        try:
            if self.control.curation_proposal(proposal_id)["status"] != "approved":
                return None
        except ControlStoreError:
            return None
        return proposal_id

    def undo(self, proposal_id: int) -> MemoryRevision:
        """Put back what an approved suggestion changed: the result gets its earlier text again (a new revision,
        so the undone one stays in History; a memory the suggestion created is retracted) and the items it used
        return to the inbox unchanged. Refused, with nothing changed, if the result was edited since."""
        try:
            suggestion = _suggestion(self.control.curation_proposal(proposal_id))
        except ControlStoreError as exc:
            raise CurationError(str(exc)) from exc
        if suggestion.status != "approved":
            raise CurationError("This suggestion isn't an approved one, so there is nothing to undo.")
        space = self.spaces.get(suggestion.space_id)
        if space is None:
            raise CurationError("The space of this suggestion is gone. Nothing was changed.")
        aside = kept_scope(space.inbox)
        result, earlier, scope = self._result(suggestion, space)
        if result is None or result.source.metadata.get("suggestion") != suggestion.proposal_id:
            raise CurationError("This was changed after the suggestion was approved, so BIO CE won't undo it. "
                                "Nothing was changed. Use History to see what it said before.")
        back = [memory_id for memory_id, _revision in suggestion.items
                if memory_id != result.memory_id or suggestion.action != MERGE]
        for memory_id in back:
            try:
                self.store.read(aside, memory_id)
            except MemoryNotFoundError:
                raise CurationError("BIO CE no longer has the items this suggestion used (it was approved by an "
                                    "earlier version, which deleted them). Nothing was changed.") from None
        undo_source = SourceProvenance("user-entered", "bio-ce-curation-undo",
                                       {"undid_suggestion": suggestion.proposal_id})
        if earlier is None:  # Keep as a memory: the new memory is retracted, never deleted
            revision = self.store.retract(scope, result.memory_id, expected_revision_id=result.revision_id,
                                          source=undo_source)
        else:
            # "kept" is set to what it was before (possibly nothing): the items given back are no longer kept for it.
            kept_before = list(earlier.source.metadata.get("kept") or ())
            source = SourceProvenance(earlier.source.source_type, earlier.source.source_ref,
                                      {**earlier.source.metadata, "kept": kept_before} if suggestion.action == MERGE
                                      else {**earlier.source.metadata, "undid_suggestion": suggestion.proposal_id,
                                            "kept": kept_before})
            revision = self.store.revise(scope, result.memory_id, expected_revision_id=result.revision_id,
                                         title=earlier.title, content=earlier.content or "", source=source)
        self.store.move(aside, space.inbox, back)
        self.control.set_curation_proposal_status(suggestion.proposal_id, "rejected")  # never suggested again
        self.control.record(host=DESKTOP_HOST, connection_id=None, action=f"suggestion-{suggestion.action}",
                            outcome="undone", memory_id=revision.memory_id, revision_id=revision.revision_id,
                            detail={"items": len(suggestion.items), "space": suggestion.space_id})
        return revision

    def _result(self, suggestion: Suggestion, space: Space):
        """(current result, its revision before the suggestion or None if the suggestion created it, scope)."""
        def revision_in(scope: MemoryScope, memory_id: str, revision_id: str) -> MemoryRevision | None:
            return next((r for r in self.store.history(scope, memory_id) if r.revision_id == revision_id), None)

        if suggestion.action == MERGE:
            for memory_id, revision_id in suggestion.items:
                try:
                    current = self.store.read(space.inbox, memory_id)
                except MemoryNotFoundError:
                    continue
                if current.source.metadata.get("suggestion") == suggestion.proposal_id:
                    return current, revision_in(space.inbox, memory_id, revision_id), space.inbox
            return None, None, space.inbox
        if suggestion.action == UPDATE_EXISTING and suggestion.target is not None:
            memory_id, revision_id = suggestion.target
            try:
                current = self.store.read(space.curated, memory_id)
            except MemoryNotFoundError:
                return None, None, space.curated
            return current, revision_in(space.curated, memory_id, revision_id), space.curated
        offset = 0
        while True:  # Keep as a memory: find the memory it created
            page = self.store.list_current(space.curated, limit=500, offset=offset)
            for current in page:
                if current.source.metadata.get("suggestion") == suggestion.proposal_id:
                    return current, None, space.curated
            if len(page) < 500:
                return None, None, space.curated
            offset += len(page)

    def reject(self, proposal_id: int) -> None:
        self._pending(proposal_id)
        self.control.set_curation_proposal_status(proposal_id, "rejected")

    def approve_many(self, proposal_ids: Iterable[int]) -> dict[str, Any]:
        """Approve each with its draft; stale or refused ones are counted and skipped. ``ids``: the approved ones."""
        approved: list[int] = []
        skipped = 0
        for proposal_id in proposal_ids:
            try:
                self.approve(proposal_id)
                approved.append(int(proposal_id))
            except (CurationError, ControlStoreError, MemoryNotFoundError):
                skipped += 1
        return {"approved": len(approved), "skipped": skipped, "ids": approved}

    def reject_many(self, proposal_ids: Iterable[int]) -> int:
        count = 0
        for proposal_id in proposal_ids:
            try:
                self.reject(proposal_id)
                count += 1
            except ControlStoreError:
                continue
        return count

    def _pending(self, proposal_id: int) -> Suggestion:
        row = self.control.curation_proposal(proposal_id)
        suggestion = _suggestion(row)
        if suggestion.status != "pending":
            raise ControlStoreError("That suggestion was already handled.")
        return suggestion


def _suggestion(row: dict[str, Any]) -> Suggestion:
    items = tuple((item[0], item[1]) for item in row["items"])
    target = tuple(row["target"]) if row.get("target") else None
    return Suggestion(int(row["proposal_id"]), row["run_at"], row["action"], row["space_id"], items,
                      target,  # type: ignore[arg-type]
                      row["draft_title"], row["draft_content"], row["status"], row.get("reason") or "",
                      row.get("batch_id"))


_WORD = re.compile(r"\w{2,}")
_STOP = {"the", "and", "for", "with", "that", "this", "user", "users", "use", "about", "from", "has", "have",
         "are", "was", "were", "사용자", "사용자는", "사용자의", "있다", "한다"}


def _marks(text: str, common: frozenset[str]) -> set[str]:
    """Two-letter pieces of the words that carry the meaning (not stop words or words most items share).
    Pieces, not whole words, so "달리기를" and "달리기는" still match."""
    marks: set[str] = set()
    for word in _WORD.findall(normalize(text)):
        if word not in _STOP and word not in common:
            marks |= {word[index:index + 2] for index in range(len(word) - 1)}
    return marks


def topic_overlap(left: str, right: str, common: frozenset[str] = frozenset()) -> float:
    """Share of the shorter text's distinctive pieces that the other text has too (0 to 1)."""
    a, b = _marks(left, common), _marks(right, common)
    if common and (not a or not b):  # every word is shared (an inbox of repeats of one fact): compare all words
        a, b = _marks(left, frozenset()), _marks(right, frozenset())
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _common_words(texts: Iterable[str]) -> frozenset[str]:
    """Words in at least 80% of the inbox items (with 5 or more), such as a tag every imported line starts with.
    Not lower: a few repeats of one fact must keep their own words (3 of 4 items once lost "deploys" this way)."""
    texts = list(texts)
    if len(texts) < 5:
        return frozenset()
    counts: dict[str, int] = defaultdict(int)
    for text in texts:
        for word in set(_WORD.findall(normalize(text))):
            counts[word] += 1
    return frozenset(word for word, count in counts.items() if count * 5 >= len(texts) * 4)


def _keywords(text: str, limit: int = 8) -> str:
    words = {word for word in _WORD.findall(normalize(text)) if word not in _STOP}
    return " ".join(sorted(words, key=lambda word: (-len(word), word))[:limit])


__all__ = ["ACTIONS", "ACTION_LABELS", "CurationError", "CurationService", "MERGE", "PROMOTE", "Suggestion",
           "UPDATE_EXISTING", "kept_scope", "merge_draft", "signature", "topic_overlap"]
