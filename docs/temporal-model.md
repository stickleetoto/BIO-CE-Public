<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Temporal and Revision Model

BIO CE exposes a narrow local temporal contract.

## Valid time

valid_from and valid_until are optional timezone-aware ISO-8601 values normalized to UTC with microsecond precision. Search evaluates the half-open interval [valid_from, valid_until) at valid_at; if omitted, valid_at uses the current UTC clock. A null start or end is open-ended. The store rejects an end that is not later than the start.

These fields are literal metadata. The store does not infer event times, validate them against an external source, or determine whether a claim was true during that period.

## Recorded time and order

recorded_at is normalized to UTC. Callers may supply it, so it is descriptive data rather than a trusted audit clock. Revision order is the integer revision_number allocated under a write transaction. The current-revision pointer is updated atomically with each append.

Revision IDs are deterministic SHA-256 identifiers over canonical revision fields. They identify data; they are not signatures or proof of source authenticity.

## Retraction

Retraction appends a retraction revision with null content. The memory's current pointer changes to that tombstone. Current search excludes it, and API reads/history block access once the current revision is retracted. Prior content rows remain in SQLite; secure deletion is not implemented.

## Conflict and abstention

FTS5 returns lexical matches and ranks them according to SQLite ranking. If multiple sources disagree, BIO CE reports matching records without choosing authority or merging claims. No match means only that the local lexical index found no match; it is not proof that a fact is globally absent.

## Concurrency semantics

Read and search select an initial SQLite snapshot, release that transaction, then revalidate observed current revisions in a fresh transaction. The first SELECT of that final validation is the freshness linearization point. If a revision or retraction committed before it, the operation raises SnapshotChangedError; if a write commits after it, that write is ordered after the read. A response may still be delivered after a later retraction commits. Strict real-time revocation and secure erasure are unsupported.

Deterministic threading.Event tests exercise the actual SQLite read_many, read, search, and history paths. This does not claim equivalence to a separate BIO Core concurrency implementation.
