<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.4.4-rc1 — Release Notes (DRAFT)

**Status: draft, not released.** The file names, sizes, and SHA-256 below are filled in from the CI build of the
candidate. Nothing here is final until the owner approves the candidate.

## Download

| File | Size | SHA-256 |
|---|---:|---|
| `BIO-CE-Setup-v0.4.4-rc1.exe` | (from CI) | (from CI) |

```powershell
Get-FileHash -Algorithm SHA256 .\BIO-CE-Setup-v0.4.4-rc1.exe
```

### The installer is not code-signed

Neither the installer nor the programs it installs carry a digital signature, and Windows SmartScreen may warn
about a downloaded copy. Run it only if the SHA-256 above matches exactly. BIO CE never asks you to turn off
SmartScreen, Microsoft Defender, or any other protection.

## Updating

- **From v0.4.3-rc1 (or older):** run the v0.4.4-rc1 installer over the existing installation. Your memories,
  settings, backups, and AI connections are kept. **Close Codex, Claude Code, and the Claude desktop app before you
  install**, and start new conversations afterwards.
- The file formats do not change: no new tables, and both databases keep their versions. New settings (language,
  the memory screen's filters, how many automatic backups to keep) are rows in the existing settings table.
- **Going back to v0.4.3-rc1 works:** run the v0.4.3-rc1 installer over v0.4.4-rc1. Memories you deleted stay
  hidden there too (v0.4.3 calls this retracting, and has no Deleted memories view); memories you forgot completely
  are gone in both versions. v0.4.3 ignores the new settings rows.

## Added

- **One memory screen.** Memories, the inbox, suggestions, and the reviews waiting for you are now tabs of one
  screen, with the spaces as chips above them. Click a card to open it in a drawer beside the cards (on a wide window
  the drawer moves the cards aside; on a narrower one it lies over them). Point at a card for Edit, Move, and Delete;
  drag cards onto a space chip to move them. The old Memories, Inbox, Suggestions, and editor pages are gone.
- **Undo instead of confirmations.** Deleting a memory, discarding an inbox item, moving cards, and rejecting a
  suggestion or a review wait 8 seconds for **Undo**. Moving an inbox item to your memories and approving a review can
  be undone too, as long as the memory hasn't changed since.
- **Reviews side by side.** A change an AI tool proposes shows the current memory and the proposal next to each other,
  with the changed words marked. When the proposal looks like a different fact, **Add as a new memory** is the first
  choice, so nothing is overwritten by mistake.
- **Forget completely.** A memory you delete stays in **Deleted memories** (hidden from searches and your AI tools).
  **Forget completely** erases it, every earlier version, the inbox items kept for it, and the review items about it
  from BIO CE's files, as far as the app can. There is no undo; backups and exports made earlier still contain it.
- **Korean.** The whole app is in Korean or English: it follows the language you chose in Setup, then the Windows
  language. Text uses Malgun Gothic in both languages, so Korean memories show evenly on an English Windows too.
  What AI tools read from BIO CE stays in English.
- **Conveniences:** a search box above every page (Ctrl+F or /), filters and sorting on the memory screen (where a
  memory came from, which AI tool, when it changed, sensitive marks; remembered), quick add (type one line and press
  Enter), selecting several cards (Ctrl+click, Shift+click) with a bar to move, delete, export, or copy them, Copy for
  one memory, and **?** for the list of keys.
- **Running MCP servers.** Connections shows how many BIO CE servers each AI tool is running and when they were last
  used, and **End idle servers…** ends the ones idle for 12 hours (only when you ask).
- **Big windows.** From about 2,200 pixels wide the pages stay at most 1,960 pixels wide and centred; cards use up to
  four columns; the dashboard lists recent memories in two columns.

## Changed

- Automatic backups no longer pile up: BIO CE keeps the newest 10 pairs (Settings → Backups) and overwrites older
  ones with zeros before deleting them. Backups you saved yourself are never removed.
- A merge suggestion's draft now starts from the most detailed item, and sentences only in the other items are listed
  apart to add if you want.
- The notices say what each action really does: a deleted memory stays in Deleted memories until you forget it
  completely; a discarded item can't be undone after the 8 seconds.

## Fixed

- The reading pane no longer runs out of height on small screens (the drawer scrolls).
- The import preview's TEXT column ends long text in "…"; hover a row for all of it. **Set date…** puts a source date
  back without opening Edit.
- Suggestions follow the space you choose.
- Long titles end in "…" instead of being cut off.

## Known limitations

See [docs/known-limitations.md](docs/known-limitations.md#v044-in-development--draft). In short: the installer is not
code-signed; Forget completely, Discard, and removing old backups erase as far as the app can, not from the drive
itself; idle MCP servers end only when you ask; the memory screen's search matches words, not meaning.
