# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Display formatting and user-facing message helpers (no Tk dependency)."""

from __future__ import annotations

from datetime import datetime, timezone
import re

from bio_ce.core.models import RevisionKind, ValidationError


TITLE_LIMIT = 512
CONTENT_LIMIT = 100_000
SOURCE_LIMIT = 512
DEFAULT_SOURCE = "user-input"

HOST_NAMES = {"codex": "Codex CLI", "claude": "Claude Code"}
HOST_COMMANDS = {"codex": "codex", "claude": "claude"}

_FIELD_LABELS = {
    "title": "Title",
    "content": "Memory text",
    "source_ref": "Source",
    "source_type": "Source",
}
_FIELD_KEYS = {"source_type": "source_ref"}
_REVISION_KIND_LABELS = {
    RevisionKind.ASSERTION: "Created",
    RevisionKind.REVISION: "Edited",
    RevisionKind.RETRACTION: "Retracted",
}


def host_name(host: str) -> str:
    return HOST_NAMES.get(host, host)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_timestamp(value: str | None, *, empty: str = "Not set") -> str:
    """Render a stored UTC timestamp in local time, to the minute."""
    parsed = parse_timestamp(value)
    if parsed is None:
        return empty if not value else value
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def relative_time(value: str | None, *, now: datetime | None = None) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return ""
    current = now or datetime.now(timezone.utc)
    seconds = (current - parsed).total_seconds()
    if seconds < 0:
        return format_timestamp(value)
    if seconds < 60:
        return "Just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hr ago"
    days = hours // 24
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    return parsed.astimezone().strftime("%Y-%m-%d")


def preview(text: str | None, limit: int = 120) -> str:
    """Collapse whitespace and shorten text for one-line previews."""
    flattened = re.sub(r"\s+", " ", text or "").strip()
    if len(flattened) <= limit:
        return flattened
    return flattened[: max(0, limit - 1)].rstrip() + "…"


def middle_ellipsis(text: str, limit: int) -> str:
    """Shorten long identifiers in the middle so both ends stay recognizable."""
    if len(text) <= limit:
        return text
    head = (limit - 1) // 2
    tail = limit - 1 - head
    return f"{text[:head]}…{text[-tail:]}"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    word = singular if count == 1 else (plural_form or f"{singular}s")
    return f"{count:,} {word}"


def file_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(value):,} bytes"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"


def revision_kind_label(kind: RevisionKind) -> str:
    return _REVISION_KIND_LABELS.get(kind, str(kind).title())


def validation_feedback(error: ValidationError) -> tuple[str | None, str]:
    """Map a store validation error to ``(field, friendly message)``.

    ``field`` is ``title``, ``content``, ``source_ref`` or ``None`` when the
    error is not tied to one form field.
    """
    message = str(error)
    match = re.match(r"(\w+) (must not be empty|exceeds (\d+) characters|contains a control character)", message)
    if not match:
        return None, "BIO CE could not save this memory because a value is not valid. Check the fields and try again."
    raw_field = match.group(1)
    field = _FIELD_KEYS.get(raw_field, raw_field)
    if field not in {"title", "content", "source_ref"}:
        return None, "BIO CE could not save this memory because a value is not valid. Check the fields and try again."
    label = _FIELD_LABELS.get(raw_field, raw_field)
    problem = match.group(2)
    if problem == "must not be empty":
        if field == "title":
            return field, "Add a short title so you can find this memory later."
        if field == "source_ref":
            return field, f"Add a source, or use “{DEFAULT_SOURCE}”."
        return field, f"{label} can’t be empty."
    if problem.startswith("exceeds"):
        return field, f"{label} is too long. The limit is {int(match.group(3)):,} characters."
    return field, f"{label} contains an unsupported control character. Remove it and try again."


__all__ = [
    "CONTENT_LIMIT",
    "DEFAULT_SOURCE",
    "HOST_COMMANDS",
    "HOST_NAMES",
    "SOURCE_LIMIT",
    "TITLE_LIMIT",
    "file_size",
    "format_timestamp",
    "host_name",
    "middle_ellipsis",
    "parse_timestamp",
    "plural",
    "preview",
    "relative_time",
    "revision_kind_label",
    "validation_feedback",
]
