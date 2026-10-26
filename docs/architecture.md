<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Architecture

BIO CE is a local Windows-first Python package with a Tkinter desktop app. It uses Python sqlite3, SQLite WAL for writable stores, a relational revision ledger, and SQLite FTS5 for lexical retrieval. A separate `control.sqlite3` holds connection grants, the AI activity log, and the review queue. CPU is the default; no model or embedding runtime is present.

## Components

~~~mermaid
flowchart TB
    CLI["CLI / explicit synthetic fixture"] --> Store["SQLiteMemoryStore"]
    Tests["Unit + integration tests"] --> Store
    Benchmark["1k / 10k synthetic benchmark"] --> Store
    Desktop["Desktop app (explicit user actions)"] --> Store
    MCP["MCPServer stdio adapter"] -->|"reads; policy-checked writes in Auto memory"| Store
    MCP --> Control["control.sqlite3: grants, activity, review queue"]
    Desktop --> Control
    Store --> Models["Validated scope, revision, provenance types"]
    Store --> DB["SQLite memories + revisions"]
    Store --> FTS["SQLite FTS5 index"]
~~~

The memories table binds an ID to one project and namespace and points at its current revision. revisions is append-only through the store API. Active content is indexed in memory_fts; a retraction revision has no content and is not inserted into FTS. Search joins the current revision and filters exact scope and valid-time interval.

## MCP call sequence

~~~mermaid
sequenceDiagram
    participant H as Local MCP host
    participant S as BIO CE stdio process
    participant A as BIO CE adapter
    participant D as SQLite database
    H->>S: start with database + connection ID (token in environment)
    S->>S: authenticate grant; bind its project/namespace
    H->>S: initialize and list tools
    S-->>H: search, read, history (+ create, update, retract)
    H->>A: bio_memory_search(query, top-k)
    A->>D: read-only FTS5 query + current revision check
    D-->>A: scoped hits with IDs/revisions
    A-->>H: structured search result
    H->>A: bio_memory_read(same ID, optional revision)
    A->>D: read-only current/historical revision query + freshness check
    D-->>A: revision and content
    A-->>H: structured read result
~~~

## Revision lifecycle

~~~text
add       -> rev_... (revision_number=1; current pointer set)
revise    -> rev_... (revision_number=n+1; previous_revision_id linked)
retract   -> rev_... (revision_number=n+1; kind=retraction; content=NULL)
~~~

Each write and current-pointer update commits in one BEGIN IMMEDIATE transaction. Retraction leaves earlier rows in place. The application API blocks reads after a memory is retracted; it does not erase stored history.

See [Temporal and Revision Model](temporal-model.md), [MCP Integration](mcp-integration.md), and [Security Boundaries](security-boundaries.md).
