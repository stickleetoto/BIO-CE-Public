<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE Desktop Installation

## Status

v0.3.0-rc1 is a **release candidate** for Windows 11 x64. It has been built and exercised only on
Windows 11 x64 (build 26200). Windows 10 has **not** been tested, and installation on a clean Windows
account or VM with no Python, Git, or developer tools is **not yet verified**. See the
[v0.3.0-rc1 report](release-v0.3-rc1-report.md) for exactly what was and was not verified.

The installer and programs are **not code-signed**. When the installer is downloaded from the internet,
Windows SmartScreen may warn that the publisher is unknown. BIO CE never asks you to turn off SmartScreen,
Microsoft Defender, or any other Windows security feature. If you are not sure the file is genuine, do not
run it; compare its SHA-256 with the `SHA256SUMS.txt` published with the release first:

```powershell
Get-FileHash -Algorithm SHA256 .\BIO-CE-Setup-v0.3.0-rc1.exe
```

## Install

1. Double-click `BIO-CE-Setup-v0.3.0-rc1.exe`. No administrator rights are requested, and no Python, Git,
   or other runtime is needed. The wizard is shown in Korean on Korean Windows and in English otherwise.
2. Keep the default folder or choose another one. The default is:

   ```text
   %LOCALAPPDATA%\Programs\BIO-CE
   ```

   Folders with spaces or Korean characters work. Setup refuses a folder inside the BIO CE data folder
   (`%LOCALAPPDATA%\BIO-CE`) so that program files and personal data never mix.
3. Optionally tick **Create a desktop shortcut**, then select **Install**.
4. Leave **Start BIO CE** ticked on the last page, or start it later from **Start → BIO CE**.

Setup installs only program files: the desktop app `BIO-CE.exe`, the separate MCP server
`MCP\BIO-CE-MCP.exe`, license files, and these documents. It registers a per-user uninstall entry
(**Settings → Apps → Installed apps → BIO Community Edition**). It does not create the memory database.

## First start

BIO CE first explains how your data is handled. Select **Continue** to create your data folder and
database, or **Quit** to close BIO CE without creating any file. BIO CE never records conversations. Memories
are stored when you select **Save memory**, or when an AI host that you switched to **Auto memory** saves a
lasting fact under BIO CE's rules.

- **Dashboard**: status, memory count, recent memories, connected AI hosts, quick search.
- **Memories**: search, read, edit (each save creates a new revision), history, and retract.
- **Connections**: connect or disconnect Codex CLI and Claude Code, choose each host's access (Read only,
  Auto memory, Paused), install session hooks, review queued AI changes, and see recent AI activity.
- **Settings**: database location, backup and restore, privacy notes, keyboard shortcuts, licenses.

## Where your data is stored

| Item | Location |
|---|---|
| Personal memory database | `%LOCALAPPDATA%\BIO-CE\data\memories.sqlite3` |
| BIO CE settings | `%LOCALAPPDATA%\BIO-CE\settings.json` |
| AI host configuration backups | `%LOCALAPPDATA%\BIO-CE\connections\backups` |
| Connection grants, AI activity log, review queue | `%LOCALAPPDATA%\BIO-CE\data\control.sqlite3` |
| Backups you create | Wherever you choose in **Settings → Create backup…** |

The database is not encrypted. Retraction hides a memory from BIO CE and from AI hosts but keeps earlier
revisions inside the SQLite file; it is not secure deletion.

## Update

Run a newer BIO CE installer. Setup finds the existing installation, offers to close BIO CE (and any
`BIO-CE-MCP.exe` started by an AI host) if it is running, replaces the program files, and leaves everything
under `%LOCALAPPDATA%\BIO-CE` untouched. Installing into the same folder keeps existing Codex/Claude
connections valid because the MCP server path does not change.

## Uninstall

1. In BIO CE, open **Connections** and disconnect Codex CLI and Claude Code. Uninstall does not edit host
   settings.
2. Open **Settings → Apps → Installed apps → BIO Community Edition → Uninstall**.
3. Confirm removal. Setup then asks separately whether to delete your local BIO CE data. The default
   answer is **No**, which keeps memories, settings, and configuration backups so that a later reinstall
   picks them up again. A silent uninstall (`unins000.exe /VERYSILENT`) always keeps data.

## Connect Codex CLI or Claude Code

Install the host first and confirm `codex --version` or `claude --version` works in a new terminal. A host
that is not installed is shown as **Not installed** and can simply be skipped; BIO CE works without one.

On **Connections**, select **Connect** for a host and read the confirmation. When you confirm, BIO CE:

1. backs up the host's MCP settings to `%LOCALAPPDATA%\BIO-CE\connections\backups`;
2. creates a connection with its own token and runs the host's own command (`codex mcp add` or
   `claude mcp add --scope user`) to add one stdio entry named `bio-ce` that starts `MCP\BIO-CE-MCP.exe` for
   your personal database;
3. starts that server once with the official MCP SDK and runs a read-only search/read check. If the check
   fails, the entry is removed again.

A new connection is **Read only**: the host can search and read your active memories. You can switch it to
**Auto memory** (it may also save and update lasting memories; secrets and document content are refused, and
uncertain changes and all retractions wait for your review) or **Paused**, and optionally install session
hooks. In Codex CLI, Auto memory is currently limited; see [Codex support](codex-support.md). Memories a host
reads or writes become part of your conversation and **may be sent to the AI model provider that host uses**
(for example OpenAI for Codex CLI or Anthropic for Claude Code) under that provider's terms. BIO CE itself
never calls an AI model. **Disconnect** revokes the connection and removes only BIO CE's entries, after another
backup.

## Developer build

Requirements: Windows 11 x64, the official python.org CPython 3.12 x64 installer build, and
[Inno Setup](https://jrsoftware.org/isinfo.php) 6.7 (per-user or per-machine install). v0.3.0-rc1 was built
with CPython 3.12.10 and Inno Setup 6.7.3.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-mcp.lock.txt -r requirements-test.lock.txt -r requirements-build.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q tests
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\packaging\build_windows.ps1
```

`build_windows.ps1` runs PyInstaller with a minimal `PATH`, refuses to package Universal CRT DLLs picked up
from the build machine, generates the icon and version resources, collects third-party notices, compiles
`packaging\BIO-CE.iss`, and writes the installer, `SHA256SUMS.txt`, and a per-file `build-manifest.json`.
Use `-Python`, `-BuildRoot`, and `-DistRoot` to build from a separate environment or folder.
