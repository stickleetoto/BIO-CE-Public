# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Export memories as text in the "[date] - content" format (v0.4.3 D).

The file can be pasted into another AI's memory import or imported back into BIO CE. Rules:

- Spaces are chosen by the user; Personal only when it is on and the user ticks it (the app warns first).
- Curated memories by default; the inbox only when asked. Retracted memories, the review queue, discarded items,
  and older revisions are never exported.
- Dates (12.1): a memory made in BIO CE uses the day it was first saved. An imported memory uses only the date the
  user confirmed (``said_at``; a month stays ``YYYY-MM``); without one it is ``[unknown]``. With "add the source's
  date", an unconfirmed date is added as `` (claimed YYYY-MM-DD)``, which BIO CE reads back as the claimed date.
- "Title: content" when the title isn't the start of the content; line breaks become spaces.
- Never overwrites a file. The file is not encrypted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Iterable

from bio_ce.auto_memory import AUTO_SOURCE_TYPE
from bio_ce.core.models import MemoryRevision
from bio_ce.memory_policy import normalize
from bio_ce.spaces import Space
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


SOURCE_KINDS = ("user", "ai_host", "chatgpt", "claude", "other")
SOURCE_LABELS = {"user": "Entered by you", "ai_host": "Saved by an AI host", "chatgpt": "Imported from ChatGPT",
                 "claude": "Imported from Claude", "other": "Imported from another AI"}
UNENCRYPTED_NOTICE = "This file is not encrypted. Check what is in it before you share it."


class ExportRefused(ValueError):
    """The export can't be written as asked (an existing file, Personal not allowed, nothing selected)."""


@dataclass(frozen=True, slots=True)
class ExportOptions:
    space_ids: tuple[str, ...]
    include_inbox: bool = False
    sources: frozenset[str] = field(default_factory=lambda: frozenset(SOURCE_KINDS))
    date_from: str | None = None  # YYYY-MM-DD, inclusive
    date_to: str | None = None
    include_claimed: bool = False


@dataclass(frozen=True, slots=True)
class ExportResult:
    text: str
    count: int
    by_space: dict[str, int]


def source_kind(revision: MemoryRevision) -> str:
    metadata = revision.source.metadata
    imported = metadata.get("import_source")
    if imported:
        return imported if imported in ("chatgpt", "claude") else "other"
    if revision.source.source_type == AUTO_SOURCE_TYPE or metadata.get("host"):
        return "ai_host"
    return "user"


def export_date(revision: MemoryRevision, created_at: str | None) -> str | None:
    """The date written in brackets: confirmed said_at for imported memories, the first save day otherwise."""
    metadata = revision.source.metadata
    if metadata.get("import_source") or metadata.get("claimed_date") or metadata.get("said_at"):
        said = metadata.get("said_at")
        return str(said) if said else None
    stamp = created_at or revision.recorded_at
    return stamp[:10] if stamp else None


def export_line(revision: MemoryRevision, created_at: str | None, *, include_claimed: bool) -> str:
    content = " ".join((revision.content or "").split())
    title = " ".join(revision.title.split())
    if title and not normalize(content).startswith(normalize(title)):
        text = f"{title}: {content}" if content else title
    else:
        text = content or title
    day = export_date(revision, created_at)
    line = f"[{day or 'unknown'}] - {text}"
    claimed = revision.source.metadata.get("claimed_date")
    if include_claimed and claimed and not revision.source.metadata.get("said_at"):
        line += f" (claimed {claimed})"
    return line


def build_export(store: SQLiteMemoryStore, spaces: Iterable[Space], options: ExportOptions, *,
                 personal_allowed: bool, now: datetime | None = None) -> ExportResult:
    by_id = {space.space_id: space for space in spaces}
    if not options.space_ids:
        raise ExportRefused("Choose at least one space.")
    unknown = [space_id for space_id in options.space_ids if space_id not in by_id]
    if unknown:
        raise ExportRefused("A chosen space no longer exists.")
    if any(by_id[space_id].is_personal for space_id in options.space_ids) and not personal_allowed:
        raise ExportRefused("Personal is included only when it is on and you tick it.")
    if not options.sources:
        raise ExportRefused("Choose at least one source.")
    lines: list[str] = []
    by_space: dict[str, int] = {}
    for space_id in options.space_ids:
        space = by_id[space_id]
        scopes = [space.curated] + ([space.inbox] if options.include_inbox else [])
        count = 0
        for scope in scopes:
            created = store.created_dates(scope)
            for revision in _all(store, scope):
                if source_kind(revision) not in options.sources:
                    continue
                day = export_date(revision, created.get(revision.memory_id))
                if (options.date_from or options.date_to) and not _in_range(day, options):
                    continue
                lines.append(export_line(revision, created.get(revision.memory_id),
                                         include_claimed=options.include_claimed))
                count += 1
        by_space[space.display_name] = count
    now = now or datetime.now(timezone.utc)
    names = ", ".join(by_id[space_id].display_name for space_id in options.space_ids)
    conditions = [f"spaces: {names}", "stage: curated and inbox" if options.include_inbox else "stage: curated",
                  "sources: " + ", ".join(kind for kind in SOURCE_KINDS if kind in options.sources)]
    if options.date_from or options.date_to:
        conditions.append(f"dates: {options.date_from or '…'} to {options.date_to or '…'}")
    header = f"<!-- BIO CE export, {now.date().isoformat()}, " + "; ".join(conditions) + " -->"
    text = header + "\n\n```\n" + "\n".join(lines) + ("\n" if lines else "") + "```\n"
    return ExportResult(text, len(lines), by_space)


def write_export(path: str | os.PathLike[str], text: str) -> Path:
    """Write a new file; an existing file is never replaced."""
    target = Path(path)
    try:
        with open(target, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        raise ExportRefused("A file with this name already exists. Choose a new name; BIO CE never overwrites "
                            "files.") from None
    return target


def _all(store: SQLiteMemoryStore, scope) -> list[MemoryRevision]:
    items: list[MemoryRevision] = []
    while True:
        page = store.list_current(scope, limit=500, offset=len(items))
        items.extend(page)
        if len(page) < 500:
            return items


def _in_range(day: str | None, options: ExportOptions) -> bool:
    if not day:
        return False  # a date range leaves out memories whose date is unknown
    start = options.date_from or "0000-00-00"
    end = options.date_to or "9999-99-99"
    if len(day) == 7:  # a month is in range when any day of it is
        return start[:7] <= day <= end[:7]
    return start <= day <= end


__all__ = ["ExportOptions", "ExportRefused", "ExportResult", "SOURCE_KINDS", "SOURCE_LABELS", "UNENCRYPTED_NOTICE",
           "build_export", "export_date", "export_line", "source_kind", "write_export"]
