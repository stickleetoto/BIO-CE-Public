# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

"""Reproducible single-process CPU benchmark for BIO CE's real SQLite store."""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import tempfile
import time
from typing import Any

try:
    import resource
except ImportError:  # Windows
    resource = None

from bio_ce.core.models import (
    MemoryNotFoundError,
    MemoryScope,
    SourceProvenance,
    ValidationError,
)
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


def run(size: int, warm_searches: int) -> dict[str, Any]:
    if size not in (1_000, 10_000):
        raise ValueError("size must be 1000 or 10000")
    if not 50 <= warm_searches <= 1_000:
        raise ValueError("warm_searches must be from 50 to 1000")

    process_cpu_start = time.process_time()
    wall_start = time.perf_counter()
    scope = MemoryScope("benchmark-project", "synthetic-fts5")
    other_scope = MemoryScope("benchmark-project", "other-synthetic-namespace")
    source = SourceProvenance(
        "synthetic-benchmark", "fixture:benchmarks/run_fts5_benchmark.py",
        {"synthetic": True},
    )
    query_ids = tuple(range(0, size, max(1, size // 50)))[:50]
    query_tokens = tuple(_anchor(index) for index in query_ids)

    with tempfile.TemporaryDirectory(prefix="bio-ce-fts5-benchmark-") as scratch:
        database = Path(scratch) / "benchmark.sqlite3"
        store_open_start = time.perf_counter()
        store = SQLiteMemoryStore(database)
        store_open_seconds = time.perf_counter() - store_open_start

        try:
            base_seed_start = time.perf_counter()
            for index in range(size):
                anchor = _anchor(index)
                store.add(
                    scope,
                    memory_id=f"mem_benchmark_{index:08d}",
                    title=f"Synthetic benchmark item {index:08d}",
                    content=(
                        f"Synthetic item {index:08d} contains {anchor}, sharedcommonterm, "
                        "alpha beta gamma, and a deterministic lexical retrieval target."
                    ),
                    source=source,
                    recorded_at="2026-10-20T00:00:00Z",
                )
            base_seed_seconds = time.perf_counter() - base_seed_start

            edge_fixture_start = time.perf_counter()
            boundary = store.add(
                other_scope,
                memory_id="mem_benchmark_namespace_01",
                title="Namespace boundary fixture",
                content="namespaceboundarytoken belongs to the other synthetic namespace.",
                source=source,
                recorded_at="2026-10-20T00:00:00Z",
            )
            withdrawn = store.add(
                scope,
                memory_id="mem_benchmark_retracted_01",
                title="Retracted benchmark fixture",
                content="retractedfixturetoken must not be returned.",
                source=source,
                recorded_at="2026-10-20T00:00:00Z",
            )
            store.retract(
                scope,
                withdrawn.memory_id,
                expected_revision_id=withdrawn.revision_id,
                source=source,
                recorded_at="2026-10-20T00:00:01Z",
            )
            edge_fixture_seconds = time.perf_counter() - edge_fixture_start
            index_preparation_seconds = (
                store_open_seconds + base_seed_seconds + edge_fixture_seconds
            )

            cold_start = time.perf_counter()
            cold_hits = store.search(scope, query_tokens[0], limit=5)
            cold_latency_ms = (time.perf_counter() - cold_start) * 1000
            cold_accuracy = _rank_of_target(cold_hits, query_ids[0])

            current = store.read(scope, f"mem_benchmark_{query_ids[0]:08d}")
            explicit_revision = store.read(
                scope,
                current.memory_id,
                revision_id=current.revision_id,
            )
            valid_revision_round_trip = (
                explicit_revision.memory_id == current.memory_id
                and explicit_revision.revision_id == current.revision_id
                and explicit_revision.content == current.content
            )
            invalid_revision_rejected = False
            try:
                store.read(scope, current.memory_id, revision_id="rev_invalid")
            except ValidationError:
                invalid_revision_rejected = True
            unknown_revision_rejected = False
            try:
                store.read(scope, current.memory_id, revision_id="rev_" + "0" * 64)
            except MemoryNotFoundError:
                unknown_revision_rejected = True

            query_cases = (
                ("unique_hit", scope, query_tokens[0]),
                ("mixed_hit", scope, f"{query_tokens[1]} sharedcommonterm"),
                ("ambiguous_common", scope, "sharedcommonterm"),
                ("miss", scope, "biocequerythatdoesnotexist"),
                ("retracted", scope, "retractedfixturetoken"),
                ("namespace_boundary", scope, "namespaceboundarytoken"),
                ("other_namespace_positive_control", other_scope, "namespaceboundarytoken"),
            )
            query_case_results: dict[str, dict[str, Any]] = {}
            for case_name, case_scope, query in query_cases:
                result_by_k: dict[str, int] = {}
                for limit in (1, 5, 10):
                    hits = store.search(case_scope, query, limit=limit)
                    result_by_k[str(limit)] = len(hits)
                expected_nonempty = case_name in {
                    "unique_hit", "mixed_hit", "ambiguous_common",
                    "other_namespace_positive_control",
                }
                case_passed = (result_by_k["1"] > 0) == expected_nonempty
                query_case_results[case_name] = {
                    "result_counts_by_top_k": result_by_k,
                    "expected_nonempty": expected_nonempty,
                    "passed": case_passed,
                }

            quality: dict[str, dict[str, float]] = {}
            for difficulty, make_query in (
                ("unique_token", lambda query: query),
                ("rare_plus_common", lambda query: f"{query} sharedcommonterm"),
            ):
                metrics: dict[str, float] = {}
                for limit in (1, 5, 10):
                    recall_count = 0
                    reciprocal_ranks: list[float] = []
                    for query_id, query in zip(query_ids, query_tokens, strict=True):
                        hits = store.search(scope, make_query(query), limit=limit)
                        rank = _rank_of_target(hits, query_id)
                        if rank is not None and rank <= limit:
                            recall_count += 1
                        reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
                    metrics[f"recall_at_{limit}"] = round(recall_count / len(query_ids), 6)
                    metrics[f"mrr_at_{limit}"] = round(
                        sum(reciprocal_ranks) / len(reciprocal_ranks), 6
                    )
                quality[difficulty] = metrics

            warm_cases = (query_cases[0], query_cases[1], *query_cases[2:])
            latency_samples: dict[str, list[float]] = {
                case_name: [] for case_name, _, _ in warm_cases
            }
            for index in range(warm_searches):
                case_name, case_scope, query = warm_cases[index % len(warm_cases)]
                limit = (1, 5, 10)[index % 3]
                start = time.perf_counter()
                store.search(case_scope, query, limit=limit)
                latency_samples[case_name].append((time.perf_counter() - start) * 1000)

            fts5_table = store._connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'memory_fts'"
            ).fetchone()[0]
            fts5_available = bool(fts5_table)
            synchronous_mode = int(store._connection.execute("PRAGMA synchronous").fetchone()[0])
            namespace_scope_clean = not store.search(scope, "namespaceboundarytoken")
            namespace_scope_positive = bool(store.search(other_scope, "namespaceboundarytoken"))
            retracted_scope_clean = not store.search(scope, "retractedfixturetoken")
        finally:
            store.close()

        peak_rss = _peak_rss_bytes()

    wall_seconds = time.perf_counter() - wall_start
    process_cpu_seconds = time.process_time() - process_cpu_start
    return {
        "benchmark": "BIO CE SQLite FTS5 synthetic lexical retrieval",
        "measured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "synthetic_data_only": True,
        "dataset_size": size,
        "warm_searches": warm_searches,
        "quality_queries": len(query_ids),
        "environment": {
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
            "cpu_logical_count": os.cpu_count(),
            "fts5_table_created": fts5_available,
        },
        "measurements": {
            "index_preparation_seconds": round(index_preparation_seconds, 6),
            "index_preparation_components_seconds": {
                "store_open_and_schema": round(store_open_seconds, 6),
                "base_memory_adds": round(base_seed_seconds, 6),
                "edge_case_fixtures": round(edge_fixture_seconds, 6),
            },
            "cold_search_ms": round(cold_latency_ms, 6),
            "warm_search_ms": {
                "p50": round(_percentile([v for values in latency_samples.values() for v in values], 0.50), 6),
                "p95": round(_percentile([v for values in latency_samples.values() for v in values], 0.95), 6),
                "p99": round(_percentile([v for values in latency_samples.values() for v in values], 0.99), 6),
                "samples_by_case": {
                    name: {
                        "count": len(values),
                        "p50": round(_percentile(values, 0.50), 6) if values else None,
                        "p95": round(_percentile(values, 0.95), 6) if values else None,
                        "p99": round(_percentile(values, 0.99), 6) if values else None,
                    }
                    for name, values in latency_samples.items()
                },
            },
            "cold_query_target_rank": cold_accuracy,
            "retrieval_quality_by_difficulty_and_top_k": quality,
            "query_case_results": query_case_results,
            "valid_revision_round_trip": valid_revision_round_trip,
            "invalid_revision_rejected": invalid_revision_rejected,
            "unknown_revision_rejected": unknown_revision_rejected,
            "namespace_scope_clean": namespace_scope_clean,
            "namespace_positive_control": namespace_scope_positive,
            "retracted_scope_clean": retracted_scope_clean,
            "sqlite_synchronous_pragma": synchronous_mode,
            "query_case_expectations_passed": all(
                result["passed"] for result in query_case_results.values()
            ),
            "revision_checks_passed": (
                valid_revision_round_trip
                and invalid_revision_rejected
                and unknown_revision_rejected
            ),
            "scope_and_retraction_checks_passed": (
                namespace_scope_clean
                and namespace_scope_positive
                and retracted_scope_clean
            ),
            "process_cpu_seconds": round(process_cpu_seconds, 6),
            "process_cpu_percent_of_wall": round(
                100 * process_cpu_seconds / wall_seconds, 3
            ) if wall_seconds else 0.0,
            "wall_seconds": round(wall_seconds, 6),
            "peak_rss_bytes": peak_rss,
            "peak_rss_source": "Windows PeakWorkingSetSize" if os.name == "nt" else "resource.ru_maxrss",
        },
        "method": {
            "indexing": "one SQLiteMemoryStore.add and committed revision per base fixture; schema open, base seed, and edge fixtures timed separately",
            "query_matrix": [
                "unique-token hit",
                "rare token plus a common token",
                "ambiguous common-token hit",
                "miss",
                "retracted token",
                "wrong-namespace miss and matching-namespace positive control",
            ],
            "top_k_values": [1, 5, 10],
            "latency_population": "one first search after indexing; warm p50/p95/p99 grouped by query case and across the matrix",
            "quality": "synthetic exact-target Recall@K and MRR at K=1,5,10 for unique-token and rare-plus-common queries; not semantic quality",
            "scope": {"project": scope.project, "namespace": scope.namespace},
            "other_scope": {"project": other_scope.project, "namespace": other_scope.namespace},
            "freshness": "search results pass the CE final revision freshness check before returning",
        },
    }


def _anchor(index: int) -> str:
    """Create a unique all-letter FTS token with deterministic base-26 suffix."""
    value = index
    encoded = ""
    while True:
        value, remainder = divmod(value, 26)
        encoded = chr(ord("a") + remainder) + encoded
        if value == 0:
            break
        value -= 1
    return f"bioceanchor{encoded}target"


def _rank_of_target(hits, index: int) -> int | None:
    target_id = f"mem_benchmark_{index:08d}"
    return next((hit.rank for hit in hits if hit.memory_id == target_id), None)


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    position = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[position]


def _peak_rss_bytes() -> int | None:
    if os.name == "nt":
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        process = get_current_process()
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            ctypes.c_ulong,
        ]
        get_info.restype = ctypes.c_int
        if not get_info(process, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.PeakWorkingSetSize)

    if resource is None:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if platform.system() == "Darwin" else peak * 1024)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, choices=(1_000, 10_000), required=True)
    parser.add_argument("--warm-searches", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.size, args.warm_searches)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
