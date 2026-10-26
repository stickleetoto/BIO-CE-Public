# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Collect license text for pinned Python runtime dependencies in the app bundle."""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
from pathlib import Path
import re
import sys


# Verbatim copy of python/cpython Doc/license.rst at tag v3.12.10. It carries the
# notices for code the Windows build links in (OpenSSL, expat, libffi, zlib,
# libmpdec, ...) that the installed LICENSE.txt does not repeat.
CPYTHON_INCORPORATED = Path(__file__).resolve().parent / "notices" / "cpython-3.12.10-license.rst"
CPYTHON_INCORPORATED_VERSION = "3.12.10"
CPYTHON_INCORPORATED_SHA256 = "341832873fd316a37927e79385093fbbfd40a467428480835fe435a80cadf4e5"
CPYTHON_INCORPORATED_SOURCE = "https://github.com/python/cpython/blob/v3.12.10/Doc/license.rst"


def _locked_names(lock_path: Path) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)==", line)
        if match and match.group(1).lower() not in seen:
            names.append(match.group(1))
            seen.add(match.group(1).lower())
    return names


def _license_files(distribution: metadata.Distribution) -> list[tuple[str, bytes]]:
    result: list[tuple[str, bytes]] = []
    for entry in distribution.files or ():
        relative = Path(str(entry))
        name = relative.name.lower()
        if not (
            name.startswith(("license", "licence", "copying", "notice"))
            or "/licenses/" in str(entry).lower()
        ):
            continue
        if relative.suffix.lower() in {".py", ".pyc", ".pyd", ".dll", ".so", ".json"}:
            continue
        try:
            content = distribution.locate_file(entry).read_bytes()
        except OSError:
            continue
        if content and len(content) <= 2_000_000:
            result.append((str(entry).replace("\\", "/"), content))
    return result


def collect(lock_path: Path, output: Path, *, version: str, installer_license: Path | None = None) -> None:
    sections = [
        f"BIO CE {version} - third-party runtime notices",
        "",
        "The following license texts are copied from exact installed distributions resolved by requirements-mcp.lock.txt.",
        "Each upstream component remains under its own license. BIO CE does not relicense these components.",
        "",
    ]
    missing: list[str] = []
    for name in _locked_names(lock_path):
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        license_name = (
            distribution.metadata.get("License-Expression")
            or distribution.metadata.get("License")
            or "See included license text"
        )
        files = _license_files(distribution)
        sections.extend(
            [
                "=" * 78,
                f"{distribution.metadata.get('Name', name)} {distribution.version}",
                f"Declared license: {license_name}",
                "",
            ]
        )
        if not files:
            missing.append(f"{name} {distribution.version}: no license text in installed distribution")
            continue
        for filename, content in files:
            sections.extend(
                [
                    f"--- {filename} ---",
                    content.decode("utf-8", errors="replace").strip(),
                    "",
                ]
            )

    candidates = (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE")
    python_license = next((path for path in candidates if path.is_file()), None)
    if python_license is None:
        missing.append("CPython runtime license file")
    else:
        sections.extend(
            [
                "=" * 78,
                f"CPython {sys.version.split()[0]} (Python Software Foundation License)",
                "",
                python_license.read_text(encoding="utf-8", errors="replace").strip(),
                "",
            ]
        )
    runtime_version = sys.version.split()[0]
    incorporated = CPYTHON_INCORPORATED.read_bytes() if CPYTHON_INCORPORATED.is_file() else b""
    if runtime_version != CPYTHON_INCORPORATED_VERSION:
        missing.append(
            f"CPython incorporated-software notices for {runtime_version} "
            f"(packaging/notices covers {CPYTHON_INCORPORATED_VERSION})"
        )
    elif hashlib.sha256(incorporated).hexdigest() != CPYTHON_INCORPORATED_SHA256:
        missing.append("unmodified CPython incorporated-software notices")
    else:
        text = incorporated.decode("utf-8")
        start = text.index("Licenses and Acknowledgements for Incorporated Software")
        sections.extend(
            [
                "=" * 78,
                f"CPython {runtime_version} - Licenses and Acknowledgements for Incorporated Software",
                f"Source: {CPYTHON_INCORPORATED_SOURCE}",
                "Covers, among others, OpenSSL (libcrypto-3-x64.dll, libssl-3-x64.dll), expat (pyexpat),",
                "libffi, zlib, and libmpdec (_decimal) as built into the Windows runtime.",
                "SQLite (sqlite3.dll) and liblzma (_lzma) are in the public domain and need no notice.",
                "",
                text[start:].strip(),
                "",
            ]
        )
    tk_license = Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms"
    if tk_license.is_file():
        sections.extend(
            [
                "=" * 78,
                "Tcl/Tk 8.6 license terms (bundled with the Python Tk runtime)",
                "",
                tk_license.read_text(encoding="utf-8", errors="replace").strip(),
                "",
            ]
        )
    else:
        missing.append("Tcl/Tk runtime license terms")
    try:
        bootloader = metadata.distribution("pyinstaller")
    except metadata.PackageNotFoundError:
        missing.append("PyInstaller bootloader license")
    else:
        bootloader_files = [item for item in _license_files(bootloader) if "copying" in item[0].lower()]
        if not bootloader_files:
            missing.append("PyInstaller bootloader license text")
        sections.extend(
            [
                "=" * 78,
                f"PyInstaller {bootloader.version} bootloader (embedded in BIO-CE.exe and BIO-CE-MCP.exe;"
                " GPL-2.0-or-later with the PyInstaller bootloader exception)",
                "",
            ]
        )
        for filename, content in bootloader_files:
            sections.extend([f"--- {filename} ---", content.decode("utf-8", errors="replace").strip(), ""])
    if installer_license is not None:
        if not installer_license.is_file():
            missing.append("Inno Setup license text")
        else:
            sections.extend(
                [
                    "=" * 78,
                    "Inno Setup 6 (setup and uninstall programs that install BIO CE)",
                    "",
                    installer_license.read_text(encoding="utf-8", errors="replace").strip(),
                    "",
                ]
            )
    if missing:
        raise RuntimeError("Runtime license materials are incomplete: " + "; ".join(missing))
    output.write_text("\n".join(sections) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "requirements-mcp.lock.txt",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True, help="BIO CE version shown in the notice header")
    parser.add_argument("--installer-license", type=Path, help="Inno Setup license.txt used to build Setup")
    args = parser.parse_args()
    collect(args.lock, args.output, version=args.version, installer_license=args.installer_license)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
