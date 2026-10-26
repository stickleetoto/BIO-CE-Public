<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.3 Autonomous Memory — Development Report

Date: 2026-10-22 · Branch `feat/autonomous-memory-v0.3` (from the preserved v0.2.0-rc1
state on `feat/desktop-oneclick-v0.2`) · Version `0.3.0.dev0` · Windows 11 Home 26200, official CPython 3.12.10.
Nothing was pushed, released, or made public. **No AI model was called.** BIO Core was not touched. Only
synthetic data was used.

## Verdict

| Layer | Status |
|---|---|
| Implementation (Phases 1–5) | **Done** |
| Synthetic verification: official MCP SDK client scripted as a host, 14 scenarios | **Pass** |
| Host plumbing with the **real** Codex CLI 0.162.1 and Claude Code 2.1.306, model replaced by a scripted local mock | **Pass** |
| A real model deciding on its own to save, update, and recall memories | **NOT VERIFIED**, needs your approval for model calls |
| Installer E2E of the v0.3 build on a clean machine | **NOT RUN** (dev installer built only) |

## What was built

| Phase | Result |
|---|---|
| 1. MCP write API | `bio_memory_search`, `_read`, `_history`, `_create`, `_update`, `_retract` on the existing `SQLiteMemoryStore`. Writes are single `BEGIN IMMEDIATE` transactions with revision checks; retraction keeps its meaning (tombstone, not secure erase). The memory schema is unchanged (v1). Host, connection, category, confidence, evidence, and reason go into each revision's source metadata. |
| 2. Memory judgment | The host's model decides (no extra LLM). `bio_ce/memory_policy.py` enforces: secrets refused; document/tool-sourced content refused; injected instructions refused; low confidence, trivial text, and questions refused; duplicates detected; uncertain items, credential mentions, conflicts, and all retractions go to review; clear corrections update. Policy text is delivered via MCP server instructions, tool descriptions, and session hooks. |
| 3. Host integration | `SessionStart` + `UserPromptSubmit` hooks for both hosts (`BIO-CE-MCP.exe hook …`): memory policy and related memories at session start, prompt-based recall per message. The prompt is never stored or logged. Auto memory pre-approves only BIO CE's six tools in each host (Codex `approval_mode`, Claude Code `permissions.allow`). See [Auto Memory](auto-memory.md) for what does not work without hooks. |
| 4. Permissions | Per-connection ID + random token (hash stored); modes Read only (default) / Auto memory / Paused; revocation on disconnect; grant re-checked on every call; v0.2 tokenless entries stay read-only; 30 changes/hour rate limit; separate `control.sqlite3` for grants, audit log, and review queue. |
| 5. Desktop UI | Connections page: access mode per host (with consent dialog), session hooks toggle, legacy **Reconnect**, **Needs your review** (approve / edit and approve / reject), **Recent AI activity** (opens the memory), **Pause all AI access**. Dashboard pills show the mode; first-run, Settings, and Dashboard wording updated. v0.2 design kept. |

## Synthetic scenarios (official MCP SDK, real stdio server, `tests/integration/test_auto_memory_scenarios.py`)

| # | Scenario | Result |
|---|---|---|
| 1 | New user preference stored | PASS (`created`, provenance metadata recorded) |
| 2 | Same content repeated / reworded | PASS (`duplicate`, same memory ID) |
| 3 | Clear correction of a decision | PASS (`updated`, revision 2) |
| 4 | Ambiguous conflict | PASS (`queued_for_review`, memory unchanged); stale revision → `conflict` |
| 5 | One-off question, greeting, guess | PASS (`rejected`) |
| 6 | API key and Korean password | PASS (`rejected`; not in memory DB, review queue, or audit log; titles of secret proposals not logged) |
| 7 | Instruction from an external document / injected instruction | PASS (`rejected`) |
| 8 | Recall after server restart; hooks recall it | PASS (session-start and per-prompt context contain it; prompt not echoed) |
| 9 | Writes with Auto memory off | PASS (refused in Read only; Paused refuses reads too) |
| 10 | Revocation on an already-open connection; wrong token | PASS (next call refused; server refuses to start with a bad token) |
| 11 | Two agents update the same memory concurrently | PASS (one `updated`, one `conflict`; history has exactly 2 revisions) |
| 12 | History kept; retraction | PASS (retract only queued; applied after user approval; assertion → revision → retraction rows kept) |
| 13 | Writer process killed mid-stream | PASS (`integrity_check` ok, no orphaned rows, writes continue) |
| 14 | v0.2 database and v0.2 host entry | PASS (reads work, writes refused, `user_version` still 1, no control DB needed) |

Also covered: review approval with user edits, hook silence when paused or revoked, hook config merging that keeps
other users' hooks, policy unit rules, and Auto-memory UI controls against a real control database.

## Host plumbing with real host CLIs (model replaced by a local scripted mock)

Both CLIs were pointed at `tests/host_harness/mock_model_server.py` on `127.0.0.1` using their supported
custom-endpoint settings, in isolated profiles (`CODEX_HOME`, `CLAUDE_CONFIG_DIR`). The mock records each request
and answers with one scripted tool call. **This proves the hosts run BIO CE's hooks and tools; it says nothing about
a real model's choices.** Codex's `--dangerously-bypass-hook-trust` was used for these test runs only, because they
used hooks generated moments earlier; real users approve hooks with `/hooks`.

| Check | Codex CLI | Claude Code |
|---|---|---|
| Connect via BIO CE (token in host env), default Read only | PASS (via the desktop GUI) | PASS (via the same manager API) |
| Auto memory on: approvals written, other entries kept, backup made | PASS (GUI) | PASS |
| `SessionStart` hook ran; its context reached the model request | PASS | PASS (`hook_response` events) |
| `UserPromptSubmit` hook context reached the model request | PASS | PASS |
| MCP server instructions (policy) reached the model | PASS (namespace description) | Tools listed; deferred behind `ToolSearch` |
| Host executed `bio_memory_create` through BIO CE | PASS (`created`, later `duplicate` on repeat) | PASS (`ToolSearch` → `created`, no permission prompt) |
| New session recalls the memory (hook context + `bio_memory_search`) | PASS | — |
| Secret proposed through the host | — | PASS (`rejected`, not stored) |
| Connection paused in BIO CE while the host config is unchanged | — | PASS (call refused) |

Findings that shaped the design:
- Codex prompts for MCP tool calls by default. Without BIO CE's per-tool approvals, writes failed under
  `approval_policy = never`. Hence the approvals that Auto memory adds and removes.
- Codex waits only `mcp_optional_startup_grace_ms` (default 1000 ms) before the first turn. BIO CE's server is
  ready in 1.22 s (frozen) / ~1.3–1.6 s (source), so the BIO tools can miss the first turn; the test runs set
  `-c mcp_optional_startup_grace_ms=5000`. Registering BIO CE as `required` would make Codex fail to start whenever
  BIO CE is unavailable, so it was not done. Documented as a known limitation.
- Claude Code exposes MCP tools through `ToolSearch`; the session-start context names the BIO CE tools so a model can
  find them.

## Frozen build

`dist/0.3.0-dev0/BIO-CE-Setup-v0.3.0-dev0.exe`
(SHA-256 `38dfd069c50f11f332001f766607f3129ab56d617b5d82794427ebfb6f13cd0a`, unsigned, development build).
Build output now defaults to version-specific folders, so the v0.2.0-rc1 artifacts in `dist/release` were left
untouched (their SHA-256 re-verified). With Python removed from `PATH`, the frozen `BIO-CE-MCP.exe`:
exposed six tools; authenticated the token and stored a policy-checked memory; refused calls after revocation;
refused to start with a wrong token; and its hook recalled a Korean memory from UTF-8 stdin. The packaged-EXE
SDK test passed against it. The installer itself was not run in this pass.

## Tests and scans

- `pytest -q tests`: **86 passed**, 44 subtests (including the packaged-EXE SDK test against the v0.3 build).
- Real-CLI connection tests (`test_host_connections`, isolated profiles): connect → Read only default →
  Auto memory with approvals → Read only removes approvals → hooks install → disconnect revokes the grant, removes
  hooks and approvals, and keeps other MCP entries. Pass for both hosts.
- Gitleaks 8.18.4: 0 findings on the 89-file candidate tree and the 4-commit history. Two synthetic look-alike
  credentials in tests were rewritten to be assembled at run time.

## To verify next (needs your decision)

1. **Real model run (paid usage).** With your approval: one Codex session and one Claude Code session in isolated
   profiles with Auto memory and hooks on. Use a short synthetic conversation: state a preference, correct it, and
   paste a fake key. Check what was saved, refused, or queued, and that a new session recalls it.
2. Install the v0.3 installer through the real GUI (as done for RC1) and repeat the connection flow from the
   installed app.
3. Decide whether to suggest raising Codex's `mcp_optional_startup_grace_ms` to users, or to reduce BIO CE server
   startup below 1 s.
