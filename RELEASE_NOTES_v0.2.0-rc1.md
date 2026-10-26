<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.2.0-rc1 — Release Notes

Release candidate 1 of the BIO Community Edition Windows desktop app. **Not a public release.** Overall
qualification: **PARTIAL** — see "Not verified" below and the [test report](docs/release-v0.2-test-report.md).

## Download

| File | Size | SHA-256 |
|---|---:|---|
| `BIO-CE-Setup-v0.2.0-rc1.exe` | 44,101,936 bytes | `3b1fd86c09f02aecc1a6b76d6e4d14cc596ed4df6f31bfe25bf368ef3ac24e75` |

Check it before running: `Get-FileHash -Algorithm SHA256 .\BIO-CE-Setup-v0.2.0-rc1.exe`. The installer is
**not code-signed**; Windows SmartScreen may show an unknown-publisher warning for a downloaded copy.

## Requirements

- Windows 11 x64. (Only Windows 11 Home build 26200 was exercised. Windows 10 is not tested or supported.)
- No administrator rights, Python, Git, or other runtime. Codex CLI or Claude Code only if you want to connect one.

## What's new since the v0.2.0 developer preview

- **New installer.** Per-user Inno Setup 6.7.3 wizard (Korean/English) replaces the IExpress + PowerShell
  package. No elevation, no PowerShell, a real uninstaller in **Settings → Apps**, update-in-place that replaces
  the runtime folders wholesale, a guard against installing into the data folder, version resources, and an
  opt-in-only data removal prompt (default: keep).
- **App icon** on `BIO-CE.exe`, `BIO-CE-MCP.exe`, Setup, and the window title bar (the title-bar icon was
  previously lost on every launch after the first).
- **One window at a time.** A second launch focuses the running window. Setup and the uninstaller detect a
  running BIO CE.
- **Clearer AI-host disclosure.** The first-run notice, the Connections page, and every Connect confirmation now
  say that memories a host reads may be sent to that host's AI model provider.
- **Backup/restore hygiene.** Backups are self-contained single files; creating, validating, or restoring one no
  longer leaves `-wal`/`-shm` files behind. A backup with pending write-ahead-log data is refused. The "database
  in use" message now names another BIO CE window as a possible cause.
- **Licensing.** `THIRD_PARTY_NOTICES` now also carries CPython's notices for OpenSSL, expat, zlib, and libmpdec,
  the PyInstaller bootloader exception, and the Inno Setup license.
- **Build.** Official python.org CPython 3.12.10; minimal-`PATH` PyInstaller run that refuses stray Universal CRT
  DLLs; per-file `build-manifest.json`.

## Verified

- 67 automated tests passed on Windows 11 with CPython 3.12.10 (66 + 1 skipped packaged-EXE test in the clean
  pre-build snapshot run; the packaged-EXE test then passed against the RC1 binary).
- On the developer's own Windows 11 account, through the real GUI (OS mouse/keyboard input, synthetic data
  only): installer wizard, Start menu launch, first-run notice (declining creates no data), add/search/read/edit
  (revision 2)/history/retract, restart persistence, backup, restore, update from an older build, uninstall
  keeping data, reinstall picking the data up again, and opt-in data removal.
- Codex CLI 0.162.1 and Claude Code 2.1.306 connect/disconnect through the GUI against isolated host profiles,
  with other MCP entries preserved; the installed `BIO-CE-MCP.exe` passed official MCP SDK checks.
- Gitleaks 8.18.4: 0 findings in source and Git history. No personal paths, emails, or secrets in source or in
  the built binaries (three upstream Rust wheels embed their CI runner's build paths; not local data).

## Not verified

- Installation on a **clean** Windows 11 VM or account without Python/Git (no VM or Windows Sandbox available).
- A real AI model calling BIO CE's tools (no model call was made).
- Windows 10; real 125%/150% display scaling (simulated only); GitHub Actions CI; code signing.

## Upgrade notes

The unreleased v0.2.0 IExpress developer preview is replaced in place: Setup removes its uninstall entry and
`uninstall.ps1`. Data under `%LOCALAPPDATA%\BIO-CE` is reused unchanged.
