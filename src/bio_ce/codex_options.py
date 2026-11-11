# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Codex's code-mode option for the bio-ce MCP server.

Codex runs its standard models in code mode, which may not show MCP tools or their instructions to the
model directly. Codex 0.166 and later accept ``omit_tools_from = ["code_mode"]`` on one MCP server, which
shows that server's tools and instructions (verified with Codex 0.166.0). Codex validates the values of
this key strictly, and one bad value makes its whole configuration unreadable, so BIO CE writes exactly
one known line, checks the result, and restores the previous file if anything is off.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any

SERVER_NAME = "bio-ce"
MINIMUM_CODEX_VERSION = (0, 166, 0)
MARKER = "# Added by BIO CE: show BIO CE's tools and instructions in Codex code mode."
OPTION_LINE = 'omit_tools_from = ["code_mode"]'

APPLIED = "applied"
MISSING = "missing"
USER_SET = "user_set"
NOT_REGISTERED = "not_registered"

_HEADER = re.compile(r'^[ \t]*\[[ \t]*mcp_servers[ \t]*\.[ \t]*(?:bio-ce|"bio-ce"|\'bio-ce\')[ \t]*\][ \t]*(?:#[^\r\n]*)?(\r?\n|$)',
                     re.MULTILINE)
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class CodeModeOptionError(ValueError):
    """The option cannot be written safely; the file was not changed."""


def parse_codex_version(text: str) -> tuple[int, int, int] | None:
    """``codex-cli 0.166.0`` -> (0, 166, 0). Pre-release suffixes count as that release."""
    match = _VERSION.search(text or "")
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def version_supported(version: tuple[int, int, int] | None) -> bool:
    return version is not None and version >= MINIMUM_CODEX_VERSION


def option_state(raw: str) -> str:
    """Whether BIO CE's server entry already shows its tools in code mode."""
    entry = _entry(tomllib.loads(raw))
    if entry is None:
        return NOT_REGISTERED
    value = entry.get("omit_tools_from")
    if value is None:
        return MISSING
    if isinstance(value, list) and "code_mode" in value:
        return APPLIED
    return USER_SET


def add_option(raw: str) -> str:
    """Return ``raw`` with the option added directly under the ``[mcp_servers.bio-ce]`` table header."""
    before = tomllib.loads(raw)
    state = option_state(raw)
    if state != MISSING:
        raise CodeModeOptionError(f"the bio-ce entry is {state.replace('_', ' ')}")
    headers = list(_HEADER.finditer(raw))
    if len(headers) != 1:
        # An inline-table entry or several headers: too unusual to edit safely.
        raise CodeModeOptionError("the bio-ce table header was not found exactly once")
    header = headers[0]
    newline = header.group(1) or ("\r\n" if "\r\n" in raw else "\n")
    insert_at = header.end()
    prefix = raw[:insert_at] if header.group(1) else raw[:insert_at] + newline
    updated = prefix + MARKER + newline + OPTION_LINE + newline + raw[insert_at:]
    after = tomllib.loads(updated)  # refuse to write anything Codex could not read
    expected = _with_option(before)
    if after != expected:
        raise CodeModeOptionError("adding the option would change other settings")
    return updated


def remove_orphan_marker(raw: str) -> str:
    """Drop BIO CE's marker comment (and its line) if the entry they belonged to is gone."""
    if _entry(tomllib.loads(raw)) is not None:
        return raw
    pattern = re.compile(r"^[ \t]*" + re.escape(MARKER) + r"[ \t]*\r?\n(?:[ \t]*" + re.escape(OPTION_LINE)
                         + r"[ \t]*\r?\n)?", re.MULTILINE)
    return pattern.sub("", raw)


def _entry(config: dict[str, Any]) -> dict[str, Any] | None:
    servers = config.get("mcp_servers")
    entry = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
    return entry if isinstance(entry, dict) else None


def _with_option(config: dict[str, Any]) -> dict[str, Any]:
    import copy

    expected = copy.deepcopy(config)
    expected["mcp_servers"][SERVER_NAME]["omit_tools_from"] = ["code_mode"]
    return expected


__all__ = [
    "APPLIED",
    "MARKER",
    "MINIMUM_CODEX_VERSION",
    "MISSING",
    "NOT_REGISTERED",
    "OPTION_LINE",
    "USER_SET",
    "CodeModeOptionError",
    "add_option",
    "option_state",
    "parse_codex_version",
    "remove_orphan_marker",
    "version_supported",
]
