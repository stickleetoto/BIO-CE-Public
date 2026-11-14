# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Spaces: General, Personal, and Project memory areas, mapped onto the existing project and namespace columns.

| Space            | project            | curated namespace | inbox namespace   |
|------------------|--------------------|-------------------|-------------------|
| General          | ``bio-ce-personal``| ``default``       | ``default.inbox`` |
| Personal         | ``bio-ce-personal``| ``personal``      | ``personal.inbox``|
| Project <name>   | ``project:<slug>`` | ``default``       | ``default.inbox`` |

Personal is built in (not a row of the ``spaces`` table, whose CHECK constraint allows only general and project).
It is off until the user turns it on, and a host reaches it only through an explicit per-connection permission.

When a name cannot be resolved to exactly one space, BIO CE uses General and says so. A permission denial is
never redirected to General: that would turn a refusal into a way around it. Nothing ever falls back to Personal.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ntpath
import os
from pathlib import PureWindowsPath
import re
import unicodedata
from typing import Iterable

from bio_ce.core.models import MemoryScope


GENERAL_SPACE_ID = "general"
GENERAL_PROJECT = "bio-ce-personal"
PROJECT_PREFIX = "project:"
CURATED_NAMESPACE = "default"
INBOX_NAMESPACE = "default.inbox"
PERSONAL_SPACE_ID = "personal"
PERSONAL_NAMESPACE = "personal"
PERSONAL_DISPLAY_NAME = "Personal"
INBOX_SUFFIX = ".inbox"
SLUG_LIMIT = 64

RESOLVED_EXACT = "exact"
RESOLVED_DEFAULT = "default"
RESOLVED_FALLBACK = "fallback_general"
REASON_AMBIGUOUS = "ambiguous"
REASON_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Space:
    space_id: str
    kind: str
    project: str
    display_name: str
    archived_at: str | None = None
    namespace: str = CURATED_NAMESPACE

    @property
    def is_general(self) -> bool:
        return self.kind == "general"

    @property
    def is_personal(self) -> bool:
        return self.kind == "personal"

    @property
    def slug(self) -> str:
        return self.project[len(PROJECT_PREFIX):] if self.project.startswith(PROJECT_PREFIX) else self.project

    @property
    def curated(self) -> MemoryScope:
        return MemoryScope(self.project, self.namespace)

    @property
    def inbox(self) -> MemoryScope:
        return MemoryScope(self.project, self.namespace + INBOX_SUFFIX)


PERSONAL_SPACE = Space(PERSONAL_SPACE_ID, "personal", GENERAL_PROJECT, PERSONAL_DISPLAY_NAME,
                       namespace=PERSONAL_NAMESPACE)


def is_personal_request(requested: str | None) -> bool:
    """space="personal" or "Personal" (any case) asks for the built-in Personal space."""
    return requested is not None and requested.strip().casefold() == PERSONAL_SPACE_ID


def is_reserved_name(display_name: str) -> bool:
    """Project spaces can't be called Personal: that name always means the built-in space."""
    return unicodedata.normalize("NFKC", display_name).strip().casefold() == PERSONAL_SPACE_ID


def space_for_scope(spaces: Iterable[Space], scope: MemoryScope) -> Space | None:
    """The space that owns a curated or inbox scope; Personal is included even though it is not a table row."""
    namespace = scope.namespace[: -len(INBOX_SUFFIX)] if scope.namespace.endswith(INBOX_SUFFIX) else scope.namespace
    for space in (*spaces, PERSONAL_SPACE):
        if space.project == scope.project and space.namespace == namespace:
            return space
    return None


@dataclass(frozen=True, slots=True)
class Resolution:
    space: Space
    how: str  # RESOLVED_EXACT, RESOLVED_DEFAULT (nothing asked), or RESOLVED_FALLBACK
    reason: str | None = None  # REASON_AMBIGUOUS or REASON_UNKNOWN for a fallback

    def as_result(self) -> dict[str, object]:
        result: dict[str, object] = {"space": {"id": self.space.space_id, "name": self.space.display_name},
                                     "space_resolution": self.how}
        if self.reason:
            result["space_resolution_reason"] = self.reason
        return result


def slugify(display_name: str, taken: Iterable[str] = ()) -> str:
    """Lower case, spaces and punctuation to '-', at most 64 characters, '-2', '-3' ... when taken."""
    text = unicodedata.normalize("NFKC", display_name).casefold()
    text = re.sub(r"[^\w]+", "-", text, flags=re.UNICODE).replace("_", "-")
    text = re.sub(r"-{2,}", "-", text).strip("-") or "space"
    base = text[:SLUG_LIMIT].strip("-") or "space"
    used = set(taken)
    if base not in used:
        return base
    number = 2
    while True:
        suffix = f"-{number}"
        candidate = base[: SLUG_LIMIT - len(suffix)].strip("-") + suffix
        if candidate not in used:
            return candidate
        number += 1


def resolve_space(spaces: Iterable[Space], requested: str | None) -> Resolution:
    """The MCP ``space`` argument: id, then display name (any case), then slug; exactly one match or General."""
    available = [space for space in spaces if space.archived_at is None]
    general = next(space for space in available if space.is_general)
    if requested is None or not requested.strip():
        return Resolution(general, RESOLVED_DEFAULT)
    wanted = requested.strip()
    for space in available:
        if space.space_id == wanted:
            return Resolution(space, RESOLVED_EXACT)
    folded = wanted.casefold()
    for matches in ([space for space in available if space.display_name.casefold() == folded],
                    [space for space in available if space.slug == folded or space.project == wanted]):
        if len(matches) == 1:
            return Resolution(matches[0], RESOLVED_EXACT)
        if len(matches) > 1:
            return Resolution(general, RESOLVED_FALLBACK, REASON_AMBIGUOUS)
    return Resolution(general, RESOLVED_FALLBACK, REASON_UNKNOWN)


def folder_key(path: str | os.PathLike[str]) -> str:
    """SHA-256 of a normalized Windows folder path; only this hash is stored, never the path."""
    return hashlib.sha256(normalize_folder(path).encode("utf-8")).hexdigest()


def normalize_folder(path: str | os.PathLike[str]) -> str:
    text = ntpath.normpath(str(os.fspath(path)).strip().replace("/", "\\"))
    text = ntpath.normcase(text)
    if len(text) > 3:
        text = text.rstrip("\\")
    return text


def folder_chain(path: str | os.PathLike[str]) -> list[str]:
    """The folder and each parent, deepest first, normalized."""
    current = PureWindowsPath(normalize_folder(path))
    chain = [str(current)]
    for parent in current.parents:
        chain.append(normalize_folder(str(parent)))
    return chain


def resolve_folder(spaces: Iterable[Space], links: Iterable[tuple[str, str]], cwd: str | None) -> Resolution:
    """The deepest linked folder above ``cwd`` picks the space; two spaces at the same depth mean General."""
    available = {space.space_id: space for space in spaces if space.archived_at is None}
    general = next(space for space in available.values() if space.is_general)
    if not cwd:
        return Resolution(general, RESOLVED_DEFAULT)
    by_key: dict[str, set[str]] = {}
    for space_id, key in links:
        if space_id in available:
            by_key.setdefault(key, set()).add(space_id)
    for folder in folder_chain(cwd):
        found = by_key.get(hashlib.sha256(folder.encode("utf-8")).hexdigest())
        if not found:
            continue
        if len(found) > 1:
            return Resolution(general, RESOLVED_FALLBACK, REASON_AMBIGUOUS)
        return Resolution(available[next(iter(found))], RESOLVED_EXACT)
    return Resolution(general, RESOLVED_DEFAULT)


__all__ = [
    "CURATED_NAMESPACE",
    "GENERAL_PROJECT",
    "GENERAL_SPACE_ID",
    "INBOX_NAMESPACE",
    "INBOX_SUFFIX",
    "PERSONAL_DISPLAY_NAME",
    "PERSONAL_NAMESPACE",
    "PERSONAL_SPACE",
    "PERSONAL_SPACE_ID",
    "PROJECT_PREFIX",
    "REASON_AMBIGUOUS",
    "REASON_UNKNOWN",
    "RESOLVED_DEFAULT",
    "RESOLVED_EXACT",
    "RESOLVED_FALLBACK",
    "Resolution",
    "Space",
    "folder_chain",
    "folder_key",
    "is_personal_request",
    "is_reserved_name",
    "space_for_scope",
    "normalize_folder",
    "resolve_folder",
    "resolve_space",
    "slugify",
]
