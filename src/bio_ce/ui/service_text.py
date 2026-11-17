# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Service messages in the app's language (v0.4.4 U5).

The services (store, control file, importer, connections, policy) explain refusals and failures in English, and
the MCP server passes those texts to AI tools, which must keep reading English. The screens show some of them
(``str(exc)``, a policy or importer reason). ``say(text)`` gives such a text in the app's language: in English the
text itself; in Korean the translation of the template it matches, with its values filled in. A text no template
matches is shown as it is. ``tests/unit/test_service_text.py`` checks that every message a screen can show has a
template (or is listed as never shown).

Decision (2026-11-17, logged): the screen side translates, instead of reason codes in every service, so the
services and the MCP replies stay as they are.
"""

from __future__ import annotations

import re

from bio_ce.ui.i18n import language, t

# (English template with {name} placeholders, text key). The English template is the service text exactly.
# The first template that matches wins, so a narrower one comes before a wider one that would also match it.
TEMPLATES: tuple[tuple[str, str], ...] = (
    # connections.py
    ("Host registration requires explicit user approval.", "svc.conn.register_approval"),
    ("{host} CLI is not installed.", "svc.conn.cli_missing"),
    ("The host did not save the expected BIO CE MCP configuration.", "svc.conn.not_saved"),
    ("Reconnect this host in BIO CE first; only connections made by this version can change modes.",
     "svc.conn.reconnect_for_modes"),
    ("Connect this host in BIO CE first.", "svc.conn.connect_first"),
    ("Installing host hooks requires explicit user approval.", "svc.conn.hooks_approval"),
    ("Connect this host first; hooks use the same BIO CE connection.", "svc.conn.hooks_connect_first"),
    ("Removing host hooks requires explicit user approval.", "svc.conn.hooks_remove_approval"),
    ("Host removal requires explicit user approval.", "svc.conn.remove_approval"),
    ("The configured bio-ce entry does not match BIO CE; it was left untouched.", "svc.conn.entry_mismatch"),
    ("BIO CE revoked this connection but could not remove its host entry. The configuration backup was retained.",
     "svc.conn.revoked_entry_left"),
    ("The Claude desktop app is not installed for this Windows user.", "svc.conn.desktop_missing"),
    ("Open the Claude desktop app once so it creates its settings, then connect.", "svc.conn.desktop_open_once"),
    ("The Claude desktop settings changed meanwhile; BIO CE kept its backup and did not overwrite them.",
     "svc.conn.desktop_changed"),
    ("BIO CE revoked this connection but could not remove its entry. The settings backup was kept.",
     "svc.conn.revoked_desktop_left"),
    ("Installing the memory skill requires explicit user approval.", "svc.conn.skill_approval"),
    ("Connect this host first; the skill uses its BIO CE connection.", "svc.conn.skill_connect_first"),
    ("Removing the memory skill requires explicit user approval.", "svc.conn.skill_remove_approval"),
    ("Changing Codex settings requires explicit user approval.", "svc.conn.codex_approval"),
    ("Connect Codex in BIO CE first.", "svc.conn.codex_connect_first"),
    ("BIO CE could not confirm that Codex's settings were restored. A copy is in {path}.",
     "svc.conn.codex_restore_copy"),
    ("BIO CE could not confirm that Codex's settings were restored.", "svc.conn.codex_restore"),
    ("BIO CE could not confirm that Codex's settings were restored.{more}", "svc.conn.codex_restore_more"),
    ("The packaged MCP/BIO-CE-MCP.exe is missing beside the desktop app.", "svc.conn.mcp_exe_missing"),
    ("{host} CLI is not installed or cannot be launched safely.", "svc.conn.cli_unsafe"),
    ("Automatic rollback could not be verified. The MCP configuration backup was retained.",
     "svc.conn.rollback_unverified"),
    ("BIO CE personal database is not ready for a read-only connection.", "svc.conn.database_not_ready"),
    ("The server name bio-ce is already used by a different MCP configuration.", "svc.conn.name_taken"),
    ("BIO CE could not replace its earlier read-only host entry.", "svc.conn.replace_failed"),
    ("BIO CE MCP verification failed; the host registration was rolled back.", "svc.conn.verify_rolled_back"),
    ("BIO CE could not update {host}'s tool approvals in {file}; it was left unchanged.",
     "svc.conn.approvals_failed"),
    ("BIO CE could not update {file}; it was left unchanged.", "svc.conn.update_failed"),
    ("The Claude desktop settings file can't be read as JSON; BIO CE left it unchanged.",
     "svc.conn.desktop_not_json"),
    ("The Claude desktop settings did not keep the expected entry.", "svc.conn.desktop_entry_lost"),
    ("BIO CE MCP verification failed; the Claude desktop settings were put back.",
     "svc.conn.desktop_verify_restored"),
    ("BIO CE revoked this connection, but the Claude desktop settings file can't be read, so its entry was left in "
     "place.", "svc.conn.revoked_desktop_unreadable"),
    ("The configured BIO CE MCP server did not pass local SDK verification.", "svc.conn.sdk_verify_failed"),
    ("Windows PowerShell is required to run the Codex CLI wrapper.", "svc.conn.powershell_needed"),
    ("{host} MCP command could not be completed.", "svc.conn.mcp_command_failed"),
    ("MCP server collection is not an object", "svc.conn.collection_not_object"),
    ("BIO CE MCP entry is not an object", "svc.conn.entry_not_object"),
    ("{host} MCP configuration is unreadable; BIO CE left it unchanged.", "svc.conn.config_unreadable"),
    ("BIO CE could not back up the host MCP configuration; no host change was attempted.",
     "svc.conn.backup_failed"),
    ("BIO CE host entry remains after rollback.", "svc.conn.entry_remains"),
    ("Automatic rollback failed. The MCP configuration backup was retained.", "svc.conn.rollback_failed"),
    ("The official Python MCP SDK is unavailable.", "svc.conn.sdk_missing"),
    ("The MCP tool set does not match this BIO CE version.", "svc.conn.tools_mismatch"),
    ("The MCP search probe failed.", "svc.conn.search_probe_failed"),
    ("The MCP search probe returned an unexpected scope.", "svc.conn.search_probe_scope"),
    ("The MCP read probe did not match the selected revision.", "svc.conn.read_probe_revision"),
    ("The MCP read probe did not fail closed for an absent ID.", "svc.conn.read_probe_absent"),
    # claude_desktop.py, codex_options.py
    ("The Claude desktop settings file is not a JSON object", "svc.desktop_file.not_object"),
    ("mcpServers in the Claude desktop settings file is not an object", "svc.desktop_file.servers_not_object"),
    ("The Claude desktop settings file is not valid JSON", "svc.desktop_file.not_json"),
    ("the bio-ce entry is {state}", "svc.codex.entry_state"),
    ("the bio-ce table header was not found exactly once", "svc.codex.header"),
    ("adding the option would change other settings", "svc.codex.other_settings"),
    # control_store.py
    ("Give the space a name.", "svc.ctrl.space_name"),
    ("Space names can be at most 80 characters.", "svc.ctrl.space_name_long"),
    ("BIO CE control database has an unsupported version.", "svc.ctrl.version"),
    ("This BIO CE connection is unknown. Reconnect the host in BIO CE.", "svc.ctrl.unknown_connection"),
    ("BIO CE rejected this connection's credentials.", "svc.ctrl.credentials_rejected"),
    ("Access for this connection was revoked in BIO CE.", "svc.ctrl.revoked"),
    ("That connection no longer exists or was revoked.", "svc.ctrl.connection_gone"),
    ("That review item no longer exists.", "svc.ctrl.review_gone"),
    ("That review item was already handled.", "svc.ctrl.review_handled"),
    ("That space no longer exists.", "svc.ctrl.space_gone"),
    ("Personal is a built-in space. Choose another name.", "svc.ctrl.personal_builtin"),
    ("General can't be renamed.", "svc.ctrl.general_rename"),
    ("General can't be archived.", "svc.ctrl.general_archive"),
    ("Archived spaces can't get new folders.", "svc.ctrl.archived_folders"),
    ("the number of automatic backups to keep is from {low} to {high}", "svc.ctrl.backup_keep_range"),
    ("Personal write access needs read access", "svc.ctrl.write_needs_read"),
    ("Turn on Personal in Settings → Spaces first.", "svc.ctrl.personal_off"),
    ("{setting} must be between {low} and {high}", "svc.ctrl.setting_range"),
    ("That clean-up item was already handled.", "svc.ctrl.cleanup_handled"),
    ("That import no longer exists.", "svc.ctrl.import_gone"),
    ("That suggestion no longer exists.", "svc.ctrl.suggestion_gone"),
    ("A space with this name already exists. Choose another name.", "svc.ctrl.space_exists"),
    # auto_memory.py, desktop.py, switching.py, engines
    ("Too many automatic memory changes in the last hour; BIO CE paused writes for now.", "svc.auto.rate_limit"),
    ("Only a proposed change can be added as a new memory.", "svc.auto.only_proposed"),
    ("This text contains a password, token, or key, so BIO CE won't store it.", "svc.secret_refused"),
    ("That review item was already handled. Nothing was changed.", "svc.auto.review_handled"),
    ("The memory changed after this request was made. Nothing was changed.", "svc.auto.memory_changed"),
    ("retraction always needs the user's approval", "svc.auto.retract_needs_approval"),
    ("BIO CE settings have an unsupported format", "svc.desktop.settings_format"),
    ("Windows LOCALAPPDATA is not available", "svc.desktop.no_localappdata"),
    ("BIO CE settings could not be read", "svc.desktop.settings_unreadable"),
    ("BIO CE privacy setting could not be saved", "svc.desktop.privacy_not_saved"),
    ("The active database cannot be restored from itself.", "svc.desktop.restore_self"),
    ("This request belongs to an engine connection that is no longer active. Nothing was changed.",
     "svc.switch.inactive"),
    ("BIO CE access for this connection is unavailable.", "svc.engine.access_unavailable"),
    ("The {engine} engine does not offer {capability} through BIO CE.", "svc.engine.unsupported_capability"),
    ("the engine answer has no {field} list", "svc.ext.no_list"),
    ("the engine description is not valid protocol v1 data", "svc.ext.bad_description"),
    ("The engine is not connected.", "svc.ext.not_connected"),
    ("the binding is for a different engine", "svc.ext.other_engine"),
    ("the engine did not return a session", "svc.ext.no_session"),
    ("Not installed.", "svc.ext.not_installed"),
    ("the engine answer is not an object", "svc.ext.not_object"),
    ("the engine reported an error", "svc.ext.error"),
    ("This host session was closed.", "svc.ext.session_closed"),
    ("the engine returned invalid context", "svc.ext.bad_context"),
    ("the engine returned an unknown proposal status", "svc.ext.bad_proposal"),
    ("the engine reported a saved memory without its revision", "svc.ext.no_revision"),
    ("The engine is not running or did not answer.", "svc.ext.not_running"),
    ("The engine refused this connection.", "svc.ext.refused"),
    ("the engine does not support this operation", "svc.ext.unsupported"),
    ("the engine returned an invalid memory", "svc.ext.bad_memory"),
    ("the engine returned an invalid search result", "svc.ext.bad_search"),
)

_compiled: list[tuple[re.Pattern[str], str]] | None = None


def _pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{\w+\})", template)
    regex = "".join(f"(?P<{part[1:-1]}>.+?)" if re.fullmatch(r"\{\w+\}", part) else re.escape(part)
                    for part in parts)
    return re.compile(regex + r"\Z", re.DOTALL)


def _templates() -> list[tuple[re.Pattern[str], str]]:
    global _compiled
    if _compiled is None:
        _compiled = [(_pattern(template), key) for template, key in TEMPLATES]
    return _compiled


def translate(text: str) -> str | None:
    """The text in the app's language when a template matches it, else None."""
    for pattern, key in _templates():
        match = pattern.match(text)
        if match:
            return t(key, **match.groupdict())
    return None


def say(text: object) -> str:
    """A service message (or exception) as the screens show it: in the app's language where BIO CE knows it."""
    value = str(text)
    if language() == "en" or not value:
        return value
    whole = translate(value.strip())
    if whole is not None:
        return whole
    # Messages joined by the screens ("reason; reason") or followed by a second sentence the service added.
    pieces = [translate(piece.strip()) or piece.strip() for piece in value.split("; ")]
    return "; ".join(pieces)
