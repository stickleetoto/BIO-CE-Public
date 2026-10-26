# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

"""Deterministic lexical retrieval over the current revision of exact-scope rows."""

from __future__ import annotations

import re
import sqlite3
import json

from bio_ce.core.models import MemoryScope, SearchHit, SourceProvenance


_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class FTS5Retriever:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def search(
        self,
        scope: MemoryScope,
        query: str,
        *,
        limit: int,
        valid_at: str,
    ) -> tuple[SearchHit, ...]:
        tokens = tuple(dict.fromkeys(token.casefold() for token in _TOKEN.findall(query)))[:32]
        if not tokens:
            return ()
        expression = " OR ".join(f'"{token}"' for token in tokens)
        rows = self._connection.execute(
            """SELECT m.memory_id, r.revision_id, r.title, r.content,
                      r.source_type, r.source_ref, r.source_metadata_json,
                      r.recorded_at, r.valid_from, r.valid_until,
                      bm25(memory_fts, 0.0, 0.0, 0.0, 0.0, 5.0, 1.0) AS raw_score
               FROM memory_fts
               JOIN memories AS m ON m.memory_id = memory_fts.memory_id
               JOIN revisions AS r ON r.revision_id = m.current_revision_id
               WHERE memory_fts MATCH ?
                 AND memory_fts.revision_id = m.current_revision_id
                 AND m.project = ?
                 AND m.namespace = ?
                 AND r.kind IN ('assertion', 'revision')
                 AND (r.valid_from IS NULL OR r.valid_from <= ?)
                 AND (r.valid_until IS NULL OR r.valid_until > ?)
               ORDER BY raw_score ASC, m.memory_id COLLATE BINARY ASC
               LIMIT ?""",
            (expression, scope.project, scope.namespace, valid_at, valid_at, limit),
        ).fetchall()
        hits: list[SearchHit] = []
        for rank, row in enumerate(rows, start=1):
            source = SourceProvenance(
                source_type=str(row["source_type"]),
                source_ref=str(row["source_ref"]),
                metadata=json.loads(row["source_metadata_json"]),
            )
            content = str(row["content"] or "")
            hits.append(SearchHit(
                memory_id=str(row["memory_id"]),
                revision_id=str(row["revision_id"]),
                rank=rank,
                score=round(-float(row["raw_score"]), 12),
                title=str(row["title"]),
                preview=content[:240],
                source=source,
                recorded_at=str(row["recorded_at"]),
                valid_from=None if row["valid_from"] is None else str(row["valid_from"]),
                valid_until=None if row["valid_until"] is None else str(row["valid_until"]),
            ))
        return tuple(hits)


__all__ = ["FTS5Retriever"]
