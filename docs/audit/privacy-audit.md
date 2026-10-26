<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Candidate Privacy and Artifact Audit

Audit snapshot: 2026-10-21. At scan time, GitHub `main` was verified Private at its documentation commit of that day (private development history, not part of the public repository). The local cleanup worktree was uncommitted; its 43-file source snapshot was checked separately from the two-commit history then present. Local `.venv` and `.test-tmp` contents are ignored and are not release payload. The recorded SHA, visibility, and history describe this snapshot, not later repository state.

## Checks

- Email patterns and public profile email field; values are never written to this report.
- Personal absolute paths, host/profile/config locations, common credential patterns, private-key markers, and synthetic markers.
- Gitleaks against the exact 43-file candidate snapshot and committed history with full redaction.
- SQLite databases, WAL/SHM, executables, wheels, archives, caches, and temporary files in tracked content.
- Git history separation, license notices, dependency inventory, and vendored third-party source.

## Candidate snapshot and history

| Check | Result |
|---|---:|
| Candidate payload files | 43 |
| Candidate Git history | Two commits: independent root plus documentation sync; no BIO Core/private CE history |
| Gitleaks 8.18.4 on the 2026-10-21 pre-commit 43-file snapshot | 0 findings |
| Gitleaks 8.18.4 on the two-commit history at that snapshot | 0 findings |
| Email-pattern matches in source payload | 0 |
| Personal path-pattern matches in source payload | 0 |
| Credential and private-key patterns in source payload | 0 |
| Binary/database artifacts in tracked payload | 0 |
| Public GitHub profile API email field | Null in the unauthenticated check recorded on 2026-10-21; this is a point-in-time result |

The commit identity uses the user-approved GitHub noreply identity; its address is withheld. An email in an authenticated profile response does not establish public exposure.

## Ignored local environment findings

The prior broad local worktree scan reported 18 Gitleaks heuristic findings in ignored third-party package files: 9 in the candidate-root `.venv` and 9 in ignored `.test-tmp\ce8-venv`. The rules were generic API key (12), JWT (2), and private key (4), attributed to `cryptography`, `PyJWT`, and `pywin32`. The reports were fully redacted. These files were outside the tracked payload and candidate Git history; the findings do not establish that a credential is present.

## Artifacts and notices

The earlier 43-file audit found no SQLite database, database sidecars, executable, wheel, archive, cache, or vendored third-party package source. The inventory covers 36 lock entries; names and versions matched the installed environment, and each installed distribution had a license or notice file. Lock files do not pin wheel hashes or an index host. Inspect exact artifacts and carry required notices before distributing a bundled package.

`LICENSE` is Apache-2.0. BIO CE source headers carry the candidate copyright and license. Privacy scanning does not establish copyright ownership; see [Source Provenance Audit](source-provenance.md).

## Publication boundary

The scan applies to the local 43-file tracked snapshot and the two-commit history as they existed on 2026-10-21. Uncommitted edits were included in the source snapshot but not the Git-history scan. The historical candidate directory label remains in the unchanged CE-7 report only. Rerun the audit against the exact release tree and full history before Public release.
