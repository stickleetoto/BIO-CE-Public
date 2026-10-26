<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# CPU Benchmark Methodology

The benchmark runs the actual SQLiteMemoryStore in one local Python process with synthetic rows and SQLite FTS5. It does not use BIO Core, a vector database, a model API, or an MCP host. It is not a semantic-quality or end-to-end latency benchmark.

## Reproduce on Windows

~~~powershell
New-Item -ItemType Directory -Force .test-tmp\results | Out-Null
.\.venv\Scripts\python.exe benchmarks\run_fts5_benchmark.py --size 1000 --warm-searches 200 --output .test-tmp\results\fts5-1k.json
.\.venv\Scripts\python.exe benchmarks\run_fts5_benchmark.py --size 10000 --warm-searches 200 --output .test-tmp\results\fts5-10k.json
~~~

The result JSON files record platform/Python/SQLite version, index preparation time and its schema/base-seed/edge-fixture components, first-search latency, warm p50/p95/p99, process CPU time/percent-of-wall, peak RSS, and exact-target retrieval quality.

## Candidate run summary

Measured on Windows 11 x64, CPython 3.12.14, SQLite 3.53.1, 16 logical CPUs; 200 warm searches per data size.

| Synthetic memories | Index preparation | Cold search | Warm p50 / p95 / p99 | CPU seconds / wall share | Peak RSS | Recall@5 / MRR@5 |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 4.376 s | 0.681 ms | 0.277 / 4.471 / 4.834 ms | 1.766 s / 32.4% | 27.2 MB | 1.000 / 1.000 |
| 10,000 | 52.237 s | 0.649 ms | 0.312 / 60.923 / 62.403 ms | 19.328 s / 29.7% | 27.7 MB | 1.000 / 1.000 |

The 10k mixed and ambiguous common-token cases are materially slower than unique-token hits: their per-case p95 values are about 59–62 ms. Index preparation time is dominated by one individually committed add per base synthetic row. These results expose current behavior; no performance optimization is included. The measured Recall/MRR of 1.0 is limited to the deterministic synthetic exact-target query set.

## Query and quality matrix

The harness measures unique-token hits, rare-plus-common hits, ambiguous common-token hits, misses, retracted-only terms, and wrong-namespace misses with a matching-namespace positive control. It tests Top-K values 1, 5, and 10; malformed and unknown revision IDs; active revision round-trips; and scope/retraction checks. Recall@K and MRR use deterministic synthetic target IDs for unique-token and rare-plus-common queries. These are not semantic retrieval metrics.

The first search after indexing is reported separately as cold. Warm samples are collected afterward and grouped by case and across the full matrix. Index preparation includes schema open, one committed add per base row, and two edge fixtures plus one retraction; each component is timed separately.

## Limits

Results are local snapshots on one Windows 11 x64 machine and vary with SQLite, Python, storage, CPU power policy, and background load. In-process latency excludes MCP framing, host scheduling, prompt construction, model inference, and network round trips. Do not present these numbers as real MCP/model latency or comparative BIO Core performance.
