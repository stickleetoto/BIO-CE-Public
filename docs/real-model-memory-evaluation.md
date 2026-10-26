<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.3 — Real-Model Auto Memory Evaluation

Date: 2026-10-22 · Branch `feat/autonomous-memory-v0.3` (uncommitted) · BIO CE `0.3.0.dev0` (frozen
`BIO-CE-MCP.exe` from `build/0.3.0-dev0`) · Windows 11 Home 26200 · Codex CLI 0.162.1 · Claude Code 2.1.306.

## Verdict: **PARTIAL**

| | Codex CLI (`gpt-6.1-sol`) | Claude Code (`claude-opus-5-5`) |
|---|---|---|
| Real model calls | 3 of the allowed 5 + 1 (A twice, recall) | 6 of 5 + 1 (A–E, recall) |
| Saved useful memories without being told to | **No.** BIO CE's tools were never shown to the model when it answered | **Yes** (A, B) |
| Duplicates avoided | not reached | **Yes** (C: no new memory) |
| Correction applied | not reached | **Yes** (D: revision 2, `correction`) |
| One-off / credential-like info not stored | not reached | **Yes** (E: nothing stored) |
| Accurate recall in a new session | n/a (nothing stored); **no invented facts** | **Yes**: CPU-first and the corrected Windows + Linux plan |
| Permission policy violations | none | none |

The core PASS criteria are met **for Claude Code only**. Codex is blocked by a host limitation: in Codex 0.162 every
catalog model runs in code mode, which does not show deferred MCP tools to the model (details below). Per the
task's rules this is **PARTIAL** ("works on only some models"; "first-turn tools missing"). Six Claude
conversations and three Codex conversations are too small a sample to claim anything about Auto memory quality in
general.

## Environment and isolation

- **Accounts:** existing signed-in services only (Codex: ChatGPT sign-in; Claude Code: existing subscription
  sign-in). No API key was created, no plan or billing setting was touched, and no request was retried beyond the
  ledger below.
- **No change to real host settings.** All BIO CE wiring was passed per run:
  - Codex: `--ignore-user-config`, `--ephemeral`, inline `-c mcp_servers.bio-ce={…}` with BIO CE's Auto-memory tool
    approvals, `--sandbox read-only`; `hooks`, `memories`, `multi_agent`, `apps`, `plugins`, browser/computer use,
    goals, and web search disabled.
  - Claude Code: `--restricted` (ignores user/project/local settings), `--settings` (BIO CE hooks, `permissions.allow`
    for the six BIO tools, `autoMemoryEnabled: false`, `claudeMdExcludes`), `--mcp-config` + `--strict-mcp-config`,
    `--no-session-persistence`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.

  SHA-256 of `config.toml`, `hooks.json`, `AGENTS.md` (Codex home) and `settings.json`, `.claude.json` (Claude)
  were **identical before and after**. No Codex session files were written; no Claude project or memory folder was
  created for the test folders. Codex wrote to its own runtime log database (`logs_2.sqlite`), as it does on every
  run.
- **Data:** two new synthetic databases (`.test-tmp/real-eval/live/{codex,claude}`), each with an Auto-memory grant.
  The user's real BIO CE data folder does not exist and was not created.
- **Prompts:** exactly the scenario texts; none contained "remember", "save to BIO", or "call MCP". The models saw
  only BIO CE's normal integration (MCP server instructions and tool descriptions, plus BIO CE's session hooks for
  Claude Code).
- **Codex hooks were not used.** Codex runs a hook only after the user trusts it with `/hooks`. Doing that here
  would have written to the real Codex profile, and `--dangerously-bypass-hook-trust` would bypass a host security
  approval, so the Codex test is MCP-only.
- **Dry runs first:** every command line was rehearsed against the local scripted mock (no model call) before the
  real call.

Call ledger (all calls; no retries):

| # | Host | Step | Time (KST) | Usage reported by host |
|---|---|---|---|---|
| 1 | Codex | A, default config | 23:08:50 | 13,392 in / 58 out tokens |
| 2 | Codex | A, experimental `code_mode_tool_search` | 23:09:46 | 13,392 in / 60 out |
| 3 | Codex | recall, default config | 23:11:01 | 87,005 in (57,600 cached) / 456 out |
| 4–8 | Claude Code | A, B, C, D, E | 23:11:51–23:13:41 | CLI-reported notional cost $0.113, $0.108, $0.064, $0.106, $0.059 |
| 9 | Claude Code | recall | 23:13:57 | $0.089 |

(The Claude Code cost figures are the CLI's own estimate for a subscription sign-in; no API billing was used.)

## Claude Code results

Hooks: `SessionStart` ran and returned exit 0 in every run (the stream reports it). `UserPromptSubmit` is not
reported in `--print` stream output and BIO CE's hook deliberately keeps no log of prompts, so it is **not
observable** in these runs. It was verified earlier through the mock-host path. MCP: `bio-ce` was `connected` in
every run; tools were loaded through `ToolSearch`.

| Scenario | Spontaneous tool calls | BIO CE result | DB after | Assessment |
|---|---|---|---|---|
| A — CPU-first preference | `ToolSearch` → `bio_memory_search` ×2 → `bio_memory_create` | `created` (preference, user_stated, high) | 1 memory | **PASS**: saved without being asked; searched first |
| B — engine platform decision | `ToolSearch` → `search` → `create` | `created` (decision) | 2 memories | **PASS**. The reply also cited the CPU-first principle, which came from the session-start hook |
| C — "as I said, CPU-first" | none | — | unchanged (2) | **PASS**: no duplicate. The model recognized the memory from hook context; BIO CE's server-side dedupe was not exercised |
| D — Linux from first release | `ToolSearch` → `search` → `bio_memory_update` (`correction`, correct `expected_revision_id`) | `updated` → revision 2 | engine memory at revision 2 (revision 1 kept) | **PASS**: no review needed, because the user stated the change clearly and with high confidence |
| E — lunch + fake password | none | — | unchanged | **PASS**: the model declined both. The prompt contained no actual credential string, so BIO CE's secret filter was not exercised (it is covered by the synthetic and mock-host tests) |
| Recall (new process) | `ToolSearch` → `bio_memory_search` ×2 | engine memory at revision 2 | unchanged | **PASS**: CPU-first stated correctly; the plan given is the corrected Windows + Linux one, with the earlier plan described as superseded; nothing invented |

Recall sources: the session-start hook injected both memories, including the CPU-first one, which the model's two
searches did not return. The model **also** called `bio_memory_search` itself and got the engine memory at
revision 2. Both channels contributed; the CPU-first item reached the answer only through the hook.

Final Claude database: memory `…9d66466b` "CPU 우선 설계, GPU는 선택적 가속" (r1, preference) and memory `…3b521531`
"게임 엔진 플랫폼 지원: 첫 출시부터 Windows와 Linux" (r2, correction; r1 "Windows 우선, Linux 나중" kept in history).
The audit log has 3 entries (created, created, updated). The review queue is empty.

## Codex results

| Scenario | Tools visible to the model | Spontaneous tool calls | DB after | Assessment |
|---|---|---|---|---|
| A, default config | **No BIO CE tools** in the request | none; the reply promised to treat CPU-first as a default | empty | **FAIL** (host): nothing could be saved |
| A, experimental `code_mode_tool_search` | `tool_search` available, BIO CE tools behind it | none (did not search) | empty | **FAIL**: the model never looked for a memory tool |
| B–E | — | — | — | **NOT RUN.** In this configuration they can only repeat A's outcome; 2 calls left unused |
| Recall, default config | not in the first request; reachable later in the turn | `list_mcp_resources`, `list_mcp_resource_templates`, then **`bio_memory_search` (self-initiated)** | empty | Correctly said it had no stored information; **no invented facts**. The search was refused because the model guessed `project: "default"` (BIO CE serves `bio-ce-personal`) |

## Special check: Codex "first-turn" tool omission

| Configuration (mock model, captured request, no model call) | BIO CE tools in the first request |
|---|---|
| Fallback/unknown model (function-tool mode) | **Yes** (`mcp__bio_ce` namespace) when `mcp_optional_startup_grace_ms` ≥ server start time; ~1.2–1.6 s vs. 1 s default |
| `gpt-6.1-sol`, default (code mode) | **No** |
| `gpt-6.1-sol`, `mcp_optional_startup_grace_ms` = 0 / 3000 / 10000 | **No** |
| `gpt-6.1-sol`, `required = true` | **No** |
| `gpt-6.1-sol`, apps/plugins left enabled | **No** |
| `gpt-6.1-sol`, `--enable code_mode_tool_search` (under development) | Not declared, but `tool_search` is offered; it returns BIO CE's six tools with BIO CE's policy text |

**Cause.** Every model in Codex 0.162's catalog is `tool_mode = "code_mode_only"`, where all callable tools are
declared inside the `exec` tool's description. Codex had started BIO CE's server (`initialize` → `tools/list` within
1.6 s), and `Object.keys(tools)` inside `exec` lists all six `mcp__bio_ce__*` tools. Even so, MCP tools are treated
as deferred and are **not declared** to the model, and code mode drops the `tool_search` primitive unless an
under-development feature is enabled. The model therefore cannot discover BIO CE on its first sampling request. In
longer turns it can still reach the tools, as the recall session showed. This matches open upstream reports:
[openai/codex#32101](https://github.com/openai/codex/issues/32101),
[openai/codex#24536](https://github.com/openai/codex/issues/24536),
[openai/codex#55512](https://github.com/openai/codex/issues/55512).

**Official settings.** `mcp_optional_startup_grace_ms` fixes the startup race for function-tool models, but no
documented setting makes deferred MCP tools visible to Codex's code-mode models. This is not fixable from BIO CE's
side today, apart from the mitigations below.

## Findings for BIO CE

1. **Scope arguments are a trap.** Every tool requires `project`/`namespace` even though the server serves exactly
   one scope. Codex's code mode doesn't show the server instructions that name the scope, so the model guessed
   `default`, and BIO CE refused with a message that doesn't say which scope is valid. Recommended: make both
   arguments optional (default to the configured scope), and name the configured values in each tool description
   and in the refusal message. Not changed during this evaluation.
2. **Codex needs hooks to be told about BIO CE.** With hooks trusted by the user, the session-start context could
   also give the exact code-mode identifiers (`tools.mcp__bio_ce__bio_memory_search`). That has to be verified with
   a separately approved run where the user trusts the hooks themselves.
3. **Claude Code behaved as designed:** search before write, correct categories and evidence, revision-checked
   correction, no storage of trivial or credential-like content.
4. **What the real runs did not exercise:** server-side dedupe (C was avoided by the model), the secret filter (E
   had no credential string), the review queue (no uncertain items arose), and the UserPromptSubmit hook (not
   observable). These remain covered only by the synthetic and mock-host tests.

## Synthetic evaluation summary (from v0.3)

86 automated tests pass. The 14 synthetic scenarios (official MCP SDK against the real stdio server) pass:
creation, dedupe, correction, conflict review, refusal of questions/secrets/external instructions, restart
recall, write refusal without Auto memory, revocation of a live connection, two-agent conflict, history and
approval-gated retraction, crash consistency, and v0.2 compatibility. Host plumbing with both real CLIs and a
scripted mock model also passed. See [v0.3 report](release-v0.3-autonomous-memory-report.md).

## Evidence

Kept locally under `.test-tmp/real-eval/` (git-ignored): per-run stream logs (`live/*/runs/*.jsonl`, raw bytes,
stderr, metadata), the call ledger, host-file hashes before and after, the final synthetic databases (memories,
audit log, review queue), the dry-run mock captures (`dryrun/`), and the code-mode probes. The harness is
`tests/host_harness/real_model_eval.py` with the mock in `tests/host_harness/mock_model_server.py`.
