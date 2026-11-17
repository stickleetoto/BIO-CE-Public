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
    # storage/backup.py
    ("The selected database file does not exist.", "svc.backup.missing"),
    ("The selected file is corrupt or has an unsupported BIO CE schema.", "svc.backup.corrupt"),
    ("The backup destination must differ from the active database.", "svc.backup.same_as_active"),
    ("The backup destination already exists; choose a new filename.", "svc.backup.exists"),
    ("The selected file still has unsaved SQLite changes in a -wal file. Choose a backup created by BIO CE.",
     "svc.backup.wal"),
    ("The selected database could not be validated.", "svc.backup.not_validated"),
    ("BIO CE could not create a safe no-overwrite backup at this location.", "svc.backup.unsafe_location"),
    ("BIO CE could not finalize the connection records snapshot.", "svc.backup.control_finalize"),
    ("BIO CE could not verify the connection records snapshot.", "svc.backup.control_verify"),
    ("BIO CE could not create the connection records snapshot.", "svc.backup.control_create"),
    ("BIO CE could not finalize the SQLite snapshot.", "svc.backup.sqlite_finalize"),
    ("BIO CE could not create the SQLite snapshot.", "svc.backup.sqlite_create"),
    ("The selected backup could not be checked.", "svc.backup.not_checked"),
    ("The selected database could not be opened read-only.", "svc.backup.not_opened"),
    # storage/sqlite_store.py, core/models.py (what a user action can cause)
    ("database is in use; close connected readers and retry", "svc.store.in_use"),
    ("memory is unavailable in the requested scope", "svc.store.unavailable"),
    ("expected revision is stale", "svc.store.stale"),
    ("memory store is closed", "svc.store.closed"),
    ("read-only database does not exist", "svc.store.readonly_missing"),
    ("database schema {version} is not supported", "svc.store.schema"),
    ("read-only database does not contain a supported BIO CE schema", "svc.store.readonly_schema"),
    ("memory is not retracted", "svc.store.not_retracted"),
    ("memory changed during read; retry the request", "svc.store.changed"),
    ("query must be text of at most 8192 characters", "svc.store.query"),
    ("memory store was opened read-only", "svc.store.readonly"),
    ("{field} must not be empty", "svc.model.empty"),
    ("{field} exceeds {limit} characters", "svc.model.too_long"),
    ("{field} contains a control character", "svc.model.control_character"),
    ("{field} must not have leading or trailing whitespace", "svc.model.whitespace"),
    # importer.py
    ("BIO CE couldn't read this file's text encoding. Save it as UTF-8 and try again.", "svc.import.encoding"),
    ("Choose a .md or .txt file.", "svc.import.file_type"),
    ("This file is larger than 5 MB. Split it and import the parts one by one.", "svc.import.too_large"),
    ("This has {count} entries; BIO CE imports at most {limit} at once. Split it and import the parts one by one.",
     "svc.import.too_many"),
    ("unknown destination space", "svc.import.unknown_space"),
    ("Use a date such as 2025-03-14 or 2025-03.", "svc.import.date"),
    ("Nothing is selected to import.", "svc.import.nothing_selected"),
    ("Choose a destination space for every selected entry first.", "svc.import.choose_destination"),
    ("This import was already undone.", "svc.import.already_undone"),
    ("The preview was cancelled.", "svc.import.cancelled"),
    ("the same entry appears earlier in this import", "svc.import.repeated"),
    ("the entry has no text", "svc.import.empty"),
    ("secrets are never stored ({kinds})", "svc.import.secret"),
    ("this reads like an instruction to an AI; rewrite it as your preference", "svc.import.instruction"),
    ("at most {limit} characters (title and text together); shorten it in the preview", "svc.import.too_long"),
    ("contains a local path, which can identify you or your PC", "svc.import.local_path"),
    ("BIO CE already has this in the destination space", "svc.import.exists"),
    ("imported text may differ from an existing memory; you review it, nothing is overwritten",
     "svc.import.may_differ"),
    ("Imported text may differ from this memory. Nothing was overwritten.", "svc.import.review_differs"),
    ("Contains a local path, which can identify you or your PC.", "svc.import.review_path"),
    # curation.py
    ("These items changed since BIO CE suggested this. Nothing was changed.", "svc.cur.changed"),
    ("Title and text can't be empty.", "svc.cur.empty"),
    ("This suggestion isn't an approved one, so there is nothing to undo.", "svc.cur.not_approved"),
    ("The space of this suggestion is gone. Nothing was changed.", "svc.cur.space_gone"),
    ("This was changed after the suggestion was approved, so BIO CE won't undo it. Nothing was changed. Use History "
     "to see what it said before.", "svc.cur.changed_after"),
    ("That suggestion was already handled.", "svc.cur.handled"),
    ("BIO CE no longer has the items this suggestion used (it was approved by an earlier version, which deleted "
     "them). Nothing was changed.", "svc.cur.items_gone"),
    ("Your memories already have this (“{title}”). Discard the inbox item instead.", "svc.cur.duplicate"),
    ("the same thing was saved on different days", "svc.cur.reason_days"),
    ("these items say nearly the same", "svc.cur.reason_same"),
    ("it may add to or change a memory you have", "svc.cur.reason_adds"),
    ("your AI hosts used it again and again", "svc.cur.reason_used"),
    # memory_policy.py
    ("user-stated durable information", "svc.policy.user_stated"),
    ("collected in the inbox (marked as a guess)", "svc.policy.inbox_guess"),
    ("collected in the inbox", "svc.policy.inbox"),
    ("collected in the inbox{note}", "svc.policy.inbox_more"),
    ("user correction", "svc.policy.user_correction"),
    ("user refinement", "svc.policy.user_refinement"),
    ("user conflict", "svc.policy.user_conflict"),
    ("user {change}", "svc.policy.user_change"),
    ("category must be one of: {choices}", "svc.policy.category"),
    ("a correction should update the memory it corrects; it was kept for the user to review because no matching "
     "memory was given", "svc.policy.correction_no_target"),
    ("not stated or confirmed by the user with high confidence", "svc.policy.not_confirmed"),
    ("mentions credentials or sensitive identifiers", "svc.policy.credentials"),
    ("secrets and sensitive identifiers are never stored ({kinds})", "svc.policy.secret"),
    ("evidence must be one of: {choices}", "svc.policy.evidence"),
    ("confidence must be one of: {choices}", "svc.policy.confidence"),
    ("tool output is not stored; the user must state or confirm it", "svc.policy.tool_output"),
    ("text from a file or page is collected only when the user asked for it; say so in reason",
     "svc.policy.file_text"),
    ("the text contains instructions aimed at an AI assistant", "svc.policy.instructions"),
    ("low-confidence guesses are not stored", "svc.policy.low_confidence"),
    ("too short or trivial to be a lasting memory", "svc.policy.trivial"),
    ("a question is not a lasting fact; store the answer the user confirmed instead", "svc.policy.question"),
    ("change_type must be one of: {choices}", "svc.policy.change_type"),
    ("the memory already says this", "svc.policy.same"),
    ("conflicting information is never overwritten automatically", "svc.policy.conflict"),
    ("changes need a high-confidence statement or confirmation from the user", "svc.policy.change_needs"),
    ("content from documents, web pages, or tool output is not stored automatically; the user must state or confirm "
     "it", "svc.policy.documents"),
    ("text taken from a file or page can be at most {limit} characters (title and content together); summarize the "
     "part the user asked for and save again", "svc.policy.file_too_long"),
    ("an equivalent memory already exists; update it instead if the user changed something",
     "svc.policy.duplicate_update"),
    ("an equivalent memory already exists", "svc.policy.duplicate"),
    # exporter.py
    ("Choose at least one space.", "svc.export.space"),
    ("A chosen space no longer exists.", "svc.export.space_gone"),
    ("Personal is included only when it is on and you tick it.", "svc.export.personal"),
    ("Choose at least one source.", "svc.export.source"),
    ("A file with this name already exists. Choose a new name; BIO CE never overwrites files.",
     "svc.export.file_exists"),
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
