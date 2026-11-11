# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Read-only check: which AI hosts still point to one BIO CE installation.

The uninstaller runs ``BIO-CE-MCP.exe host-check --app-dir <install folder>`` before it removes anything.
Uninstalling does not edit host settings, so a host that still lists this installation's MCP server or
hooks would keep pointing to a removed program; the uninstaller then suggests disconnecting first.
Only entries that start *this* installation's ``MCP\\BIO-CE-MCP.exe`` count. Nothing is written.

Exit code: 0 when nothing points here; otherwise 100 plus a bit mask (see ``FLAGS``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
import os
from pathlib import Path
import tomllib
from typing import Any

from bio_ce import host_hooks

CODEX_MCP, CODEX_HOOKS, CLAUDE_MCP, CLAUDE_HOOKS = 1, 2, 4, 8
FLAGS = {CODEX_MCP: "Codex MCP server", CODEX_HOOKS: "Codex hooks", CLAUDE_MCP: "Claude Code MCP server",
         CLAUDE_HOOKS: "Claude Code hooks"}
FOUND_BASE = 100


def server_executable(app_dir: Path) -> Path:
    return app_dir / "MCP" / "BIO-CE-MCP.exe"


def _same(path: object, executable: Path) -> bool:
    if not isinstance(path, str) or not path.strip():
        return False
    return os.path.normcase(os.path.normpath(path.strip().strip('"'))) == os.path.normcase(
        os.path.normpath(str(executable)))


def _mentions(command: object, executable: Path) -> bool:
    """A hook command line (or exec-form command) that starts this executable."""
    if not isinstance(command, str):
        return False
    text = command.strip()
    if _same(text, executable):
        return True
    first = text[1:].split('"', 1)[0] if text.startswith('"') else text.split(" ", 1)[0]
    return _same(first, executable)


def _commands(value: Any) -> Iterable[object]:
    if isinstance(value, dict):
        if "command" in value:
            yield value["command"]
        for child in value.values():
            yield from _commands(child)
    elif isinstance(value, list):
        for child in value:
            yield from _commands(child)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def references(app_dir: Path, env: Mapping[str, str]) -> int:
    """Bit mask of host settings that still start this installation's MCP executable."""
    executable = server_executable(app_dir)
    found = 0
    codex_home = env.get("CODEX_HOME")
    profile = Path(env.get("USERPROFILE") or Path.home())
    codex_config = (Path(codex_home) if codex_home else profile / ".codex") / "config.toml"
    raw = _read(codex_config)
    if raw is not None:
        try:
            entry = (tomllib.loads(raw).get("mcp_servers") or {}).get("bio-ce") or {}
            if isinstance(entry, dict) and _same(entry.get("command"), executable):
                found |= CODEX_MCP
        except ValueError:
            pass
    claude_dir = env.get("CLAUDE_CONFIG_DIR")
    claude_config = (Path(claude_dir) / ".claude.json") if claude_dir else profile / ".claude.json"
    raw = _read(claude_config)
    if raw is not None:
        try:
            entry = (json.loads(raw).get("mcpServers") or {}).get("bio-ce") or {}
            if isinstance(entry, dict) and _same(entry.get("command"), executable):
                found |= CLAUDE_MCP
        except (ValueError, AttributeError):
            pass
    for flag, host in ((CODEX_HOOKS, "codex"), (CLAUDE_HOOKS, "claude")):
        raw = _read(host_hooks.hooks_path(host, env))
        if raw is None:
            continue
        try:
            hooks = json.loads(raw).get("hooks")
        except (ValueError, AttributeError):
            continue
        if any(_mentions(command, executable) for command in _commands(hooks)):
            found |= flag
    return found


def describe(mask: int) -> list[str]:
    return [label for flag, label in FLAGS.items() if mask & flag]


def main(app_dir: str, env: Mapping[str, str] | None = None) -> int:
    mask = references(Path(app_dir), os.environ if env is None else env)
    return FOUND_BASE + mask if mask else 0


__all__ = ["CLAUDE_HOOKS", "CLAUDE_MCP", "CODEX_HOOKS", "CODEX_MCP", "FLAGS", "FOUND_BASE", "describe", "main",
           "references", "server_executable"]
