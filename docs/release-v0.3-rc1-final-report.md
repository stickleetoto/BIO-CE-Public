<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.3.0-rc1 — Final Release Candidate Report

Date: 2026-10-26 · Windows 11 Home x64 10.0.26200 (ko-KR, 100% scale, standard user token) · Build runtime:
official CPython 3.12.10, PyInstaller 6.22.3, Inno Setup 6.7.3 · Claude Code 2.1.306 (isolated profile, local
mock model).
No push, tag, GitHub Release, visibility change, or paid model call was made. BIO Core was not touched. Only
synthetic data was used; the user's real memory database and Codex/Claude settings were neither read nor changed.
No new features were added; this round only tested, fixed defects, and documented.

## Verdict: PARTIAL (release candidate)

| Area | Status |
|---|---|
| A. Installer built from the public source, hashed, inspected | **PASS** |
| B. Installer E2E on the developer's Windows 11 account | **PASS** (25/25 steps) |
| B. Same flow on a clean Windows account or VM | **NOT RUN**: no VM, Windows Sandbox, or second account available |
| B. Windows 10 | **NOT RUN**: Windows 10 is not claimed |
| C. Auto memory synthetic regressions | **PASS** (18 scenarios; 4 added in this round) |
| C. Codex CLI Auto memory | **Limited** (unchanged; no workaround added) |
| D. README, LICENSE, SECURITY.md, private commit IDs | **PASS** |
| D. GitHub Actions workflow | Configuration checked locally; **hosted CI BLOCKED** (account billing) |
| D. Gitleaks and exposure scans | **PASS** |
| D. Full regression | **PASS**: 103 tests |

## Source

The public history starts at commit `d433ebd01cd61fbace397a15d88bc96f6edc62b6`, a root commit with no parent. The
installer was built from a fresh clone of that commit. The following commit adds only this report, the release
notes, other documentation, and a fix to the installer E2E harness; no file that goes into the installer changes.

## A. Installer

| Item | Value |
|---|---|
| File | `BIO-CE-Setup-v0.3.0-rc1.exe` |
| Bytes | 44,231,910 |
| SHA-256 | `2d79e7d4c9dff1187ff90149a1bc7418f014f9c0209a6c984ffa5d2d741572ee` |
| Signature | Not signed |
| Payload | 2,566 files, 114,490,844 bytes; per-file hashes in `build-manifest.json` |
| `THIRD_PARTY_NOTICES` | 351,466 bytes (same coverage as earlier candidates) |

**How it was built.** `git clone` of the public commit with Git's Windows default `core.autocrlf=true`, then
`packaging\build_windows.ps1 -Python <venv>` from that clone. The build venv is official CPython 3.12.10 with
`requirements-mcp.lock.txt` and `requirements-build.lock.txt` (PyInstaller 6.22.3); Inno Setup 6.7.3's `ISCC.exe`
carries a valid Pyrsys B.V. signature. The script runs PyInstaller with a minimal `PATH` and refuses stray
Universal CRT DLLs.

**Defect found and fixed.** The first build from a fresh clone failed. With `core.autocrlf=true`, Git converted
`packaging/notices/cpython-3.12.10-license.rst` to CRLF, so its pinned SHA-256 no longer matched and the notice
collector stopped the build. `LICENSE` also stopped being byte-identical to the ASF text. A new `.gitattributes`
keeps both files' exact bytes in every checkout. Earlier builds had run from the original working tree, where the
files had not been converted.

**Correspondence with the source.** Every `bio_ce` module frozen into `BIO-CE.exe` (28 modules) and
`MCP\BIO-CE-MCP.exe` (31 modules) was compared with `compile()` of the public source file: no differences. A
control run with one changed constant was detected. The payload file list equals the manifest.

**Reproducibility.** A second build of the same clone produced the same 2,566 files. 2,564 are byte-identical;
the two executables differ only in 6 bytes each (PE build timestamp, PE checksum, one embedded timestamp), and
their frozen code is identical. The installer file itself differs between builds because Inno Setup embeds time
stamps. Compared with the 2026-10-24 build, only the two executables and the two bundled documents changed.

**Payload inspection.**

- No tests, harness, Git or CI files, BIO CE `.py` sources, databases, backups, key or env files, debug symbols,
  or logs.
- No local user name, email address, development drive path, or BIO Core name.
- `C:\Users\…` strings come only from upstream binaries: Rust crate build paths of the CI runner that built
  `cryptography`, `pydantic-core`, and `rpds-py`, and a docstring example in CPython's `ntpath`.
  `python312.dll` is byte-identical to the official installation.
- Gitleaks on the payload reported 4 `aws-access-token` matches, all in Tcl's `cp949.enc` encoding table, which is
  byte-identical to the official CPython file: false positives. Gitleaks on the installer: 0.

## B. Installer E2E

`tests/host_harness/install_e2e.py`, started through `explorer.exe` so it runs outside the MSIX app container
(`GetCurrentPackageFullName` returned `APPMODEL_ERROR_NO_PACKAGE`). It refuses to run when BIO CE is installed or
data exists, uses isolated Codex/Claude profiles and a local mock model, runs every installer silently, checks the
GUI by window capture only (no input is sent to the desktop), and removes only what it created.

| # | Step | Result |
|---|---|---|
| 1 | Preflight: no install, data, shortcut, or uninstall entry | Pass |
| 2 | Install v0.2.0-rc1 as a standard user (no UAC) | Pass |
| 3 | v0.2-format data (memory schema v1, revision 2, Hangul; no control database) | Pass |
| 4 | Update to v0.3.0-rc1 | Pass: 2,566/2,566 installed files match the manifest |
| 5 | v0.2 data unchanged by the update | Pass: byte-identical, `integrity_check` ok |
| 6 | Installed GUI opens the v0.2 data | Pass |
| 7 | First-run notice in a fresh profile; closing it creates nothing | Pass |
| 8 | User add, search, edit (revision 2) | Pass |
| 9 | User retract: hidden from list and search | Pass |
| 10 | Backup, then restore: retracted memory back, `integrity_check` ok | Pass |
| 11 | Claude Code connection through the installed `BIO-CE-MCP.exe` (real `claude mcp add`, SDK check) | Pass, Read only |
| 12 | Auto memory on; approvals limited to BIO CE's tools | Pass |
| 13 | Session hooks installed | Pass |
| 14 | Claude Code creates a memory through the installed server | Pass; host, connection, evidence recorded |
| 15 | **New session** recalls it: hook context and search result both reach the model | Pass |
| 16 | Conflicting update queued; memory unchanged; activity log shows it | Pass |
| 17 | User rejects the queued update; AI retraction request waits; user approves it; memory gone | Pass |
| 18 | Hooks removed: no hook context in the next session; tools still work | Pass |
| 19 | Paused: hook context suppressed and tool calls refused | Pass |
| 20 | Disconnect revokes: entry, hooks, approvals removed; old token refused (server exit 3) | Pass |
| 21 | GUI after AI activity | Pass |
| 22 | Uninstall keeps memories and settings; program, shortcut, uninstall entry removed | Pass |
| 23 | Reinstall: manifest match, data byte-identical | Pass |
| 24 | GUI after reinstall, no first-run notice | Pass |
| 25 | Cleanup: machine back to its pre-test state | Pass |

The first full run passed steps 1–24, and step 25 failed because of a harness defect. After an uninstall
followed at once by a reinstall, Inno Setup names the new uninstaller `unins001.exe`, because the previous one
is still being removed. The registry uninstall entry points to it correctly, but the harness hardcoded
`unins000.exe`. The harness now uses the registry's `UninstallString`. The machine was cleaned with the fixed
harness's cleanup mode, and the second full run passed all 25 steps. This naming is standard Inno Setup behavior,
and Windows' own uninstall uses the registry entry.

**Not covered:** the interactive wizard, clicking through the GUI by hand, and the uninstall data-removal prompt.
These were verified for v0.2.0-rc1 through the real GUI; this round sent no input while the user was working. The
real-Tk UI tests exercise the same pages. Codex through the installed build is covered by the Codex stage probe.

## C. Auto memory quality (synthetic, no model calls)

`tests/integration/test_auto_memory_scenarios.py` drives the real stdio server with the official MCP SDK client.
New in this round:

| Scenario | What it checks |
|---|---|
| 15 | Corrections carrying a secret (in content or title), an injected instruction (English or Korean), or document-sourced text are refused; the memory stays at revision 1; nothing of the secret or injection is stored or logged; a secret added while approving a queued item is refused and marks it failed |
| 16 | Each AI revision records host, connection, kind, reason, and evidence; approved items record the review ID; user-entered memories keep their own source type; the activity log links each change to its revision |
| 17 | A memory saved through one host is found by another host in a new session, the other host's duplicate is detected, and its session hook shows the memory |
| 18 | The hourly write limit applies per connection; duplicates are not counted; the limit is logged |

Existing scenarios cover storing user-stated facts, duplicates, corrections versus ambiguous conflicts, one-off
questions, secrets, injected instructions, restart and hook recall, mode and revocation on a running connection,
concurrent updates, history and user-approved retraction, a killed writer, and v0.2 compatibility. The earlier
real-model evidence is kept unchanged ([evaluation](real-model-memory-evaluation.md)). No paid model was called.

**Codex CLI** stays **Limited**: its code-mode models are not shown MCP tools ([Codex support](codex-support.md)).
No unofficial setting or workaround was added.

## D. Public candidate

| Check | Result |
|---|---|
| README, LICENSE, SECURITY.md | Reviewed; `LICENSE` is byte-identical to the ASF Apache-2.0 text in a fresh clone |
| Private commit IDs | Audit and report documents no longer cite commits that exist only in the private development history; GitHub Actions run links were removed |
| GitHub Actions workflow | The three actions are pinned to full SHAs, and each matches its release tag on GitHub (`git ls-remote`). Least-privilege `contents: read`, no persisted credentials, pinned CPython 3.12.10, lock files, `pip check`, timeout, concurrency. **A hosted run is BLOCKED**: GitHub refused the only run before a runner started, for an account billing reason |
| Local run of the workflow's steps | Fresh clone (CRLF checkout) and fresh CPython 3.12.10 venv: `pip check` ok, 102 passed and 1 skipped. The skip is the packaged-EXE test, which then passed against the shipped `BIO-CE-MCP.exe`. This is not a CI result |
| Full regression on the development interpreter | 103 passed, 69 subtests, 0 skipped |
| Gitleaks 8.18.4 | Public source history and tree: 0 findings |
| Personal and private names | Public source: no user name, email, local path, or BIO Core name; author and committer use the GitHub noreply identity |
| BIO Core exposure scan | 7,370 BIO Core-specific terms against the public source: only generic words, no internal names, codenames, or paths; no new terms compared with the previous candidate |

## Remaining blockers before a public release

1. **GitHub Actions CI**: resolve the account billing issue, then push with approval and get a real hosted PASS.
2. **Clean Windows account or VM** E2E (no Python or Git), including the interactive wizard and GUI click paths.
3. **Code signing**, or an explicit decision to ship unsigned.
4. **Codex Auto memory** waits on an upstream Codex fix.
5. **Larger real-model evaluation** before claiming Auto memory quality beyond one short run.
6. Windows 10 and real 125%/150% scaling, only if they are to be claimed.
7. Owner actions when going public: choose a new repository or a force-push (see the
   [release gates](audit/public-release-gates.md)), and enable private vulnerability reporting.

Evidence is kept locally and is not published: `.test-tmp/final/` (build logs, payload inspection, E2E results,
logs, and screenshots of both runs, the CI-style test log and JUnit XML, Gitleaks reports), plus
`build/0.3.0-rc1-final/build-manifest.json` and `dist/0.3.0-rc1-final/`.
