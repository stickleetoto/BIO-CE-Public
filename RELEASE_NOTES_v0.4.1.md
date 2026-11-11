<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.4.1-rc1 — Release Notes (candidate)

**Status: pre-release.** Not a final release.

## Download

| File | Size | SHA-256 |
|---|---:|---|
| `BIO-CE-Setup-v0.4.1-rc1.exe` | 40,877,765 bytes | `a3cccbfc47634f8de1e62094515fc278fa6532729d4c235aa9368b7bb34681b3` |

Built and tested on a GitHub-hosted Windows runner (GitHub Actions run 43010601697) from source commit
`89a8ba5d583222d20524136de70f690e0d3925bc`, with CPython 3.12.10, PyInstaller 6.22.3, and Inno Setup 6.7.3. The
tag also contains a later commit that changes only this file and `docs/known-limitations.md`; neither goes into
the installer.

```powershell
Get-FileHash -Algorithm SHA256 .\BIO-CE-Setup-v0.4.1-rc1.exe
```

### The installer is not code-signed

Neither the installer nor the programs it installs carry a digital signature, and Windows SmartScreen may warn
about a downloaded copy. Run it only if the SHA-256 above matches exactly. BIO CE never asks you to turn off
SmartScreen, Microsoft Defender, or any other protection.

## Updating

- **From v0.4.0-rc1:** run the v0.4.1-rc1 installer over the existing installation; your memories, settings,
  and AI connections are kept. Close Codex and Claude Code before you install.
- **After updating, start new conversations in Codex and Claude Code.** Setup closes the BIO CE MCP servers that
  AI hosts are running so it can replace them, and Codex does not start BIO CE again inside a conversation that
  was open during the update: memory tools fail there until you start a new conversation. The last page of the
  installer says so too.

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

## Verified for this candidate

- On the GitHub-hosted runner, for this exact installer: the automated test suite (222 passed; 3 skipped for
  tools the runner does not have); the release payload check (every file against the build manifest, no test
  code, no credentials, build-machine identity, or private identifiers, license notices); an unattended clean
  install, first launch, installed MCP server and hook, and uninstall; and an upgrade from the published
  v0.4.0-rc1 that keeps every memory, review item, connection, and backup, **including an upgrade while an AI host
  still runs the previous MCP server** (Setup closes it and replaces every file).
- Codex 0.166 (command-line tool) and the Codex desktop app's bundled 0.167 app-server, with a scripted local
  model: the code-mode option shows BIO CE's tools; an idle server keeps answering in the same conversation and
  releases the database while idle; the memory skill is offered to the model from the skills folder.
- One real-model Codex session with and without the memory skill: with it, the model searched first, saved the
  decisions the user stated, and did not save progress status or guesses; without it, the model did not use
  BIO CE. (One run each; not a statistical result.)
- By hand on the developer's PC with this installer: upgrading while a Codex conversation was open (Setup asked to
  close BIO CE), the finish-page note, the Connections page, the connect and disconnect check boxes, the skill
  preview, the uninstall warning (its default button cancels), and reinstalling into the same folder.

## Not verified

- **A Windows PC without Python or Git.**
- Claude Code and Codex registration from the installed app on the hosted runner (no CLI there); it was verified
  on the developer's PC.
- Whether real AI models use BIO CE on their own over many sessions.
- Real 125%/150% display scaling, Windows 10, and screen readers.

## Known limitations

See `docs/known-limitations.md` (v0.4.1 section). In short: idle servers stay until their conversation closes,
an upgrade ends open conversations' access to BIO CE, BIO CE cannot check the Codex desktop app's bundled version, the skill's effect on real models
is not evaluated at scale, the installer and programs are not code-signed, and a PC without Python has not been
tested.
