<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.2.0-rc1 — Release Engineering and Installation Qualification Report

**Overall status: PARTIAL.** Packaging, licensing, security scans, automated tests, and a real-GUI
install/update/uninstall run on the developer's own Windows 11 account passed. Installation on a **clean**
Windows 11 VM/account is **NOT VERIFIED**, so the PASS criterion is not met. RC1 is not a public release.

Updated: 2026-10-22  
Branch: `feat/desktop-oneclick-v0.2` (uncommitted working tree on top of the v0.1 documentation commit, private development history)  
Machine: Windows 11 Home x64 10.0.26200, ko-KR, 100% display scale (96 DPI), standard (non-elevated) token  
Build runtime: official python.org CPython 3.12.10 x64 (PSF-signed), PyInstaller 6.22.3, Inno Setup 6.7.3  
No commit, tag, push, GitHub Release, visibility change, CI run, or AI model call was made.

## RC1 artifact

| File | Bytes | SHA-256 |
|---|---:|---|
| `dist/release/BIO-CE-Setup-v0.2.0-rc1.exe` | 44,101,936 | `3b1fd86c09f02aecc1a6b76d6e4d14cc596ed4df6f31bfe25bf368ef3ac24e75` |

- Authenticode: **NotSigned**. Setup, `BIO-CE.exe`, and `BIO-CE-MCP.exe` all request `asInvoker`.
- Payload: 2,566 files, 114,352,404 bytes. Per-file hashes: `dist/release/build-manifest.json`.
- Built from a frozen source snapshot in a fresh venv. The snapshot's 41 build-relevant files (all of `src/`
  and `packaging/`, `LICENSE`, `pyproject.toml`, runtime/build lock files, and the two docs shipped in the
  payload) have fingerprint `d2e7a0f9e123d4b11f2e847e8fccb3650fc4e207c6d8f58b3a927ea7bd1091a0`, identical to
  the working tree at report time. The program installed during the E2E run was compared file by file with
  the manifest: 2,566/2,566 identical, no stale files. **The verified UI and the shipped installer are the
  same source.**

## Summary

| Area | Status | Evidence |
|---|---|---|
| Automated tests | **PASS** | `pytest -q tests`: 67 passed, 25 subtests (CPython 3.12.10). Clean snapshot run before the build: 66 passed, 1 skipped (packaged-EXE test, no build yet); that test then passed against the RC1 binary. Baseline at start of this pass: 57 passed. |
| Phase A — UI on the installed RC1 | **PASS (host)** | Real-GUI run below. 125%/150% scaling **simulated only**. |
| Phase B — installer | **PASS (host)** | Inno Setup per-user installer; details below. |
| Phase C — clean Windows 11 E2E | **NOT VERIFIED** | Windows 11 Home has no Windows Sandbox or Hyper-V. No separate VM or account was available, and creating an account needs administrator rights. Not replaced by a simulation. |
| Phase C steps on the developer's own account | **PASS (non-clean)** | All 20 steps, real GUI, synthetic data only. Python and Git are present on this machine. |
| Phase D — Codex CLI / Claude Code | **PASS (SDK/host CLI)** | Isolated host profiles, real GUI connect/disconnect, host health-check, official SDK. |
| Model-issued tool calls | **NOT VERIFIED** | No model was invoked; needs separate approval. |
| Phase E — reproducibility, licenses, security | **PASS with caveats** | See below. |
| Windows 10 | **NOT RUN** | |
| GitHub Actions CI | **NOT RUN** | |
| Code signing | **NOT SIGNED** | SmartScreen may warn on downloaded copies. |

## Test-environment finding: MSIX container redirection

The automation shell runs as a child of the Claude desktop app, an MSIX package. Processes started from it
are not packaged (`GetCurrentPackageFullName` → 15700), but Windows still redirected **new** top-level
folders under `%LOCALAPPDATA%`/`%APPDATA%` and HKCU writes into the package's private storage. Writes into
already-existing folders such as `%LOCALAPPDATA%\Programs` were not redirected. A first exploratory install
started from that shell therefore had real program files but a container-only uninstall key and data
folder. That run was discarded as evidence and cleaned up. **Every E2E step below was started through
`explorer.exe`, which runs outside the container.** State was checked with a probe that also ran outside
the container (`reg query`, `dir`, `tasklist`). The same redirection would affect any user who starts BIO
CE from inside a packaged app; this is listed in the known limitations.

## Real-GUI E2E on the developer's account (Phases A and C, non-clean)

The real windows were driven with OS-level mouse and keyboard input (`SendInput`), guarded so input was only
sent when a BIO CE or Setup window was in the foreground. Screenshots were taken with `PrintWindow`. Only
synthetic text was entered. The app was started from the real Start-menu shortcut, via a launcher that pointed
`CODEX_HOME`/`CLAUDE_CONFIG_DIR` at throwaway profiles so the user's real host configs were never read or
changed by the GUI runs. (One earlier in-container launch did read the real configs to show connection
status; nothing was written.) Evidence: `.test-tmp/rc1/evidence/e2e/` (ignored, local only).

| # | Step | Result |
|---|---|---|
| 1 | Python/Git-free environment | **NOT MET**: developer machine. The packaged GUI was also started with `PATH` limited to `System32` and ran normally. |
| 2–3 | Double-click Setup, complete wizard | PASS. Korean wizard. Default `%LOCALAPPDATA%\Programs\BIO-CE`. No UAC prompt. Uninstall entry and Start-menu shortcut created. A folder inside `%LOCALAPPDATA%\BIO-CE` is refused. |
| 4 | Start from Start menu | PASS |
| 5 | Privacy notice | PASS. **Quit** exits 0 and creates no folder (real session; re-checked on the RC1 EXE). |
| 6 | DB created only after **Continue** | PASS |
| 7 | Save memory (Hangul + English) | PASS |
| 8 | Search | PASS (1 result for the marker) |
| 9 | Detail view | PASS |
| 10 | Edit → revision 2, history | PASS (header shows Revision 2; history lists 2 revisions) |
| 11 | Retract, read blocked | PASS. Confirm dialog quotes the title and focuses **Cancel**. Delete+Enter within 0.4 s did not confirm. Esc cancels. Retracted memory no longer found. |
| 12–13 | Close, relaunch, data kept | PASS |
| 14 | Backup | PASS. RC1 backup is one self-contained file (rollback-journal header), no sidecars. |
| 15 | Restore | PASS on RC1: a post-backup memory disappeared, revision 2 restored, no leftover files. |
| 16 | Update | PASS. Older build → RC1 while the old app was running. Restart Manager listed it, closed it, and kept the folder. Installed files = RC1 manifest. |
| 17 | Data kept after update | PASS |
| 18 | Uninstall | PASS. Custom confirmation. Running BIO CE detected (AppMutex). Data prompt defaults to **No** (Enter kept data). Program, shortcut, and uninstall key removed. |
| 19 | Data kept after uninstall | PASS (memories, settings, connection backups) |
| 20 | Reinstall → data back | PASS. No first-run notice; the preserved memory is shown. |
| — | Final cleanup | Uninstall with **Yes** to data removal: program, shortcut, uninstall key, and data folder all removed. Machine back to its pre-test state. |

Additional Phase A checks:

- **Hangul**: titles and body render correctly in Malgun Gothic; Hangul typed through `KEYEVENTF_UNICODE`.
  Interactive IME composition was not exercised.
- **DPI**: real 100% only. 125% and 150% are covered by the simulated-scale UI tests
  (`test_desktop_ui_redesign`).
- **Minimum size**: asking for 400×300 is clamped to 876×599 including the frame (860×560 logical). The
  sidebar collapses to icons.
- **Keyboard**: Tab moves a visible focus ring through the sidebar; Enter activates. Ctrl+1–4, Ctrl+N/E/H/F/S
  and Esc were used throughout the run.
- **Single instance**: a second launch leaves one process and brings the existing window forward.
- **Hangul/space install path**: a dev build was installed through the wizard into `…\Programs\BIO CE 테스트
  경로`. It launched from there, and the Codex connection with SDK check passed from that path. (That run was
  inside the container, so it is evidence for path handling only.)

### Defects found by the GUI run and fixed before the RC1 build

1. Window icon fell back to the generic Windows icon on every launch after the first, because Tk drops
   `iconphoto` set before the root is first mapped. It is now re-applied after the window is shown.
2. Several BIO CE windows could run at once. A second instance holds the DB open, so restore failed with a
   message that blamed "connected AI hosts". Fix: per-session single-instance mutex (second launch focuses
   the first), `AppMutex` in Setup/uninstaller, and a message that names another BIO CE window.
3. Backup/restore left `-wal`/`-shm` files beside backups and in the data folder. The SQLite page copy kept
   WAL mode, and read-only validation then created sidecars. Backups are now converted to rollback-journal
   files, user-chosen backups are read `immutable`, backups with a pending non-empty `-wal` are refused, and
   temporary sidecars are cleaned up. Regression tests added.
4. Connect confirmation, Connections page, and first-run notice did not say that memories a host reads may be
   sent to the host's model provider. Text added (Phase D requirement) with a regression assertion.
5. `THIRD_PARTY_NOTICES` lacked the OpenSSL, expat, zlib, and libmpdec notices for code built into the CPython
   runtime (also missing in the preview). Fixed; see Phase E.

## Phase B — installer stabilization

| Requirement | Result |
|---|---|
| Target `%LOCALAPPDATA%\Programs\BIO-CE` | PASS (`DefaultDirName={userpf}\BIO-CE`) |
| User DB under `%LOCALAPPDATA%\BIO-CE`, never touched by Setup | PASS. `[Code]` refuses overlapping folders; data deletion only through the opt-in uninstall prompt. |
| No administrator rights | PASS (`PrivilegesRequired=lowest`, `asInvoker`, no UAC prompt) |
| Shortcut and Start-menu entry | PASS; optional desktop shortcut (unchecked by default) |
| EXE icon | PASS: generated multi-size ICO on Setup, GUI, and MCP EXEs; version resources on all three |
| Spaces/Hangul in install path | PASS (dev build, container run; see above) |
| MCP stdio | PASS: console-subsystem `BIO-CE-MCP.exe` separate from the windowed GUI; Claude Code's health check and the official SDK spoke stdio to the installed copy |
| Changing the install folder | PASS: chosen in the wizard; refused inside the data folder |
| Update over an existing install | PASS: same AppId, `_internal` runtimes replaced wholesale, Restart Manager plus AppMutex |
| Existing DB kept on update / uninstall | PASS |
| No Python/Git/venv needed | Packaged GUI ran with `PATH` = `System32` only. Clean machine **NOT VERIFIED**. |

**IExpress → Inno Setup.** Microsoft publishes no specific redistribution terms for IExpress-generated
self-extractors. The preview also depended on PowerShell with `-ExecutionPolicy Bypass`, had no real
uninstaller, and wrote no version data. Inno Setup 6.7.3 (installed per-user; `ISCC.exe` Authenticode-signed
by its publisher, checked by the build script) is distributed under the Inno Setup License, which allows "any
purpose, including commercial applications" with notices retained. Since 6.5.0 the authors also sell optional
commercial licenses and *ask* commercial users to buy one. The license text shipped with 6.7.3 does not make
that a condition. Recorded in `docs/THIRD_PARTY_LICENSES.md`; the license text is bundled in
`THIRD_PARTY_NOTICES`.

**UCRT DLLs.** The earlier builds that contained `api-ms-win-*.dll`/`ucrtbase.dll` were run from the Codex
agent shell. Its `PATH` included Codex-runtime native tool folders (`poppler`, `libheif`, `jxrlib`) that ship
app-local Universal CRT forwarders, and PyInstaller copies DLLs it finds on `PATH`. Builds from other shells
lacked them. The build now runs PyInstaller with a minimal `PATH` and fails if any UCRT DLL is bundled.
Windows 10/11 include the UCRT. No compatibility claim is made beyond the Windows 11 build actually tested.

## Phase D — MCP host connection

Codex CLI 0.162.1 and Claude Code 2.1.306 were detected on `PATH`. Both host profiles were throwaway copies
that each started with one unrelated synthetic MCP entry.

| Check | Result |
|---|---|
| Host detection | PASS (both "Installed / Not connected") |
| Explicit approval | PASS. Per-host confirmation lists access scope, provider transfer, backup, and the local check. |
| Config backup before change | PASS (4 backups: 2 connect + 2 disconnect) |
| Registration | PASS. `bio-ce` stdio entry with the installed MCP path and the real DB path; unrelated entry preserved. |
| Packaged server runs under the host | PASS. `claude mcp list` health-check started the installed `BIO-CE-MCP.exe`: "Connected". `codex mcp list` shows the entry. |
| Official SDK search/read | PASS against the installed EXE with a synthetic DB: tools = {search, read}; read matches revision; retracted read blocked; wrong scope rejected; `bio_memory_add` rejected; DB bytes unchanged. |
| Read-only | PASS (above; server opens SQLite `mode=ro` + `query_only`) |
| Disconnect | PASS. Only `bio-ce` removed; Codex config byte-identical to the original afterwards. |
| Rollback on failure | Automated tests (`test_host_connections`): verification failure removes BIO CE's entry and keeps others. Not reproduced through the GUI. |
| Host not installed | Automated tests: shown as "Not installed"; connection is optional. |
| Model-issued tool call | **NOT VERIFIED** (not run without separate approval) |

## Phase E — reproducibility and security

- **Clean rebuild**: frozen snapshot, fresh venv from official CPython 3.12.10, pinned locks, `pip check` clean.
- **Second build from the same snapshot**: 2,564 of 2,566 payload files byte-identical. `BIO-CE.exe` and
  `BIO-CE-MCP.exe` differ in 6 bytes each (PE `TimeDateStamp`, PE checksum, debug timestamp). Inno Setup also
  embeds its build time, so the installer hash differs per build (second build:
  `0566e9cf6f2ed725349d4c1aedef0b22c72c6a5b7921ded6b1ba17cfc8164ea6`). Content-reproducible; not
  bit-reproducible.
- **Bundle contents**: CPython 3.12.10 runtime (OpenSSL 3.0.16, SQLite 3.49.1, expat 2.7.1, zlib 1.3.1,
  libmpdec 2.5.1, Tcl/Tk 8.6), `VCRUNTIME140*.dll`, locked MCP runtime packages; no UCRT DLLs.
- **Licenses**: `THIRD_PARTY_NOTICES` (≈351 KB) contains every locked runtime distribution's license files,
  CPython `LICENSE.txt`, CPython 3.12.10 "Licenses and Acknowledgements for Incorporated Software" (verbatim
  `Doc/license.rst`, SHA-256-pinned in `packaging/notices/`), Tcl/Tk terms, the PyInstaller bootloader
  exception, and the Inno Setup license. Caveat: crates statically linked into the Rust wheels
  (`cryptography`, `pydantic-core`, `rpds-py`) are covered only by those wheels' own license files.
- **Gitleaks 8.18.4** (archive SHA-256 matched the publisher checksum list): final candidate tree, 81 files → 0
  findings; Git history, 3 commits → 0 findings. Reports are redacted.
- **Source text scan**: 0 hits for the account name, account email, machine name, local paths, Codex
  runtime, or MSIX package name; no email addresses.
- **Binary scan** of all 2,566 payload files and the installer (ASCII and UTF-16, with a positive control):
  0 personal or local-path strings, 0 AWS/GitHub/OpenAI/Anthropic/Slack/private-key patterns. Six `.pyd`
  files (the Rust wheels above, in GUI and MCP) contain `C:\Users\runneradmin\…` paths, which is the upstream
  CI build account and not local data.
- **Signing**: not signed. SmartScreen may warn on downloaded copies. Users are never asked to disable or
  bypass Windows protections. The only `-ExecutionPolicy Bypass` left is a per-process flag BIO CE uses to
  start the user's npm `codex.ps1` wrapper; it is documented in `docs/desktop-security.md`.
- **Backup/restore integrity**: SQLite `integrity_check` = ok on the GUI-made backup. Restore verified through
  the GUI; corrupt, pending-WAL, and active-reader cases fail closed in automated tests.
- **Logs**: BIO CE writes no log files and discards host CLI output. The four Inno Setup logs from this run
  contain installation paths only (no memory text); they were moved out of `%TEMP%` into the ignored
  evidence folder.

## Reproduction

```powershell
py -3.12 -m venv .venv            # official python.org CPython 3.12.10 x64
.\.venv\Scripts\python.exe -m pip install -r requirements-mcp.lock.txt -r requirements-test.lock.txt -r requirements-build.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q tests
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\packaging\build_windows.ps1
```

Inno Setup 6.7 must be installed. The build fails if the interpreter is not CPython 3.12.10 (notice coverage)
or if UCRT DLLs end up in the bundle.

## Remaining blockers before a public release

1. Clean Windows 11 VM/account E2E without Python/Git, ideally also as a standard (non-admin) user.
2. Separately approved model-issued Codex/Claude tool calls with synthetic data.
3. Code signing, or an explicit decision to ship unsigned.
4. Windows 10 and real 125%/150% scaling, if they are to be claimed.
5. GitHub Actions CI (none run), commit/tag approval, and the BIO Core source-provenance item that remains
   PARTIAL from v0.1.
