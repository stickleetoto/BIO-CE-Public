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

## v0.4.4-rc4 (pre-release)

- **Don't copy or replace the files in the data folder by hand, and don't keep it in a cloud sync folder**
  (OneDrive, Dropbox, Google Drive). The data folder is `%LOCALAPPDATA%\BIO-CE\data`. SQLite applies the
  `memories.sqlite3-wal` file beside the database to it, whatever file that `-wal` came from. A `-wal` left there by
  a hand copy, or put back or moved separately by a sync program, is laid over your memories as soon as the app, an
  AI tool's BIO CE server or a session hook opens the file, and the app's next close makes it permanent: memories
  can be lost. Use **Settings → Create backup…** and **Restore** instead, and keep the data folder outside any sync
  folder. If you already copied files into it, copy the whole data folder somewhere else before you start BIO CE
  again. The next release refuses to open a data file over a `-wal` it didn't write for that file.
- The installer and the programs it installs are **not code-signed**.
- **A memory moved to another space can leave its kept inbox item behind.** When a memory made from an inbox item
  (with **To memories** or an approved suggestion) is moved to another space, the inbox item kept for its Undo stays
  in the first space's kept area. Deleting or forgetting the memory completely in its new space does not remove that
  kept item, so its text can stay in BIO CE's database file. No list shows it and it is not used anywhere. To avoid
  it, forget the memory completely before moving it, or move it back first. A fix is planned for v0.4.5.
- **The Forget completely confirmation for a deleted memory doesn't count its kept inbox items.** For a memory in
  **Deleted memories**, the confirmation does not say how many kept inbox items go with it, but Forget completely
  still erases them (unless another memory still keeps one).
- **Delete and Forget completely are different.** Deleting a memory hides it from BIO CE's searches and your AI
  tools; it stays in **Deleted memories** (and in the database file) until you use **Forget completely**. Forget
  completely erases the memory, every earlier version, the inbox items kept for it, and the review items about it from
  BIO CE's files as far as the app can, with no undo. BIO CE cannot guarantee erasure from the drive itself (SSD wear
  leveling, the Windows page file, file system journals); backups and exports made earlier still contain it, and what
  an AI tool already read stays in that conversation.
- **Discard really deletes.** A discarded inbox item can be brought back with Undo for 8 seconds; after that it can't
  be undone.
- Automatic backups: BIO CE keeps the newest automatic backup pairs (10 by default; Settings → Backups) and removes
  older ones by overwriting them with zeros and then deleting them, as far as the app can (the same drive caveat
  applies). Only files with the names BIO CE gives its own automatic backups are removed; backups you saved yourself
  are never touched.
- Running BIO CE MCP servers: Connections shows how many are running for each AI tool. **End idle servers…** ends the
  ones without a request for 12 hours, only when you ask; BIO CE never ends them on its own, because it is not known
  whether every AI tool starts a new server for a conversation whose server was ended. A conversation that used an
  ended server may fail its next memory call until the AI tool starts a new one.
- The memory screen's search finds memories that contain every word you type, in the tab you are on; it is not ranked
  the way your AI tools' search is.
- Undoing **To memories** or an approved review gives a memory its earlier text back only if it hasn't changed since;
  otherwise it is left as it is.
- Korean and English: the app follows the language chosen in Setup, then the Windows language. Text uses Malgun Gothic
  in both languages. In the Korean app on a Japanese or Chinese Windows, the Windows UI font is used, which may not
  show Hangul evenly. What AI tools read from BIO CE (tool texts, server instructions, the memory skill) stays in
  English. A rare service message BIO CE doesn't know yet is shown in English in the Korean app.
- Big screens (1920x1080, 2560x1440) and the Korean text widths were checked with simulated screen sizes in the layout
  tests, not on real monitors of those sizes.
- Fixed since v0.4.3-rc1: the reading-pane height on small screens (the drawer scrolls), the import preview's TEXT
  column (long text ends in "…", hover a row for all of it), Suggestions now follow the space you choose, **Set
  date…** in the import preview, automatic backups no longer pile up, long titles end in "…", and a merge draft keeps
  the most detailed item. Fixed in rc4: Forget completely no longer erases an inbox item that another memory still
  keeps.

## v0.3 Auto memory (v0.3.0-rc1)

- Real-model behavior was checked once per host with a short synthetic conversation ([evaluation](real-model-memory-evaluation.md)): Claude Code saved, deduplicated, corrected, and recalled memories as intended; Codex never saw BIO CE's tools. Six and three conversations are too few to generalize. Server-side dedupe, the secret filter, and the review queue were exercised only by synthetic and mock-model tests.
- Installation on a clean Windows account or VM is **not verified**: creating another Windows account needs administrator rights, and Windows 11 Home has no Windows Sandbox. The v0.3.0-rc1 installer E2E ran silently on the developer's own account with synthetic data, and the GUI was checked by window capture only (no input was sent while the user was working).
- The policy's secret, injection, triviality, and duplicate checks are heuristics. A credential without digits or symbols, an instruction phrased in an unlisted way, or a paraphrased duplicate can pass; mentions of credentials are sent to review instead of being stored. The host model's judgment comes first and BIO CE's checks are a backstop.
- **Codex CLI: Auto memory is limited.** Codex 0.162 runs its catalog models in code mode, which shows the model neither BIO CE's MCP tools nor its server instructions (open Codex issues #32101, #24536, #55512; no fix through 0.164.0). BIO CE's server, tool listing, and tool calls work, so a model that knows the tool names can use them; with trusted session hooks BIO CE tells it the names, which was not verified with a real model. BIO CE does not apply unofficial Codex settings such as `features.code_mode.direct_only_tool_namespaces`. See [Codex support](codex-support.md).
- Codex runs new or changed hooks only after the user approves them with `/hooks`. Claude Code defers MCP tools behind `ToolSearch`, so the model must load BIO CE's tools before calling them.
- The connection token is stored in the host's user configuration in plain text. Grants limit what an AI host does through BIO CE; they do not protect against other programs running as the same Windows user.
- FTS5 recall is lexical. Korean words with attached particles (e.g. "배포를" vs "배포") may not match each other, so per-prompt recall can miss related memories.
- Settings backups are two files (`X.sqlite3` and `X.control.sqlite3`). A restore keeps the current connections, permissions, activity log, review queue, and app settings (inbox periods, file text limit); it only brings back project spaces, folder links, and inbox bookkeeping from the second file. Backups made by v0.4.1 or earlier have no second file and restore memories only.
- Automatic retraction is disabled by design; every retraction request waits for the user.

## v0.4.2-rc1 (pre-release)

- Discarding an inbox item removes it from BIO CE's files as far as the app can (freed space in the database and its
  log is overwritten). BIO CE cannot guarantee erasure from the drive itself (SSD wear leveling, the Windows page
  file, file system journals), and backups made earlier still contain the item.
- Going back from 0.4.2 to 0.4.1 keeps General memories and existing connections working. Inbox items and
  project-space memories are not shown by 0.4.1; they stay in the database and appear again after updating to
  0.4.2 again.
- Backups made by 0.4.1 or earlier are one file and restore memories only; project spaces found in them come back
  named "Restored: <name>".
- A space name that matches no space, or more than one, uses General (the result says so). Hosts that ignore the
  `space` argument save to General.
- Inbox and space management (moving, discarding, the space picker) is part of the built-in Community Engine only,
  like the review queue.
- Inbox expiry runs while the BIO CE app is open (at start and then daily); with the app closed, items are proposed
  and discarded the next time it runs.
- No real-model comparison of curated and collect mode was run for this candidate.

## v0.4.3-rc1 (candidate)

- The installer and the programs it installs are **not code-signed**.
- Claude desktop app: verified with the Microsoft Store version 5.11492 on 2026-11-14 (a memory saved in a chat
  was visible at once in BIO CE and Codex, and the other way round). The installer (non-Store) version was not
  run. The app has no session hooks, and whether its model uses BIO CE on its own, without being asked, has not
  been verified. The memory skill can only be added by uploading the ZIP yourself.
- The Claude desktop app reads its settings when it starts: quit it completely and reopen it after connecting or
  disconnecting. If it is open while BIO CE changes the file, it may write its old settings back when it quits.
- Imports: sensitive-entry labels and source-note detection are local word patterns (Korean and English). They
  can miss things or label harmless entries; check the preview. Dates written by another AI are never treated as
  confirmed until you confirm them.
- Sorting suggestions compare wording, not meaning: two entries that say the same in different words are not
  suggested for merging, and entries that share only their opening words ("The user …") are not merged either.
  An approved suggestion can be undone (right after approving, from History, or with Undo merge in the inbox): the
  inbox items it used are kept, not deleted, and so is an inbox item you move to your memories. They stay in your
  memory file, and in backups, until you undo or delete the result (Discard, or Retract the memory): then they are
  deleted with it, the way a discard deletes. There is no separate place to view them. A suggestion approved before
  0.4.3-rc1's fourth candidate deleted them and can't be undone.
- Restoring a backup first saves your current memories as a backup ("auto-before-restore-…" in the backups folder
  of the data folder). These automatic backups are not removed by BIO CE; delete the ones you no longer need.
- Exports are plain text and not encrypted; a Personal export contains your personal memories.
- The smallest supported window is 860x560 at 100% display scaling (1290x840 at 150%). A screen that can't fit it, such as 1024x768 at 150%, gets a smaller window: nothing is cut off sideways (buttons wrap, table columns fit, long lines end in “…”), but the Memories and Inbox reading panes can run out of height, so lines under the title, and in Memories the Show details row, may not fit. Maximize the window, use a lower display scaling, or use the right-click menu on the Memories list.
- The MCP server refuses to start until the BIO CE app has created its data folder. An AI app connected before
  BIO CE was opened once shows the server as failed until you open BIO CE.
- On a 768 px tall screen with Windows text size set much larger (about 150%), the Memories reading pane can be
  too short for its buttons; use the right-click menu on the list.
- In the import preview, the TEXT column shows the start of long entries when the window is narrow (the short
  columns keep their full text first). Select a row to read the whole entry under the table.
- The Suggestions page lists suggestions for every space and names the space on each card; the Space box above it
  doesn't filter them.
- Changing an entry's text with **Edit…** in the import preview clears its source date, because that date was about
  the original text. **Confirm dates…** can't bring it back (it confirms source dates); type the date in the Edit
  window's "Said on" field if you know it.
- An imported entry that is close to an item already in the inbox is imported as a new item, and Suggestions then
  offers to merge them. Only an entry close to one of your memories goes to review as a possible change.

## v0.4.1-rc1 (pre-release)

- The installer and the programs it installs are **not code-signed**. A Windows PC without Python or Git has **not been verified**; the automated clean install ran on a GitHub-hosted runner that has both.
- Codex keeps one BIO CE MCP server per open conversation and does not start a new one if it ends, so BIO CE does not end idle servers: they stay until the conversation or Codex closes. An idle server uses little memory and, after 60 seconds, holds no database file open. Setting `BIO_CE_MCP_IDLE_SECONDS` ends idle servers, but then the next memory call in that conversation fails (verified with Codex 0.166 and the desktop app's 0.167).
- Upgrading closes running BIO CE MCP servers (Setup asks first; a silent install closes them and logs it). Open Codex or Claude Code conversations then need a new conversation to use BIO CE again.
- The Codex code-mode option needs Codex 0.166 or later. BIO CE checks the command-line tool's version; it cannot check the version bundled with the Codex desktop app.
- The memory skill only says when to use BIO CE; whether a real model follows it on its own has not been evaluated at scale. The server's memory policy still decides what may be stored.
- Uninstalling now warns when Codex or Claude Code still start this installation, but it still does not change their settings: disconnect in BIO CE first. The warning only appears in an interactive uninstall.
- The Claude desktop chat app is not supported; Claude Code is.

## v0.4.0-rc1 (candidate)

- BIO CE uses only its built-in Community Engine. Settings → Memory engine lists BIO Core as not installed; choosing another engine is disabled in this version, and BIO CE never switches engines on its own. Each engine would keep its own memories; nothing is copied between engines.
- Repeated identical review requests are merged only when their normalized title and text match exactly. A reworded repeat still creates a second review item, and two hosts sending the same request at the same moment can, rarely, create two.
- Uninstalling does not disconnect AI hosts: the uninstaller does not edit Codex or Claude Code settings, so after an uninstall with a host still connected, the host's `bio-ce` MCP server entry and session hooks point to the removed program and may fail to start. Disconnect each host on the Connections page first, or remove those entries afterwards.
- The installer and the programs it installs are **not code-signed**; Windows SmartScreen may warn about a downloaded copy. Check the SHA-256 in the release notes before running it.
- The unattended clean install ran on a fresh GitHub-hosted Windows runner, which has Python and Git installed. Other installer runs used the developer's own Windows account, including one inside another app's MSIX package context where Windows redirected `%LOCALAPPDATA%` and one started through Explorer. A Windows PC without Python or Git is still **not verified**.
