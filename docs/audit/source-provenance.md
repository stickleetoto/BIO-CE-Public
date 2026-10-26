<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Source Provenance and IP Audit

**Status: PASS (2026-10-25), with the residuals listed in section 8.** This supersedes the 2026-10-21 PARTIAL
status, which rested on the full BIO Core source being unavailable for comparison. The complete local BIO Core
source and Git history, plus a read-only mirror of its private remote repository, were compared with every BIO CE
file version that a public repository would expose. No BIO Core code was found in BIO CE. This is an engineering
audit, not a legal opinion or ownership clearance.

Audited BIO CE state: branch `feat/autonomous-memory-v0.3` as of 2026-10-25, all local and remote-tracking refs of the
candidate repository, the private pre-candidate CE repository's full history, and the working tree.

## 1. What was compared

| Side | Sources | Unique text files |
|---|---|---:|
| BIO CE | Every blob on every ref of the public candidate (6 commits, 118 paths), the private pre-candidate CE repository (3 commits), and the working tree | 240 |
| BIO Core (main pass) | The live BIO Core repository: all 34 local refs and 385 commits, plus its working tree including untracked files; the 2026-10-13 non-destructive snapshot (Git bundle with 31 heads, one of them absent from the live repository, plus its copied worktree); a sanitized BIO Core reference copy (171 commits); 20 older BIO Core release and companion-app source folders, including every `.zip` source archive inside them | 34,320 |
| BIO Core (remote pass) | A read-only mirror of the private BIO Core GitHub repository (all 90 refs, including 13 refs and 17 commits absent from every local copy, and pull-request refs) and 179 hidden experiment, staging, and temporary copies inside the live and snapshot worktrees | 28,095 |
| BIO Core (supplement) | Remaining BIO folders found on the machine (diagnostic run folders with source archives, a training workspace) | 518 |

Text-like files up to 1.5 MB were included (Python, Markdown, TOML, JSON, PowerShell, shell, Inno Setup, YAML,
and similar). Virtual environments, `site-packages`, `node_modules`, caches, and build output were excluded
because they hold third-party code, not BIO Core authorship. Nothing in any BIO Core repository was modified. The
private remote was read with the owner's existing GitHub CLI login, and nothing was sent elsewhere.

## 2. Methods

1. **Exact.** Git blob IDs and whitespace-normalized content hashes across all corpora.
2. **Raw token fingerprints.** Comments, blank lines, and docstrings removed; winnowed 12-token fingerprints.
3. **Abstract token fingerprints.** Identifiers, strings, and numbers replaced by placeholders; winnowed 40-token
   fingerprints. This finds code that was renamed, reformatted, split across files, or moved.
4. **AST.** Every Python function and class of at least 40 nodes, with names, arguments, attributes, and constants
   abstracted. Exact structural hashes, plus node-type 8-gram Jaccard ≥ 0.6 for restructured code.
5. **Prose.** 8-word shingles over Markdown and text.
6. **Identifiers.** Distinctive identifiers (10+ characters) present in both corpora. Each distinctive one was
   traced to the BIO Core file defining it, and the two files were compared directly.
7. **Contiguous runs.** For every candidate pair, the longest contiguous common token run was measured in raw and
   abstract form across all historical versions of both files. Every run of 25 raw or 40 abstract tokens or more
   was reviewed side by side.

## 3. Results

| Layer | Result |
|---|---|
| Exact files | 1: `src/bio_ce/__main__.py`, a 2-line Python entry point (`from .cli import main` / `raise SystemExit(main())`) that is boilerplate in both projects |
| Raw fingerprints | Hits in 58 CE files, but sparse. Longest contiguous common run: 94 tokens (section 4, item 1); every other run ≤ 55 tokens (about 7 lines) |
| Abstract fingerprints | Longest runs come from benchmark JSON number arrays and dict-literal or keyword-argument shapes; no restructured copy of BIO Core logic |
| AST | Exact shape only for the Win32 structure in item 1; structural matches only for small frozen dataclasses, a chunked SHA-256 helper, and a test `tearDown` |
| Prose | At most 6 shared 8-word shingles, all in the third-party license inventory (dependency and license names) |
| Identifiers | 199 shared, nearly all from the Python standard library, Tk, the MCP SDK, or Win32. The distinctive ones (`_SECRET_PATTERNS`, `_STOPWORDS`, `_REQUIRED_TABLES`, `hash_token`, `build_context`, `_memory_line`, and the MCP tool names `bio_memory_search`/`bio_memory_read`) sit in BIO Core files whose code shares at most one 12-token line with the CE file. CE's MCP server shares no code with BIO Core's own MCP server. |

## 4. Every reviewed overlap

| # | CE location | Overlap | Classification | Decision |
|---|---|---|---|---|
| 1 | `benchmarks/run_fts5_benchmark.py` (`_peak_rss_bytes`) | The Win32 `PROCESS_MEMORY_COUNTERS` ctypes field list (94 tokens) | Interface dictated by Microsoft's documented API; any correct definition has these fields in this order | Publishable |
| 2 | `src/bio_ce/connections.py` (`_file_digest`), `tests/host_harness/install_e2e.py` (`sha256`) | Chunked `hashlib.sha256` file loop (≈7 lines) | Canonical Python idiom | Publishable |
| 3 | `src/bio_ce/control_store.py` (`__init__`) | `Path(...).resolve()`, `mkdir`, `threading.RLock()`, `sqlite3.connect(...)` | Standard setup sequence | Publishable |
| 4 | `src/bio_ce/desktop.py` (`save_privacy_acknowledgement`) | Atomic write: temp file → `flush` → `fsync` → `os.replace` → cleanup | Standard idiom; payload and error handling differ | Publishable |
| 5 | `src/bio_ce/core/models.py` | Canonical `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)` | Standard idiom | Publishable |
| 6 | `cli.py`, `packaging/build_assets.py`, benchmark | `def main(argv: list[str] \| None = None)` with `argparse` | Standard idiom | Publishable |
| 7 | `tests/host_harness/mock_model_server.py` | `send_header`/`end_headers`/`wfile.write` response lines | Standard library usage | Publishable |
| 8 | `.github/workflows/ci.yml` | `actions/checkout` and `actions/setup-python` steps | Standard GitHub Actions usage | Publishable |
| 9 | `src/bio_ce/__main__.py`, `src/bio_ce/mcp_entry.py` | 2–3 line entry points | Boilerplate | Publishable |
| 10 | `docs/evaluation/results/*.json` | JSON shape of numeric benchmark arrays | Abstract structural coincidence; values and keys differ | Publishable |
| 11 | `mcp_server.py`, `ui/theme.py`, `ui/pages/*.py` (abstract only) | Dict serializers, keyword-argument lists, dict literals | Structural coincidence; different names, keys, and logic | Publishable |

No overlap required tracing an original BIO Core author, date, or license: none is substantive code. The shared
style (type-hinted `main(argv)`, `pathlib`, chunked hashing) is consistent with one owner and the same AI coding
tools across both projects. Design-level ideas BIO CE shares with BIO Core (local memory with revisions,
retraction tombstones, scoped MCP tools) are concepts, not copied implementation. Whether those concepts should
stay confidential is a business decision for the owner (section 8).

## 5. Authorship and rights

- **BIO CE development history** (6 commits as of 2026-10-25): author and committer `stickleetoto` with the GitHub noreply address.
  Three later commits carry a `Co-Authored-By: Claude` trailer (AI assistance). No other human contributor appears.
- **Private pre-candidate CE repository.** 3 commits by `stickleetoto`. They are not part of the public history:
  the first published root commit is an independent root commit. This repository uses the owner's personal
  email, which is therefore not exposed.
- **BIO Core.** All 400 commits in the remote mirror share one email identity under two author names (one is
  `stickleetoto`; the other is a private name not repeated here). There are also GitHub web-merge commits and one
  commit by a backup automation identity. No `Co-authored-by` trailers. No second human contributor is evident.
- **Owner statement (2026-10-26).** The project owner confirmed in writing that they own both BIO Core and BIO CE,
  and that every Git author name used in both projects is their own. This is recorded as the owner's
  representation; it has not been independently or legally verified. Earlier, the owner also stated that they
  hold the rights needed to develop and publish this code.
- **AI-generated code.** BIO CE was written with AI coding assistants: OpenAI Codex agent sessions for earlier
  phases (per the build-environment records) and Anthropic Claude for later phases (commit trailers). Both
  providers' terms generally assign output rights to the user; check the terms that applied to the accounts used.
  Whether AI-assisted code is copyrightable affects how strong the Apache-2.0 license is, not whether the owner may
  publish it.

## 6. Third-party and external code

- No third-party implementation source is vendored. The only third-party texts in the tree are `LICENSE` (the
  exact Apache-2.0 text, byte-identical to apache.org) and the pinned CPython 3.12.10 license document under
  `packaging/notices/`.
- No "copied from", "adapted from", Stack Overflow, or gist markers, and no foreign copyright lines, in source,
  tests, packaging, or CI. Every source and document file carries the Apache-2.0 SPDX or copyright header.
- Runtime and build dependencies are installed from pinned lock files and listed with their licenses in
  [Third-Party Licenses](../THIRD_PARTY_LICENSES.md). The only copyleft component is PyInstaller
  (GPL-2.0-or-later with the bootloader exception, which allows distributing the built executables). The
  installer bundles all required notices (`THIRD_PARTY_NOTICES`). Dependencies are unchanged since v0.2.0-rc1.
- The CE Git history contains no binaries, databases, archives, keys, or logs: 118 paths, largest blob the CPython
  license text.

## 7. Exposure of BIO Core material through BIO CE

7,370 BIO Core-specific terms were extracted: path and module names from all history, class, function, and
constant names, internal codenames from commit messages, repository names, and local path fragments. They were
searched across 1,716 BIO CE surfaces: every blob on every ref, every commit message, the working tree, and the
strings of all 2,566 files in the v0.3.0-rc1 installer payload.

- No BIO Core package or module names, repository name or URL, local paths, internal ticket or phase codenames,
  or the second author name appear anywhere in BIO CE, its history, or its build output.
- The 158 terms that do appear are ordinary words or Python names (`memory`, `revision`, `server`, `__init__`).
- BIO CE documents say that a private "BIO Core" exists and was neither used nor modified. They contain no BIO
  Core code, structure, or design detail.
- **Fixed in this audit:** two internal names were removed from the current documents. They were the local folder
  name of the sanitized BIO Core reference copy (in the CE-7 report and the candidate manifest) and an internal
  BIO Core benchmark codename (in the earlier version of this register). Both still exist in the earlier private
  development commits (section 8). The public candidate history, a new root commit, does not contain them.

## 8. Residuals and owner decisions

| Item | Effect on publication | Who decides |
|---|---|---|
| Earlier commits keep two low-sensitivity internal names (section 7) | Visible in history if those commits are published. Removing them needs a history rewrite (for example publishing a new squashed root). | Owner |
| Author names and ownership | **Resolved by owner statement (2026-10-26):** the owner owns both projects and used every author name. | Owner (done) |
| Verbatim reproduction of public third-party code by AI assistants was not checked against public code databases: that would require sending the private source to a third-party service | Residual risk judged low. The code is application glue around SQLite, Tk, and the MCP SDK; no license markers or foreign headers were found. | Owner may accept, or run a local snippet scanner before release |
| Whether BIO Core's design concepts (not code) should remain confidential | Business decision | Owner |
| BIO Core content outside this machine and its GitHub remote (other computers, cloud drives, deleted history) | Not examined; out of scope "local sources" | Owner |

## 9. Reproduction

The comparison tools were run from a scratch folder outside every repository, because their raw output names
private BIO Core files. They are not part of BIO CE. Raw outputs were kept locally and not published.
