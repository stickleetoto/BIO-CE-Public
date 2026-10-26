<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE Desktop Security Boundaries

## Data handling

- The first-run notice is shown before BIO CE creates the personal database.
- A memory is persisted by an explicit desktop Save action, or (v0.3, opt-in per host) by a connected AI host in Auto memory mode under the server-side policy in [Auto Memory](auto-memory.md). BIO CE never records or ingests conversations, never reads host transcript files, and makes no model calls.
- Personal memory and synthetic demo files use separate paths and separate SQLite stores.
- SQLite memory data is local and unencrypted at rest. Backups and MCP host-config backups are plain files; protect them with the Windows account and filesystem permissions.
- Retraction appends a tombstone and blocks application read/search. Old revision rows remain in SQLite, so retraction is not secure erase.
- Backup restore validates SQLite integrity and the expected schema before staging replacement. Restore refuses an invalid backup and detects known active-reader/WAL conflicts; it is not a transactional multi-process database migration service.

## MCP boundary

The local MCP process reads through a SQLite `mode=ro` + `query_only` connection. It registers six tools: `bio_memory_search`, `bio_memory_read`, `bio_memory_history`, and (v0.3) `bio_memory_create`, `bio_memory_update`, `bio_memory_retract`. It is bound to one project/namespace pair: a desktop-app connection takes it from the connection's grant and refuses a different pair in its launch arguments; a server without a connection takes it from its launch arguments. Tool calls may omit the pair and are refused if they name another one. The desktop connection UI asks before it modifies each host's configuration and uses official host CLI add/remove commands.

Since v0.3 each connection made by the desktop app has its own connection ID and random token (passed to the server in `BIO_CE_CONNECTION_TOKEN`; only its SHA-256 is stored in `control.sqlite3`). The server authenticates at startup and re-reads the connection's grant on every call: **Read only** (default) allows search/read/history, **Auto memory** also allows policy-checked writes, **Paused** allows nothing, and a disconnected (revoked) connection is refused. Writes open a short-lived writable connection for one atomic, revision-checked transaction. Secrets, content declared as coming from documents or tools, and text with injected instructions are refused; uncertain or conflicting changes and every retraction go to the user's review queue. v0.2 entries without a connection ID stay read-only.

Project and namespace strings are routing, not authentication, and never widen what a connection can reach. The token protects against an AI host doing more through BIO CE's tools than the user allowed; it is not a defense against other programs running as the same Windows user, which can read the host configuration and the SQLite files directly. There is no HTTP listener, remote sharing, or key management.

BIO CE never calls an AI model. Once a host is connected, however, whatever the host reads or writes through
BIO CE's tools or hooks becomes part of that host's conversation and may be sent to the
host's model provider (for example OpenAI for Codex CLI or Anthropic for Claude Code) under that provider's
terms. The first-run notice, the Connections page, and every Connect confirmation state this before a host
is registered.

With session hooks installed (v0.3), the host runs `BIO-CE-MCP.exe hook` at session start and on each prompt. The hook uses the prompt only to look up related memories; it never stores, logs, or forwards it, and prints nothing for a paused or revoked connection. Turning on Auto memory also lets the host run BIO CE's own six tools without asking each time (Codex `approval_mode`, Claude Code `permissions.allow`); other tools keep the user's settings, and the change is undone when Auto memory is turned off or the host is disconnected.

Before changing a host config, BIO CE writes a local backup. A backup may include secrets or environment values belonging to other MCP servers. BIO CE does not print the CLI's stdout/stderr into the GUI or tests, but the backup remains unencrypted and must be handled as sensitive. On failed SDK verification, it attempts to remove only its matching `bio-ce` entry; if the config changed concurrently it refuses to overwrite the new config and retains the backup.

## Freshness and concurrency

The SQLite store checks the selected revision again in a final fresh transaction. A revision change or retraction committed before that check fails closed. The final check's first SELECT is the read linearization point; a commit after it is ordered after the read, even if the response is delivered later. Strict instant revocation is not claimed.

## Installer boundary

The installer is built with Inno Setup and runs `asInvoker` with `PrivilegesRequired=lowest`: it never
requests elevation and writes only per-user locations: program files under
`%LOCALAPPDATA%\Programs\BIO-CE` (or the folder the user picks), a Start menu shortcut, an optional desktop
shortcut, and an `HKCU` uninstall entry. No PowerShell script, execution-policy change, service, scheduled
task, or machine-wide setting is involved. Setup refuses a program folder that overlaps
`%LOCALAPPDATA%\BIO-CE`, and updates replace the frozen runtime folders wholesale so no stale DLL survives.

Memory data remains under `%LOCALAPPDATA%\BIO-CE`. Uninstall keeps memories, settings, and configuration
backups unless the user answers **Yes** to a separate prompt whose default is **No**; silent uninstall
always keeps them. Host MCP entries are left untouched by uninstall; disconnect each host from the app
before removal.

The GUI (`BIO-CE.exe`) and the MCP server (`MCP\BIO-CE-MCP.exe`) are separate PyInstaller programs; the MCP
server speaks only stdio and is started by the host, never by the installer. Neither program writes a log
file. Host CLI output is captured and discarded. Inno Setup writes its own install log to `%TEMP%`; it
contains file paths, not memory content.

## Signing and Windows security

RC1 is **not code-signed**. Windows SmartScreen may show an unknown-publisher warning for a downloaded
installer, and Microsoft Defender scans it like any other program. BIO CE does not ask users to disable or
bypass SmartScreen, Defender, User Account Control, or any other Windows protection; verify the published
SHA-256 instead. To start the npm-installed Codex CLI wrapper (`codex.ps1`) the Connections page runs
Windows PowerShell with `-ExecutionPolicy Bypass` for that single child process only. It does not change
the user or machine execution policy.

RC1 has no auto-update, telemetry, encryption at rest, or production incident/backup service. The test
report distinguishes source tests, synthetic host CLI/SDK checks, actual model calls, and clean-machine
install evidence. It does not treat a synthetic fixture or SDK client as proof that an AI model called a
tool.
