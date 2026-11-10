<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.4.0-rc1 — Release Notes (candidate)

**Status: candidate, not published.** Nothing below is a release until the owner approves the remaining gates
(see "Not verified" and the release checklist). `v0.3.0-rc1` stays published as it is.

## Download (candidate build)

| File | Size | SHA-256 |
|---|---:|---|
| `BIO-CE-Setup-v0.4.0-rc1.exe` | 40,803,029 bytes | `fd5ca6e21d5fb44d1aee8505a2c7f92e2d332ba39c59015c095e878b3b044e09` |

Built on a GitHub-hosted Windows runner with the official `packaging/build_windows.ps1`: CPython 3.12.10,
PyInstaller 6.22.3, Inno Setup 6.7.3. The same run tested this exact file (see "Verified for this candidate").
If anything that goes into the installer changes, the installer is rebuilt and this table is updated.

```powershell
Get-FileHash -Algorithm SHA256 .\BIO-CE-Setup-v0.4.0-rc1.exe
```

### The installer is not code-signed

As in v0.3.0-rc1, neither the installer nor the programs it installs carry a digital signature, and Windows
SmartScreen may warn about a downloaded copy. Run it only if the SHA-256 above matches exactly. BIO CE never asks
you to turn off SmartScreen, Microsoft Defender, or any other protection.

## Known limitations

- **Not code-signed.** The installer and the programs it installs have no digital signature (see above).
- **Not verified on a PC without Python.** The automated clean install ran on a fresh GitHub-hosted Windows
  runner, which has Python and Git installed. A Windows PC without Python or Git has not been tested.
- More limitations, including items not yet verified, are listed under "Not verified" below and in
  `docs/known-limitations.md`.

## What changed since v0.3.0-rc1

### Fixed

- Approving a review item that was already handled no longer changes memories. Before, a rejected suggestion could
  still be saved, a rejected retraction applied, and a second approval created a duplicate.
- Rejecting a suggestion from a review card that was already handled no longer shows an internal error.
- When an AI host repeats the same uncertain suggestion or the same retraction request, BIO CE now keeps one review
  item instead of one per request.

### Added

- **Settings → Memory engine.** Shows the engine BIO CE uses (the built-in Community Engine), its status, and a
  notice that each engine keeps its own memories. BIO Core appears as **not installed** and cannot be selected;
  BIO CE works fully without it.
- The sidebar shows the engine in use. If an engine does not offer an action, its button is disabled with the reason.
- Review cards say that nothing is stored until you approve it.

### Unchanged

- Memory database, settings, and AI connection data formats: an upgrade from v0.3.0-rc1 keeps every memory,
  revision, review item, connection, setting, and backup (verified, see below).
- MCP tool names and results, hook output, and all third-party components and their versions.

## Upgrading

Run the new installer; it updates BIO CE in place. Your data in `%LOCALAPPDATA%\BIO-CE` is not modified. To
be safe, create a backup in Settings first. Connected AI hosts keep working without reconnecting.

## Verified for this candidate

- The automated test suite (178 passed, 3 skipped for tools the runner does not have) on a GitHub-hosted Windows
  runner, and 180 tests on the development PC; the packaged MCP server against the official MCP SDK.
- Release payload check: installer hash, every payload file against the build manifest, no bundled Universal CRT,
  no test code, no credentials or build-machine identity, license notices for every bundled component.
- Unattended clean install of this exact installer on a fresh GitHub-hosted Windows runner where it had never been installed:
  install, first-run notice, first launch creating the database, installed MCP server and hook, uninstall
  keeping data, and full cleanup. The same run repeated the upgrade test below.
- Installer run on the developer's Windows account with synthetic data: install v0.3.0-rc1, create data with it,
  upgrade to this candidate with all data unchanged, installed MCP server and hook (Korean text), Claude Code and
  Codex registration and hook install/remove in isolated profiles, revocation, backup and restore including
  recovery from a backup made before the upgrade, uninstall keeping data, reinstall into a folder whose name has
  Korean letters, spaces, and `#`, and full cleanup.

## Not verified

- **A Windows PC without Python or Git.** The clean install ran on a hosted runner that has both.
- Claude Code and Codex registration from the installed app on the runner (neither CLI is installed there); it
  was verified on the developer's account.
- Backup and restore by clicking in the installed app (the same code passes the automated UI tests).
- The uninstaller's interactive "also remove my data" question (silent uninstalls always keep data, by design).
- Real 125%/150% display scaling, Windows 10, screen readers.
- Whether real AI models decide on their own to use BIO CE's memory tools. Codex Auto memory remains **limited**.
- BIO Core: not part of this release.
