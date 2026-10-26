<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Windows Reproducibility Record

Candidate-specific results were collected in a new local venv under this candidate.

## Platform boundary

- Target policy: Windows 10/11 x64. This policy does not imply both versions were exercised.
- Verified platform: Windows 11 x64, OS build 26200; Microsoft identifies build 26200 as Windows 11 version 25H2 ([release information](https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information)). CPython 3.12.14, SQLite 3.53.1, 16 logical CPUs.
- Windows 10 is **NOT RUN**; no Windows 10 compatibility result is claimed.
- Linux is outside the current support and test roadmap.

## Checks

| Check | Result | Evidence |
|---|---|---|
| Fresh CPython 3.12 x64 venv under candidate | PASS WITH BOOTSTRAP WORKAROUND | venv created with no application packages; this managed Python's ensurepip command failed. pip 26.2.1 was installed into the new target venv using pip's --python option from a separate pip-enabled interpreter. The fallback command in README was exercised. |
| Pinned MCP/test install and package install | PASS | Both lock files installed; candidate editable install succeeded. |
| Package SPDX metadata | PASS | License-Expression Apache-2.0 and License-File LICENSE present in installed metadata. |
| pip check | PASS | No broken requirements found. |
| SQLite FTS5 availability | PASS | In-memory FTS5 virtual table created successfully. |
| Synthetic CLI demo and DB seed | PASS | Demo showed revision, retraction, conflict/abstention examples; isolated seed created 3 synthetic memories. |
| Official MCP SDK stdio search/read and ID/revision equality | PASS | Actual server subprocess; SDK tool discovery, search/read, matching ID/revision, scope rejection, missing/invalid ID, retraction, stderr marker check, server shutdown/reconnect. |
| Wrong scope, missing ID, retraction, reconnect | PASS | Covered by dedicated official SDK integration test. |
| Explicit full pytest tests | PASS | 2026-10-21 repository-cleanup finalization rerun: 18 passed in 13.05 s using candidate CPython 3.12.14 with process-local temp redirected to ignored `.test-tmp`. |
| 1k synthetic CPU benchmark | PASS | All query-case, revision, scope, and retraction checks true; result at ../evaluation/results/fts5-1k.json. |
| 10k synthetic CPU benchmark | PASS | All query-case, revision, scope, and retraction checks true; result at ../evaluation/results/fts5-10k.json. |
| Windows 10 | NOT RUN | No Windows 10 host was available in this verification. |
| Codex/Claude model-issued calls | NOT RUN | No actual model-host calls were made. SDK-client tests are not host verification. |
| GitHub Actions | NOT VERIFIED | The 2026-10-21 push run ended in failure before a runner was assigned; the `pytest` job had no steps, so no CI tests ran. |

The default Windows Temp location was not writable in the constrained verification session. A test attempt using that location failed during temporary-file setup; a restricted retry later stalled at MCP stdio startup. The bounded run with temporary paths redirected to the ignored candidate `.test-tmp` directory completed the full suite: 18 passed in 11.54 seconds. A fresh rerun after the final documentation review passed all 18 tests in 4.56 seconds. No application source was changed to accommodate the local sandbox. GitHub-hosted execution remains unverified because the push-triggered job did not reach a runner.

## Pre-public cleanup recheck

On 2026-10-21, the locked dependency install, editable install, and `pip check` passed in the retained CPython 3.12.14 candidate environment. The restricted session denied the default Windows Temp path for editable installation and the CLI demo; both completed after process-local `TEMP`, `TMP`, and `TMPDIR` were redirected to ignored `.test-tmp\temp`. The README's demo and synthetic database seed commands passed. The full README test command passed 18 tests in 4.04 seconds; the dedicated MCP integration module passed all 3 integration tests in 3.81 seconds with the same temp redirection.

The 1k and 10k benchmark commands also completed into new ignored output paths, and both output files parsed as JSON with the benchmark's query, revision, scope, and retraction checks passing. The integration test directory passed all 3 tests, including the official stdio case. Existing checked-in benchmark result files were preserved and not replaced by these reruns. The Windows 10, actual model-host, and GitHub Actions statuses remain unchanged.

## Repository-cleanup finalization recheck

On 2026-10-21, the full suite passed 18 tests in 13.05 seconds, and `tests/integration` passed 3 tests in 10.71 seconds. The CLI demo and a fresh synthetic seed database also completed; `pip check` reported no broken requirements. These checks used the retained CPython 3.12.14 environment with process-local temporary paths under ignored `.test-tmp`. Windows 10, actual Codex/Claude model calls, and GitHub Actions remain NOT RUN or NOT VERIFIED as described above.
