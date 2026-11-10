# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Verify a built BIO CE release before anyone publishes it.

Checks (each reported as PASS, FAIL, or NOT RUN in the JSON report):

* hashes: the installer's SHA-256 matches SHA256SUMS.txt and build-manifest.json, and every
  payload file still matches the manifest;
* runtime: no Universal CRT DLLs; no test or pytest modules inside either executable; bundled
  BIO CE code carries only relative source paths;
* leaks: no credential patterns, no build-machine user name, profile path, or git e-mail, and,
  when a hash list is supplied, no identifier whose SHA-256 is on that list (private names are
  passed only as hashes, so this public script never contains them);
* licenses: every runtime distribution pinned in requirements-mcp.lock.txt has a notice section,
  plus the CPython, Tcl/Tk, PyInstaller bootloader, and Inno Setup notices.

Usage:
  python verify_release.py --repo REPO --build-root BUILD --dist-root DIST --report OUT.json
         [--private-hashes FILE]   (one lowercase-identifier SHA-256 per line; or env BIO_CE_PRIVATE_HASHES)

Requires PyInstaller (the build environment) to read the executables' archives.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys


CREDENTIALS = {
    "GitHub token": rb"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}",
    "API key (sk-)": rb"\bsk-(?:ant-|proj-)[A-Za-z0-9_-]{20,}",
    "AWS access key": rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "private key": rb"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Slack token": rb"\bxox[abprs]-[A-Za-z0-9-]{10,}",
}
IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{3,63}")
TEXT_SUFFIXES = {".py", ".txt", ".md", ".json", ".toml", ".cfg", ".ini", ".tcl", ".tm", ".html", ".xml", ""}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def identity_patterns(repo: Path) -> dict[str, bytes]:
    """The build machine's own identity, read at run time (never written into this file)."""
    values = {"user name": getpass.getuser(), "profile path": os.environ.get("USERPROFILE", "")}
    try:
        email = subprocess.run(["git", "-C", str(repo), "config", "user.email"], capture_output=True, text=True,
                               timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        email = ""
    values["git e-mail"] = email
    # Shared account names (hosted CI runners) are not a personal identity: third-party wheels built on
    # hosted runners already contain C:\Users\runneradmin.
    shared = {"runneradmin", "user", "admin"}
    patterns = {}
    for name, value in values.items():
        if value and len(value) >= 4 and value.lower() not in shared and \
                PureWindowsPath(value).name.lower() not in shared:
            patterns[name] = re.escape(value.encode("utf-8"))
    return patterns


def load_private_hashes(path: str | None) -> set[str] | None:
    text = Path(path).read_text(encoding="utf-8") if path else os.environ.get("BIO_CE_PRIVATE_HASHES")
    if not text:
        return None
    return {line.strip().lower() for line in text.splitlines() if re.fullmatch(r"[0-9a-fA-F]{64}", line.strip())}


def scan_bytes(data: bytes, patterns: dict[str, re.Pattern], private: set[str] | None) -> list[str]:
    found = [name for name, pattern in patterns.items() if pattern.search(data)]
    if private:
        for token in set(IDENTIFIER.findall(data)):
            if hashlib.sha256(token.lower()).hexdigest() in private:
                found.append("private identifier (by hash)")
                break
    return found


def archive_modules(exe: Path):
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    name = next(entry for entry in archive.toc if "PYZ" in entry)
    return archive.open_embedded_archive(name)


def code_strings(code) -> list[str]:
    values = [code.co_filename, *code.co_names]
    for constant in code.co_consts:
        if isinstance(constant, str):
            values.append(constant)
        elif hasattr(constant, "co_filename"):
            values.extend(code_strings(constant))
    return values


def verify(repo: Path, build: Path, dist: Path, private: set[str] | None) -> dict:
    checks: dict[str, dict] = {}

    def check(name: str, ok: bool | None, **detail) -> None:
        checks[name] = {"result": "NOT RUN" if ok is None else ("PASS" if ok else "FAIL"), **detail}

    manifest = json.loads((build / "build-manifest.json").read_text(encoding="utf-8-sig"))
    installer = dist / manifest["installer"]["name"]
    actual = sha256(installer) if installer.is_file() else None
    sums = (dist / "SHA256SUMS.txt").read_text(encoding="ascii").split() if (dist / "SHA256SUMS.txt").is_file() else []
    check("installer hash", actual is not None and actual == manifest["installer"]["sha256"]
          and sums[:2] == [actual, installer.name], installer=installer.name, sha256=actual,
          bytes=installer.stat().st_size if actual else None, signature=manifest.get("installer_signature"))

    payload = build / "payload"
    mismatched = [entry["path"] for entry in manifest["files"]
                  if not (payload / entry["path"]).is_file() or sha256(payload / entry["path"]) != entry["sha256"]]
    on_disk = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
    extra = sorted(on_disk - {entry["path"] for entry in manifest["files"]})
    check("payload matches manifest", not mismatched and not extra, files=len(on_disk),
          mismatched=mismatched[:10], unlisted=extra[:10])

    crt = [p.name for p in payload.rglob("*.dll") if p.name.lower().startswith("api-ms-win-") or
           p.name.lower() == "ucrtbase.dll"]
    check("no bundled Universal CRT", not crt, found=crt)

    patterns = {name: re.compile(value) for name, value in {**CREDENTIALS, **identity_patterns(repo)}.items()}
    leaks: dict[str, list[str]] = {}
    for path in payload.rglob("*"):
        if path.is_file():
            hits = scan_bytes(path.read_bytes(), patterns, private if path.suffix.lower() in TEXT_SUFFIXES
                              or path.suffix.lower() in {".exe", ".pyd", ".dll"} else None)
            for hit in hits:
                leaks.setdefault(hit, []).append(path.relative_to(payload).as_posix())
    check("payload leak scan", not leaks, findings={k: v[:5] for k, v in leaks.items()},
          private_hash_list="used" if private else "not supplied")
    if private is None:
        checks["private identifier scan"] = {"result": "NOT RUN", "reason": "no hash list supplied"}

    for exe in (payload / "BIO-CE.exe", payload / "MCP" / "BIO-CE-MCP.exe"):
        pyz = archive_modules(exe)
        test_modules = sorted(n for n in pyz.toc if n.split(".")[0] in {"tests", "pytest", "_pytest", "unittest_mock"})
        absolute, code_leaks = [], set()
        for name in pyz.toc:
            if not name.startswith("bio_ce"):
                continue
            code = pyz.extract(name)
            if code is None:
                continue
            strings = code_strings(code)
            if re.match(r"^[A-Za-z]:[\\/]|^/", code.co_filename):
                absolute.append(name)
            blob = "\n".join(strings).encode("utf-8")
            code_leaks.update(scan_bytes(blob, patterns, private))
        check(f"{exe.name} bundled code", not test_modules and not absolute and not code_leaks,
              bio_ce_modules=sum(1 for n in pyz.toc if n.startswith("bio_ce")), test_modules=test_modules[:5],
              absolute_paths=absolute[:5], leaks=sorted(code_leaks))

    notices = (payload / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8") if (payload / "THIRD_PARTY_NOTICES").is_file() else ""
    def canonical(name: str) -> str:  # PEP 503: "typing_extensions" and "typing-extensions" are one distribution
        return re.sub(r"[-_.]+", "-", name).lower()

    headers = set()
    for line in notices.splitlines():
        parts = line.strip().split(" ")
        if len(parts) == 2:
            headers.add(f"{canonical(parts[0])} {parts[1]}")
    missing = []
    for line in (repo / "requirements-mcp.lock.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if match and f"{canonical(match.group(1))} {match.group(2)}" not in headers:
            missing.append(f"{match.group(1)}=={match.group(2)}")
    extras = {name: name.lower() in notices.lower() for name in ("CPython", "Tcl", "PyInstaller", "Inno Setup")}
    check("license notices", bool(notices) and not missing and all(extras.values()), missing=missing,
          runtime_components=extras)
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--build-root", required=True, type=Path)
    parser.add_argument("--dist-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--private-hashes")
    args = parser.parse_args(argv)
    checks = verify(args.repo.resolve(), args.build_root.resolve(), args.dist_root.resolve(),
                    load_private_hashes(args.private_hashes))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(checks, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, result in checks.items():
        print(f"{result['result']:8} {name}")
    return 0 if all(r["result"] != "FAIL" for r in checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
