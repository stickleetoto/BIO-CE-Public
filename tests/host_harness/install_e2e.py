# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Per-user installer end-to-end run on the current Windows account (synthetic data only).

Steps: v0.2 install + v0.2-format data -> v0.3 update over it -> launch checks -> user add,
search, edit, retract, backup and restore on the installed data -> Claude Code connection through
the installed binaries (isolated host profile, local mock model) -> Auto memory, hooks, recall in
a new session, review queue (reject, approved retraction), activity log, hook removal, pause,
revoke -> uninstall keeping data -> reinstall -> full cleanup. Every installer run is silent.
GUI windows are only captured (PrintWindow) and closed with WM_CLOSE; no keyboard or mouse input
is sent.

Safety: refuses to start if BIO CE is already installed or a BIO CE data folder exists for this
user, never touches the user's real Codex/Claude settings, and removes only what it created.
It must run outside any MSIX app container (start it through explorer.exe).

Usage: python install_e2e.py OUT_DIR SETUP_V02 SETUP_V03 BUILD_MANIFEST
       python install_e2e.py OUT_DIR --cleanup-only   (remove what an interrupted run left behind)
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import time
import traceback
import winreg
import zlib

HERE = Path(__file__).resolve().parent
PYTHON = sys.executable  # captured before claude_flow points sys.executable at the installed app
LOCAL = Path(os.environ["LOCALAPPDATA"])
DATA_ROOT = LOCAL / "BIO-CE"
DATABASE = DATA_ROOT / "data" / "memories.sqlite3"
APP_DIR = LOCAL / "Programs" / "BIO-CE"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{8A3FE668-FA42-4564-9D91-AC3121E700EA}_is1"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "BIO CE" / "BIO CE.lnk"
MARKER = ".bio-ce-e2e-synthetic"
TITLE = "BIO Community Edition"
user32 = ctypes.windll.user32


class Run:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.results: list[dict] = []
        out.mkdir(parents=True, exist_ok=True)

    def step(self, name: str, ok: bool, **detail) -> bool:
        entry = {"step": name, "ok": bool(ok), **detail}
        self.results.append(entry)
        with (self.out / "results.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return bool(ok)


# Machine state ------------------------------------------------------------------


def uninstall_entry() -> dict | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            return {name: winreg.QueryValueEx(key, name)[0]
                    for name in ("DisplayVersion", "InstallLocation", "UninstallString")}
    except OSError:
        return None


def machine_state() -> dict:
    return {"app_exe": (APP_DIR / "BIO-CE.exe").is_file(), "mcp_exe": (APP_DIR / "MCP" / "BIO-CE-MCP.exe").is_file(),
            "shortcut": SHORTCUT.is_file(), "uninstall_entry": uninstall_entry(), "data_root": DATA_ROOT.is_dir(),
            "database": DATABASE.is_file()}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def integrity() -> tuple[str, int]:
    connection = sqlite3.connect(f"file:{DATABASE.as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    return result, version


def install(run: Run, setup: Path, tag: str) -> bool:
    log = run.out / f"setup-{tag}.log"
    completed = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log}"],
                               timeout=600)
    return completed.returncode == 0


def uninstall(run: Run, tag: str) -> bool:
    # Inno Setup numbers the uninstaller (unins000, unins001, ...) when a reinstall finds the previous
    # one still being removed, so use the path Windows itself uses.
    entry = uninstall_entry()
    uninstaller = Path(entry["UninstallString"].strip('"')) if entry else None
    if uninstaller is None or not uninstaller.is_file():
        return False
    subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    f"/LOG={run.out / f'uninstall-{tag}.log'}"], timeout=600)
    deadline = time.time() + 180
    while time.time() < deadline and (uninstall_entry() is not None or (APP_DIR / "BIO-CE.exe").exists()):
        time.sleep(1)
    return uninstall_entry() is None and not (APP_DIR / "BIO-CE.exe").exists()


def installed_matches_manifest(manifest: Path) -> tuple[int, list[str]]:
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    mismatched = [entry["path"] for entry in data["files"]
                  if not (APP_DIR / entry["path"]).is_file() or sha256(APP_DIR / entry["path"]) != entry["sha256"]]
    return len(data["files"]), mismatched


# GUI capture (no input) ---------------------------------------------------------


def find_window(existing: set[int]) -> int | None:
    found: list[int] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buffer, 256)
        if user32.IsWindowVisible(hwnd) and buffer.value == TITLE and hwnd not in existing:
            found.append(hwnd)
        return True

    user32.EnumWindows(proc(callback), 0)
    return found[0] if found else None


def all_windows() -> set[int]:
    seen: set[int] = set()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(proc(lambda hwnd, _: seen.add(hwnd) or True), 0)
    return seen


def capture(hwnd: int, path: Path) -> None:
    gdi32 = ctypes.windll.gdi32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    gdi32.SelectObject(memory, bitmap)
    user32.PrintWindow(hwnd, memory, 2)
    header = ctypes.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0),
                                         44)
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory, bitmap, 0, height, buffer, header, 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(None, screen)
    raw, stride, rows = buffer.raw, width * 4, bytearray()
    for y in range(height):
        line = raw[y * stride:(y + 1) * stride]
        rgb = bytearray(width * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
        rows += b"\x00" + rgb
    rows = bytes(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def launch_and_capture(run: Run, env: dict, name: str, wait: float = 4.0) -> dict:
    before = all_windows()
    process = subprocess.Popen([str(APP_DIR / "BIO-CE.exe")], env=env, cwd=str(APP_DIR))
    hwnd, deadline = None, time.time() + 60
    while hwnd is None and time.time() < deadline and process.poll() is None:
        hwnd = find_window(before)
        time.sleep(0.25)
    if hwnd is None:
        process.kill()
        return {"window": False, "exit": process.poll()}
    time.sleep(wait)
    capture(hwnd, run.out / f"{name}.png")
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    try:
        code = process.wait(30)
    except subprocess.TimeoutExpired:
        process.kill()
        code = "killed"
    return {"window": True, "exit": code, "screenshot": f"{name}.png"}


# Claude Code through the installed binaries ----------------------------------------


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def claude_turn(root: Path, profile: Path, script: dict, tag: str, prompt: str, expect: str | None = None) -> dict:
    script_file, log = root / f"script-{tag}.json", root / f"model-{tag}.jsonl"
    script_file.write_text(json.dumps(script), encoding="utf-8")
    port = free_port()
    mock = subprocess.Popen([PYTHON, "-I", str(HERE / "mock_model_server.py"), str(port), str(log),
                             str(script_file)], stdout=subprocess.PIPE, text=True)
    mock.stdout.readline()
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(profile / ".claude"), ANTHROPIC_BASE_URL=f"http://127.0.0.1:{port}",
               ANTHROPIC_API_KEY="mock-not-a-real-key", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
               CLAUDE_CODE_DISABLE_AUTO_MEMORY="1", MCP_TIMEOUT="30000")
    work = root / "claude-work"
    work.mkdir(exist_ok=True)
    try:
        completed = subprocess.run([shutil.which("claude"), "-p", prompt, "--output-format", "stream-json",
                                    "--verbose", "--no-session-persistence"], cwd=work, env=env,
                                   stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
    finally:
        mock.terminate()
        mock.wait(10)
    (root / f"claude-{tag}.jsonl").write_bytes(completed.stdout)
    text = completed.stdout.decode("utf-8", "replace")
    requests = log.read_text(encoding="utf-8") if log.exists() else ""
    tool_results = [json.loads(line) for line in text.splitlines() if '"tool_result"' in line]
    errors = ['"is_error":true' in json.dumps(r).replace(" ", "") for r in tool_results]
    result = {"exit": completed.returncode, "hook_context_reached_model": "BIO CE (the user's local long-term memory)"
              in requests, "tool_result_errors": errors, "transcript_mentions_bio_tool": "bio_memory_" in text}
    if expect is not None:
        result["expected_in_tool_result"] = expect in json.dumps(tool_results, ensure_ascii=False)
        result["expected_in_model_requests"] = expect in requests
    return result


def user_memory_flow(run: Run, root: Path) -> None:
    """What the Memories page and Settings > Backup do, through the app's service on the installed data."""
    from bio_ce.desktop import DesktopMemoryService

    service = DesktopMemoryService(DATABASE)
    try:
        start = service.count()
        added = service.add(title="Afternoon drink (synthetic)", content="Tea, not coffee, after 3 pm.",
                            source_ref="user-input")
        found = [hit.memory_id for hit in service.search("afternoon tea")]
        revised = service.revise(added, title="Afternoon drink (synthetic)", content="Green tea after 3 pm.",
                                 source_ref="user-input")
        run.step("user-add-search-edit", added.memory_id in found and service.count() == start + 1
                 and len(service.history(added.memory_id)) == 2
                 and service.read(added.memory_id).content == "Green tea after 3 pm.")
        backup = root / "exports" / "e2e-backup.sqlite3"
        service.create_backup(backup)
        service.retract(revised)
        run.step("user-retract", service.count() == start
                 and added.memory_id not in [hit.memory_id for hit in service.search("afternoon tea")])
        service.restore_backup(backup)
        run.step("backup-restore", service.count() == start + 1
                 and service.read(added.memory_id).content == "Green tea after 3 pm.", integrity=integrity())
    finally:
        service.close()


def claude_flow(run: Run, root: Path) -> None:
    sys.frozen = True  # behave exactly like the installed desktop app when registering hosts
    sys.executable = str(APP_DIR / "BIO-CE.exe")
    from bio_ce.connections import MCPConnectionManager
    from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, MODE_PAUSED, control_database_for
    from bio_ce.core.models import MemoryScope
    from bio_ce.desktop import DesktopMemoryService
    from bio_ce.storage.sqlite_store import SQLiteMemoryStore

    scope = MemoryScope("bio-ce-personal", "default")
    profile = root / "claude-profile"
    (profile / ".claude").mkdir(parents=True, exist_ok=True)
    (profile / "codex").mkdir(exist_ok=True)
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(profile / ".claude"), CODEX_HOME=str(profile / "codex"),
               USERPROFILE=str(profile), HOME=str(profile))
    manager = MCPConnectionManager(DATABASE, DATA_ROOT, env=env)
    try:
        result = manager.connect("claude", approved=True)
        status = manager.status("claude")
        config = json.loads((profile / ".claude" / ".claude.json").read_text(encoding="utf-8"))
        entry = config["mcpServers"]["bio-ce"]
        run.step("claude-connect-installed-mcp", result.connected and status.connected and status.mode == "read_only"
                 and Path(entry["command"]) == APP_DIR / "MCP" / "BIO-CE-MCP.exe",
                 command=entry["command"], mode=status.mode, sdk_verified=True)
        manager.set_mode("claude", MODE_AUTO_MEMORY)
        settings_path = profile / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        run.step("claude-auto-memory-on", manager.status("claude").mode == MODE_AUTO_MEMORY,
                 allowed=[rule for rule in settings.get("permissions", {}).get("allow", []) if "bio" in rule])
        manager.install_hooks("claude", approved=True)
        run.step("claude-hooks-installed", manager.status("claude").hooks_installed)

        before = SQLiteMemoryStore(DATABASE, read_only=True)
        count_before = before.count_current(scope)
        before.close()
        created = claude_turn(root, profile, {"tool": "bio_memory_create", "arguments": {
            "title": "Prefers concise commit messages", "content": "The user prefers short, imperative commit messages.",
            "category": "preference", "confidence": "high", "evidence": "user_stated",
            "reason": "Synthetic installer E2E statement."}}, "create",
            "Synthetic test: I prefer short imperative commit messages.")
        store = SQLiteMemoryStore(DATABASE, read_only=True)
        hits = store.search(scope, "concise commit messages", limit=5)
        created_memory = store.read(scope, hits[0].memory_id) if hits else None
        count_after = store.count_current(scope)
        store.close()
        run.step("claude-create-through-installed-exe", created_memory is not None and count_after == count_before + 1
                 and created_memory.source.metadata.get("host") == "claude" and not any(created["tool_result_errors"]),
                 **created, provenance=dict(created_memory.source.metadata) if created_memory else None)

        # Each `claude -p` run is a new session (--no-session-persistence).
        recalled = claude_turn(root, profile, {"tool": "bio_memory_search", "arguments": {"query": "commit messages"}},
                               "recall", "Synthetic test: how should my commit messages look?",
                               expect="Prefers concise commit messages")
        run.step("new-session-recall", recalled["expected_in_tool_result"] and recalled["hook_context_reached_model"]
                 and recalled["expected_in_model_requests"] and not any(recalled["tool_result_errors"]), **recalled)

        queued = claude_turn(root, profile, {"tool": "bio_memory_update", "arguments": {
            "memory_id": created_memory.memory_id, "expected_revision_id": created_memory.revision_id,
            "title": "Prefers detailed commit messages", "content": "The user may prefer detailed commit messages.",
            "change_type": "conflict", "confidence": "medium", "evidence": "user_stated",
            "reason": "Unclear which statement is current."}}, "conflict",
            "Synthetic test: maybe detailed commit messages are better, not sure.")
        with ControlStore(control_database_for(DATABASE)) as control:
            reviews = control.reviews()
            activity = control.recent_activity(limit=20)
        store = SQLiteMemoryStore(DATABASE, read_only=True)
        unchanged = store.read(scope, created_memory.memory_id).revision_id == created_memory.revision_id
        store.close()
        run.step("review-queue-and-activity", len(reviews) == 1 and reviews[0].kind == "update" and unchanged
                 and {entry.outcome for entry in activity} >= {"created", "queued"}, **queued,
                 activity=[(entry.action, entry.outcome, entry.host) for entry in activity])

        service = DesktopMemoryService(DATABASE)
        try:
            with ControlStore(control_database_for(DATABASE)) as control:
                service.reject_review(control, reviews[0].review_id)
                rejected = not control.reviews()
            retract = claude_turn(root, profile, {"tool": "bio_memory_retract", "arguments": {
                "memory_id": created_memory.memory_id, "expected_revision_id": created_memory.revision_id,
                "reason": "Synthetic: the user asked to forget this."}}, "retract",
                "Synthetic test: forget my commit message preference.")
            still_there = service.read(created_memory.memory_id).revision_id == created_memory.revision_id
            with ControlStore(control_database_for(DATABASE)) as control:
                pending = control.reviews()
                if len(pending) == 1 and pending[0].kind == "retract":
                    service.approve_review(control, pending[0].review_id)
                outcomes = [(entry.action, entry.outcome) for entry in control.recent_activity(limit=5)]
            gone = created_memory.memory_id not in [hit.memory_id for hit in service.search("concise commit messages")]
        finally:
            service.close()
        run.step("review-reject-and-approved-retraction", rejected and still_there and gone
                 and not any(retract["tool_result_errors"]), **retract, activity=outcomes)

        manager.remove_hooks("claude", approved=True)
        unhooked = claude_turn(root, profile, {"tool": "bio_memory_search", "arguments": {"query": "afternoon"}},
                               "unhooked", "Synthetic test: what do I drink in the afternoon?")
        hooks_after = json.loads(settings_path.read_text(encoding="utf-8")).get("hooks", {})
        run.step("hooks-removed", not manager.status("claude").hooks_installed
                 and "BIO-CE-MCP" not in json.dumps(hooks_after) and not unhooked["hook_context_reached_model"]
                 and not any(unhooked["tool_result_errors"]), **unhooked)
        manager.install_hooks("claude", approved=True)

        manager.set_mode("claude", MODE_PAUSED)
        paused = claude_turn(root, profile, {"tool": "bio_memory_search", "arguments": {"query": "commit messages"}},
                             "paused", "Synthetic test: what commit style do I like?")
        run.step("pause-refuses-tool-calls", any(paused["tool_result_errors"]) and not paused["hook_context_reached_model"],
                 **paused)

        grant_id = manager.status("claude").connection_id
        old_token = entry["env"]["BIO_CE_CONNECTION_TOKEN"]
        disconnect = manager.disconnect("claude", approved=True)
        after = json.loads((profile / ".claude" / ".claude.json").read_text(encoding="utf-8"))
        settings_after = json.loads(settings_path.read_text(encoding="utf-8"))
        probe = subprocess.run([str(APP_DIR / "MCP" / "BIO-CE-MCP.exe"), "mcp-stdio", "--db", str(DATABASE),
                                "--connection", grant_id], env=dict(os.environ, BIO_CE_CONNECTION_TOKEN=old_token),
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        run.step("revoke-on-disconnect", not disconnect.connected and "bio-ce" not in after.get("mcpServers", {})
                 and "BIO-CE-MCP" not in json.dumps(settings_after.get("hooks", {})) and probe.returncode == 3,
                 revoked_server_exit=probe.returncode)
    finally:
        manager.close()


# Main ------------------------------------------------------------------------------


def cleanup(run: Run) -> bool:
    cleaned = uninstall(run, "cleanup") if uninstall_entry() is not None else True
    if (DATA_ROOT / MARKER).is_file():
        shutil.rmtree(DATA_ROOT, ignore_errors=True)
    final = machine_state()
    return run.step("cleanup-restores-machine", cleaned and not any(final.values()), state=final)


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--cleanup-only"]:
        run = Run(Path(argv[0]).resolve())
        ok = cleanup(run)
        (run.out / "done").write_text("cleanup", encoding="utf-8")
        return 0 if ok else 1
    out, setup02, setup03, manifest = (Path(arg).resolve() for arg in argv[:4])
    run = Run(out)
    start = machine_state()
    if any(value for value in start.values()):
        run.step("preflight-no-existing-install-or-data", False, state=start)
        (out / "done").write_text("aborted", encoding="utf-8")
        return 2
    run.step("preflight-no-existing-install-or-data", True, state=start,
             package_full_name_error=ctypes.windll.kernel32.GetCurrentPackageFullName(
                 ctypes.byref(ctypes.c_uint32(0)), None))
    profiles = out / "host-profiles"
    (profiles / ".claude").mkdir(parents=True, exist_ok=True)
    (profiles / "codex").mkdir(exist_ok=True)
    gui_env = dict(os.environ, CLAUDE_CONFIG_DIR=str(profiles / ".claude"), CODEX_HOME=str(profiles / "codex"))
    try:
        # v0.2 install with v0.2-format user data (memory schema v1, settings v1, no control database)
        ok = install(run, setup02, "v02")
        run.step("install-v0.2.0-rc1", ok and machine_state()["app_exe"], entry=uninstall_entry())
        sys.path.insert(0, str(HERE.parents[1] / "src"))
        from bio_ce.desktop import AppDataPaths, DesktopMemoryService, save_privacy_acknowledgement

        paths = AppDataPaths.under(DATA_ROOT)
        save_privacy_acknowledgement(paths.settings_file)
        (DATA_ROOT / MARKER).write_text("created by tests/host_harness/install_e2e.py", encoding="utf-8")
        service = DesktopMemoryService(paths.user_database)
        seeded = service.add(title="v0.2 era note (synthetic)", content="Created in the v0.2 data format: 한글 포함.",
                             source_ref="user-input")
        revised = service.revise(seeded, title="v0.2 era note (synthetic)",
                                 content="Revised in the v0.2 data format: 한글 포함.", source_ref="user-input")
        service.close()
        run.step("seed-v0.2-data", (DATA_ROOT / "data" / "memories.sqlite3").is_file()
                 and not (DATA_ROOT / "data" / "control.sqlite3").exists(), revision=revised.revision_number)
        data_hash = sha256(DATABASE)

        # update to v0.3 over v0.2
        ok = install(run, setup03, "v03-update")
        total, mismatched = installed_matches_manifest(manifest)
        run.step("update-to-v0.3.0-rc1", ok and (uninstall_entry() or {}).get("DisplayVersion") == "0.3.0-rc1"
                 and not mismatched, files=total, mismatched=mismatched[:10], entry=uninstall_entry())
        run.step("v0.2-data-untouched-by-update", sha256(DATABASE) == data_hash, integrity=integrity())

        # first launch on v0.2 data (no consent screen), then a first-run launch in a fresh profile
        launched = launch_and_capture(run, gui_env, "gui-after-update")
        run.step("gui-opens-v0.2-data", launched["window"] and launched["exit"] == 0, **launched,
                 integrity=integrity())
        fresh = out / "fresh-profile"
        fresh.mkdir(exist_ok=True)
        consent = launch_and_capture(run, dict(gui_env, LOCALAPPDATA=str(fresh)), "gui-first-run-consent")
        run.step("first-run-consent-closed-creates-nothing", consent["window"] and consent["exit"] == 0
                 and not any(fresh.iterdir()), **consent)

        user_memory_flow(run, out)

        # Claude Code through the installed binaries
        claude_flow(run, out)
        launched = launch_and_capture(run, gui_env, "gui-after-claude")
        run.step("gui-after-ai-activity", launched["window"] and launched["exit"] == 0, **launched)

        # uninstall keeps data, reinstall restores the app on the same data
        data_hash = sha256(DATABASE)
        removed = uninstall(run, "keep-data")
        run.step("uninstall-keeps-data", removed and not SHORTCUT.exists() and sha256(DATABASE) == data_hash
                 and (DATA_ROOT / "settings.json").is_file(), state=machine_state())
        ok = install(run, setup03, "v03-reinstall")
        total, mismatched = installed_matches_manifest(manifest)
        run.step("reinstall-v0.3.0-rc1", ok and not mismatched and sha256(DATABASE) == data_hash, files=total)
        launched = launch_and_capture(run, gui_env, "gui-after-reinstall")
        run.step("gui-after-reinstall", launched["window"] and launched["exit"] == 0, **launched)
    except Exception:
        run.step("unexpected-error", False, traceback=traceback.format_exc())
    finally:
        cleanup(run)
        (out / "done").write_text("finished", encoding="utf-8")
    return 0 if all(entry["ok"] for entry in run.results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
