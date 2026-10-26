# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Real Tk + real SQLite regression tests for the redesigned desktop UI."""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import patch

from bio_ce.connections import (
    ConnectionResult,
    DiagnosticCheck,
    HostStatus,
    MCPConnectionConflict,
    MCPConnectionError,
)
from bio_ce.core.models import SourceProvenance
from bio_ce.desktop import PERSONAL_SCOPE, AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.storage.sqlite_store import SQLiteMemoryStore
from bio_ce.ui.dialogs import ConfirmDialog
from bio_ce.ui.theme import Theme
from bio_ce.ui.widgets import Button
from tests.tk_support import new_tk_root


new_root = new_tk_root  # kept for tests that import the old name


class FakeConnections:
    """Stands in for MCPConnectionManager; never touches real host settings."""

    def __init__(self, **statuses: HostStatus) -> None:
        self.statuses = {
            "codex": statuses.get("codex", HostStatus("codex", True, False)),
            "claude": statuses.get("claude", HostStatus("claude", False, False)),
        }
        self.calls: list[tuple[str, str]] = []
        self.fail_with: BaseException | None = None
        self.release = threading.Event()
        self.release.set()

    def status(self, host: str) -> HostStatus:
        return self.statuses[host]

    def connect(self, host: str, *, approved: bool = False) -> ConnectionResult:
        assert approved is True
        self.release.wait(10)
        self.calls.append(("connect", host))
        if self.fail_with is not None:
            raise self.fail_with
        self.statuses[host] = HostStatus(host, True, True)
        return ConnectionResult(host, True, False, Path("backup.toml"))

    def disconnect(self, host: str, *, approved: bool = False) -> ConnectionResult:
        assert approved is True
        self.calls.append(("disconnect", host))
        self.statuses[host] = HostStatus(host, True, False)
        return ConnectionResult(host, False, False, Path("backup.toml"))

    def diagnose(self, host: str, *, run_server_check: bool = True):
        self.calls.append(("diagnose", host))
        return (
            DiagnosticCheck("Host command", "pass", "Found."),
            DiagnosticCheck("BIO CE entry", "info", "Not registered."),
            DiagnosticCheck("Read-only tools", "fail", "Server did not answer."),
        )


class RedesignedDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-ui-redesign-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeConnections()
        self.root: tk.Tk | None = None
        self.app: BIOCEDesktop | None = None

    def tearDown(self) -> None:
        if self.app is not None and self.root is not None:
            try:
                self.app.tasks.wait(10)
                self.app.editor.load(None)
                self.app.close()
            except tk.TclError:
                self.service.close()
        else:
            self.service.close()
            if self.root is not None:
                self.root.destroy()
        self.temp.cleanup()

    def _open(self, *, scale: float | None = None) -> BIOCEDesktop:
        self.root = new_root()
        if scale is not None:
            self.root.tk.call("tk", "scaling", scale * 96 / 72)
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.update()
        return self.app

    def _press(self, sequence: str, widget: tk.Misc | None = None) -> None:
        """Deliver a key event to ``widget`` (default: the focused widget or root).

        Tk drops generated key events while another application owns the
        keyboard focus, which is common on a developer desktop. In that case
        the widget's bindings are dispatched in bindtag order, as Tk would.
        """
        self.root.focus_force()
        self.root.update()
        focused = self.root.focus_get()
        target = widget or focused or self.root
        if focused is not None:
            target.focus_set()
            self.root.update()
            target.event_generate(sequence)
        else:
            for tag in target.bindtags():
                script = str(target.tk.call("bind", tag, sequence))
                if not script:
                    continue
                script = re.sub(r"%(.)", lambda m: str(target) if m.group(1) == "W" else "0", script)
                try:
                    target.tk.eval(script)
                except tk.TclError as exc:
                    if "break" in str(exc):
                        break
                    raise
        self.root.update()

    def _seed(self, title: str, content: str = "Synthetic test content.") -> None:
        self.service.add(title=title, content=content, source_ref="user-input")

    # Shell ------------------------------------------------------------------

    def test_four_page_shell_with_keyboard_navigation_and_shortcuts(self):
        app = self._open()
        self.assertEqual(list(app.pages), ["dashboard", "memories", "connections", "settings"])
        self.assertIs(app.current, app.dashboard)
        self.assertTrue(app.nav["dashboard"].selected)
        for index, key in enumerate(app.pages, start=1):
            self._press(f"<Control-Key-{index}>")
            self.assertIs(app.current, app.pages[key])
            self.assertTrue(app.nav[key].selected)
            self.assertEqual(app.header_title.cget("text"), app.pages[key].title)
        self._press("<Control-n>")
        self.assertIs(app.current, app.editor)
        self.assertTrue(app.nav["memories"].selected)
        self._press("<Escape>")
        self.assertIs(app.current, app.memories)
        for item in app.nav.values():
            self.assertEqual(str(item.cget("takefocus")), "1")

    def test_buttons_activate_from_keyboard_and_respect_disabled_state(self):
        app = self._open()
        pressed: list[str] = []
        button = Button(app.dashboard.actions, app.theme, "Probe", command=lambda: pressed.append("x"))
        button.pack()
        self.root.update()
        self._press("<Return>", button)
        self._press("<space>", button)
        self.assertEqual(pressed, ["x", "x"])
        button.set_enabled(False)
        self._press("<Return>", button)
        self.assertEqual(pressed, ["x", "x"])
        self.assertEqual(str(button.cget("takefocus")), "0")

    def test_dpi_scaling_and_minimum_size_keep_the_window_usable(self):
        for scale in (1.25, 1.5):
            with self.subTest(scale=scale):
                app = self._open(scale=scale)
                self.assertAlmostEqual(app.theme.scale, scale, places=2)
                self.assertEqual(app.theme.px(100), round(100 * scale))
                min_width, min_height = self.root.minsize()
                self.assertLessEqual(min_width, self.root.winfo_screenwidth())
                self.assertLessEqual(min_height, self.root.winfo_screenheight())
                self.root.geometry(f"{min_width}x{min_height}")
                self.root.update()
                self.assertTrue(app.compact)
                self.assertFalse(app.nav["memories"].label.winfo_ismapped())
                self.root.geometry(f"{app.theme.px(1200)}x{app.theme.px(760)}")
                self.root.update()
                self.assertFalse(app.compact)
                app.close()
                self.app = None
                self.root = None
                self.service = DesktopMemoryService(self.paths.user_database)

    # Memories ---------------------------------------------------------------

    def test_empty_states_guide_first_use_and_unmatched_searches(self):
        app = self._open()
        self.assertTrue(app.dashboard.recent_empty.winfo_manager())
        app.show_page("memories")
        self.root.update()
        self.assertTrue(app.memories.empty_all.winfo_ismapped())
        self._seed("Only memory", "Synthetic alphaword text.")
        app.memories.refresh()
        self.root.update()
        self.assertFalse(app.memories.empty_all.winfo_manager())
        self.assertTrue(app.memories.detail_empty.winfo_ismapped())
        app.open_search("zzznomatchword")
        self.root.update()
        self.assertTrue(app.memories.no_results.winfo_ismapped())
        self.assertIn("0 results", app.memories.result_label.cget("text"))
        app.memories.search.clear()
        self.root.update()
        self.assertFalse(app.memories.no_results.winfo_ismapped())
        self.assertEqual(len(app.memories.tree.get_children()), 1)

    def test_editor_validates_inline_and_guards_unsaved_changes(self):
        app = self._open()
        app.start_new_memory()
        self.root.update()
        self.assertIsNone(app.save_memory())
        self.root.update()
        self.assertEqual(self.service.count(), 0)
        self.assertIn("title", app.editor.title_error.cget("text").lower())
        self.assertTrue(app.editor.title_error.winfo_ismapped())
        app.title_value.set("Draft title")
        app.content_value.insert("1.0", "Unsaved synthetic text.")
        self.root.update()
        self.assertTrue(app.editor.dirty)
        with patch.object(app, "confirm", return_value=False) as confirm:
            self.assertFalse(app.show_page("dashboard"))
        confirm.assert_called_once()
        self.assertIs(app.current, app.editor)
        self.assertEqual(app.title_value.get(), "Draft title")
        with patch.object(app, "confirm", return_value=True):
            self.assertTrue(app.show_page("dashboard"))
        self.assertIs(app.current, app.dashboard)
        self.assertEqual(self.service.count(), 0)
        app.start_new_memory()
        self.assertEqual(app.title_value.get(), "")

    def test_ctrl_s_saves_and_selects_the_new_memory(self):
        app = self._open()
        app.start_new_memory()
        app.title_value.set("Keyboard saved memory")
        app.content_value.insert("1.0", "Saved with the keyboard shortcut.")
        self._press("<Control-s>")
        self.assertEqual(self.service.count(), 1)
        self.assertIs(app.current, app.memories)
        self.assertEqual(app.selected.title, "Keyboard saved memory")
        self.assertEqual(app.infobar.kind, "success")
        self.assertFalse(app.editor.dirty)

    def test_retract_asks_first_and_cancel_changes_nothing(self):
        self._seed("Keep or retract")
        app = self._open()
        record = self.service.list()[0]
        app.open_memory(record.memory_id)
        self.root.update()
        with patch.object(app, "confirm", return_value=False) as confirm:
            app.retract_selected()
        self.assertTrue(confirm.call_args.kwargs["danger"])
        self.assertEqual(confirm.call_args.kwargs["quote"], "Keep or retract")
        self.assertEqual(self.service.count(), 1)
        with patch.object(app, "confirm", return_value=True):
            app.retract_selected()
        self.assertEqual(self.service.count(), 0)
        self.assertEqual(app.infobar.kind, "success")
        self.assertTrue(app.memories.empty_all.winfo_manager())

    def test_stale_edit_is_rejected_and_the_users_text_is_kept(self):
        self._seed("Conflict target", "Original text.")
        app = self._open()
        record = self.service.list()[0]
        app.open_memory(record.memory_id)
        app.start_edit_memory()
        writer = SQLiteMemoryStore(self.paths.user_database)
        try:
            writer.revise(PERSONAL_SCOPE, record.memory_id, expected_revision_id=record.revision_id,
                          title="Changed elsewhere", content="Newer text.",
                          source=SourceProvenance("fixture", "fixture:concurrent"))
        finally:
            writer.close()
        app.content_value.delete("1.0", tk.END)
        app.content_value.insert("1.0", "My stale edit.")
        self.assertIsNone(app.save_memory())
        self.assertIs(app.current, app.editor)
        self.assertEqual(app.infobar.kind, "warning")
        self.assertEqual(app.editor.content.get(), "My stale edit.")
        self.assertEqual(self.service.read(record.memory_id).title, "Changed elsewhere")
        with patch.object(app, "confirm", return_value=True):
            app.editor.reload_latest()
        self.assertEqual(app.editor.content.get(), "Newer text.")
        self.assertEqual(app.editing.revision_number, 2)

    def test_history_lists_revisions_newest_first_and_long_text_is_readable(self):
        long_text = "Synthetic paragraph about longwordmarker. " * 600
        self._seed("History target", long_text)
        record = self.service.list()[0]
        self.service.revise(record, title="History target", content="Second revision text.", source_ref="user-input")
        app = self._open()
        app.open_search("longwordmarker")
        self.root.update()
        self.assertEqual(len(app.memories.tree.get_children()), 0)
        app.open_search("revision")
        self.root.update()
        self.assertEqual(len(app.memories.tree.get_children()), 1)
        app.memories.select(record.memory_id)
        dialog = app.show_history()
        self.root.update()
        text = dialog.view.text.get("1.0", tk.END)
        self.assertLess(text.index("Revision 2"), text.index("Revision 1"))
        self.assertIn("CURRENT", text)
        dialog.event_generate("<Escape>")
        self.root.update()
        self.assertFalse(dialog.winfo_exists())
        self._seed("Long body", long_text)
        app.memories.search.clear()
        latest = self.service.list()[0]
        app.open_memory(latest.memory_id)
        self.root.update()
        self.assertEqual(app.memories.reader.get(), long_text)

    def test_backup_and_confirmed_restore_through_settings(self):
        self._seed("Before backup")
        app = self._open()
        app.show_page("settings")
        backup = Path(self.temp.name) / "exports" / "snapshot.sqlite3"
        with patch.object(app, "ask_save_path", return_value=str(backup)):
            created = app.backup_database()
        self.assertEqual(created, backup.resolve())
        self.assertTrue(backup.is_file())
        self.assertEqual(app.infobar.kind, "success")
        self._seed("After backup")
        with patch.object(app, "ask_open_path", return_value=str(backup)), \
                patch.object(app, "confirm", return_value=False):
            self.assertFalse(app.restore_database())
        self.assertEqual(self.service.count(), 2)
        with patch.object(app, "ask_open_path", return_value=str(backup)), \
                patch.object(app, "confirm", return_value=True) as confirm:
            self.assertTrue(app.restore_database())
        self.assertTrue(confirm.call_args.kwargs["danger"])
        self.assertEqual(self.service.count(), 1)
        self.assertIn("1 active memory", app.settings.storage_stats.cget("text"))
        corrupt = Path(self.temp.name) / "corrupt.sqlite3"
        corrupt.write_bytes(b"not sqlite")
        with patch.object(app, "ask_open_path", return_value=str(corrupt)), \
                patch.object(app, "confirm", return_value=True):
            self.assertFalse(app.restore_database())
        self.assertEqual(app.infobar.kind, "error")
        self.assertIn("not changed", app.infobar.message)
        self.assertEqual(self.service.count(), 1)

    # Connections ------------------------------------------------------------

    def test_connection_states_explain_what_to_do(self):
        self.connections.statuses["claude"] = HostStatus("claude", True, False, True)
        app = self._open()
        app.show_page("connections")
        codex, claude = app.connections.cards["codex"], app.connections.cards["claude"]
        self.assertEqual(codex.primary.text, "Connect")
        self.assertTrue(codex.primary.enabled)
        self.assertIn("Needs attention", claude.pill.cget("text"))
        self.assertFalse(claude.primary.enabled)
        self.connections.statuses["claude"] = HostStatus("claude", False, False)
        app.refresh_connections()
        self.assertIn("claude --version", claude.message.cget("text"))
        self.assertFalse(claude.primary.enabled)
        self.assertTrue(claude.diagnose_button.enabled)

    def test_connect_requires_approval_runs_in_background_and_updates_state(self):
        app = self._open()
        app.show_page("connections")
        card = app.connections.cards["codex"]
        with patch.object(app, "confirm", return_value=False) as declined:
            app.connect_host("codex")
        self.assertEqual(self.connections.calls, [])
        disclosure = " ".join(declined.call_args.kwargs["points"])
        self.assertIn("may be sent to the AI model provider", disclosure)
        self.assertIn("OpenAI", disclosure)
        self.connections.release.clear()
        with patch.object(app, "confirm", return_value=True):
            app.connect_host("codex")
        self.root.update()
        self.assertTrue(card.busy)
        self.assertFalse(card.primary.enabled)
        app.close()
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(app.infobar.kind, "warning")
        self.connections.release.set()
        app.tasks.wait(10)
        self.assertFalse(card.busy)
        self.assertEqual(self.connections.calls, [("connect", "codex")])
        self.assertIn("Read only", card.pill.cget("text"))
        self.assertEqual(card.primary.text, "Disconnect")
        self.assertEqual(app.infobar.kind, "success")
        app.show_page("dashboard")
        self.assertEqual(app.dashboard.hosts_value.cget("text"), "1")
        app.show_page("connections")
        with patch.object(app, "confirm", return_value=True):
            app.disconnect_host("codex")
        app.tasks.wait(10)
        self.assertEqual(card.primary.text, "Connect")

    def test_connection_failures_and_diagnostics_are_reported(self):
        app = self._open()
        app.show_page("connections")
        self.connections.fail_with = MCPConnectionError("The host did not save the expected BIO CE MCP configuration.")
        with patch.object(app, "confirm", return_value=True):
            app.connect_host("codex")
        app.tasks.wait(10)
        self.assertEqual(app.infobar.kind, "error")
        self.assertIn("did not save", app.infobar.message)
        self.connections.fail_with = MCPConnectionConflict("The server name bio-ce is already used.")
        with patch.object(app, "confirm", return_value=True):
            app.connect_host("codex")
        app.tasks.wait(10)
        self.assertEqual(app.infobar.kind, "warning")
        self.assertIn("Nothing was changed", app.infobar.message)
        app.diagnose_host("codex")
        app.tasks.wait(10)
        card = app.connections.cards["codex"]
        self.assertEqual([check.name for check in card.checks], ["Host command", "BIO CE entry", "Read-only tools"])
        self.assertTrue(card.results.winfo_manager())
        self.assertEqual(app.infobar.kind, "warning")

    # Dialogs ----------------------------------------------------------------

    def test_confirm_dialog_names_the_action_and_escape_cancels(self):
        self.root = new_root()
        theme = Theme(self.root)
        dialog = ConfirmDialog(self.root, theme, title="Retract?", message="Synthetic.", confirm_text="Retract memory",
                               danger=True)
        labels = [child.text for child in dialog.buttons.winfo_children()]
        self.assertEqual(labels, ["Retract memory", "Cancel"])
        confirm_button = dialog.buttons.winfo_children()[0]
        self.root.after(50, confirm_button.invoke)  # too early: guarded against click-through
        self.root.after(600, lambda: self._press("<Escape>", dialog))
        self.assertFalse(dialog.ask())
        dialog = ConfirmDialog(self.root, theme, title="Connect?", message="Synthetic.", confirm_text="Connect")
        self.root.after(600, lambda: dialog.buttons.winfo_children()[0].invoke())
        self.assertTrue(dialog.ask())


if __name__ == "__main__":
    unittest.main()
