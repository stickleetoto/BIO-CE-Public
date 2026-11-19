# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Tests can't reach the user's real data or host settings: a structure, not a rule (owner, 2026-11-17).

``install()`` runs first thing in ``tests/conftest.py``, before any BIO CE module is imported, also when pytest is
started directly without the sandboxed runner:

1. LOCALAPPDATA, APPDATA, USERPROFILE, HOME (and HOMEDRIVE/HOMEPATH), TEMP/TMP, CODEX_HOME and CLAUDE_CONFIG_DIR
   point into a new folder made for this test process; the folder is removed when the tests end.
2. A guard stops the tests at once when anything opens, connects to, creates, renames, or deletes a path under a
   real user location: the user's BIO CE data (``%LOCALAPPDATA%\\BIO-CE``, or a ``BIO-CE`` folder at the root of any
   drive), Store app data
   (``%LOCALAPPDATA%\\Packages``), Claude and Codex settings and data (``Claude-Data``, ``%APPDATA%\\Claude``,
   ``~\\.claude``, ``~\\.claude.json``, ``~\\.codex``). The real locations come from Windows itself
   (the login token and the Shell Folders registry key), so a changed environment can not hide them. It checks before the call, so nothing is
   touched. In the main thread it ends the run with ``pytest.exit``; in another thread (the app's background tasks)
   it ends the process, because an exception there would only end that thread.
3. ``verify()`` (also run by a session fixture) stops the run if BIO CE's data folder would resolve to a real one.

``BIO_CE_TEST_PROTECT`` adds more locations (separated by ``;``).
"""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading

REDIRECTED = ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "TEMP", "TMP", "CODEX_HOME", "CLAUDE_CONFIG_DIR")
SANDBOX_PREFIX = "bt-"  # "BIO CE test"; kept short (see install)
ORIGINAL_ENV: dict[str, str | None] = {}
REAL: dict[str, Path] = {}
ROOT: Path | None = None
_protected: tuple[str, ...] = ()
_originals: dict[str, object] = {}


def _token_profile() -> Path | None:
    """The user's profile folder from the login token (the registry's profile list), not from USERPROFILE."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    advapi32, kernel32 = ctypes.WinDLL("advapi32"), ctypes.WinDLL("kernel32")
    userenv = ctypes.WinDLL("userenv")
    # 64-bit handles: without these types ctypes cuts them to 32 bits and the calls fail
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    userenv.GetUserProfileDirectoryW.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        return None
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not userenv.GetUserProfileDirectoryW(token, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(token)


def _shell_folder(name: str) -> Path | None:
    """An absolute folder from HKCU\\…\\Explorer\\Shell Folders (written by Windows, not expanded from the
    environment, which SHGetKnownFolderPath does: a changed USERPROFILE changes its answer)."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
            value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return Path(value) if value and "%" not in value else None


def real_locations() -> dict[str, Path]:
    """The user's real folders: from Windows, independent of this process's environment, when it can tell; else
    from the environment as it was."""
    profile = _token_profile()
    local = _shell_folder("Local AppData") or (profile / "AppData" / "Local" if profile else None)
    roaming = _shell_folder("AppData") or (profile / "AppData" / "Roaming" if profile else None)
    env = ORIGINAL_ENV or dict(os.environ)
    found = {"LOCALAPPDATA": local or (Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else None),
             "APPDATA": roaming or (Path(env["APPDATA"]) if env.get("APPDATA") else None),
             "USERPROFILE": profile or Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())}
    return {key: value for key, value in found.items() if value is not None}


def protected_roots() -> list[Path]:
    real = REAL or real_locations()
    roots = [Path(f"{drive}:/BIO-CE") for drive in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]  # a data folder at a drive's root
    if "LOCALAPPDATA" in real:
        local = real["LOCALAPPDATA"]
        roots += [local / "BIO-CE", local / "Packages", local / "Claude-Data", local / "AnthropicClaude"]
    if "APPDATA" in real:
        roots += [real["APPDATA"] / "Claude"]
    if "USERPROFILE" in real:
        profile = real["USERPROFILE"]
        roots += [profile / ".claude", profile / ".claude.json", profile / ".codex"]
    for key in ("CODEX_HOME", "CLAUDE_CONFIG_DIR"):
        value = ORIGINAL_ENV.get(key)
        if value and (ROOT is None or not _under(_norm(value), (_norm(ROOT),))):
            roots.append(Path(value))
    roots += [Path(part) for part in os.environ.get("BIO_CE_TEST_PROTECT", "").split(";") if part.strip()]
    # A junction or link points somewhere else (on this PC ~\.codex is a junction to another drive): that place
    # is just as real, under its own name.
    targets = []
    for root in roots:
        try:
            target = Path(os.path.realpath(root))
        except OSError:
            continue
        if _norm(target) != _norm(root):
            targets.append(target)
    return roots + targets


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _under(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root.rstrip("\\/") + os.sep) for root in roots)


def is_protected(path) -> bool:
    """True when ``path`` is (or is inside) a real user location the tests must never touch."""
    if isinstance(path, int):  # a file descriptor
        return False
    try:
        text = os.fspath(path)
    except TypeError:
        return False
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    if text.startswith("file:"):  # an SQLite URI
        text = text[5:].split("?", 1)[0]
        if text.startswith("///"):
            text = text[3:]
    if not text or text == ":memory:":
        return False
    return _under(_norm(text), _protected or tuple(_norm(root) for root in protected_roots()))


def _stop(path) -> None:
    message = f"BIO CE test sandbox: a test reached a real user location ({path}); the run is stopped before it " \
              f"is touched."
    try:
        sys.__stderr__.write(message + "\n")
        sys.__stderr__.flush()
    except (AttributeError, OSError, ValueError):
        pass
    if threading.current_thread() is threading.main_thread():
        import pytest

        pytest.exit(message, returncode=3)
    os._exit(3)


def _guard(name: str, position: int = 0, *, also: int | None = None):
    original = _originals[name]

    def guarded(*args, **kwargs):
        for index in (position, also):
            if index is not None and len(args) > index and is_protected(args[index]):
                _stop(args[index])
        return original(*args, **kwargs)

    guarded.__wrapped__ = original
    return guarded


def install() -> Path:
    """Point the environment into a new sandbox folder and guard the real locations. Idempotent."""
    global ROOT, _protected
    if ROOT is not None:
        return ROOT
    ORIGINAL_ENV.update({key: os.environ.get(key) for key in REDIRECTED + ("HOMEDRIVE", "HOMEPATH")})
    REAL.update(real_locations())
    # Short names: Windows paths stop at 260 characters, and the deepest test paths (a host's settings under
    # Claude-Data, SQLite files) sit inside this folder, which may itself sit inside the runner's sandbox.
    # The user's own temporary folder is short (…\AppData\Local\Temp); the runner's sandbox is not (2026-11-17: a
    # Claude-Data settings path inside it reached 274 characters and failed).
    base = REAL["LOCALAPPDATA"] / "Temp" if "LOCALAPPDATA" in REAL else None
    ROOT = Path(tempfile.mkdtemp(prefix=SANDBOX_PREFIX, dir=base if base and base.is_dir() else None)).resolve()
    for key, folder in (("LOCALAPPDATA", "l"), ("APPDATA", "r"), ("USERPROFILE", "h"), ("HOME", "h"), ("TEMP", "t"),
                        ("TMP", "t"), ("CODEX_HOME", "x"), ("CLAUDE_CONFIG_DIR", "c")):
        (ROOT / folder).mkdir(exist_ok=True)
        os.environ[key] = str(ROOT / folder)
    os.environ["HOMEDRIVE"], os.environ["HOMEPATH"] = os.path.splitdrive(str(ROOT / "h"))
    tempfile.tempdir = None  # gettempdir() reads TEMP again
    import atexit

    atexit.register(shutil.rmtree, ROOT, True)  # last: after every plugin closed its files (the time-limit log)
    _protected = tuple(_norm(root) for root in protected_roots())
    _originals.update(open=builtins.open, io_open=io.open, connect=sqlite3.connect, replace=os.replace,
                      rename=os.rename, remove=os.remove, unlink=os.unlink, rmdir=os.rmdir, mkdir=os.mkdir,
                      rmtree=shutil.rmtree)
    builtins.open = _guard("open")
    io.open = _guard("io_open")
    sqlite3.connect = _guard("connect")
    os.replace = _guard("replace", 0, also=1)
    os.rename = _guard("rename", 0, also=1)
    os.remove = _guard("remove")
    os.unlink = _guard("unlink")
    os.rmdir = _guard("rmdir")
    os.mkdir = _guard("mkdir")
    shutil.rmtree = _guard("rmtree")
    return ROOT


def verify() -> None:
    """Stop the run if BIO CE's data folder or a host settings file would resolve to a real location."""
    from bio_ce.desktop import AppDataPaths
    from bio_ce import host_hooks

    for path in (AppDataPaths.from_local_app_data().root, host_hooks.claude_settings_path(os.environ),
                 host_hooks.codex_hooks_path(os.environ), Path(tempfile.gettempdir()), Path.home()):
        if is_protected(path) or ROOT is None or not _under(_norm(path), (_norm(ROOT),)):
            _stop(path)


def remove() -> None:
    """At the end: the guard comes off and the sandbox folder (made by install) is removed."""
    global ROOT
    if ROOT is None:
        return
    builtins.open, io.open, sqlite3.connect = _originals["open"], _originals["io_open"], _originals["connect"]
    os.replace, os.rename, os.remove, os.unlink = (_originals["replace"], _originals["rename"], _originals["remove"],
                                                  _originals["unlink"])
    os.rmdir, os.mkdir, shutil.rmtree = _originals["rmdir"], _originals["mkdir"], _originals["rmtree"]
    root, ROOT = ROOT, None
    shutil.rmtree(root, ignore_errors=True)
