<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.3.0-rc1 — Release Notes

Release candidate of the BIO Community Edition Windows desktop app. **Not a published release.** Overall
qualification: **PARTIAL**. See "Not verified" below and the
[final qualification report](docs/release-v0.3-rc1-final-report.md).

## Download

| File | Size | SHA-256 |
|---|---:|---|
| `BIO-CE-Setup-v0.3.0-rc1.exe` | 44,231,910 bytes | `2d79e7d4c9dff1187ff90149a1bc7418f014f9c0209a6c984ffa5d2d741572ee` |

Built from source commit `d433ebd01cd61fbace397a15d88bc96f6edc62b6` (the first commit of the public history).
Later commits change only documentation and the installer test harness; no file that goes into the installer
differs.

Check the file before running it:

```powershell
Get-FileHash -Algorithm SHA256 .\BIO-CE-Setup-v0.3.0-rc1.exe
```

### The installer is not code-signed

- Neither `BIO-CE-Setup-v0.3.0-rc1.exe` nor the programs it installs carry a digital signature. Windows
  cannot show who published them, and a signature cannot prove that the file is unchanged. The SHA-256 above is
  the only integrity check.
- When you run a downloaded copy, **Windows SmartScreen may block it** with "Windows protected your PC" and an
  unknown publisher. Some antivirus products may also warn about unsigned, newly published programs.
- Run the installer only if its SHA-256 matches exactly. If it does not match, or you are unsure where the file
  came from, delete it. BIO CE never asks you to turn off SmartScreen, Microsoft Defender, or any other Windows
  protection.

## Requirements

- Windows 11 x64. Only Windows 11 Home build 26200 (Korean locale) was exercised. **Windows 10 is not tested
  or supported**; Setup does not block it.
- Display scaling: only 100% was exercised on real hardware. 125% and 150% were checked with simulated-scale UI
  tests only and are **not verified** on a real display.
- No administrator rights, Python, Git, or other runtime. Codex CLI or Claude Code only if you want to
  connect one.

## Install

1. Download `BIO-CE-Setup-v0.3.0-rc1.exe` and check its SHA-256 against the table above.
2. Run it. Setup installs for the current user only (`%LOCALAPPDATA%\Programs\BIO-CE`) and needs no
   administrator rights.
3. Start **BIO CE** from the Start menu and read the first-run notice. **Continue** creates your data folder;
   **Quit** creates nothing.

Updating from v0.2.0-rc1 installs over the old version and keeps your memories. Uninstalling keeps your data
unless you opt in to removing it. Full guide: [Desktop installation](docs/desktop-installation.md).

## What's new since v0.2.0-rc1

- **Auto memory (per host, off by default).** A connection starts as **Read only**. You can switch a host to
  **Auto memory**, so it may save and update lasting memories, or **Paused**. Writes pass BIO CE's memory
  policy: secrets, document- or tool-sourced content, and injected instructions are refused; uncertain changes
  and every retraction wait in your **review queue**; every AI change is recorded in the **AI activity log**;
  each connection is limited to 30 automatic changes per hour.
- **Per-connection grants.** Each host connection has its own random token (only its hash is stored) and is
  bound to one project/namespace. Pausing or disconnecting applies to running sessions on their next call.
- **Optional session hooks** for Claude Code and Codex CLI that give a new session BIO CE's relevant memories.
  They are installed only after you confirm.
- **Six MCP tools**: `bio_memory_search`, `bio_memory_read`, `bio_memory_history`, and, in Auto memory only,
  `bio_memory_create`, `bio_memory_update`, `bio_memory_retract`.
- **Redesigned desktop app**: dashboard, memories, editor, connections (with per-host Auto memory support
  shown as Available or Limited), and settings pages.
- **Fixed during v0.3 qualification:** a hook failure for tokens that began with `-`; a server that trusted
  its launch scope instead of its grant; intermittent Tcl library-load failures in the UI tests; a source build
  that failed in a fresh Windows clone because Git converted the line endings of a hash-checked notice file.

## Verified

- **Automated tests:** 103 tests passed on Windows 11 with official CPython 3.12.10, including 18 synthetic Auto
  memory scenarios over the real stdio MCP server. The same steps as the CI workflow pass in a fresh venv.
- **Installer E2E on the developer's Windows 11 account** (synthetic data, isolated Claude Code profile,
  local mock model, silent installs, GUI checked by window capture): 25 of 25 steps passed, from a v0.2.0-rc1 install with data through update, user add/search/edit/retract, backup and restore, Claude Code connection, Auto memory, recall in a new session, review queue, hook removal, pause, revoke, uninstall keeping data, and reinstall. See the final report for the step
  list.
- **Real model:** Claude Code saved, deduplicated, corrected, and recalled memories in one short synthetic run
  ([evaluation](docs/real-model-memory-evaluation.md)). No new paid model call was made for this candidate.
- **Security scans:** Gitleaks 8.18.4 found nothing in the public source and history or in the installer
  payload; personal-path and private-name scans of both were clean.
- **Source provenance:** PASS ([audit](docs/audit/source-provenance.md)).

## Not verified

- Installation on a **clean** Windows account or VM without Python or Git. Windows 11 Home has no Windows
  Sandbox, and creating another account was out of scope.
- **Windows 10**, real 125%/150% display scaling, and clicking through the GUI by hand for this build (v0.2.0-rc1
  was checked that way).
- **GitHub Actions CI on a hosted runner: not passed yet.** The first hosted run failed while installing dependencies (a conflict with tools preinstalled on the runner, fixed in the workflow); the next run passed 100 tests and failed 2 because a UI test assumed a large screen (fixed in the test; not yet re-run on GitHub). Before that, GitHub refused to start the job for an account billing
  reason. Local runs of the same steps are not a CI result.
- **Code signing.**
- **Codex CLI Auto memory: limited.** Codex's code-mode models are not shown MCP tools
  ([Codex support](docs/codex-support.md)). BIO CE applies no unofficial workaround.
- A larger real-model evaluation.

## Known limitations

See [Known limitations](docs/known-limitations.md). In short: lexical (FTS5) search only; no encryption at
rest; retraction is not secure erase; connection tokens sit in the host's configuration in plain text and do
not protect against other programs running as the same Windows user; backups cover `memories.sqlite3` only.

## Reporting security issues

See [SECURITY.md](SECURITY.md).
