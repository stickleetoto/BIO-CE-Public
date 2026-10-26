<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Public Release Gates

## Final release gates, 2026-10-26 (current)

Making the source public (Gate A) and publishing the installer as a GitHub pre-release (Gate B) are **separate
decisions**. Each needs its own explicit approval from the owner. Approving Gate A does not approve Gate B. Gate B
publishes a file in the public repository, so it can happen only after Gate A or together with it. No push,
visibility change, setting change, or release has been made.

Candidate: local branch `public/v0.3.0-rc1-release`, in the public history after the installer's source commit
`d433ebd`. The commits after `d433ebd` change only documentation and the installer test harness.

### Gate A — make the source public: READY, owner approval needed

| Check | Status | Evidence |
|---|---|---|
| Source provenance and IP | **PASS** | [Source Provenance](source-provenance.md) (2026-10-25), re-scanned on this candidate: no BIO Core names, codenames, or paths |
| Git history | **PASS** | New root commit, none of the private development history; every commit's author and committer use the GitHub noreply identity |
| Secrets | **PASS** | Gitleaks 8.18.4 on the candidate history and tree: 0 findings |
| Personal data | **PASS** | No Windows user name, email address, local path, or private repository name in any file or commit message |
| License | **PASS** | `LICENSE` byte-identical to the ASF Apache-2.0 text and protected by `.gitattributes`; `pyproject.toml` declares `Apache-2.0`; every source and document file has an SPDX or copyright header (two JSON benchmark result files cannot carry one); all 30 runtime dependencies use permissive licenses and appear in the [inventory](../THIRD_PARTY_LICENSES.md) |
| Documentation | **PASS** | README, `SECURITY.md`, release notes, and known limitations state what is and is not verified; no Windows 10, real-DPI, clean-machine, or CI claim |
| Tests | **PASS (local)** | 103 passed in a fresh clone and venv using the CI workflow's steps; this is not a CI result |
| CI workflow file | **PASS (static)** | Valid against GitHub's workflow schema (`check-jsonschema`, a broken control file was rejected); actions pinned to SHAs that match their release tags |
| Hosted CI run | **Not required for Gate A** | BLOCKED by account billing; verify after publication (below) |

**Owner decisions for Gate A:**

1. Approve pushing `public/v0.3.0-rc1-release` and making it public.
2. Choose the repository. Recommended: a **new** public repository with this branch as `main`. If the existing
   private repository is reused with a force-push, its earlier private commits and its one Actions run may stay
   retrievable by SHA.
3. Enable **private vulnerability reporting** immediately after the repository becomes public. `SECURITY.md`
   points to it.

### Gate B — publish the installer as a GitHub pre-release: BLOCKED

| Check | Status | Evidence |
|---|---|---|
| Built from public source | **PASS** | Fresh clone of `d433ebd`; frozen `bio_ce` code matches the source module by module |
| Hash and manifest | **PASS** | `BIO-CE-Setup-v0.3.0-rc1.exe`, 44,231,910 bytes, SHA-256 `2d79e7d4c9dff1187ff90149a1bc7418f014f9c0209a6c984ffa5d2d741572ee`; 2,566 payload files match `build-manifest.json` |
| Payload content | **PASS** | No development files, personal data, or private names; licenses bundled |
| Installer E2E, developer's account | **PASS** | 25/25 steps, silent installs, GUI checked by window capture |
| **Clean Windows install** | **NOT RUN, blocks Gate B** | No VM, Windows Sandbox, or second account available. Run the [clean install checklist](clean-install-checklist.md) |
| **Hosted CI** | **BLOCKED, blocks Gate B** | GitHub refused the only run before a runner started, for an account billing reason. Needs a passing hosted run of the published commit |
| Code signing | **Not signed: owner decision** | Either sign the installer and programs, or explicitly approve an unsigned pre-release. Release notes and the bundled installation guide state that the file is unsigned and that SmartScreen may warn |
| Windows 10, real 125%/150% scaling | Not claimed | Not tested; the documents say so |

**Owner decisions for Gate B:** after the clean-install checklist and a hosted CI run pass, approve (1) shipping
unsigned or signing first, and (2) creating the `v0.3.0-rc1` tag and a GitHub **pre-release** with the installer
and `SHA256SUMS.txt`. If anything that goes into the installer changes, rebuild and repeat the hash and E2E steps.

### Verify after the source is public

1. A hosted CI run on the published commit passes. Public repositories get standard GitHub-hosted runners free;
   check whether the account billing block still applies.
2. Private vulnerability reporting is on, and the `SECURITY.md` link opens the form.
3. GitHub detects Apache-2.0; README, release notes, and relative links render correctly.
4. GitHub secret scanning reports no alerts.
5. With a new repository, none of the private development SHAs resolve in it.
6. For Gate B: the uploaded asset's SHA-256 equals `SHA256SUMS.txt`, and the release is marked pre-release.

## Pre-public check, 2026-10-25 (superseded by the final gates above)

Checked read-only against the local candidate repository and the GitHub repository `stickleetoto/BIO-CE`. No
push, visibility change, setting change, or release was made.

| Gate | Status | Evidence and what is left |
|---|---|---|
| Source provenance and IP | **PASS** | Full local and remote BIO Core comparison: no BIO Core code in BIO CE. See [Source Provenance](source-provenance.md); owner decisions remain in its section 8. |
| Remote state | Private | Default branch `main` at the v0.1 documentation commit (private development history). One branch, no tags, releases, pull requests, issues, environments, deployments, secrets, webhooks, or Actions artifacts. Wiki, Pages, and Discussions are off. The one Actions run (2026-10-21) failed before a runner started, so no logs exist to expose. |
| What would be published | **Prepared (2026-10-26); owner approval needed** | Local branch `public/v0.3.0-rc1-final`: a new root commit (`d433ebd`, the source the installer was built from) and one documentation and test-harness commit on top. It carries none of the private development history. The earlier candidate branch `public/v0.3.0-rc1` is kept unchanged. Gitleaks (history and tree), a personal-data scan, and a scan for 7,370 BIO Core-specific terms found nothing. Recommended: publish this branch as the default branch of a **new** public repository. If the existing private repository is reused instead, its earlier commits (pushed in October 2026 and referenced by its one Actions run) may stay retrievable by SHA after a force-push. See the [final RC report](../release-v0.3-rc1-final-report.md). |
| Git history content | **PASS** | All refs: 118 paths, no binaries, databases, archives, keys, or logs. Every commit uses the GitHub noreply identity. Gitleaks: 0 findings. Two low-sensitivity internal names remain in earlier commits (provenance section 7). |
| `LICENSE` | **PASS** | Byte-identical to the Apache-2.0 text published by the ASF. Every source and document file carries the SPDX or copyright header. `pyproject.toml` declares `Apache-2.0`. GitHub detects Apache-2.0. |
| `README.md` | **PASS** (updated in this check) | Rewritten for v0.3.0-rc1: Auto memory, Read only by default, scope binding, current test totals, Codex limitation, links to the security policy and reports. The v0.2 text claimed read-only search/read tools only and is gone. All relative links resolve. |
| `SECURITY.md` | **PASS** (added in this check) | Private reporting through GitHub's "Report a vulnerability"; scope and out-of-scope match the documented trust boundary. **Owner action:** enable private vulnerability reporting in the repository settings when it goes public; until then the link has no form behind it. |
| CI workflow | **BLOCKED** (updated 2026-10-26) | The only run never started: GitHub's annotation says the job was not started because recent account payments failed or the spending limit needs to be increased. That is an account billing setting, not a workflow defect. The workflow was hardened: `checkout` v7.0.1, `setup-python` v7.0.0, and `upload-artifact` v7.0.2 pinned to full commit SHAs (Node 24), CPython pinned to 3.12.10, `persist-credentials: false`, workflow-level `contents: read`, a 30-minute timeout, cancel-in-progress concurrency, and `pip check`. The exact install and test commands passed locally in a fresh CPython 3.12.10 venv (99 passed); host-CLI tests skip cleanly without the CLIs, as on a hosted runner. A real hosted run needs the billing issue resolved and an approved push. |
| CONTRIBUTING / code of conduct | Not present | Optional. Without them, contributions fall under Apache-2.0 section 5 by default. |
| Clean-machine installer, Windows 10, code signing | Open | See the [final RC report](../release-v0.3-rc1-final-report.md). These affect a release, not making the source public. |

## Historical snapshot, 2026-10-21

**Audit snapshot status: PARTIAL.** Recorded on 2026-10-21 against GitHub repository `stickleetoto/BIO-CE`, whose `main` branch was Private at the time of the check. The reviewed history at that baseline contained two commits: an initial root commit and a documentation sync. Commits named here belong to the private development history. The public repository starts from a new commit and does not contain them. No BIO Core, private development CE, or reference history was imported. These are snapshot facts, not live repository status after later commits.

At snapshot time, this pre-publication cleanup was local and uncommitted. The CE-7 report is preserved as a historical snapshot; statements in it about repository creation, commits, or pushes describe its earlier point in time. Check GitHub directly for later branch or visibility changes.

## Gate results at the snapshot

| Gate | Status | Evidence and remaining limit |
|---|---|---|
| Remote visibility and branch | PASS at check time | GitHub reported the repository as Private with `main` as the default branch at the snapshot SHA above. |
| Candidate history | PASS for separation | At snapshot time, the reviewed history contained two candidate commits; the original root is preserved. Both used the user-approved noreply identity. No BIO Core/private CE/reference objects were imported. |
| Windows 11 x64 | SYNTHETIC VERIFIED | Candidate CPython 3.12.14 environment; the 2026-10-21 finalization rerun passed 18 tests in 13.05 seconds. See [Windows Verification](windows-verification.md). |
| Windows 10 x64 | NOT RUN | No Windows 10 execution is recorded. |
| Python 3.12 | VERIFIED | CPython 3.12.14 was used. Python 3.11 compatibility is not claimed. |
| MCP SDK integration | SYNTHETIC VERIFIED | Official Python MCP SDK client exercised the real CE stdio process and synthetic SQLite store, including discovery, search/read, matching ID/revision, scope rejection, retraction, shutdown, and reconnect. |
| Codex/Claude model-host calls | NOT VERIFIED | No model-issued tool calls were made. |
| GitHub Actions | NOT VERIFIED | The earlier push-triggered run failed before a runner or job steps were assigned. The later documentation commit used `[skip ci]`; no CI test pass is claimed. |
| Apache-2.0 | PASS for source candidate | `LICENSE` and package metadata identify Apache-2.0. |
| Third-party notices | PASS for source inventory | The 36 locked distributions match the inventory and installed versions; installed distributions had license or notice files. No package source, wheel, or binary is vendored. Locks do not pin artifact hashes or an index host. |
| Privacy scan | PASS for scanned pre-commit snapshot | Gitleaks 8.18.4 reported 0 findings in the 43-file working snapshot and two-commit history. Email, personal path, credential, and private-key patterns were also 0. Local ignored environments are outside the tracked payload. |
| Source provenance and ownership | PARTIAL | The complete authoritative BIO Core source was unavailable for comparison. The accessible sanitized subset does not establish independent origin or legal ownership. The project owner's rights statement is recorded separately and is not independent legal verification. |

## Snapshot and historical boundaries

- [CE-7 Qualification Report](CE-7-report.md) is an unchanged historical snapshot from before CE-8 created the candidate Git repository. Its statements about repository creation, commits, pushes, workflow runs, and account checks are historical.
- The candidate started with one independent root commit. At the recorded baseline, remote `main` had that root plus the documentation sync commit listed above.
- The earlier initial Private push triggered an Actions run, which failed before a runner was assigned. The later docs commit used `[skip ci]`; neither event provides a CI test result.
- At snapshot time, the local cleanup was not part of remote `main`. This file records that pre-commit state; evaluate the live remote separately.

## Remaining public-release decisions

1. Resolve the incomplete source comparison through a complete authorized comparison, or record the project owner's explicit decision to accept the remaining uncertainty.
2. Run and retain separate Codex CLI and Claude Code model-issued tool-call evidence before claiming those hosts are verified.
3. Run GitHub Actions when available and verify it reaches the Windows test steps.
4. Test Windows 10 before claiming it is verified; until then, label it **NOT RUN**.
5. Inspect exact dependency artifacts and carry applicable notices before distributing a wheel, executable, or bundled package.
6. Keep the release status **PARTIAL** until the required qualification evidence is complete.
