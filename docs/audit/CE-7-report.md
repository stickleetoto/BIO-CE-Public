<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE-7 Candidate Qualification Report

This is a CE-7 status snapshot recorded before CE-8 created the local Git repository. See [public release gates](public-release-gates.md) for the current local state.

**Overall: PARTIAL — executable review candidate prepared and synthetically verified; public publication remains on hold.**

This report applies only to BIO-CE-PUBLIC-CANDIDATE. The original private BIO CE checkout and the BIO Core repositories were not modified. (Internal repository name redacted on 2026-10-25 for publication; the historical report is otherwise unchanged.) No GitHub repository was created, no commit or push was made, no workflow was dispatched, and no model API or actual AI-host call was performed.

## Status summary

| Area | Status | Result |
|---|---|---|
| Apache-2.0 candidate license | PASS | Full official Apache-2.0 license text is present. Source headers, pyproject SPDX expression, and LICENSE file metadata match the user-approved choice and attribution. |
| File-level source origin review | PASS FOR CANDIDATE INCLUSION | All 20 copied Python source/test/benchmark files match the CE baseline byte-for-byte after removing the added four-line license/provenance header. The three baseline commit author names match the approved attribution. The baseline is a separate root history, and the accessible reference comparison found no substantive overlap. |
| Source origin residual | PARTIAL | The full authoritative BIO Core source was not available for comparison. The inspected evidence supports inclusion and no unverified external source is identified; similarity is not treated as ownership proof. |
| Third-party notices | PASS FOR SOURCE CANDIDATE | No third-party source or binary is vendored. Pinned dependency versions and license inventory are included. Exact downstream wheel/bundled-artifact notices remain to be inspected if such an artifact is produced. |
| Fresh Windows candidate install | PASS WITH BOOTSTRAP WORKAROUND | New CPython 3.12.14 x64 venv, pinned dependencies, editable package install, Apache package metadata, and pip check passed. The managed Python runtime's ensurepip step failed; pip was bootstrapped into the new venv using pip's target-interpreter support. |
| Windows regression and SDK integration | SYNTHETIC VERIFIED | 18 tests passed; dedicated official SDK stdio test passed against the actual synthetic SQLite store and subprocess server. |
| Synthetic CLI and FTS5 | SYNTHETIC VERIFIED | FTS5 creation, synthetic demo, and new three-row MCP fixture database succeeded. |
| Concurrency and freshness | SYNTHETIC VERIFIED | Event-controlled store tests passed, including fail-closed behavior after a revision/retraction before final freshness validation. |
| CPU benchmark | SYNTHETIC VERIFIED | 1k and 10k runs completed; all query, revision, namespace, and retraction checks passed. Results and limitations are in docs/benchmark-methodology.md and docs/evaluation/results/. |
| Candidate privacy/security scan | PASS | Count-only personal-data review and Gitleaks result are recorded in docs/audit/privacy-audit.md. |
| Candidate Git history | NOT RUN | Candidate intentionally has no .git directory or commit. No private baseline Git objects were copied. |
| Windows 10 | NOT RUN | No Windows 10 execution was performed. |
| Linux | NOT RUN / OUT OF POLICY | The project is Windows-only under the current platform freeze. |
| Actual Codex/Claude model-host calls | NOT RUN | SDK client proof is not model-issued tool-call proof. |
| GitHub Actions | NOT RUN | Workflow is included but was not dispatched. |
| Public account exposure review | BLOCKED | The prior CE-6 audit observed a non-empty public email field; this task made no account changes and did not recheck its current state. Verify the setting and future commit identity before publication. |

## Benchmark snapshot

| Size | Index preparation | Warm p50 / p95 / p99 | Recall@5 / MRR@5 |
|---:|---:|---:|---:|
| 1k | 4.376 s | 0.277 / 4.471 / 4.834 ms | 1.000 / 1.000 |
| 10k | 52.237 s | 0.312 / 60.923 / 62.403 ms | 1.000 / 1.000 |

The 10k common-token cases were much slower than unique-token hits. Metrics are local single-process synthetic measurements, not semantic quality or end-to-end MCP/model latency.

## Remaining publication actions

1. Recheck the public profile email and commit identity without exposing personal values.
2. If public source release is still intended, perform an owner review of the file-level provenance register and retain the Core comparison limitation.
3. Before distributing a wheel or bundled application, audit the exact build artifacts and dependency notices.
4. Keep Windows 10, GitHub Actions, and actual model-host verification labeled NOT RUN until performed.

No public visibility change, repository creation, commit, or push is authorized by this candidate-preparation result.
