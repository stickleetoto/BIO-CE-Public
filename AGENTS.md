<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Rules for AI agents working in this repository

BIO Community Edition (CE) is a free, local Windows memory app: a desktop app, a stdio MCP server, and session
hooks for Codex and Claude Code. These rules apply to every agent and every task in this repository.

## BIO work rules

1. **Test first.** Reproduce a defect with a failing test, then fix it, then show the test passes.
2. **Report only what you ran.** Use PASS, FAIL, PARTIAL, BLOCKED, or NOT RUN. A run on a developer PC is not a
   clean-machine result. When an earlier report was wrong, say so and correct it.
3. **Keep test evidence.** Every test run saves JUnit XML in the project's evidence folder (outside this
   repository) with a dated name and a log row, including failures and flaky results.
4. **Never touch real user data or settings in tests.** Point `TEMP`, `TMP`, `LOCALAPPDATA`, `USERPROFILE`,
   `HOME`, `CODEX_HOME`, and `CLAUDE_CONFIG_DIR` at a scratch folder. Use synthetic databases only. Installing a
   program on the user's account or sending keyboard or mouse input to their desktop needs approval each time.
5. **Schemas change only additively and with approval.** `memories.sqlite3` is at user_version 1 and
   `control.sqlite3` at user_version 2; released versions refuse other versions, so a rollback must keep working.
6. **Never rewrite published history.** No force push. Commits use the GitHub noreply address.
7. **Keep the public boundary.** Never copy code, module names, paths, keys, or tokens from the private Core
   project into this repository or a build. Report Core needs as requests instead. CE must work fully without Core,
   and no unverified Core capability may be claimed.
8. **Scan before anything leaves the machine.** Run gitleaks and a scan for private identifiers, local paths,
   personal e-mail addresses, and credentials over the diff and the commit messages.
9. **Security controls are not bypassed.** The memory policy (secret filter, prompt-injection guard, review queue)
   applies to every write. Host settings are changed only after the user confirms, with a backup first.

## CE-specific rules

1. **`origin` is public.** Pushing to it, creating tags, and creating or publishing GitHub releases each need the
   user's explicit approval. Push with explicit refspecs and `--atomic`; publish releases as drafts first.
2. **The CI mirror is private.** Push to it only when the user asks, and only after confirming that the repository
   is still private (for example `gh api repos/<owner>/<mirror> --jq .private`).
3. **No new product name in public.** The display name will change in a later version. Until the user says the
   new name may be published, do not write it in commits, code, docs, or releases. Internal identifiers stay as
   they are (`BIO-CE` data folder, `bio-ce` MCP server, `bio_memory_*` tools, `BIO_CE_CONNECTION_TOKEN`).
4. **Release candidates come from CI.** The installer that is published is the one built and tested by the
   release-qualification workflow, identified by its run and SHA-256, and re-downloaded and checked after
   publishing.
