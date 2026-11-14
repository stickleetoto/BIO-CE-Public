# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Claude desktop app (chat) connection (v0.4.3 E-1): one ``mcpServers.bio-ce`` entry in its settings file.

The desktop app has no command for adding MCP servers, so BIO CE edits ``claude_desktop_config.json`` itself:

1. Find the file. The Store (MSIX) app keeps it in ``%LOCALAPPDATA%\\Claude-Data\\claude_<id>\\``, a folder the
   package keeps out of file virtualization; the classic installer uses ``%APPDATA%\\Claude\\``. The file also holds
   the app's own settings, so it is never deleted or rewritten as a whole: only BIO CE's entry changes.
2. Back it up. Refuse to change a file that is not valid JSON.
3. Add the entry (other servers and keys stay), write atomically, read it back, and check the server with the same
   read-only probe as the other hosts. If anything fails, the grant is revoked and the file is put back.
4. Disconnect revokes the grant first, then removes only BIO CE's entry.

The app reads the file when it starts, so the user quits and reopens Claude after a change. The S1 spike
(2026-11-14) verified that the server the app starts writes to the real BIO CE data folder; the server refuses to
start when that folder does not exist (it never creates it, see ``mcp_server``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping
import uuid

from bio_ce.control_store import MODE_READ_ONLY

HOST = "claude_desktop"
CONFIG_NAME = "claude_desktop_config.json"
SERVER_NAME = "bio-ce"
RESTART_NOTE = "Quit the Claude desktop app completely (also from the system tray) and open it again."


def locate(env: Mapping[str, str]) -> tuple[bool, Path | None, str | None]:
    """(installed, settings file, kind). The file may not exist yet: the app creates it the first time it runs."""
    local = Path(env.get("LOCALAPPDATA") or "")
    roaming = Path(env.get("APPDATA") or "")
    if env.get("LOCALAPPDATA"):
        data_root = local / "Claude-Data"
        folders = sorted(path for path in data_root.glob("claude_*") if path.is_dir()) if data_root.is_dir() else []
        packages = sorted(path for path in (local / "Packages").glob("Claude_*") if path.is_dir()) \
            if (local / "Packages").is_dir() else []
        if folders:
            return True, folders[0] / CONFIG_NAME, "msix"
        if packages:
            # Installed from the Store but never opened: the app makes its data folder on first start.
            return True, data_root / packages[0].name.lower() / CONFIG_NAME, "msix"
    if env.get("APPDATA") and ((roaming / "Claude").is_dir() or (local / "AnthropicClaude").is_dir()):
        return True, roaming / "Claude" / CONFIG_NAME, "classic"
    return False, None, None


def read_config(path: Path) -> tuple[dict, bytes | None]:
    """(settings, original bytes). A missing file is empty settings; anything unreadable raises ValueError."""
    if not path.exists():
        return {}, None
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8-sig")) if raw.strip() else {}
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The Claude desktop settings file is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("The Claude desktop settings file is not a JSON object")
    servers = data.get("mcpServers", {})
    if servers is not None and not isinstance(servers, dict):
        raise ValueError("mcpServers in the Claude desktop settings file is not an object")
    return data, raw


def entry(data: Mapping) -> dict | None:
    servers = data.get("mcpServers") or {}
    value = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
    return value if isinstance(value, dict) else None


def render(data: Mapping, original: bytes | None) -> bytes:
    """Two-space indent like the app writes; keep a trailing newline only if the file had one."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if original is not None and original.endswith(b"\n"):
        text += "\n"
    return text.encode("utf-8")


def write_atomically(path: Path, content: bytes) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.bio-ce-tmp")
    temporary.write_bytes(content)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def with_entry(data: dict, command: str, args: tuple[str, ...], token_variable: str, token: str) -> dict:
    updated = json.loads(json.dumps(data))
    servers = updated.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[SERVER_NAME] = {"command": command, "args": list(args), "env": {token_variable: token}}
    updated["mcpServers"] = servers
    return updated


def without_entry(data: dict, had_servers_key: bool) -> dict:
    updated = json.loads(json.dumps(data))
    servers = updated.get("mcpServers")
    if isinstance(servers, dict):
        servers.pop(SERVER_NAME, None)
        if not servers and not had_servers_key:
            updated.pop("mcpServers", None)
    return updated


__all__ = ["CONFIG_NAME", "HOST", "MODE_READ_ONLY", "RESTART_NOTE", "SERVER_NAME", "entry", "locate",
           "read_config", "render", "with_entry", "without_entry", "write_atomically"]
