<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.4.3-rc1 — Release Notes (candidate)

**Status: pre-release candidate.** Not a final release.

## Download

| File | Size | SHA-256 |
|---|---:|---|
| `BIO-CE-Setup-v0.4.3-rc1.exe` | 41,343,197 bytes | `2db0603da1505971549c1eb49157ecceabb3c38b29e1e883cf0cf7164c52e33c` |

```powershell
Get-FileHash -Algorithm SHA256 .\BIO-CE-Setup-v0.4.3-rc1.exe
```

### The installer is not code-signed

Neither the installer nor the programs it installs carry a digital signature, and Windows SmartScreen may warn
about a downloaded copy. Run it only if the SHA-256 above matches exactly. BIO CE never asks you to turn off
SmartScreen, Microsoft Defender, or any other protection.

## Updating

- **From v0.4.2-rc1 (or older):** run the v0.4.3-rc1 installer over the existing installation. Your memories,
  settings, backups, and AI connections are kept. **Close Codex, Claude Code, and the Claude desktop app before you
  install**, and start new conversations afterwards.
- BIO CE adds two tables to its connection file (import batches and sorting suggestions). The memory database
  format does not change.
- **Going back to v0.4.2-rc1 works:** run the v0.4.2-rc1 installer over v0.4.3-rc1. General, project spaces, and
  the inbox keep working. Personal memories, import records, and suggestions are not shown by v0.4.2 but stay in
  the files and appear again when you update to v0.4.3 again. A Claude desktop app connection stays in the app's
  settings and keeps working, but v0.4.2 doesn't show it; disconnect it in v0.4.3 first if you want it gone.

## Added

- **Personal space.** A separate space for memories about you: health, family, finances, where you studied or
  served. It is off until you turn it on in **Settings → Spaces**. No AI host can read or save Personal until you
  allow that host on its card, after a confirmation that what it reads is sent to its AI service. Session hooks
  never use Personal, a search without `space` never includes it, and a name BIO CE can't match never falls back
  to it. Results from Personal are marked `personal: true`. Text that names a local folder goes to the Personal
  inbox when the host may save there, and to your review otherwise. **Memories → Move to…** moves one or more
  memories between General, Personal, and project spaces with their history, after an automatic backup.
- **Import from another AI.** **Memories → Inbox → Import…** takes the list ChatGPT, Claude, or another AI gives
  you (paste it, or open a .md or .txt file) in the "[date] - memory" format. You choose where it goes (Personal is
  recommended; nothing goes to General unless you pick it) and see a preview first:
  - secrets are blocked and masked, instructions to an AI must be rewritten as your preference, long entries must be
    shortened;
  - entries BIO CE already has are skipped, and an entry that may change one of your memories (same topic,
    different text) goes to your review queue — nothing is overwritten; an entry close to an inbox item is imported
    and offered for merging in Suggestions;
  - sensitive entries (health, military service, school, family, money, contact details) are labelled; they stay
    ticked for Personal and start unticked for General or a project;
  - the AI's explanations around the list are shown as source notes and lines BIO CE couldn't read are listed
    apart; neither is saved;
  - dates written by another AI are kept as the source's date and shown as unconfirmed. They count as "said on"
    only after you confirm them; a date used by many entries is flagged as a likely export date. Changing an
    entry's text with **Edit…** clears its source date (it was about the original text).
  New entries go to the inbox in batches of 100. **Recent imports** lets you undo an import (what is still in the
  inbox is removed; what you already kept stays) or "Review and keep" its entries.
- **Sorting suggestions.** **Memories → Suggestions** proposes merging repeated inbox items, keeping items your
  hosts use again and again, and updating a memory an inbox item adds to. Nothing changes until you approve; you can
  edit a draft first, approve or reject all shown at once, and filter by import. Rejected groups are not suggested
  again. BIO CE never calls an AI model for this. Entries that only share their opening words ("The user …") are
  not suggested together.
- **Undo for suggestions.** Approving a suggestion never deletes the inbox items it used: they are kept aside so
  you can undo it — with **Undo** right after approving (**Undo all** after "Approve all shown"), **Undo this
  suggestion…** in a memory's History, or **Undo merge…** on a merged inbox item. The result gets its earlier text
  back (the undone version stays in History), and the items come back unchanged. An inbox item you move to your
  memories is kept aside the same way. Kept items are deleted with their result when you discard it or retract the
  memory, or undo the import they came from — the way a discard deletes; the delete dialogs say so.
- **Export.** **Memories → Export…** saves chosen spaces as a "[date] - memory" .md file you can paste into another
  AI or import back. Personal is included only when you tick it and confirm again. Imported memories carry only the
  date you confirmed, otherwise `[unknown]`. Files are never overwritten, and they are not encrypted.
- **Claude desktop app.** A new card on **Connections** connects the Claude desktop chat app (Microsoft Store and
  installer versions). BIO CE backs up the app's settings file and adds one `bio-ce` entry, keeping everything
  else; quit and reopen the app afterwards. The app has no session hooks. **Save skill as ZIP** saves the memory
  skill for you to upload yourself in Claude (Customize → Skills); BIO CE never uploads anything.
- **Memory skill v3.** Adds the Personal rules and a note that imported memories were written by another AI.

## Changed

- BIO CE's MCP server no longer starts when the BIO CE data folder or database doesn't exist. It says "Open the
  BIO CE app first" and creates nothing. (A program started by the Claude desktop app can have new folders
  redirected into the app's private storage, where BIO CE and other AI tools would never see them.)
- The uninstall warning also lists a Claude desktop app that still starts this installation.
- The inbox lists every item (it stopped at 500 before).
- **Restoring a backup first saves your current memories** as a backup ("auto-before-restore-…" in the backups
  folder), so nothing is lost by a restore.
- **Only a delete removes memories from the file.** Discarding, retracting (with the items kept for it), undoing an
  import, and the inbox expiry are the only actions that delete rows; every other action is checked by a test.
- When an inbox item is discarded, the text a sorting suggestion had copied from it is removed too.
- Screens and dialogs fit the smallest window (860×560): buttons wrap, table columns fit their width, long lines
  end in "…", and titles stop at three lines (the full title shows on hover).

## Known limitations

In short (details in `docs/known-limitations.md`, section v0.4.3-rc1):

- The installer and programs are not code-signed.
- On a screen smaller than the smallest window (for example 1024×768 at 150%), reading panes can run out of
  height; nothing is cut off sideways.
- Imports and suggestions compare wording, not meaning. A date written by another AI stays unconfirmed until you
  confirm it; editing an entry's text clears it.
- Items kept for undo, and automatic backups (before a move or a restore), stay until you undo or delete; BIO CE
  doesn't remove old automatic backups.
- Suggestions show every space at once; the Space box doesn't filter them.
- Exports are plain text, not encrypted.
- The Claude desktop app reads its settings only when it starts; quit and reopen it after connecting.
