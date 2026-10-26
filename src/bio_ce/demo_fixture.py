# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

"""Explicitly seed a fresh database with the isolated synthetic MCP demo."""

from __future__ import annotations

import os
from pathlib import Path

from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


DEMO_PROJECT = "bio-ce-demo"
DEMO_NAMESPACE = "synthetic"


def seed_synthetic_mcp_demo(database: str | Path) -> tuple[str, ...]:
    """Create a new demo-only SQLite file; refuse every pre-existing path."""
    path = Path(database).expanduser().resolve()
    scope = MemoryScope(DEMO_PROJECT, DEMO_NAMESPACE)
    source = SourceProvenance(
        "synthetic-fixture", "fixture:bio-ce-mcp-demo", {"synthetic": True}
    )
    rows = (
        (
            "mem_bio_ce_demo_0001",
            "BIO CE local retrieval",
            "BIO CE demo uses SQLite FTS5 for local lexical retrieval and explicit scope.",
        ),
        (
            "mem_bio_ce_demo_0002",
            "BIO CE revision model",
            "The synthetic demo records immutable revisions and blocks reads after retraction.",
        ),
        (
            "mem_bio_ce_demo_0003",
            "BIO CE validity window",
            "Valid time uses a literal half-open interval with UTC timestamps.",
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise FileExistsError("demo database path already exists; choose a new path") from None
    os.close(descriptor)
    created: list[str] = []
    with SQLiteMemoryStore(path) as store:
        for memory_id, title, content in rows:
            created.append(
                store.add(
                    scope,
                    memory_id=memory_id,
                    title=title,
                    content=content,
                    source=source,
                ).revision_id
            )
    return tuple(created)


__all__ = ["DEMO_NAMESPACE", "DEMO_PROJECT", "seed_synthetic_mcp_demo"]
