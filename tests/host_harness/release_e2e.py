# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Installer end-to-end run for a release candidate on the current Windows account (synthetic data only).

Steps: install the previous release -> create data with it (memories, revisions, a retraction, review
items, a grant, settings, a user backup) -> upgrade to the candidate -> prove every byte of user data
survived -> launch checks -> installed MCP server and hook (Korean text, duplicate proposals) ->
Claude Code and Codex registration plus hook install/remove through the real CLIs in isolated profiles
-> revoke -> backup/restore and recovery from the pre-upgrade backup -> uninstall keeping data ->
reinstall into a folder with Korean letters, spaces, and '#' -> uninstall -> full cleanup.

No keyboard or mouse input is sent: GUI windows are captured (PrintWindow) and closed with WM_CLOSE.
Every installer run is silent. It refuses to start if BIO CE is installed or a BIO CE data folder exists
for this user, never touches the user's real Codex/Claude settings, and removes only what it created.
It must run outside any MSIX app container.

Usage: python release_e2e.py OUT_DIR PREVIOUS_SETUP CANDIDATE_SETUP CANDIDATE_MANIFEST
       python release_e2e.py OUT_DIR --clean-install-only CANDIDATE_SETUP CANDIDATE_MANIFEST
         (first install of the candidate on a machine without BIO CE: install, first-run notice, first
          launch, installed MCP server and hook, uninstall, cleanup)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))
import install_e2e as base  # noqa: E402  (shared install/uninstall/capture helpers)
from install_e2e import APP_DIR, DATA_ROOT, DATABASE, MARKER, Run, sha256, uninstall_entry  # noqa: E402

SPECIAL_DIR = base.LOCAL / "Programs" / "BIO CE 테스트 #1 (재설치)"
CONTROL = DATA_ROOT / "data" / "control.sqlite3"
PROMPT = "배포 일정이 언제였지?"


def dump(path: Path, tables: tuple[str, ...]) -> list:
    """Every row of ``tables``; compares content without depending on SQLite file-header bytes."""
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return [(table, connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()) for table in tables]
    finally:
        connection.close()


def snapshot(backup: Path) -> dict:
    return {
        "memories": dump(DATABASE, ("memories", "revisions")),
        "control": dump(CONTROL, ("connections", "review_queue", "audit_log")),
        "settings": (DATA_ROOT / "settings.json").read_bytes(),
        "backup_sha256": sha256(backup),
    }


def installed(directory: Path = APP_DIR) -> tuple[Path, Path]:
    return directory / "BIO-CE.exe", directory / "MCP" / "BIO-CE-MCP.exe"


def run_hook(mcp_exe: Path, connection_id: str, token: str, prompt: str = PROMPT) -> dict:
    completed = subprocess.run([str(mcp_exe), "hook", "user-prompt", "--host", "claude", "--db", str(DATABASE),
                                "--connection", connection_id, f"--token={token}"],
                               input=json.dumps({"prompt": prompt}, ensure_ascii=False).encode("utf-8"),
                               capture_output=True, timeout=60)
    text = completed.stdout.decode("utf-8")
    context = json.loads(text)["hookSpecificOutput"]["additionalContext"] if text.strip() else ""
    return {"exit": completed.returncode, "context": context}


async def mcp_calls(mcp_exe: Path, connection_id: str, token: str) -> dict:
    from mcp import Client, StdioServerParameters, stdio_client
    from bio_ce.mcp_server import TOKEN_ENVIRONMENT_VARIABLE

    parameters = StdioServerParameters(command=str(mcp_exe), args=["mcp-stdio", "--db", str(DATABASE),
                                                                   "--connection", connection_id],
                                       env={**os.environ, TOKEN_ENVIRONMENT_VARIABLE: token})
    async with Client(stdio_client(parameters)) as client:
        found = await client.call_tool("bio_memory_search", {"query": "배포 금요일"})
        created = await client.call_tool("bio_memory_create", {
            "title": "답변 언어", "content": "사용자는 답변을 한국어로 받는 것을 선호한다.", "category": "preference",
            "confidence": "high", "evidence": "user_stated"})
        proposal = {"title": "Standing desk", "content": "The user might prefer a standing desk.",
                    "category": "preference", "confidence": "medium", "evidence": "inferred"}
        first = await client.call_tool("bio_memory_create", proposal)
        second = await client.call_tool("bio_memory_create", proposal)
    return {"search_top": found.structured_content["results"][0]["title"] if found.structured_content["results"]
            else None, "create": created.structured_content.get("status"),
            "proposal": first.structured_content.get("status"),
            "same_review": first.structured_content.get("review_id") == second.structured_content.get("review_id")}


def host_registration(run: Run, root: Path, app_exe: Path, tag: str) -> None:
    """Connect, install hooks, run the hook exactly as written, remove hooks, disconnect: real CLIs, isolated."""
    sys.frozen = True  # behave like the installed desktop app
    sys.executable = str(app_exe)
    from bio_ce import host_hooks
    from bio_ce.connections import MCPConnectionManager

    profile = root / f"host-profile-{tag}"
    (profile / ".claude").mkdir(parents=True, exist_ok=True)
    (profile / "codex").mkdir(exist_ok=True)
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(profile / ".claude"), CODEX_HOME=str(profile / "codex"),
               USERPROFILE=str(profile), HOME=str(profile))
    manager = MCPConnectionManager(DATABASE, DATA_ROOT, env=env)
    try:
        for host in ("claude", "codex"):
            if manager._find_cli(host) is None:
                run.step(f"{tag}-{host}-registration", True, result="NOT RUN: CLI not installed")
                continue
            connected = manager.connect(host, approved=True)
            manager.install_hooks(host, approved=True)
            status = manager.status(host)
            settings = host_hooks.hooks_path(host, env)
            data = json.loads(settings.read_text(encoding="utf-8-sig"))
            handler = data["hooks"]["UserPromptSubmit"][0]["hooks"][0]
            if host == "claude":
                command = [handler["command"], *handler["args"]]
                completed = subprocess.run(command, input=json.dumps({"prompt": PROMPT}, ensure_ascii=False)
                                           .encode("utf-8"), capture_output=True, timeout=60)
            else:
                completed = subprocess.run(["cmd.exe", "/d", "/s", "/c", handler["command"]],
                                           input=json.dumps({"prompt": PROMPT}, ensure_ascii=False).encode("utf-8"),
                                           capture_output=True, timeout=60)
            context = completed.stdout.decode("utf-8")
            removed = manager.remove_hooks(host, approved=True)
            after_remove = host_hooks.hooks_installed(settings, Path(handler.get("command", "")))
            disconnected = manager.disconnect(host, approved=True)
            final = manager.status(host)
            run.step(f"{tag}-{host}-connect-hooks-disconnect",
                     connected.connected and status.connected and status.hooks_installed
                     and completed.returncode == 0 and "배포는 매주 금요일" in context
                     and not after_remove and not disconnected.connected and not final.connected,
                     server=str(manager._server_executable()), hook_exit=completed.returncode,
                     hook_has_memory="배포는 매주 금요일" in context, backup=str(removed))
    finally:
        manager.close()
        sys.frozen = False


def clean_install(out: Path, candidate: Path, manifest: Path) -> int:
    """First install of the candidate where BIO CE never was, then uninstall and leave the machine as found."""
    run = Run(out)
    start = base.machine_state()
    if any(start.values()) or SPECIAL_DIR.exists():
        run.step("preflight-no-existing-install-or-data", False, state=start)
        return 2
    run.step("preflight-no-existing-install-or-data", True, state=start)
    from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, control_database_for
    from bio_ce.desktop import AppDataPaths, DesktopMemoryService, save_privacy_acknowledgement

    gui_env = dict(os.environ, CLAUDE_CONFIG_DIR=str(out / "gui-profile" / ".claude"),
                   CODEX_HOME=str(out / "gui-profile" / "codex"))
    expected = json.loads(manifest.read_text(encoding="utf-8-sig"))["version"]
    try:
        ok = base.install(run, candidate, "clean-install")
        total, mismatched = base.installed_matches_manifest(manifest)
        entry = uninstall_entry() or {}
        run.step("clean-install-candidate", ok and not mismatched and entry.get("DisplayVersion") == expected
                 and base.SHORTCUT.is_file(), version=entry.get("DisplayVersion"), files=total,
                 mismatched=mismatched[:10])
        fresh = out / "first-run-profile"
        fresh.mkdir(exist_ok=True)
        consent = base.launch_and_capture(run, dict(gui_env, LOCALAPPDATA=str(fresh)), "gui-first-run-notice")
        run.step("first-run-notice-closed-creates-nothing", consent["window"] and consent["exit"] == 0
                 and not any(fresh.iterdir()), **consent)
        paths = AppDataPaths.under(DATA_ROOT)
        save_privacy_acknowledgement(paths.settings_file)  # what accepting the notice records
        (DATA_ROOT / MARKER).write_text("created by tests/host_harness/release_e2e.py", encoding="utf-8")
        launched = base.launch_and_capture(run, gui_env, "gui-first-launch")
        run.step("first-launch-creates-database", launched["window"] and launched["exit"] == 0
                 and DATABASE.is_file(), **launched, integrity=base.integrity() if DATABASE.is_file() else None)
        service = DesktopMemoryService(DATABASE)
        service.add(title="배포 일정", content="배포는 매주 금요일 오후에 진행한다.", source_ref="user-input")
        service.close()
        control = ControlStore(control_database_for(DATABASE))
        grant, token = control.create_grant("claude", mode=MODE_AUTO_MEMORY)
        control.close()
        _gui, mcp_exe = installed()
        calls = asyncio.run(asyncio.wait_for(mcp_calls(mcp_exe, grant.connection_id, token), timeout=120))
        run.step("installed-mcp-search-create-and-duplicate-proposal", calls["search_top"] == "배포 일정"
                 and calls["create"] == "created" and calls["proposal"] == "queued_for_review"
                 and calls["same_review"], **calls)
        hook = run_hook(mcp_exe, grant.connection_id, token)
        run.step("installed-hook-context", hook["exit"] == 0 and "배포는 매주 금요일" in hook["context"])
        app_exe, _mcp = installed()
        host_registration(run, out, app_exe, "clean-install")
        kept = base.sha256(DATABASE)
        removed = base.uninstall(run, "clean-install")
        run.step("uninstall-removes-app-keeps-data", removed and not base.SHORTCUT.exists()
                 and not (APP_DIR / "BIO-CE.exe").exists() and base.sha256(DATABASE) == kept,
                 state=base.machine_state())
    except Exception:
        run.step("unexpected-error", False, traceback=traceback.format_exc())
    finally:
        base.cleanup(run)
        (out / "done").write_text("finished", encoding="utf-8")
    return 0 if all(entry["ok"] for entry in run.results) else 1


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--clean-install-only"]:
        return clean_install(Path(argv[0]).resolve(), Path(argv[2]).resolve(), Path(argv[3]).resolve())
    out, previous, candidate, manifest = (Path(arg).resolve() for arg in argv[:4])
    run = Run(out)
    start = base.machine_state()
    if any(start.values()) or SPECIAL_DIR.exists():
        run.step("preflight-no-existing-install-or-data", False, state=start)
        return 2
    run.step("preflight-no-existing-install-or-data", True, state=start)
    from bio_ce.auto_memory import AutoMemoryWriter
    from bio_ce.control_store import ControlStore, MODE_AUTO_MEMORY, control_database_for
    from bio_ce.core.models import MemoryScope
    from bio_ce.desktop import AppDataPaths, DesktopMemoryService, save_privacy_acknowledgement
    from bio_ce.storage.backup import validate_database

    scope = MemoryScope("bio-ce-personal", "default")
    gui_env = dict(os.environ, CLAUDE_CONFIG_DIR=str(out / "gui-profile" / ".claude"),
                   CODEX_HOME=str(out / "gui-profile" / "codex"))
    try:
        # 1. previous release creates the data -------------------------------------------------
        ok = base.install(run, previous, "previous")
        previous_version = (uninstall_entry() or {}).get("DisplayVersion")
        run.step("install-previous-release", ok and base.machine_state()["app_exe"], version=previous_version)
        paths = AppDataPaths.under(DATA_ROOT)
        save_privacy_acknowledgement(paths.settings_file)
        (DATA_ROOT / MARKER).write_text("created by tests/host_harness/release_e2e.py", encoding="utf-8")
        launched = base.launch_and_capture(run, gui_env, "gui-previous-first-start")
        run.step("previous-gui-creates-database", launched["window"] and launched["exit"] == 0
                 and DATABASE.is_file(), **launched)
        service = DesktopMemoryService(DATABASE)
        korean = service.add(title="배포 일정", content="배포는 매주 금요일 오후에 진행한다.", source_ref="회의록 #1")
        revised = service.revise(korean, title="배포 일정", content="배포는 매주 금요일 오후에 진행한다. (확정)",
                                 source_ref="회의록 #1")
        gone = service.add(title="Old office", content="The office was on the 3rd floor.", source_ref="user-input")
        service.retract(gone)
        user_backup = out / "user backups" / "업그레이드 전 백업 #1.sqlite3"
        service.create_backup(user_backup)
        service.close()
        control = ControlStore(control_database_for(DATABASE))
        grant, token = control.create_grant("claude", mode=MODE_AUTO_MEMORY)
        writer = AutoMemoryWriter(DATABASE, control, scope=scope, connection_id=grant.connection_id)
        pending = writer.create(title="Quiet room", content="The user might prefer a quiet room for calls.",
                                category="preference", confidence="medium", evidence="inferred")
        control.close()
        _gui, previous_mcp = installed()
        previous_hook = run_hook(previous_mcp, grant.connection_id, token)
        run.step("previous-release-data-created", revised.revision_number == 2
                 and pending["status"] == "queued_for_review" and "배포는 매주 금요일" in previous_hook["context"])
        before = snapshot(user_backup)

        # 2. upgrade while a connected host still runs the previous MCP server ------------------------
        # Like a Codex conversation left open: the server's stdin stays open, so it keeps running and
        # holds BIO-CE-MCP.exe. Setup (CloseApplications=yes) must close it, log it, and replace the files.
        running = subprocess.Popen(
            [str(previous_mcp), "mcp-stdio", "--db", str(DATABASE), "--connection", grant.connection_id],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, BIO_CE_CONNECTION_TOKEN=token), creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(3)
        running_before = running.poll() is None
        ok = base.install(run, candidate, "upgrade")
        try:
            running.wait(30)
        except subprocess.TimeoutExpired:
            pass
        closed_by_setup = running.poll() is not None
        if not closed_by_setup:
            running.kill()
            running.wait(10)
        log_text = (out / "setup-upgrade.log").read_text(encoding="utf-8", errors="replace") \
            if (out / "setup-upgrade.log").is_file() else ""
        log_lines = [line.strip()[-160:] for line in log_text.splitlines()
                     if "application" in line.lower() and ("shut" in line.lower() or "close" in line.lower())][:6]
        total, mismatched = base.installed_matches_manifest(manifest)
        entry = uninstall_entry() or {}
        run.step("upgrade-closes-running-mcp-server", running_before and ok and closed_by_setup and not mismatched,
                 running_before=running_before, closed_by_setup=closed_by_setup, setup_log=log_lines)
        run.step("upgrade-to-candidate", ok and not mismatched and entry.get("DisplayVersion") != previous_version,
                 version=entry.get("DisplayVersion"), files=total, mismatched=mismatched[:10])
        run.step("upgrade-preserves-all-user-data", snapshot(user_backup) == before,
                 integrity=base.integrity(), memories=len(before["memories"][1][1]))
        launched = base.launch_and_capture(run, gui_env, "gui-after-upgrade")
        run.step("candidate-gui-opens-upgraded-data", launched["window"] and launched["exit"] == 0
                 and snapshot(user_backup) == before, **launched)

        # 3. installed MCP server and hook ------------------------------------------------------
        _gui, mcp_exe = installed()
        calls = asyncio.run(asyncio.wait_for(mcp_calls(mcp_exe, grant.connection_id, token), timeout=120))
        run.step("installed-mcp-korean-search-create-and-duplicate-proposal", calls["search_top"] == "배포 일정"
                 and calls["create"] == "created" and calls["proposal"] == "queued_for_review"
                 and calls["same_review"], **calls)
        hook = run_hook(mcp_exe, grant.connection_id, token)
        run.step("installed-hook-korean-context", hook["exit"] == 0 and "배포는 매주 금요일" in hook["context"])
        control = ControlStore(control_database_for(DATABASE))
        old_review = control.review(pending["review_id"])
        control.close()
        run.step("review-item-from-previous-release-still-pending", old_review.status == "pending")

        # 4. host registration and hooks through the real CLIs (isolated profiles) ---------------
        app_exe, _mcp = installed()
        host_registration(run, out, app_exe, "default-dir")

        # 5. revoke ---------------------------------------------------------------------------
        control = ControlStore(control_database_for(DATABASE))
        control.revoke(grant.connection_id)
        control.close()
        revoked = run_hook(mcp_exe, grant.connection_id, token)
        refused = subprocess.run([str(mcp_exe), "mcp-stdio", "--db", str(DATABASE), "--connection", grant.connection_id],
                                 env={**os.environ, "BIO_CE_CONNECTION_TOKEN": token}, stdin=subprocess.DEVNULL,
                                 capture_output=True, timeout=60)
        run.step("revoked-grant-gets-nothing", revoked["exit"] == 0 and revoked["context"] == ""
                 and refused.returncode == 3, server_exit=refused.returncode)

        # 6. backup, restore, and recovery from the pre-upgrade backup ----------------------------
        service = DesktopMemoryService(DATABASE)
        count = service.count()
        candidate_backup = out / "user backups" / "후보 백업.sqlite3"
        service.create_backup(candidate_backup)
        service.restore_backup(user_backup)  # recover the state the user saved before upgrading
        recovered = service.count()
        service.restore_backup(candidate_backup)
        restored = service.count()
        service.close()
        validate_database(user_backup, standalone=True)
        run.step("backup-restore-and-recovery-from-pre-upgrade-backup",
                 recovered == len([r for r in before["memories"][0][1]]) - 1 and restored == count,
                 before_upgrade_active=recovered, after=restored)

        # 7. uninstall keeps data, reinstall into a Korean/space/'#' folder ------------------------
        kept = snapshot(user_backup)
        removed = base.uninstall(run, "keep-data")
        run.step("uninstall-keeps-data", removed and not base.SHORTCUT.exists() and snapshot(user_backup) == kept,
                 state=base.machine_state())
        completed = subprocess.run([str(candidate), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                    f"/DIR={SPECIAL_DIR}", f"/LOG={out / 'setup-reinstall-special.log'}"], timeout=600)
        special_gui, special_mcp = installed(SPECIAL_DIR)
        run.step("reinstall-into-korean-space-hash-folder", completed.returncode == 0 and special_gui.is_file()
                 and special_mcp.is_file() and snapshot(user_backup) == kept,
                 location=(uninstall_entry() or {}).get("InstallLocation"))
        before_launch = base.all_windows()
        process = subprocess.Popen([str(special_gui)], env=gui_env, cwd=str(SPECIAL_DIR))
        hwnd, deadline = None, time.time() + 60
        while hwnd is None and time.time() < deadline and process.poll() is None:
            hwnd = base.find_window(before_launch)
            time.sleep(0.25)
        if hwnd:
            time.sleep(3)
            base.capture(hwnd, out / "gui-special-folder.png")
            base.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        code = process.wait(30)
        run.step("gui-from-special-folder", bool(hwnd) and code == 0)
        host_registration(run, out, special_gui, "special-dir")
        removed = base.uninstall(run, "special")
        run.step("uninstall-from-special-folder", removed and not special_gui.exists()
                 and snapshot(user_backup)["memories"] == kept["memories"])
    except Exception:
        run.step("unexpected-error", False, traceback=traceback.format_exc())
    finally:
        base.cleanup(run)
        if SPECIAL_DIR.exists():
            shutil.rmtree(SPECIAL_DIR, ignore_errors=True)
        run.step("special-folder-cleaned", not SPECIAL_DIR.exists())
        (out / "done").write_text("finished", encoding="utf-8")
    return 0 if all(entry["ok"] for entry in run.results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
