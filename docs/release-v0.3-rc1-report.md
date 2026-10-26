<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.3.0-rc1 — Stabilization and RC Qualification Report

Date: 2026-10-24 · Branch `feat/autonomous-memory-v0.3` · Windows 11 Home x64 10.0.26200 (ko-KR, 100% scale,
standard user token) · Build runtime: official CPython 3.12.10, PyInstaller 6.22.3, Inno Setup 6.7.3 · Codex CLI
0.162.1 · Claude Code 2.1.306.
No push, tag, GitHub Release, visibility change, or paid model call was made. BIO Core and other repositories were
not touched. Only synthetic data was used, and the user's real Codex/Claude settings were neither read nor changed.

## Verdict: RC candidate, PARTIAL qualification

| Area | Status |
|---|---|
| Checkpoint of the pre-stabilization v0.3 source | **Done**: local checkpoint commit in the private development history (86 tests, Gitleaks 0) |
| Scope binding (B) | **Pass** |
| Codex compatibility (C) | **Analyzed**: Auto memory **limited** in Codex; shown as such in the app |
| v0.3.0-rc1 installer E2E (D) on the developer's account | **Pass** (19/19 steps) |
| Separate, clean Windows user account | **NOT VERIFIED** (BLOCKER 1) |
| Final verification (E) | **Pass**, except the items listed as blockers |

## A. Checkpoint

- Uncommitted v0.3 work and the `0.3.0-dev0` installer were backed up to `.test-tmp/v03-stabilization/baseline/`.
- The diff contained only intended source, test, and document files: 20 modified, 12 new; no databases, logs, or
  binaries.
- `pytest -q tests`: 86 passed, 44 subtests. Gitleaks 8.18.4: 0 findings on the 93-file candidate tree and on the
  full history.
- Committed locally ("checkpoint before stabilization"; private development history). Not pushed.

## B. Scope contract

Before: every tool required `project` and `namespace`; a managed connection's server trusted whatever scope its
launch arguments named; hooks defaulted to the personal scope from their own arguments.

Now:

- Each connection grant stores its scope (control database schema v2; v1 databases are upgraded in place and bound
  to the personal scope, the only scope the app ever granted).
- A managed server takes its scope from the authenticated grant and **refuses to start** (exit 3) if its launch
  arguments name another scope. Hooks return nothing on a mismatch.
- `project`/`namespace` are optional on all six tools. Omitted means the bound scope; any other value is refused
  with a message that keeps the old "unavailable" wording (v0.2 clients unchanged) and names the bound scope.
- Servers without a connection (v0.2 entries, the demo) still need both values and stay read-only.

Security regression tests (`tests/integration/test_mcp_scope_binding.py`, official SDK over real stdio): optional
arguments in every tool schema; omitted and exact scope work; other project, other namespace, and a guessed
`default` scope are refused for reads and writes; a memory in another project of the same database cannot be found,
read, listed in history, updated, or retracted; a grant bound to another project serves only that project; a
mismatched launch scope exits 3; legacy servers still need and enforce their scope; hooks ignore mismatched scopes;
v1 → v2 migration.

**Defect found and fixed:** connection tokens come from `secrets.token_urlsafe`, so about 1 in 64 started with
`-`. Session hooks pass the token as `--token <value>`, which argparse then rejected, so the hook failed on every
prompt for that connection. Hooks now use `--token=<value>`, and new tokens never start with `-`. Regression test:
`tests/unit/test_hook_command_line.py`.

## C. Codex compatibility

Full report: [Codex support](codex-support.md). Summary for Codex CLI 0.162.1, local mock model, no paid calls:

| Stage | Function-tool models | Catalog models (code mode) |
|---|---|---|
| 1. Server start | Pass (warm frozen 0.64–0.67 s; source 0.84–0.88 s) | Pass |
| 2. `tools/list` | Pass (6 tools) | Pass |
| 3. Tools shown to the model | Pass | **Fail**: tools and server instructions withheld |
| 4. Tool call | Pass | Pass only when the model already knows the tool name |

A cold first launch of the freshly built frozen server missed Codex's default 1-second startup grace. Matching open
Codex issues: #32101, #24536, #55512; nothing in 0.164.0 (latest stable, not tested). BIO CE changes, all
through official mechanisms: optional scope arguments (the earlier real-model run failed on a guessed scope); a
Codex-only hint in the user-trusted session-start hook (not verified with a real model); and the app now
distinguishes **Connected** from **Auto memory in this host: Available / Limited**, including the dashboard pill, the
consent dialog, and diagnostics. No unofficial Codex setting is applied by default, and no approval, sandbox, or
hook-trust check is bypassed.

## D. Installer E2E (v0.3.0-rc1 installer, not RC1)

`tests/host_harness/install_e2e.py`, started through `explorer.exe` so it runs outside the MSIX container that
redirects new `%LOCALAPPDATA%` folders (see the v0.2 report). It refuses to start when BIO CE is installed or data
exists, uses isolated Codex/Claude profiles, and removes only what it created. Installers ran silently. **The GUI
was verified by window capture only:** the user was actively working, so no keyboard or mouse input was injected.

| # | Step | Result |
|---|---|---|
| 1 | Preflight: no install, data, shortcut, or uninstall entry; process not packaged | Pass |
| 2 | Install v0.2.0-rc1 (standard user, no UAC) | Pass |
| 3 | v0.2-format data (memory schema v1, settings v1, revision 2, Hangul; no control DB) | Pass |
| 4 | Update to v0.3.0-rc1 over v0.2 | Pass: 2,566/2,566 installed files match the build manifest; uninstall entry 0.3.0-rc1 |
| 5 | v0.2 data untouched by the update | Pass: byte-identical, `integrity_check` ok, `user_version` 1 |
| 6 | Installed GUI opens the v0.2 data | Pass (captured; exit 0) |
| 7 | First-run notice in a fresh profile; closing it creates nothing | Pass |
| 8 | Claude Code connection via the installed `BIO-CE-MCP.exe` (real `claude mcp add`, SDK check) | Pass, Read only by default |
| 9 | Auto memory on: approvals limited to BIO CE's six tools | Pass |
| 10 | Session hooks installed | Pass |
| 11 | Claude Code (mock model) creates a memory through the installed exe; hook context reached the model | Pass; provenance host/connection/evidence recorded |
| 12 | Conflicting update goes to the review queue, memory unchanged; recent AI activity shows create + queued | Pass |
| 13 | Paused: hook context suppressed, tool call refused | Pass |
| 14 | Disconnect revokes: entry, hooks, approvals removed; old token refused (server exit 3) | Pass |
| 15 | GUI after AI activity | Pass (AI-created memory listed) |
| 16 | Silent uninstall keeps memories and settings; program, shortcut, uninstall entry removed | Pass |
| 17 | Reinstall v0.3.0-rc1: manifest match, data byte-identical | Pass |
| 18 | GUI after reinstall, no first-run notice | Pass |
| 19 | Cleanup: machine back to its pre-test state | Pass |

Not covered by this run: the interactive wizard and the uninstall data prompt (verified for RC1 through the real GUI;
unchanged since), GUI click paths for CRUD/review/pause (covered by the real-Tk UI tests against the same code),
and Codex through the installed build (covered by the stage probe against the frozen server).

The first attempt stopped on a harness bug (the mock model was started with the installed app's path) and was
cleaned up with the harness's cleanup mode before the passing run.

## E. Final verification

| Check | Result |
|---|---|
| `pytest -q tests` | **96 passed, 62 subtests, 0 skipped** on official CPython 3.12.10 and on the dev interpreter; includes the packaged-EXE SDK test against the RC build |
| Official MCP SDK | Real stdio server in `test_mcp_stdio`, `test_auto_memory_scenarios` (14 scenarios), `test_mcp_scope_binding`, `test_packaged_mcp_exe` |
| GUI | Real-Tk tests (`test_desktop_ui*`, `test_auto_memory_ui`, incl. the Limited/Available display); installed-GUI captures above |
| Secrets and prompt injection | Refused and not stored, queued, or logged (scenarios 6–7, policy unit tests) |
| Duplicate, conflict, correction | Scenarios 2–4 and 11; installer E2E step 12 |
| Permissions and scope isolation | Scenarios 9–10, scope-binding tests, installer E2E steps 13–14 |
| Gitleaks 8.18.4 | 0 findings: 99-file candidate tree and full history |
| Privacy | 0 account, email, machine, or local-path strings in the candidate tree; binary scan of 2,568 payload/installer files (ASCII + UTF-16, positive control) 0 hits |
| Licenses | No dependency changes since RC1; `THIRD_PARTY_NOTICES` 351,466 bytes (same coverage as RC1); no UCRT DLLs bundled |
| Artifact consistency | Installer SHA-256 = `SHA256SUMS.txt` = `build-manifest.json`; 2,566/2,566 payload files match the manifest; installed copy matched twice |
| Real-model evidence | The earlier Claude/Codex evaluation is kept unchanged ([evaluation](real-model-memory-evaluation.md)); no new model calls |

## Artifact

| File | Bytes | SHA-256 |
|---|---:|---|
| `dist/0.3.0-rc1/BIO-CE-Setup-v0.3.0-rc1.exe` | 44,239,477 | `44bc95da709d2d6ee2e3ef16ed7c99f37968c3f5862058ab23a004bba715884b` |

Unsigned (`NotSigned`). Payload 2,566 files, 114,489,934 bytes; per-file hashes in
`build/0.3.0-rc1/build-manifest.json`. The v0.2.0-rc1 and 0.3.0-dev0 artifacts were left unchanged.

## Remaining BLOCKERS before a public release

1. **Clean Windows account/VM E2E** (no Python/Git, standard user), including the interactive wizard and GUI click
   paths for the v0.3 features. Needs an administrator to create the account, or a VM.
2. **Codex Auto memory** depends on an upstream Codex fix (code mode hides MCP tools). Re-run the stage probe on
   0.164.0+; a user-approved paid run would show whether the hook hint helps in the meantime.
3. **Real-model sample size**: one short synthetic conversation per host. A larger, approved evaluation is needed
   before claiming Auto memory quality.
4. Code signing, or an explicit decision to ship unsigned.
5. Windows 10 and real (not simulated) 125%/150% scaling, if they are to be claimed.
6. GitHub Actions CI, and the BIO Core source-provenance item that remains PARTIAL from v0.1.

Evidence (ignored, local only): `.test-tmp/v03-stabilization/` (probe logs, installer E2E results and captures,
Gitleaks reports, build log).
