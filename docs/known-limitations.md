<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Known Limitations

- Official support target is Windows 11 x64 for v0.3.0-rc1. Only Windows 11 Home build 26200 (Korean locale, 100% scale) was exercised. Windows 10 is not tested; Setup does not block it, but it is not supported.
- The release build and test runtime is the official python.org CPython 3.12.10 x64 build (the last 3.12 release with Windows binaries). Package metadata requires Python >=3.12; Python 3.11 compatibility is not claimed.
- CPU-first; no neural retrieval, embedding, model manager, or model API call. BIO CE never extracts memories from conversations itself; Auto memory writes come only from tool calls of a host the user switched to Auto memory.
- Search uses SQLite FTS5 lexical ranking. Recall/MRR data measures exact synthetic targets, not semantic evaluation.
- MCP uses local stdio only. There is no HTTP transport or remote listener. Per-connection tokens identify host connections; there are no user accounts or multi-user access control.
- The MCP server serves one scope. Managed (v0.3) connections take it from their grant and refuse any other; servers without a connection take it from their launch arguments. Scope strings are never used as authentication.
- Reads revalidate freshness immediately before return; a write committed after that check is ordered after the read. Strict immediate revocation is unsupported.
- Retraction blocks application reads but keeps earlier rows in SQLite; secure erasure is unsupported.
- recorded_at may be caller-supplied and is not a trusted audit timestamp.
- Conflicts are surfaced as lexical results; the store does not choose authoritative sources or resolve truth.
- No encryption at rest, key management, retention, production monitoring, or deployment hardening. Desktop SQLite backup and validated restore exist, but there is no automated backup lifecycle or cloud backup.
- The installer and executables are unsigned; SmartScreen may warn on downloaded copies. Installation on a clean Windows 11 VM or account without Python/Git/developer tools is NOT VERIFIED (no VM or Windows Sandbox was available on the Windows 11 Home test machine). The real-GUI install/update/uninstall run used the developer's own account.
- Display scaling of 125% and 150% is covered only by simulated-scale UI tests, not by changing the Windows display setting. BIO CE is system-DPI aware, not per-monitor aware.
- Launching BIO CE from a process inside an MSIX app container (for example a terminal started by a packaged app) lets Windows redirect new `%LOCALAPPDATA%` folders into that package's private storage. BIO CE then stores its data in, and registers host connections with, the redirected path. Start BIO CE from the Start menu.
- Uninstall leaves host MCP settings unchanged. Disconnect Codex/Claude from the Connections page before removing the app.
- Actual Codex CLI and Claude Code model-issued tool calls are not verified by the SDK suite.
- Python dependency pins do not include artifact hashes or a package-index URL. The RC1 bundle includes license texts for its pinned Python dependencies, CPython 3.12.10 and its incorporated libraries, Tcl/Tk, the PyInstaller bootloader, and Inno Setup. Licenses of Rust crates statically linked into `pydantic-core`, `rpds-py`, and `cryptography` are represented only by those distributions' own license files.
- The installer is not byte-for-byte reproducible across machines; `build-manifest.json` records per-file hashes so two builds can be compared.
- Source provenance: the full local BIO Core source, history, and its private remote were compared with BIO CE on 2026-10-25 and no BIO Core code was found. The owner decisions and residual risks (for example, AI-assisted code was not checked against public code databases) are listed in the [provenance audit](audit/source-provenance.md).
- GitHub Actions CI: **PASS** on commit `9a59ed4` ([run 40283656213](https://github.com/stickleetoto/BIO-CE-Public/actions/runs/40283656213), 2026-10-26, `windows-2025`, CPython 3.12.10): 100 passed, 3 skipped. The skips are expected on a hosted runner: two host-connection tests need the Codex and Claude Code CLIs, and the packaged-EXE test needs a local installer build; all three pass locally. The CI runner has no display scaling, no real desktop session, and no AI host CLIs, so it does not replace the installer E2E. Windows 10 remains NOT RUN.

## v0.3 Auto memory (v0.3.0-rc1)

- Real-model behavior was checked once per host with a short synthetic conversation ([evaluation](real-model-memory-evaluation.md)): Claude Code saved, deduplicated, corrected, and recalled memories as intended; Codex never saw BIO CE's tools. Six and three conversations are too few to generalize. Server-side dedupe, the secret filter, and the review queue were exercised only by synthetic and mock-model tests.
- Installation on a clean Windows account or VM is **not verified**: creating another Windows account needs administrator rights, and Windows 11 Home has no Windows Sandbox. The v0.3.0-rc1 installer E2E ran silently on the developer's own account with synthetic data, and the GUI was checked by window capture only (no input was sent while the user was working).
- The policy's secret, injection, triviality, and duplicate checks are heuristics. A credential without digits or symbols, an instruction phrased in an unlisted way, or a paraphrased duplicate can pass; mentions of credentials are sent to review instead of being stored. The host model's judgment comes first and BIO CE's checks are a backstop.
- **Codex CLI: Auto memory is limited.** Codex 0.162 runs its catalog models in code mode, which shows the model neither BIO CE's MCP tools nor its server instructions (open Codex issues #32101, #24536, #55512; no fix through 0.164.0). BIO CE's server, tool listing, and tool calls work, so a model that knows the tool names can use them; with trusted session hooks BIO CE tells it the names, which was not verified with a real model. BIO CE does not apply unofficial Codex settings such as `features.code_mode.direct_only_tool_namespaces`. See [Codex support](codex-support.md).
- Codex runs new or changed hooks only after the user approves them with `/hooks`. Claude Code defers MCP tools behind `ToolSearch`, so the model must load BIO CE's tools before calling them.
- The connection token is stored in the host's user configuration in plain text. Grants limit what an AI host does through BIO CE; they do not protect against other programs running as the same Windows user.
- FTS5 recall is lexical. Korean words with attached particles (e.g. "배포를" vs "배포") may not match each other, so per-prompt recall can miss related memories.
- Settings backups cover `memories.sqlite3` only; the AI audit log and review queue in `control.sqlite3` are not backed up or restored.
- Automatic retraction is disabled by design; every retraction request waits for the user.
