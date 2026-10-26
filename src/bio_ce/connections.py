# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Consent-gated MCP host registration for the supported Windows CLIs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Mapping, Sequence
import uuid

from bio_ce import host_hooks
from bio_ce.control_store import (
    AccessDenied,
    ControlStore,
    Grant,
    MODE_AUTO_MEMORY,
    MODE_READ_ONLY,
    control_database_for,
)
from bio_ce.core.models import MemoryScope
from bio_ce.mcp_server import TOKEN_ENVIRONMENT_VARIABLE, TOOL_NAMES
from bio_ce.storage.backup import validate_database
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


SERVER_NAME = "bio-ce"
_PERSONAL_SCOPE = MemoryScope("bio-ce-personal", "default")
_EXPECTED_TOOLS = set(TOOL_NAMES)


class MCPConnectionError(RuntimeError):
    """A host could not be connected or disconnected safely."""


class MCPConnectionConsentRequired(MCPConnectionError):
    """The caller did not provide explicit approval for a host config change."""


class MCPConnectionConflict(MCPConnectionError):
    """A different entry already owns the BIO CE MCP server name."""


@dataclass(frozen=True, slots=True)
class HostStatus:
    host: str
    installed: bool
    connected: bool
    configuration_conflict: bool = False
    legacy: bool = False
    mode: str | None = None
    connection_id: str | None = None
    hooks_installed: bool = False


@dataclass(frozen=True, slots=True)
class AutoMemorySupport:
    """Whether a host's model can actually use BIO CE's tools, separate from being connected.

    ``level`` is ``available`` (verified with a real model), ``limited`` (the server and
    tools work but the host often does not show them to its model), or ``unverified``.
    """

    host: str
    level: str
    summary: str
    detail: str


AUTO_MEMORY_SUPPORT = {
    "claude": AutoMemorySupport(
        "claude", "available", "Available",
        "Verified with Claude Code 2.1.306: the model found BIO CE's tools on its own and saved, deduplicated, "
        "corrected, and recalled memories.",
    ),
    "codex": AutoMemorySupport(
        "codex", "limited", "Limited",
        "Codex CLI runs its standard models in code mode, which does not show MCP tools or their instructions "
        "to the model (an open Codex issue, unfixed through 0.164). BIO CE's server and tools work, and calls "
        "succeed when the model uses them, but the model is usually not told they exist. With session hooks "
        "installed and trusted in Codex, BIO CE tells it where to find them; this was not verified with a real "
        "model.",
    ),
}


def auto_memory_support(host: str) -> AutoMemorySupport:
    return AUTO_MEMORY_SUPPORT.get(host) or AutoMemorySupport(host, "unverified", "Not verified", "")


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    host: str
    connected: bool
    already_configured: bool
    backup_file: Path | None


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    """One read-only diagnostic step. ``outcome`` is pass, fail, info, or skip."""

    name: str
    outcome: str
    detail: str


class MCPConnectionManager:
    """Run official host management CLIs and verify the local SDK route.

    Configuration backups are made only after explicit consent is passed.
    CLI output is captured and discarded so it cannot echo credentials or local
    configuration into the GUI, logs, or test evidence.
    """

    def __init__(
        self,
        database: str | Path,
        local_data_root: str | Path,
        *,
        env: Mapping[str, str] | None = None,
        sdk_verifier=None,
    ) -> None:
        self.database = Path(database).expanduser().resolve()
        self.local_data_root = Path(local_data_root).expanduser().resolve()
        self.env = dict(os.environ if env is None else env)
        self._sdk_verifier = sdk_verifier or self._verify_local_sdk
        self._control: ControlStore | None = None

    @property
    def control(self) -> ControlStore:
        """Grants for host connections, kept beside the memory database."""
        if self._control is None:
            self._control = ControlStore(control_database_for(self.database))
        return self._control

    def close(self) -> None:
        if self._control is not None:
            self._control.close()
            self._control = None

    def detect(self) -> tuple[HostStatus, HostStatus]:
        return tuple(self.status(host) for host in ("codex", "claude"))  # type: ignore[return-value]

    def status(self, host: str) -> HostStatus:
        host = _validate_host(host)
        executable = self._find_cli(host)
        if executable is None:
            return HostStatus(host, False, False)
        try:
            entry = self._read_entry(host)
        except MCPConnectionError:
            return HostStatus(host, True, False, True)
        if entry is None:
            return HostStatus(host, True, False)
        grant = self._grant_for_entry(host, entry)
        if grant is not None:
            hooks = host_hooks.hooks_installed(
                host_hooks.hooks_path(host, self.env), self._server_executable(), grant.connection_id
            )
            return HostStatus(host, True, True, mode=grant.mode, connection_id=grant.connection_id,
                              hooks_installed=hooks)
        if self._matches_legacy_server(entry):
            return HostStatus(host, True, True, legacy=True, mode=MODE_READ_ONLY)
        return HostStatus(host, True, False, True)

    def connect(self, host: str, *, approved: bool = False) -> ConnectionResult:
        if approved is not True:
            raise MCPConnectionConsentRequired("Host registration requires explicit user approval.")
        host = _validate_host(host)
        if self._find_cli(host) is None:
            raise MCPConnectionError(f"{host} CLI is not installed.")
        try:
            validate_database(self.database)
        except Exception as exc:
            raise MCPConnectionError("BIO CE personal database is not ready for a read-only connection.") from exc

        existing = self._read_entry(host)
        if existing is not None:
            grant = self._grant_for_entry(host, existing)
            if grant is not None:
                self._verify_or_raise(grant.connection_id, self._entry_token(existing))
                return ConnectionResult(host, True, True, None)
            if not self._matches_legacy_server(existing):
                raise MCPConnectionConflict(
                    "The server name bio-ce is already used by a different MCP configuration."
                )
            # A v0.2 read-only entry: replace it with a managed connection.
            self._backup_config(host, self._config_path(host))
            self._run_cli(host, self._remove_arguments(host))
            if self._read_entry(host) is not None:
                raise MCPConnectionError("BIO CE could not replace its earlier read-only host entry.")

        config_path = self._config_path(host)
        backup_file = self._backup_config(host, config_path)
        grant, token = self.control.create_grant(
            host, project=_PERSONAL_SCOPE.project, namespace=_PERSONAL_SCOPE.namespace
        )
        command, server_args = self._mcp_server_command(grant.connection_id)
        arguments = self._add_arguments(host, command, server_args, token)
        try:
            completed = self._run_cli(host, arguments)
        except MCPConnectionError:
            self.control.revoke(grant.connection_id)
            raise
        configured = self._read_entry(host)
        if completed.returncode != 0 or configured is None or self._grant_for_entry(host, configured) is None:
            self.control.revoke(grant.connection_id)
            if configured is not None:
                self._rollback_added(host, backup_file)
            raise MCPConnectionError("The host did not save the expected BIO CE MCP configuration.")

        try:
            self._sdk_verifier(self.database, _PERSONAL_SCOPE, command, server_args,
                               {TOKEN_ENVIRONMENT_VARIABLE: token})
        except Exception as exc:
            self.control.revoke(grant.connection_id)
            self._rollback_added(host, backup_file)
            raise MCPConnectionError(
                "BIO CE MCP verification failed; the host registration was rolled back."
            ) from exc
        return ConnectionResult(host, True, False, backup_file)

    def set_mode(self, host: str, mode: str) -> Grant:
        """Change what a connected host may do. Running servers apply it on their next call."""
        status = self.status(host)
        if not status.connected or status.connection_id is None:
            raise MCPConnectionError(
                "Reconnect this host in BIO CE first; only connections made by this version can change modes."
            )
        auto = mode == MODE_AUTO_MEMORY
        if auto:
            # Allow BIO CE's tools first: if that fails, the mode stays as it was.
            self._sync_tool_approval(host, True)
            return self.control.set_mode(status.connection_id, mode)
        grant = self.control.set_mode(status.connection_id, mode)
        self._sync_tool_approval(host, False)
        return grant

    def _sync_tool_approval(self, host: str, enabled: bool) -> None:
        path = host_hooks.tool_approval_path(host, self.env)
        if not enabled and not path.is_file():
            return
        if host_hooks.tool_approval_enabled(host, path) == enabled:
            return
        self._backup_config(f"{host}-approvals", path)
        try:
            host_hooks.set_tool_approval(host, path, enabled)
        except (OSError, ValueError) as exc:
            raise MCPConnectionError(
                f"BIO CE could not update {host_name_for(host)}'s tool approvals in {path.name}; "
                "it was left unchanged."
            ) from exc

    def install_hooks(self, host: str, *, approved: bool = False) -> Path | None:
        """Add BIO CE's SessionStart/UserPromptSubmit hooks to the host's user settings."""
        if approved is not True:
            raise MCPConnectionConsentRequired("Installing host hooks requires explicit user approval.")
        host = _validate_host(host)
        entry = self._read_entry(host)
        grant = self._grant_for_entry(host, entry) if entry is not None else None
        if grant is None:
            raise MCPConnectionError("Connect this host first; hooks use the same BIO CE connection.")
        path = host_hooks.hooks_path(host, self.env)
        backup = self._backup_config(f"{host}-hooks", path)
        command = host_hooks.HookCommand(
            self._server_executable_or_raise(), self.database, grant.connection_id, self._entry_token(entry),
            () if getattr(sys, "frozen", False) else ("-m", "bio_ce"),
        )
        try:
            host_hooks.install_hooks(host, path, command)
        except (OSError, ValueError) as exc:
            raise MCPConnectionError(f"BIO CE could not update {path.name}; it was left unchanged.") from exc
        return backup

    def remove_hooks(self, host: str, *, approved: bool = False) -> Path | None:
        if approved is not True:
            raise MCPConnectionConsentRequired("Removing host hooks requires explicit user approval.")
        host = _validate_host(host)
        path = host_hooks.hooks_path(host, self.env)
        if not path.is_file():
            return None
        backup = self._backup_config(f"{host}-hooks", path)
        try:
            host_hooks.remove_hooks(path, self._server_executable())
        except (OSError, ValueError) as exc:
            raise MCPConnectionError(f"BIO CE could not update {path.name}; it was left unchanged.") from exc
        return backup

    def disconnect(self, host: str, *, approved: bool = False) -> ConnectionResult:
        if approved is not True:
            raise MCPConnectionConsentRequired("Host removal requires explicit user approval.")
        host = _validate_host(host)
        if self._find_cli(host) is None:
            raise MCPConnectionError(f"{host} CLI is not installed.")
        existing = self._read_entry(host)
        if existing is None:
            self._revoke_host(host)
            return ConnectionResult(host, False, False, None)
        if self._grant_for_entry(host, existing) is None and not self._matches_legacy_server(existing):
            raise MCPConnectionConflict(
                "The configured bio-ce entry does not match BIO CE; it was left untouched."
            )
        # Revoke first: even if the host keeps a stale entry, its token no longer works.
        self._revoke_host(host)
        try:
            self._sync_tool_approval(host, False)
        except MCPConnectionError:
            pass  # the entry is removed below; leftover approvals then name a server that no longer exists
        backup_file = self._backup_config(host, self._config_path(host))
        self._run_cli(host, self._remove_arguments(host))
        if self._read_entry(host) is not None:
            raise MCPConnectionError(
                "BIO CE revoked this connection but could not remove its host entry. "
                "The configuration backup was retained."
            )
        try:
            hooks_file = host_hooks.hooks_path(host, self.env)
            if hooks_file.is_file():
                self._backup_config(f"{host}-hooks", hooks_file)
                host_hooks.remove_hooks(hooks_file, self._server_executable())
        except (OSError, ValueError, MCPConnectionError):
            pass  # hooks of a revoked connection print nothing, so leaving them is harmless
        return ConnectionResult(host, False, False, backup_file)

    def _revoke_host(self, host: str) -> None:
        for grant in self.control.grants():
            if grant.host == host:
                self.control.revoke(grant.connection_id)

    def diagnose(self, host: str, *, run_server_check: bool = True) -> tuple[DiagnosticCheck, ...]:
        """Explain the connection state without changing any host configuration.

        The optional server check starts the local read-only MCP server once
        and exercises search/read exactly like the post-connect verification.
        """
        host = _validate_host(host)
        checks: list[DiagnosticCheck] = []
        cli_found = self._find_cli(host) is not None
        checks.append(DiagnosticCheck(
            "Host command",
            "pass" if cli_found else "fail",
            f"The {host} command is available." if cli_found
            else f"The {host} command was not found on PATH. Install the host, open a new terminal to confirm "
                 f"`{host} --version` works, then refresh.",
        ))
        entry_ok = False
        try:
            entry = self._read_entry(host)
        except MCPConnectionError:
            checks.append(DiagnosticCheck(
                "Host settings", "fail",
                "The host MCP settings file could not be read. BIO CE will not change it until it is valid.",
            ))
        else:
            config_exists = self._config_path(host).is_file()
            checks.append(DiagnosticCheck(
                "Host settings", "pass",
                "The host MCP settings file is readable." if config_exists
                else "No host settings file exists yet; connecting will create one.",
            ))
            grant = self._grant_for_entry(host, entry) if entry is not None else None
            if entry is None:
                checks.append(DiagnosticCheck("BIO CE entry", "info", "BIO CE is not registered with this host."))
            elif grant is not None:
                entry_ok = True
                checks.append(DiagnosticCheck(
                    "BIO CE entry", "pass", "Registered and pointing at this BIO CE installation and database.",
                ))
                checks.append(DiagnosticCheck(
                    "Permissions", "info",
                    {"read_only": "Read only: the host can search and read memories.",
                     "auto_memory": "Auto memory: the host can also save and update memories under the BIO CE "
                                    "policy. Retractions wait for your approval.",
                     "paused": "Paused: the host cannot read or change memories until you resume it."}[grant.mode],
                ))
            elif self._matches_legacy_server(entry):
                entry_ok = True
                checks.append(DiagnosticCheck(
                    "BIO CE entry", "info",
                    "Registered by BIO CE v0.2 (read only, no permission controls). Reconnect to manage permissions.",
                ))
            else:
                checks.append(DiagnosticCheck(
                    "BIO CE entry", "fail",
                    f"Another MCP server already uses the name {SERVER_NAME}. BIO CE left it untouched; remove or "
                    "rename that entry in the host, then refresh.",
                ))
        try:
            validate_database(self.database)
        except Exception:
            database_ok = False
            checks.append(DiagnosticCheck(
                "Memory database", "fail", "The personal memory database could not be validated.",
            ))
        else:
            database_ok = True
            checks.append(DiagnosticCheck("Memory database", "pass", "The personal memory database is valid."))
        try:
            command, server_args = self._mcp_server_command()
        except MCPConnectionError as exc:
            checks.append(DiagnosticCheck("MCP server", "fail", str(exc)))
            return tuple(checks)
        checks.append(DiagnosticCheck("MCP server", "pass", "The BIO CE MCP server program is present."))
        if not run_server_check or not database_ok:
            checks.append(DiagnosticCheck(
                "Server check", "skip",
                "Skipped because the database is not valid." if not database_ok else "Not run.",
            ))
            return tuple(checks)
        try:
            self._sdk_verifier(self.database, _PERSONAL_SCOPE, command, server_args, {})
        except Exception:
            checks.append(DiagnosticCheck(
                "Server check", "fail",
                "The local MCP server did not start or did not answer the search/read check.",
            ))
        else:
            checks.append(DiagnosticCheck(
                "Server check", "pass",
                "The server started locally and answered a search/read check without changing anything. "
                "No AI model was called.",
            ))
        support = auto_memory_support(host)
        checks.append(DiagnosticCheck(
            "Model access", "pass" if support.level == "available" else "info",
            f"Auto memory: {support.summary.lower()}. {support.detail}",
        ))
        if cli_found and not entry_ok:
            checks.append(DiagnosticCheck(
                "Next step", "info", "Select Connect to register BIO CE with this host.",
            ))
        return tuple(checks)

    def _verify_or_raise(self, connection_id: str, token: str | None) -> None:
        command, server_args = self._mcp_server_command(connection_id)
        try:
            self._sdk_verifier(self.database, _PERSONAL_SCOPE, command, server_args,
                               {TOKEN_ENVIRONMENT_VARIABLE: token or ""})
        except Exception as exc:
            raise MCPConnectionError("The configured BIO CE MCP server did not pass local SDK verification.") from exc

    def _server_executable(self) -> Path:
        """The program hosts start: the packaged MCP exe, or this Python when running from source."""
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "MCP" / "BIO-CE-MCP.exe"
        return Path(sys.executable).resolve()

    def _server_executable_or_raise(self) -> Path:
        executable = self._server_executable()
        if not executable.is_file():
            raise MCPConnectionError("The packaged MCP/BIO-CE-MCP.exe is missing beside the desktop app.")
        return executable

    def _mcp_server_command(self, connection_id: str | None = None) -> tuple[str, tuple[str, ...]]:
        command = str(self._server_executable_or_raise())
        args: tuple[str, ...] = () if getattr(sys, "frozen", False) else ("-m", "bio_ce")
        args = args + (
            "mcp-stdio",
            "--db",
            str(self.database),
            "--project",
            "bio-ce-personal",
            "--namespace",
            "default",
        )
        if connection_id is not None:
            args = args + ("--connection", connection_id)
        return command, args

    def _add_arguments(
        self, host: str, command: str, server_args: Sequence[str], token: str
    ) -> tuple[str, ...]:
        secret = f"{TOKEN_ENVIRONMENT_VARIABLE}={token}"
        if host == "codex":
            return ("mcp", "add", SERVER_NAME, "--env", secret, "--", command, *server_args)
        return (
            "mcp",
            "add",
            "--transport",
            "stdio",
            "--scope",
            "user",
            SERVER_NAME,
            "-e",
            secret,
            "--",
            command,
            *server_args,
        )

    def _remove_arguments(self, host: str) -> tuple[str, ...]:
        if host == "codex":
            return ("mcp", "remove", SERVER_NAME)
        return ("mcp", "remove", "--scope", "user", SERVER_NAME)

    def _find_cli(self, host: str) -> Path | None:
        found = shutil.which(host, path=self.env.get("PATH"))
        if not found:
            return None
        path = Path(found)
        if path.suffix.lower() in {".cmd", ".bat"}:
            powershell_peer = path.with_suffix(".ps1")
            if powershell_peer.is_file():
                return powershell_peer
            return None
        return path

    def _run_cli(self, host: str, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        executable = self._find_cli(host)
        if executable is None:
            raise MCPConnectionError(f"{host} CLI is not installed or cannot be launched safely.")
        if executable.suffix.lower() == ".ps1":
            powershell = shutil.which("powershell.exe", path=self.env.get("PATH"))
            if powershell is None:
                raise MCPConnectionError("Windows PowerShell is required to run the Codex CLI wrapper.")
            command = [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(executable),
                *args,
            ]
        else:
            command = [str(executable), *args]
        try:
            return subprocess.run(
                command,
                cwd=str(self.database.parent),
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MCPConnectionError(f"{host} MCP command could not be completed.") from exc

    def _config_path(self, host: str) -> Path:
        if host == "codex":
            profile = self.env.get("CODEX_HOME")
            if profile:
                return Path(profile).expanduser().resolve() / "config.toml"
            user_profile = self.env.get("USERPROFILE")
            base = Path(user_profile).expanduser() if user_profile else Path.home()
            return (base / ".codex" / "config.toml").resolve()
        profile = self.env.get("CLAUDE_CONFIG_DIR")
        if profile:
            return Path(profile).expanduser().resolve() / ".claude.json"
        user_profile = self.env.get("USERPROFILE")
        base = Path(user_profile).expanduser() if user_profile else Path.home()
        return (base / ".claude.json").resolve()

    def _read_entry(self, host: str) -> Mapping[str, object] | None:
        path = self._config_path(host)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            if host == "codex":
                config = tomllib.loads(raw)
                entries = config.get("mcp_servers", {})
            else:
                config = json.loads(raw)
                entries = config.get("mcpServers", {})
            if not isinstance(entries, dict):
                raise ValueError("MCP server collection is not an object")
            if SERVER_NAME not in entries:
                return None
            entry = entries[SERVER_NAME]
            if not isinstance(entry, dict):
                raise ValueError("BIO CE MCP entry is not an object")
            return entry
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            raise MCPConnectionError(
                f"{host} MCP configuration is unreadable; BIO CE left it unchanged."
            ) from exc

    def _entry_matches(self, entry: Mapping[str, object], connection_id: str | None) -> bool:
        try:
            command, args = self._mcp_server_command(connection_id)
        except MCPConnectionError:
            return False
        actual_command = entry.get("command")
        actual_args = entry.get("args", ())
        return (
            isinstance(actual_command, str)
            and os.path.normcase(os.path.normpath(actual_command))
            == os.path.normcase(os.path.normpath(command))
            and isinstance(actual_args, list)
            and tuple(str(value) for value in actual_args) == tuple(args)
        )

    def _matches_legacy_server(self, entry: Mapping[str, object]) -> bool:
        """A v0.2 entry: same server and database, but no connection or token."""
        return self._entry_matches(entry, None)

    @staticmethod
    def _entry_token(entry: Mapping[str, object] | None) -> str:
        env = entry.get("env") if isinstance(entry, Mapping) else None
        value = env.get(TOKEN_ENVIRONMENT_VARIABLE) if isinstance(env, Mapping) else None
        return value if isinstance(value, str) else ""

    def _grant_for_entry(self, host: str, entry: Mapping[str, object]) -> Grant | None:
        """The active grant this host entry authenticates as, if it is a current BIO CE entry."""
        args = entry.get("args")
        if not isinstance(args, list) or "--connection" not in args:
            return None
        index = args.index("--connection")
        if index + 1 >= len(args):
            return None
        connection_id = str(args[index + 1])
        if not self._entry_matches(entry, connection_id):
            return None
        try:
            grant = self.control.authenticate(connection_id, self._entry_token(entry))
        except AccessDenied:
            return None
        return grant if grant.host == host else None

    def _backup_config(self, host: str, config_path: Path) -> Path | None:
        if not config_path.is_file():
            return None
        backup_root = self.local_data_root / "connections" / "backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = backup_root / f"{host}-mcp-config-{timestamp}-{uuid.uuid4().hex[:8]}.backup"
        try:
            shutil.copy2(config_path, destination)
        except OSError as exc:
            raise MCPConnectionError(
                "BIO CE could not back up the host MCP configuration; no host change was attempted."
            ) from exc
        return destination

    def _rollback_added(self, host: str, backup_file: Path | None) -> None:
        config_path = self._config_path(host)
        after_hash = _file_digest(config_path)
        try:
            self._run_cli(host, self._remove_arguments(host))
            if self._read_entry(host) is None:
                return
        except MCPConnectionError:
            pass
        # Restore only when the config is byte-for-byte unchanged since our add.
        # If another process changed it, keep the backup and refuse to overwrite.
        if after_hash is None or _file_digest(config_path) != after_hash:
            raise MCPConnectionError(
                "Automatic rollback could not be verified. The MCP configuration backup was retained."
            )
        try:
            if backup_file is None:
                config_path.unlink(missing_ok=True)
            else:
                temporary = config_path.with_name(f"{config_path.name}.{uuid.uuid4().hex}.restore")
                shutil.copy2(backup_file, temporary)
                os.replace(temporary, config_path)
            if self._read_entry(host) is not None:
                raise MCPConnectionError("BIO CE host entry remains after rollback.")
        except (OSError, MCPConnectionError) as exc:
            raise MCPConnectionError(
                "Automatic rollback failed. The MCP configuration backup was retained."
            ) from exc

    def _verify_local_sdk(
        self,
        database: Path,
        scope: MemoryScope,
        command: str,
        args: Sequence[str],
        env: Mapping[str, str] | None = None,
    ) -> None:
        try:
            from mcp import Client, StdioServerParameters, stdio_client
        except ImportError as exc:
            raise MCPConnectionError("The official Python MCP SDK is unavailable.") from exc

        store = SQLiteMemoryStore(database, read_only=True)
        try:
            sample = store.list_current(scope, limit=1)
        finally:
            store.close()

        stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        parameters = StdioServerParameters(command=command, args=list(args), env=dict(env) if env else None)

        async def exercise() -> None:
            async with Client(stdio_client(parameters, errlog=stderr)) as client:
                discovered = await asyncio.wait_for(client.list_tools(), timeout=15)
                if {tool.name for tool in discovered.tools} != _EXPECTED_TOOLS:
                    raise MCPConnectionError("The MCP tool set does not match this BIO CE version.")
                search = await asyncio.wait_for(
                    client.call_tool(
                        "bio_memory_search",
                        {
                            "project": scope.project,
                            "namespace": scope.namespace,
                            "query": "bioce-connection-probe-7d8f4a",
                            "limit": 1,
                        },
                    ),
                    timeout=15,
                )
                data = search.structured_content
                if search.is_error or not isinstance(data, dict):
                    raise MCPConnectionError("The MCP search probe failed.")
                if data.get("project") != scope.project or data.get("namespace") != scope.namespace:
                    raise MCPConnectionError("The MCP search probe returned an unexpected scope.")
                if sample:
                    record = sample[0]
                    read = await asyncio.wait_for(
                        client.call_tool(
                            "bio_memory_read",
                            {
                                "project": scope.project,
                                "namespace": scope.namespace,
                                "memory_id": record.memory_id,
                                "revision_id": record.revision_id,
                            },
                        ),
                        timeout=15,
                    )
                    read_data = read.structured_content
                    if (
                        read.is_error
                        or not isinstance(read_data, dict)
                        or read_data.get("memory_id") != record.memory_id
                        or read_data.get("revision_id") != record.revision_id
                    ):
                        raise MCPConnectionError("The MCP read probe did not match the selected revision.")
                else:
                    missing = await asyncio.wait_for(
                        client.call_tool(
                            "bio_memory_read",
                            {
                                "project": scope.project,
                                "namespace": scope.namespace,
                                "memory_id": "mem_bio_ce_connectprobe_0001",
                            },
                        ),
                        timeout=15,
                    )
                    if not missing.is_error:
                        raise MCPConnectionError("The MCP read probe did not fail closed for an absent ID.")

        try:
            asyncio.run(asyncio.wait_for(exercise(), timeout=40))
        finally:
            stderr.close()


def host_name_for(host: str) -> str:
    return {"codex": "Codex CLI", "claude": "Claude Code"}.get(host, host)


def _validate_host(host: str) -> str:
    if host not in {"codex", "claude"}:
        raise ValueError("host must be codex or claude")
    return host


def _file_digest(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


__all__ = [
    "AUTO_MEMORY_SUPPORT",
    "AutoMemorySupport",
    "ConnectionResult",
    "DiagnosticCheck",
    "HostStatus",
    "MCPConnectionConflict",
    "MCPConnectionConsentRequired",
    "MCPConnectionError",
    "MCPConnectionManager",
    "SERVER_NAME",
    "auto_memory_support",
]
