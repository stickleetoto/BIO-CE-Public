<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Public Candidate Manifest

This public candidate was assembled separately from the CE checkout. Its initial commit was a standalone root commit with no parent. At the 2026-10-21 audit baseline, remote `main` was a documentation-only descendant of that root. Both commits belong to the private development history; the public repository starts from a new commit and does not contain them. This is a point-in-time baseline, not a statement of the later current HEAD. No private CE or BIO Core Git objects (including the sanitized BIO Core reference copy) were imported. The full authoritative BIO Core source was not available for a complete code comparison; see [source-provenance.md](source-provenance.md).

## Included executable files

- pyproject.toml, requirements-mcp.lock.txt, requirements-test.lock.txt, .gitignore
- .github/workflows/ci.yml
- src/bio_ce/**/*.py — 12 package files
- tests/**/*.py — 7 test files
- benchmarks/run_fts5_benchmark.py

## Included legal and documentation files

- LICENSE and README.md
- docs/architecture.md, mcp-integration.md, security-boundaries.md, temporal-model.md, benchmark-methodology.md, known-limitations.md
- docs/THIRD_PARTY_LICENSES.md
- docs/audit/candidate-manifest.md, source-provenance.md, privacy-audit.md, windows-verification.md, public-release-gates.md, third-party-license-inventory.md, CE-7-report.md
- docs/evaluation/results/fts5-1k.json and fts5-10k.json

The JSON result files contain synthetic aggregates only.

## Excluded local material

.venv/, .test-tmp/, SQLite databases and WAL/SHM files, Python caches, build output, dist/, *.egg-info, credentials, host profiles, logs, and downloaded tools are excluded from the tracked tree. At the 2026-10-21 baseline, the reviewed history contained the independent candidate root and one documentation-only commit; no private CE, BIO Core, or reference history was included. The required fresh .venv stays local and is not tracked/public content.

No user memory or product database is included.
