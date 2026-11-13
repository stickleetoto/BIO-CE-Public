<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.4.2-rc1 — Release Notes (candidate)

**Status: pre-release.** Not a final release.

## Download

| File | Size | SHA-256 |
|---|---:|---|
| `BIO-CE-Setup-v0.4.2-rc1.exe` | 41,035,622 bytes | `2e641efa677ed59adb1b5b9efa89a68ce05e63372157b176a314a162bb6406a2` |

Built and tested on a GitHub-hosted Windows runner (GitHub Actions run 43370145994) from source commit
`7bb7e7c43f1e3633270066c1411890683d3d8985`, with CPython 3.12.10, PyInstaller 6.22.3, and Inno Setup 6.7.3. The tag also contains a later commit
that changes only this file and `docs/known-limitations.md`; neither goes into the installer.

```powershell
Get-FileHash -Algorithm SHA256 .\BIO-CE-Setup-v0.4.2-rc1.exe
```

### The installer is not code-signed

Neither the installer nor the programs it installs carry a digital signature, and Windows SmartScreen may warn
about a downloaded copy. Run it only if the SHA-256 above matches exactly. BIO CE never asks you to turn off
SmartScreen, Microsoft Defender, or any other protection.

## Updating

- **From v0.4.1-rc1 or v0.4.0-rc1:** run the v0.4.2-rc1 installer over the existing installation. Your memories,
  settings, backups, and AI connections are kept. **Close Codex and Claude Code before you install.**
- **After updating, start new conversations in Codex and Claude Code.** Setup closes the BIO CE MCP servers that
  AI hosts are running so it can replace them; conversations that were open during the update can no longer reach
  BIO CE.
- On first start, BIO CE copies its connection file once to `control.before-0.4.2.sqlite3` in the data folder and
  then adds new tables. The memory database format does not change.
- **Going back to v0.4.1-rc1 works:** run the v0.4.1-rc1 installer over v0.4.2-rc1. Your General memories and
  connections keep working. Inbox items and project-space memories are not shown by v0.4.1 but stay in the
  database, and they appear again when you update to v0.4.2 again. Close Codex and Claude Code first here too.

## Added

- **Collect mode and the inbox.** Each AI host can save in **Curated** mode (the default, as before: only what you
  stated or confirmed) or **Collect** mode, which you switch on the host's card after a confirmation. In Collect
  mode the host saves lasting information to your **inbox** without asking: what you said, its own guesses
  (marked as guesses), and, when you ask it to remember a file or page, a summary of at most 2,000 characters.
  Hosts don't use the inbox unless they ask for it, and session hooks never do. On **Memories → Inbox** you move
  what is worth keeping to your memories (BIO CE offers to update a similar memory instead of adding a copy) or
  discard it. Items unused for 30 days are proposed for discarding and discarded 7 days later unless you keep
  them; both periods are in **Settings → Inbox**.
- **Project spaces.** General holds all your existing memories. A project space keeps one project's memories
  apart: create it in **Settings → Spaces** and link the project's folder (BIO CE stores only a fingerprint of the
  path and the folder name). AI tools pass the space by name; when a name doesn't match exactly one space, BIO CE
  uses General and says so. Session hooks pick the space of the folder you work in. The Memories page has a space
  picker. Each host card can switch project spaces off for that host.
- **Two-file backups.** A backup is now `name.sqlite3` (your memories, in the same format as before) and
  `name.control.sqlite3` (connection records, spaces, and inbox bookkeeping, tied to the memory file by a
  checksum). Keep the two files together and don't share them. A restore never brings back connections,
  permissions, the activity log, or app settings from a backup; those stay as they are now. Backups made by
  v0.4.1 or earlier still restore (memories only).
- **Reviews at a glance.** The Dashboard shows what waits for you (review items and inbox clean-up), and the
  sidebar shows the counts next to Connections and Memories.
- **Memory skill v2.** The skill BIO CE installs explains spaces and follows the host's saving mode; switching
  modes rewrites the skill BIO CE installed (it asks first if you edited it).

## Discarding inbox items: what "discard" means

Discarded inbox items are removed from BIO CE's database **as far as the app can**: BIO CE overwrites the freed
space in the database file and its log. It **cannot guarantee erasure from the drive itself** (for example SSD
wear leveling, the Windows page file, or file system journals). **Backups you made earlier still contain these
items;** delete old backups you no longer need. Curated memories are never deleted this way: retracting one hides
it and keeps its history, as before.

## Fixed

- A folder path such as `notes/2026-11-11/project` was refused as a "high-entropy token". Relative paths are now
  stored. Your own profile folder is saved as `%USERPROFILE%`, other users' profile folders lose the user name,
  and any other absolute or network path waits for your review instead of being stored.
- The AI hosts list on the Dashboard no longer cuts off long status labels.

## Unchanged

- The memory database format (`memories.sqlite3`) and the existing connection format. Existing connections keep
  working without reconnecting. Curated saving behaves as in v0.4.1.

## Verified for this candidate

- On the GitHub-hosted runner, for this exact installer: the automated test suite (301 passed; 3 skipped for tools the runner does not have); the release
  payload check (every file against the build manifest, no test code, no credentials, build-machine identity, or
  private identifiers, license notices); an unattended clean install, first launch, installed MCP server and hook,
  and uninstall; an upgrade from the published v0.4.1-rc1, including while an AI host still runs the previous MCP
  server, that keeps every memory, review item, connection, and backup; and a **rollback**: data only v0.4.2
  understands (a project-space memory and an inbox item), then v0.4.1-rc1 installed over it, which still serves
  General through its MCP server, hook, and window and changes no memory or connection row, then v0.4.2-rc1 again,
  which shows the inbox and project items.
- Automated tests on the developer's PC: after an inbox item is discarded, its text is not found in the bytes of
  the database, its log, the connection file, or a backup made afterwards (and, as a control, a plain delete
  without these steps does leave it in the file).

## Not verified

- **A Windows PC without Python or Git.**
- Claude Code and Codex registration from the installed app on the hosted runner (no CLI there).
- Whether real AI models use Collect mode and spaces well over many sessions; no real-model comparison was run
  for this candidate.
- Real 125%/150% display scaling, Windows 10, and screen readers.

## Known limitations

See `docs/known-limitations.md` (v0.4.2 section). In short: discarding cannot guarantee erasure from the drive
and earlier backups keep discarded items; v0.4.1 does not show inbox or project-space memories after a rollback;
v0.4.1 backups restore memories only; an upgrade ends open conversations' access to BIO CE; uninstalling does not
disconnect AI hosts; Codex Auto memory is limited in code mode; the installer and programs are not code-signed;
and a PC without Python has not been tested.
