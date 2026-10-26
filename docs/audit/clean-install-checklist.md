<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Clean Windows Install Checklist (manual)

This checklist is the missing release gate for the installer. It has **not been run yet**: the qualification PC
(Windows 11 Home) has no Windows Sandbox or Hyper-V, no VM software, and no second account. Creating one needs an
administrator. Until someone completes every step on a clean machine, the clean install stays **NOT RUN**.

## Environment

Use one of these:

- **A virtual machine** (for example VirtualBox or VMware Workstation) with a fresh Windows 11 x64 evaluation
  image, or
- **A new local standard (non-administrator) Windows account** on a PC. An administrator creates it; never use
  someone else's existing account.

The environment must have no Python, Git, Codex CLI, or Claude Code, and no earlier BIO CE install or data.
Install Claude Code only for steps 9 to 13. Use only synthetic memories, never real personal data. Record the
Windows edition, build, display scale, and locale.

## Steps

| # | Step | Expected result |
|---|---|---|
| 1 | Download `BIO-CE-Setup-v0.3.0-rc1.exe` and run `Get-FileHash -Algorithm SHA256` on it | Matches the release notes and `SHA256SUMS.txt` |
| 2 | Run the installer from the download folder | SmartScreen may warn about an unknown publisher (unsigned file); no administrator prompt; the wizard completes |
| 3 | Start BIO CE from the Start menu | The first-run notice appears; **Quit** creates nothing under `%LOCALAPPDATA%\BIO-CE` |
| 4 | Start again and select **Continue** | The dashboard opens with 0 memories |
| 5 | Add, search, edit, and retract a synthetic memory with the GUI | Each change is shown; the edit becomes revision 2; the retracted memory disappears |
| 6 | **Settings**: create a backup, add one more memory, restore the backup | The added memory is gone after the restore |
| 7 | Close and reopen BIO CE | The data is kept; no first-run notice |
| 8 | Start BIO CE a second time while it is open | The open window comes to the front; no second window |
| 9 | Install Claude Code; on **Connections**, connect it and confirm | Shown as connected, Read only; Auto memory shown as Available |
| 10 | Switch Claude Code to **Auto memory**; install session hooks and confirm | Mode and hooks are shown |
| 11 | In Claude Code, state a lasting synthetic preference | It appears in BIO CE, with Claude Code as its source |
| 12 | Start a new Claude Code session and ask about it | The preference is recalled |
| 13 | Ask Claude Code to forget it | The retraction waits in the review queue until you approve it; the AI activity list shows each step |
| 14 | Pause, then disconnect Claude Code | Paused: tools refused. Disconnected: BIO CE's entry and hooks removed from Claude Code |
| 15 | Run the installer again (update over itself) | Data is kept |
| 16 | Uninstall from **Settings → Apps**, keep data | Program and Start menu entry removed; `%LOCALAPPDATA%\BIO-CE` kept |
| 17 | Reinstall, start, then uninstall again choosing to remove data | Memories are back after the reinstall; the data folder is removed at the end |

Record pass or fail, a screenshot, and any message for each step. A failing step blocks the installer
pre-release (Gate B in the [release gates](public-release-gates.md)).

## Separate checks, only if they are to be claimed

- **Windows 10 x64:** repeat the steps on Windows 10 22H2. Until then, Windows 10 is not supported.
- **Display scaling:** repeat steps 3 to 6 at 125% and 150% on a real display. Until then, only simulated-scale
  tests exist.
