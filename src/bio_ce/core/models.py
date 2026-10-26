# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

"""Validated, storage-independent types for the BIO CE preview."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
import re
from typing import Any, Mapping


class MemoryErrorBase(Exception):
    """Base class for expected memory API errors."""


class ValidationError(MemoryErrorBase, ValueError):
    """An input does not satisfy the CE's bounded v0.1 contract."""


class MemoryNotFoundError(MemoryErrorBase, LookupError):
    """A memory is absent from the requested exact scope or is retracted."""


class RevisionConflictError(MemoryErrorBase):
    """A caller tried to revise a stale revision or reuse a memory ID."""


class SnapshotChangedError(MemoryErrorBase):
    """A current revision changed before a read passed final freshness validation."""


class RevisionKind(StrEnum):
    ASSERTION = "assertion"
    REVISION = "revision"
    RETRACTION = "retraction"


@dataclass(frozen=True, slots=True)
class MemoryScope:
    project: str
    namespace: str

    def __post_init__(self) -> None:
        _validate_identifier(self.project, "project", 128)
        _validate_identifier(self.namespace, "namespace", 128)


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Descriptive source metadata; it conveys no authority or trust."""

    source_type: str
    source_ref: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_text(self.source_type, "source_type", 64)
        _validate_text(self.source_ref, "source_ref", 512)
        try:
            encoded = json.dumps(
                dict(self.metadata), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError("source metadata must be finite JSON data") from exc
        if len(encoded) > 4096:
            raise ValidationError("source metadata exceeds 4096 characters")

    def to_json(self) -> str:
        return json.dumps(
            dict(self.metadata), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )


@dataclass(frozen=True, slots=True)
class MemoryRevision:
    memory_id: str
    revision_id: str
    revision_number: int
    kind: RevisionKind
    scope: MemoryScope
    title: str
    content: str | None
    source: SourceProvenance
    recorded_at: str
    valid_from: str | None = None
    valid_until: str | None = None
    previous_revision_id: str | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    memory_id: str
    revision_id: str
    rank: int
    score: float
    title: str
    preview: str
    source: SourceProvenance
    recorded_at: str
    valid_from: str | None
    valid_until: str | None


_PROJECT_ID = re.compile(r"mem_[A-Za-z0-9_-]{8,96}\Z")
_REVISION_ID = re.compile(r"rev_[0-9a-f]{64}\Z")


def validate_memory_id(value: str) -> str:
    if not isinstance(value, str) or _PROJECT_ID.fullmatch(value) is None:
        raise ValidationError("memory_id must use mem_ followed by 8-96 safe characters")
    return value


def validate_revision_id(value: str) -> str:
    if not isinstance(value, str) or _REVISION_ID.fullmatch(value) is None:
        raise ValidationError("revision_id must use rev_ followed by a SHA-256 digest")
    return value


def normalize_timestamp(value: str | datetime | None, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError(f"{field_name} must be an ISO-8601 timestamp") from exc
    else:
        raise ValidationError(f"{field_name} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{field_name} must include a UTC offset")
    normalized = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return normalized.replace("+00:00", "Z")


def utc_now() -> str:
    value = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    return value.replace("+00:00", "Z")


def _validate_identifier(value: str, field_name: str, maximum: int) -> None:
    _validate_text(value, field_name, maximum)
    if value != value.strip():
        raise ValidationError(f"{field_name} must not have leading or trailing whitespace")


def validate_memory_text(value: str, field_name: str, maximum: int, *, allow_empty: bool = False) -> str:
    _validate_text(value, field_name, maximum, allow_empty=allow_empty, multiline=True)
    return value


def _validate_text(
    value: str,
    field_name: str,
    maximum: int,
    *,
    allow_empty: bool = False,
    multiline: bool = False,
) -> None:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    if not allow_empty and not value.strip():
        raise ValidationError(f"{field_name} must not be empty")
    if len(value) > maximum:
        raise ValidationError(f"{field_name} exceeds {maximum} characters")
    for char in value:
        if ord(char) < 32 and not (multiline and char in "\n\t\r"):
            raise ValidationError(f"{field_name} contains a control character")


__all__ = [
    "MemoryErrorBase", "MemoryNotFoundError", "MemoryRevision", "MemoryScope",
    "RevisionConflictError", "RevisionKind", "SearchHit", "SnapshotChangedError", "SourceProvenance",
    "ValidationError", "normalize_timestamp", "utc_now", "validate_memory_id",
    "validate_memory_text", "validate_revision_id",
]
