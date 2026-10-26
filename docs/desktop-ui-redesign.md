<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# BIO CE v0.2 Desktop UI Redesign

Updated: 2026-10-22 · Branch: `feat/desktop-oneclick-v0.2` · Platform: Windows 11 x64, CPython 3.12.14, Tk 8.6

The Windows client was rebuilt as a dark, sidebar-based desktop app with four screens
(Dashboard, Memories, Connections, Settings). Storage, the SQLite schema, the MCP
protocol, backup/restore, and host registration logic are unchanged. No automatic
memory capture or AI-initiated write path was added. Nothing was committed or pushed.

## 1. Problems in the previous UI

| Area | Problem |
|---|---|
| Rendering | The process was not DPI-aware, so Windows bitmap-stretched the window at 125%/150% (blurry text). |
| Visual system | Default light `vista` ttk theme mixed with raw `tk.Listbox`/`tk.Text`; no color, spacing, or type scale. |
| Information | The list showed internal memory IDs and raw UTC timestamps with microseconds; the detail pane mixed body text and metadata in one plain text block. |
| Navigation | "Add Memory" was a top-level tab; selecting **Edit** jumped to a tab titled "Add a memory". Leaving the editor silently kept or lost state. |
| Feedback | Every success opened a modal box; failures used generic Yes/No boxes or raw exception text. |
| Responsiveness | Connecting a host ran the CLI and SDK verification on the UI thread (up to ~40 s of "Not responding"). |
| Empty states | None. Home showed a session-only "Recent actions" list that was empty after every restart. |
| Layout | Fixed `wraplength=900` labels clipped or wasted space when the window was resized. |
| Keyboard | No shortcuts; search required a mouse click; history window could not be closed with Esc. |

## 2. Framework decision

Stayed on the standard library (`tkinter` + `ttk` `clam` base) with custom widgets.
CustomTkinter (MIT) was considered and rejected for this release:

- It needs `--collect-data customtkinter` for its theme JSON and adds a dependency to the
  pinned lock files, runtime notices, and license inventory.
- It has no table widget (`ttk.Treeview` is still required) and its widgets don't expose
  better keyboard focus or screen-reader support than plain Tk.
- Everything the design needed (flat surfaces, focus rings, hover/pressed states, icons,
  scaling) was achievable with Tk primitives, so the bundle gained **no new third-party code**.

## 3. Design system (`src/bio_ce/ui/theme.py`)

- **Color**: graphite palette (`bg #17181b`, `sidebar #1d1f23`, `surface #212328`,
  `surface_alt #272a30`), one calm blue accent (`#3b6fd4`, text accent `#8aaef5`),
  semantic success/warning/danger/info pairs. A unit test checks every text color against
  every surface for WCAG AA (≥ 4.5:1).
- **Type**: Segoe UI Variable (Display/Text/Small) with Segoe UI fallback. Scale: display 20pt,
  title 15, section 12, reading 11, body 10, caption 9, mono 9 (Cascadia Mono → Consolas).
  On Korean/Japanese/Chinese Windows the text fonts switch to Malgun Gothic / Yu Gothic UI /
  Microsoft YaHei UI / JhengHei UI because Tk cannot use Windows font linking and otherwise
  renders Hangul with an uneven fallback font.
- **Spacing**: 4/8/12/16/24/32 logical px, converted with `Theme.px()` for the current DPI.
- **Icons**: Segoe Fluent Icons (Windows 11) or Segoe MDL2 Assets (Windows 10); no bundled images.
- **Window chrome**: system DPI awareness before the first `Tk()`, dark title bar and caption
  color via DWM, generated window icon.

Components (`src/bio_ce/ui/widgets.py`): `Button` (primary/secondary/subtle/danger/
danger_subtle/link), `IconButton`, `NavItem`, `RowButton`, `Card`, `Pill`, `Field`,
`SearchBox`, `TextArea`, `ScrollFrame`, `EmptyState`, `InfoBar`, `Tooltip`, `WrapLabel`.
All interactive widgets take Tab focus, show a 2px focus ring, and activate with Enter/Space.

## 4. New UI structure

```
src/bio_ce/ui/
  app.py          BIOCEDesktop shell: sidebar, page header, InfoBar, routing, shortcuts,
                  responsive sidebar, backup/restore actions, compatibility API
  theme.py        tokens, fonts, ttk styles, DPI awareness, title bar, icon
  widgets.py      component library
  dialogs.py      ConfirmDialog, HistoryDialog, TextViewerDialog, first-run notice
  tasks.py        TaskRunner: host CLI work on worker threads, results on the Tk thread
  format.py       pure formatting and user-facing error mapping
  pages/
    dashboard.py  status, memory count, AI host count, recent memories, host overview, search
    memories.py   search, list (100 per page + Load more), reader, details, retract, history
    editor.py     add/edit with inline validation, counters, unsaved-change guard, conflict reload
    connections.py host cards, connect/disconnect, diagnostics, install guidance, backups folder
    settings.py   database location, backup/restore, privacy & security, shortcuts, about/license
```

`src/bio_ce/desktop.py` keeps `AppDataPaths`, the settings functions, and
`DesktopMemoryService` byte-for-byte (AST-identical); only `run_desktop()` changed (DPI
awareness, theme, in-window first-run notice). `connections.py` gained one read-only method,
`MCPConnectionManager.diagnose()`; every existing method is AST-identical.

### Screens

- **Dashboard**: search box (Enter opens Memories with the query), status/count/host stat
  cards, six most recent memories (click or Enter opens one), host pills, privacy footnote.
  Empty database shows "No memories yet" with **Add your first memory**.
- **Memories**: resizable list/reader split. Reader uses an 11pt reading font, word wrap,
  and a ~760px measure. Details (IDs with copy buttons, source, timestamps, validity) are
  collapsible. Empty states: no memories at all, no search matches (with **Clear search**),
  nothing selected.
- **Editor**: Title, Memory, Source with live character counters, field-level error messages,
  `Save memory` / `Cancel`, Ctrl+S, Esc. Leaving with unsaved text asks
  **Discard / Keep editing**. A stale revision is never overwritten; the text is kept and an
  InfoBar offers **Reload latest**.
- **Connections**: read-only callout, one card per host with status pill
  (Connected / Not connected / Not installed / Needs attention), plain-language next step
  (e.g. confirm `codex --version` works), Connect/Disconnect, **Run diagnostics**
  (host command, settings readability, entry ownership, database validity, MCP server
  presence, live read-only tool check). Work runs in the background with a progress bar;
  closing the window waits for it.
- **Settings**: database path (copy, open folder), size and count, backup, restore,
  privacy and security points, settings-backup folder, keyboard shortcuts, version,
  Apache-2.0 license and third-party notices in an in-app viewer.

### Dialogs and feedback

- Confirmations name the action ("Retract memory", "Replace memories", "Connect",
  "Disconnect", "Discard"). Destructive ones use a red button with focus on **Cancel**, quote
  the affected memory or file, and list consequences. Esc cancels.
- Dialog buttons ignore activation for 0.4 s after appearing so a click or key press aimed at
  the window underneath can't confirm a destructive action (found during testing).
- Success, info, warning, and error messages appear in an inline InfoBar under the page
  header (success/info auto-dismiss; errors stay). Backup success offers **Show in folder**.
- First run shows the data notice inside the main window; **Quit**, Esc, or closing the
  window exits without creating settings or a database.

### Keyboard

Ctrl+1…4 pages · Ctrl+N new memory · Ctrl+F search · Ctrl+S save · Esc leave editor/close
dialog · Ctrl+E edit · Ctrl+H history · Delete retract (asks) · F5 refresh · Tab/Shift+Tab,
Enter/Space on every control · arrow keys in the list.

### Size and DPI behaviour

Default 1200×780 logical px, minimum 860×560, both clamped to the screen. Below 1000 px wide
the sidebar collapses to icons (tooltips keep the labels). Settings, Dashboard, Connections,
and the first-run notice scroll when the window is short. Verified at simulated 100%, 125%,
and 150% scaling.

## 5. Preserved behaviour

`SQLiteMemoryStore`, schema, `mcp_server.py`, `storage/backup.py`, retrieval, packaging scripts,
and all pre-existing tests except one were byte-identical before and after this work.
`tests/integration/test_desktop_ui.py` changed in two lines for the new navigation API (four
pages instead of five notebook tabs; confirmation via `app.confirm` instead of
`messagebox.askyesno`) and still drives add → search → read → revise → confirmed retract
against real SQLite. `bio_ce.__version__` was aligned with `pyproject.toml` (0.2.0.dev0).

## 6. Verification

| Check | Result |
|---|---|
| Full suite `pytest -q tests` | **57 passed, 25 subtests passed** (33 pre-existing + 24 new), repeated green runs |
| New UI integration tests (real Tk + real SQLite) | 14: shell/shortcuts, keyboard buttons, 125%/150% scaling + minimum size, empty states, inline validation + unsaved guard, Ctrl+S, retract cancel/confirm, stale-edit conflict + reload, history order + 25k-char reader, backup + restore (cancel/confirm/corrupt), host states, background connect/disconnect, failures + diagnostics, dialog guard/Esc |
| New unit tests | formatting/error mapping (5), `diagnose()` without config writes (3), CJK font selection and WCAG contrast (2) |
| Real host CLIs | Diagnostics and connect/disconnect ran against installed Codex CLI in an isolated profile; the real read-only MCP check passed |
| Source entry point `python -m bio_ce desktop` | Isolated `LOCALAPPDATA`: closing the first-run notice → exit 0, no settings, no database; acknowledged profile → opens and exits 0 |
| Frozen `BIO-CE.exe` (Python removed from PATH) | Same two scenarios passed |
| Packaged MCP EXE / installer script tests | Passed after rebuild |
| Privacy/license scan | No personal paths, emails, or secrets in changed sources; no profile or checkout path strings in the GUI bundle or PYZ; SPDX headers on all new files; UI imports are standard-library only |

Environment note: on this machine `tk.Tk()` occasionally failed to read Tcl's own
`init.tcl`/`tk.tcl` from the Codex-bundled base interpreter that the `.venv` uses. It happened
before any BIO CE code ran and could not be reproduced in 90 back-to-back create/close cycles.
The new UI tests retry only that specific Tcl library-load error.

## 7. Packaging impact

| Item | Before (2026-10-21) | After |
|---|---|---|
| GUI onedir | 62,974,218 B · 1,319 files | 60,734,218 B · 1,276 files |
| Installer | 56,119,296 B · `35d49b31…7c7d` | 54,280,192 B · `0f7411c3…e345` |
| New bundled modules | — | 13 `bio_ce.ui` modules (~167 KB source), no new packages |

The 43 fewer files are the `api-ms-win-*.dll`/`ucrtbase.dll` Universal CRT forwarders, which
PyInstaller copies only when it finds them on the build machine's search path. This depends on
the build environment, not on the UI change; Windows 10 and 11 ship the UCRT. The build is not
yet byte-reproducible across environments. The previous installer and checksum are kept in
`.test-tmp/ui-redesign-baseline/dist-release-before/`.

These figures describe the IExpress preview build. The RC1 installer (Inno Setup, CPython 3.12.10)
and its numbers are recorded in `docs/release-v0.2-test-report.md`.

## 8. Screenshots

Captured from the real app with synthetic data (window-only capture, ignored folder):
`.test-tmp/ui-redesign/screenshots/` — `before-*.png` (old UI), `after-100/` (all screens and
dialogs, including the Korean font check), `after-125/`, `after-150/`, and `live/`
(source and frozen EXE launches).

## 9. Remaining UX issues

1. **Screen readers**: custom Tk widgets aren't exposed to Windows UI Automation as buttons or
   links, so Narrator support is limited. Keyboard access is complete; assistive-technology
   support is not.
2. **Dark theme only**: no light theme and no "follow Windows" option yet. Tokens are
   centralized, so a light palette is a contained follow-up.
3. **Per-monitor DPI**: the app is system-DPI aware. Moving it to a monitor with a different
   scale makes Windows bitmap-scale it.
4. **Tk visual limits**: square corners, no Mica/acrylic, no motion.
5. **Search semantics**: lexical whole-word OR search capped at 50 results, and it hides
   memories outside their validity window while the list shows them. The UI doesn't explain
   this difference yet.
6. **Long paths** in Settings are truncated in the field (copy/open buttons provided). On
   Korean Windows, paths in Malgun Gothic show `\` as `₩`, matching Explorer.
7. **EXE icon**: resolved in RC1. `packaging/build_assets.py` generates the icon for Setup and both
   executables, and the title-bar icon is re-applied after the window is first shown.
8. **Clean-account verification**: frozen GUI CRUD through the installed shortcut was verified on the
   developer's own account in RC1; a clean Windows account or VM remains open.
9. **IME**: Hangul display and search were verified; interactive IME composition in the editor
   was not exercised by automation.
