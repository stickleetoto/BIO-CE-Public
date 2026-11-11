<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.4.1-rc1 — Release Notes (candidate)

**Status: candidate, not published.**

## Fixed

- **Idle MCP servers no longer hold the database.** The Codex desktop app keeps one BIO CE server per conversation
  open. After 60 seconds without a request, a server now closes its database connections (the next request opens
  them again), so a restore in the app is no longer blocked by a connected but idle AI tool. A server also ends
  when the program that started it ends.
- **Upgrading with a connected AI tool.** Setup closes running BIO CE MCP servers before it replaces them (it asks
  first; a silent install closes them and logs it), so no stale program file is left behind.

## Added

- **Codex code mode.** When you connect Codex 0.166 or later, BIO CE adds Codex's official
  `omit_tools_from = ["code_mode"]` option to its own entry, so Codex's standard models see BIO CE's tools and
  instructions. Your settings are backed up first, the result is checked with Codex, and the previous file is
  restored if Codex rejects it. Connections made earlier can apply it from the Connections page.
- **Memory skill.** Connect can install a short skill for Claude Code and Codex that tells the AI when to search
  BIO CE and what to save: decisions and their reasons, rejected options, project rules, and lasting preferences;
  never secrets, personal information, progress status, or guesses. You can preview it, and BIO CE never replaces
  or removes a copy you edited without asking.
- **Uninstall warning.** If Codex or Claude Code still start this installation, the uninstaller says so and offers
  to cancel so you can disconnect first.
- **One version everywhere.** The app, the About section, the MCP server information, and the memory skill show
  the same version string as the installer.

## Changed

- Codex is shown as **Codex (CLI · desktop app)**: both use the same settings, so one connection covers both.
  Claude Code's card says that the Claude desktop chat app is not supported.
- The Connections page says that you can close the BIO CE app: connected AI tools keep using your memories.
- The Codex note no longer refers to a specific Codex version as unfixed.

## Unchanged

- Memory database, settings, and connection data formats. Existing connections keep working without
  reconnecting.

## Known limitations

See `docs/known-limitations.md` (v0.4.1 section). In short: idle servers stay until their conversation closes,
an upgrade ends open conversations' access to BIO CE, BIO CE cannot check the Codex desktop app's bundled version, the skill's effect on real models
is not evaluated at scale, the installer and programs are not code-signed, and a PC without Python has not been
tested.
