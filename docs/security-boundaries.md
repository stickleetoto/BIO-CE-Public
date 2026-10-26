<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Security Boundaries

## Guarantees implemented

- The MCP process binds one local database and exactly one project/namespace pair at startup. A connection made
  by the desktop app takes that pair from its authenticated grant; a server without a connection takes it from its
  launch arguments. Requests may omit the pair; any other pair is refused. Identifiers and text are length- and
  format-checked.
- Each desktop-app connection has its own random token (only its SHA-256 is stored) and a mode: **Read only**
  (default), **Auto memory**, or **Paused**. The grant is re-read on every tool call, so pausing or disconnecting
  applies to running sessions. Servers without a connection (v0.2 entries) are read-only.
- The adapter registers six tools: `bio_memory_search`, `bio_memory_read`, and `bio_memory_history` for reading,
  and `bio_memory_create`, `bio_memory_update`, and `bio_memory_retract`, which work only in Auto memory mode.
  Writes pass BIO CE's memory policy (secrets, document- or tool-sourced content, and injected instructions are
  refused) and run in one revision-checked `BEGIN IMMEDIATE` transaction each. Uncertain or conflicting changes
  and every retraction wait in the user's review queue; AI writes are recorded in a local activity log.
- Reads use a separate SQLite `mode=ro` connection.
- Retractions append a tombstone, leave the active FTS view, and block current and historical API reads.
- A selected search/read snapshot is revalidated in a fresh SQLite transaction before results return. A revision change or retraction observed at that final check causes a fail-closed retry error.
- The stdio adapter does not start an HTTP server or network listener. MCP frames use stdout; storage diagnostics are generic and go to logging.

## Limits

Scope strings never authenticate anyone. Connection tokens live in plain text in the host's user configuration, so they protect against an AI host doing more through BIO CE's tools than the user allowed, not against other programs running as the same Windows user. Security against other local processes depends on Windows account permissions, process isolation, and filesystem ACLs. The memory policy's secret and injection checks are heuristics, and the host model's own judgment comes first.

The freshness check defines a read's linearization point at the first SELECT of its final validation transaction. A write committed before that point is observed and blocks the read. A write committed after it is ordered after the read, even if response delivery occurs later. Strict real-time revocation at tombstone commit is not promised.

Retraction is not secure erasure: historical rows remain in SQLite and can be inspected by a process with direct database access. The preview has no encryption at rest, key management, authorization server, network transport, external audit sink, backup lifecycle, or production availability guarantee.

BIO CE never reads host transcripts or records conversations. Memories enter BIO CE only when the user saves them or when a host the user switched to Auto memory calls a write tool. See [Auto Memory](auto-memory.md).

## Verification boundary

Unit and SDK subprocess tests validate the listed behavior against synthetic databases. They are not a penetration test, deployment assessment, or Windows 10 run. A short real-model check is described in the [real-model evaluation](real-model-memory-evaluation.md). Report vulnerabilities as described in the [security policy](../SECURITY.md). See the dated [public release-gate audit snapshot](audit/public-release-gates.md), and check GitHub directly for live repository state. The [CE-7 qualification report](audit/CE-7-report.md) is a historical snapshot and does not describe the current GitHub state.
