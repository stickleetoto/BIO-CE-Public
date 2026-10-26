<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Codex CLI Support Status (BIO CE v0.3.0-rc1)

Date: 2026-10-24 · Codex CLI 0.162.1 (installed, tested) · Latest stable Codex release: 0.164.0 (2026-10-23, **not tested**)

**Status: Connected — Auto memory LIMITED.** BIO CE registers with Codex, Codex starts BIO CE's server and lists
its tools, and tool calls succeed. Codex's standard (catalog) models, however, run in *code mode*, which shows the
model neither BIO CE's tools nor BIO CE's server instructions. A model that is not told the tools exist rarely uses
them, so Auto memory cannot be relied on in Codex today. The desktop app shows this as **Auto memory: Limited**,
separately from the connection state.

## Four stages, measured separately

Method: `tests/host_harness/codex_stage_probe.py`. Real Codex CLI 0.162.1 with `--ignore-user-config`, an isolated
`CODEX_HOME`, hooks disabled, and no sandbox or hook-trust bypass. The model API is the local scripted mock
(`mock_model_server.py`), so **no model was called**. A JSON-RPC relay (`mcp_traffic_log.py`) records what passed
between Codex and the server: methods, timing, tool names, and argument *names* only. Each variant used a fresh
synthetic database with an Auto memory grant.

| Variant | 1. Server start (`initialize` answered) | 2. `tools/list` | 3. Tools shown to the model | 4. Tool call executed |
|---|---|---|---|---|
| Model unknown to Codex (function-tool mode), defaults | Pass | Pass (6 tools) | **Pass** (`mcp__bio_ce` namespace, with server instructions) | **Pass**, direct call |
| Same, `mcp_optional_startup_grace_ms=5000` | Pass | Pass | Pass | Pass |
| Catalog model `gpt-6.1-sol` (code mode), defaults | Pass | Pass | **Fail**: not declared; server instructions absent | Pass **only** when the model already knows the name (`tools.mcp__bio_ce__bio_memory_search` inside `exec`) |
| Catalog model, grace 5000 ms | Pass | Pass | Fail | Same as above |
| Catalog model, `--enable code_mode_tool_search` (under development; diagnostic only) | Pass | Pass | Fail | Same as above |

All calls in stage 4 sent only `query` — no `project`/`namespace` — and succeeded (see "Scope arguments" below).

**Server startup vs. Codex's first turn.** Codex waits `mcp_optional_startup_grace_ms` (default 1000 ms) for
optional servers before the first model request.

| Server | `initialize` answered after |
|---|---|
| Source (`python -m bio_ce`, CPython 3.12.10) | 0.84–0.88 s |
| Frozen `BIO-CE-MCP.exe` (v0.3.0-rc1), warm | 0.64–0.67 s (4 runs) |
| Frozen `BIO-CE-MCP.exe`, **first launch after build** (cold file cache and antivirus scan) | not answered before the turn ended — tools absent from that first turn |

Warm starts fit the default grace period; a cold first start can miss the first turn.

## Cause

In Codex 0.162 every catalog model has `tool_mode = "code_mode_only"`. Codex sends such models their tools in an
`additional_tools` input item: one `exec` tool (JavaScript) whose description lists the built-in nested tools.
MCP tools are treated as *deferred*: they exist on the `tools` object inside `exec`, but they are not listed, and
the MCP server's `instructions` are not sent. Code mode also drops the `tool_search` primitive. Codex's `exec`
description mentions `ALL_TOOLS`, which a model can inspect, but nothing prompts it to look for BIO CE.

Public reports (all **open**, no maintainer response or fix as of 2026-10-24):

- [openai/codex#32101](https://github.com/openai/codex/issues/32101): code mode omits `tool_search` from `exec`,
  degrading deferred MCP discovery (reported on 0.144–0.153).
- [openai/codex#24536](https://github.com/openai/codex/issues/24536): `codex exec` silently completes empty when MCP
  tools are deferred behind `tool_search` (0.133; also Windows Desktop).
- [openai/codex#55512](https://github.com/openai/codex/issues/55512): MCP tools unreachable; tool search fails with
  "unsupported call" (0.160.1, 0.163.0, including Windows).

The 0.164.0 release notes mention MCP authentication and Windows environment fixes but nothing about code mode,
deferred tools, or tool search.

## What BIO CE changed (safe, official mechanisms only)

1. **Scope arguments are optional** on every tool, and the server's scope comes from the connection's grant. In
   the earlier real-model run, Codex's model guessed `project="default"` and was refused with a message that didn't
   name the valid scope. Calls may now omit both values, and a refusal names the bound scope.
2. **Session hook hint (Codex only).** When the user installs BIO CE's session hooks and trusts them in Codex
   (`/hooks`), the session-start context now tells the model where BIO CE's tools are
   (`tools.mcp__bio_ce__bio_memory_search`, `ALL_TOOLS`). Hook context is the only BIO CE text a code-mode model
   still receives. **Not verified with a real model** (needs user-trusted hooks and a paid model run).
3. **Honest status in the app.** The Connections page shows *Auto memory in this host: Limited* for Codex, with the
   reason. The dashboard pill reads "Auto memory (limited)". Turning Auto memory on for Codex says so before asking
   for consent, and diagnostics include a "Model access" line.

## Deliberately not applied

| Option | Why not |
|---|---|
| `features.code_mode.direct_only_tool_namespaces = ["mcp__bio_ce"]` | Community workaround from #32101, not documented as a supported setting, wildcards unsupported. It would also change how Codex treats tools globally for the user. |
| `--enable code_mode_tool_search` | Marked under development; it did not expose BIO CE's tools in the probe, and #55512 reports tool search failing on 0.163. |
| `required = true` for the BIO CE server | Did not expose the tools in code mode, and Codex then refuses to start whenever BIO CE is unavailable. |
| `--dangerously-bypass-hook-trust`, approval or sandbox bypasses | Not used by the product or by these probes. Users approve hooks themselves. |
| Raising `mcp_optional_startup_grace_ms` globally | Not needed for warm starts; it is a global Codex setting that BIO CE should not change. |

## Safe paths forward

- Re-run `codex_stage_probe.py` on each new Codex release (start with 0.164.0) and change the app's support level
  only when stage 3 passes for catalog models.
- With user approval for paid model calls: one Codex session with BIO CE hooks installed and trusted by the user,
  to see whether the hint makes the model use BIO CE.
- Until then, Codex users can ask for BIO CE explicitly in a prompt ("check BIO CE memory"). This is guided use,
  not Auto memory.
