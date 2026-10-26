# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

"""Synthetic-only fixture and self-contained preview demonstration."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import TextIO
import sys

from bio_ce.core.models import MemoryNotFoundError, MemoryScope, SourceProvenance
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


SCOPE = MemoryScope(project="synthetic-demo", namespace="portfolio")


def seed_synthetic_fixture(store: SQLiteMemoryStore) -> dict[str, str]:
    """Load stable synthetic IDs and timestamps into an empty demo store."""
    source_v1 = SourceProvenance("fixture", "fixture:release-calendar:v1", {"synthetic": True})
    source_v2 = SourceProvenance("fixture", "fixture:release-calendar:v2", {"synthetic": True})
    first = store.add(
        SCOPE,
        memory_id="mem_demo_release_window_01",
        title="Nimbus 2.0 release plan",
        content="Nimbus 2.0 release is planned for 2027-04-15.",
        source=source_v1,
        recorded_at="2026-09-21T09:00:00Z",
    )
    current = store.revise(
        SCOPE,
        first.memory_id,
        expected_revision_id=first.revision_id,
        title="Nimbus 2.0 release plan",
        content="Nimbus 2.0 release is planned for 2027-04-22.",
        source=source_v2,
        recorded_at="2026-10-02T09:00:00Z",
    )

    retired = store.add(
        SCOPE,
        memory_id="mem_demo_retired_note_01",
        title="Retired preview schedule",
        content="The synthetic export preview was scheduled for 2026-11-02.",
        source=SourceProvenance("fixture", "fixture:preview-schedule:v1", {"synthetic": True}),
        recorded_at="2026-10-03T09:00:00Z",
    )
    store.retract(
        SCOPE,
        retired.memory_id,
        expected_revision_id=retired.revision_id,
        source=SourceProvenance("fixture", "fixture:withdrawal:v1", {"synthetic": True}),
        recorded_at="2026-10-04T09:00:00Z",
    )

    for memory_id, source_ref, end_date in (
        ("mem_demo_support_source_a_01", "fixture:support-plan:a", "2027-12-31"),
        ("mem_demo_support_source_b_01", "fixture:support-plan:b", "2028-06-30"),
    ):
        store.add(
            SCOPE,
            memory_id=memory_id,
            title="Nimbus support window",
            content=f"The Nimbus support window ends on {end_date}.",
            source=SourceProvenance("fixture", source_ref, {"synthetic": True}),
            recorded_at="2026-10-05T09:00:00Z",
        )

    return {"release_memory_id": current.memory_id, "first_revision_id": first.revision_id,
            "current_revision_id": current.revision_id, "retracted_memory_id": retired.memory_id}


def run_demo(*, output: TextIO | None = None) -> int:
    """Run the portfolio fixture in an isolated temporary SQLite database."""
    out = output or sys.stdout
    with tempfile.TemporaryDirectory(prefix="bio-ce-synthetic-") as scratch:
        db_path = Path(scratch) / "synthetic.sqlite3"
        with SQLiteMemoryStore(db_path) as store:
            ids = seed_synthetic_fixture(store)

            print("BIO Community Edition - synthetic memory demo", file=out)
            print(f"Scope: project={SCOPE.project!r}, namespace={SCOPE.namespace!r}", file=out)

            print("\n1. Fact search", file=out)
            hits = store.search(SCOPE, "Nimbus release planned", limit=5)
            _print_hits(hits, out)

            print("\n2. Revision history", file=out)
            prior = store.read(SCOPE, ids["release_memory_id"], revision_id=ids["first_revision_id"])
            current = store.read(SCOPE, ids["release_memory_id"])
            print(f"{prior.revision_id} (revision {prior.revision_number}): {prior.content}", file=out)
            print(f"{current.revision_id} (revision {current.revision_number}): {current.content}", file=out)

            print("\n3. Retraction", file=out)
            remaining = store.search(SCOPE, "synthetic export preview schedule", limit=5)
            print(f"search hits after retraction: {len(remaining)}", file=out)
            try:
                store.read(SCOPE, ids["retracted_memory_id"])
            except MemoryNotFoundError:
                print("read after retraction: BLOCKED (memory_not_found)", file=out)

            print("\n4. Source comparison", file=out)
            conflicts = store.search(SCOPE, "Nimbus support window ends", limit=5)
            _print_hits(conflicts, out)
            if len(conflicts) > 1:
                print("These fixture sources disagree; the engine reports both without choosing authority.", file=out)

            print("\n5. Uncertain query", file=out)
            uncertain = store.search(SCOPE, "Owl Harbor weekend opening schedule", limit=5)
            if not uncertain:
                print("ABSTAIN: no matching local evidence; this is not a global completeness claim.", file=out)
            else:
                _print_hits(uncertain, out)

    return 0


def _print_hits(hits, output: TextIO) -> None:
    if not hits:
        print("(no lexical matches)", file=output)
        return
    for hit in hits:
        print(
            f"rank={hit.rank} score={hit.score:.6f} "
            f"{hit.memory_id}@{hit.revision_id} source={hit.source.source_ref!r}: {hit.preview}",
            file=output,
        )


__all__ = ["SCOPE", "run_demo", "seed_synthetic_fixture"]
