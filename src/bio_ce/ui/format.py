# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Display formatting and user-facing message helpers (no Tk dependency)."""

from __future__ import annotations

from datetime import datetime, timezone
import re

from bio_ce.core.models import RevisionKind, ValidationError
from bio_ce.ui.i18n import t


TITLE_LIMIT = 512
CONTENT_LIMIT = 100_000
SOURCE_LIMIT = 512
DEFAULT_SOURCE = "user-input"

# English names (hosts and logs); host_name() shows them in the app's language.
HOST_NAMES = {"codex": "Codex (CLI · desktop app)", "claude": "Claude Code", "claude_desktop": "Claude desktop app"}
HOST_COMMANDS = {"codex": "codex", "claude": "claude", "claude_desktop": "Claude desktop app"}
HOSTS = ("codex", "claude", "claude_desktop")

_FIELD_LABELS = {"title": "format.field.title", "content": "format.field.content", "source_ref": "format.field.source",
                 "source_type": "format.field.source"}
_FIELD_KEYS = {"source_type": "source_ref"}
_REVISION_KIND_LABELS = {RevisionKind.ASSERTION: "format.revision.created", RevisionKind.REVISION: "format.revision.edited",
                         RevisionKind.RETRACTION: "format.revision.retracted"}


def host_name(host: str) -> str:
    return t(f"format.host.{host}") if host in HOST_NAMES else host


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


def format_timestamp(value: str | None, *, empty: str | None = None) -> str:
    """Render a stored UTC timestamp in local time, to the minute."""
    parsed = parse_timestamp(value)
    if parsed is None:
        return (t("format.not_set") if empty is None else empty) if not value else value
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
        return t("time.just_now")
    minutes = int(seconds // 60)
    if minutes < 60:
        return t("time.minutes", count=minutes)
    hours = minutes // 60
    if hours < 24:
        return t("time.hours", count=hours)
    days = hours // 24
    if days == 1:
        return t("time.yesterday")
    if days < 7:
        return t("time.days", count=days)
    return parsed.astimezone().strftime("%Y-%m-%d")


def body_without_title(title: str | None, body: str | None) -> str:
    """The body as a card or the drawer shows it under ``title`` (rc3, owner 2026-11-18): "" when it says the same as
    the title, only the rest when it starts with the title, else the whole body. Letters and digits are compared,
    ignoring case, spaces, and punctuation; the title must end where a word ends in the body ("tea" is not the start
    of "teapot"). What is stored is never changed."""
    body = body or ""
    key = [ch for ch in (title or "").casefold() if ch.isalnum()]
    if not key or not body:
        return body
    matched = 0
    for index, ch in enumerate(body):
        if not ch.isalnum():
            continue
        if matched == len(key):  # the title is used up: the body goes on, after a word break only
            return body if body[index - 1].isalnum() else body[index:].strip()
        if ch.casefold() != key[matched]:
            return body
        matched += 1
    return "" if matched == len(key) else body


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
    """English only; screen texts use t() with a plural key instead (v0.4.4 U5)."""
    word = singular if count == 1 else (plural_form or f"{singular}s")
    return f"{count:,} {word}"


def file_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "bytes":
                return t("format.bytes", count=int(value), size=f"{int(value):,}")
            return f"{value:.1f} {unit}"
        value /= 1024
    return t("format.bytes", count=size, size=str(size))


def revision_kind_label(kind: RevisionKind) -> str:
    key = _REVISION_KIND_LABELS.get(kind)
    return t(key) if key else str(kind).title()


def validation_feedback(error: ValidationError) -> tuple[str | None, str]:
    """Map a store validation error to ``(field, friendly message)``.

    ``field`` is ``title``, ``content``, ``source_ref`` or ``None`` when the
    error is not tied to one form field.
    """
    message = str(error)
    match = re.match(r"(\w+) (must not be empty|exceeds (\d+) characters|contains a control character)", message)
    if not match:
        return None, t("format.invalid")
    raw_field = match.group(1)
    field = _FIELD_KEYS.get(raw_field, raw_field)
    if field not in {"title", "content", "source_ref"}:
        return None, t("format.invalid")
    label = t(_FIELD_LABELS[raw_field]) if raw_field in _FIELD_LABELS else raw_field
    problem = match.group(2)
    if problem == "must not be empty":
        if field == "title":
            return field, t("format.title_empty")
        if field == "source_ref":
            return field, t("format.source_empty", default=DEFAULT_SOURCE)
        return field, t("format.empty", label=label)
    if problem.startswith("exceeds"):
        return field, t("format.too_long", label=label, limit=f"{int(match.group(3)):,}")
    return field, t("format.control_char", label=label)


__all__ = [
    "body_without_title",
    "CONTENT_LIMIT",
    "DEFAULT_SOURCE",
    "HOST_COMMANDS",
    "HOST_NAMES",
    "HOSTS",
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
