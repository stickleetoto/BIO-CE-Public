<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# MCP Integration

BIO CE uses the official Python MCP SDK and stdio transport. At startup, the server opens one existing SQLite database in read-only URI mode and is bound to exactly one project and namespace. A server started by a desktop-app connection takes that scope from the connection's grant (v0.3); a server without a connection (v0.2 entries, the synthetic demo) takes it from `--project` and `--namespace`.

**The desktop app does not need to be running.** Codex and Claude Code start BIO CE's MCP server
(`BIO-CE-MCP.exe mcp-stdio`) themselves; it opens the database directly. You can close the BIO CE app: connected AI
tools keep using your memories.

**Server lifetime (0.4.1).** A server ends when its host closes stdin or when the process that started it ends.
Hosts that keep one server per conversation open, such as the Codex desktop app, do not start a new server if it
ends on its own, so an idle server is not ended (`BIO_CE_MCP_IDLE_SECONDS` can set a limit; the default `0` means
none). Instead, after 60 seconds without a request (`BIO_CE_MCP_RELEASE_SECONDS`) it closes its database
connections and folds the write-ahead log back into the database file, so it does not block a restore or an
upgrade; the next request opens them again. A request in progress always finishes first.

## Exposed tools

| Tool | Inputs | Output |
|---|---|---|
| bio_memory_search | lexical query, limit 1–50, optional project/namespace | scoped current hits with memory ID, revision ID, rank, score, preview, source metadata, and time fields |
| bio_memory_read | memory ID, optional revision ID, optional project/namespace | one active current or selected historical revision with ID, revision number, content, provenance, and time fields |
| bio_memory_history | memory ID, optional project/namespace | every revision of a current memory |
| bio_memory_create / _update / _retract (v0.3) | see [Auto memory](auto-memory.md); optional project/namespace | policy-checked writes, allowed only for connections in Auto memory mode; retraction only queues a request |

`project` and `namespace` are optional on every tool. Omitted, they mean the server's bound scope. When a client passes them, they must match the bound scope exactly; anything else is refused with a message that names the bound scope. v0.2 clients that always send both values keep working.

Without a v0.3 connection the server registers the same tools but refuses every write. Tool errors fail closed on scope mismatch, invalid identifiers, missing/retracted memories, and stale reads. Storage failures return generic tool errors; logs do not include query text, memory contents, or credential values.

## Scope trust boundary

A scope string never grants access by itself. Each desktop-app connection is bound to one scope when it is created and stored with its grant in `control.sqlite3`; the server authenticates the token and then uses the grant's scope. If the host configuration asks for a different `--project`/`--namespace`, the server refuses to start; the session hooks likewise return nothing. Memories in other scopes of the same database cannot be found, read, changed, or retracted through that server (`tests/integration/test_mcp_scope_binding.py`). Control databases created before scope binding (schema v1) are upgraded in place and bound to the personal scope, the only scope the desktop app ever granted.

For servers without a connection, the scope is trusted only as local startup configuration. None of this is a defense against another program running as the same Windows user, which can open the SQLite files directly.

## Local SDK-client proof

tests/integration/test_mcp_stdio.py starts the actual package server process over stdio, uses the official SDK Client, discovers tools, searches the synthetic on-disk CE database, reads the returned ID, checks revision equality, rejects mismatched scopes and IDs, checks retraction blocking, verifies a clean stderr marker check, then starts a second server/client session after the first exits. This is synthetic SDK-client integration, not a model-issued call through Codex CLI or Claude Code.
