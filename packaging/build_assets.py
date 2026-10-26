# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Generate the Windows icon and PyInstaller version resources for a release build.

The icon reproduces the runtime window mark from ``bio_ce.ui.theme.app_icon``
(three stacked memory cards on the accent tile) so no binary asset is kept in
source control. Output is deterministic for a given version string.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import struct
import zlib


ACCENT = (0x3B, 0x6F, 0xD4)
ON_ACCENT = (0xFF, 0xFF, 0xFF)
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SUPERSAMPLE = 4


def _inside_tile(x: float, y: float) -> bool:
    # Tile spans 2..30 of a 32-unit grid with a 3-unit corner radius.
    low, high, radius = 2.0, 30.0, 3.0
    if not (low <= x <= high and low <= y <= high):
        return False
    cx = min(max(x, low + radius), high - radius)
    cy = min(max(y, low + radius), high - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius


def _inside_bar(x: float, y: float) -> bool:
    for top, right in ((9.0, 24.0), (15.0, 24.0), (21.0, 18.0)):
        if 8.0 <= x <= right and top <= y <= top + 3.0:
            return True
    return False


def render(size: int) -> list[tuple[int, int, int, int]]:
    """Return top-down RGBA pixels for one icon size."""
    pixels: list[tuple[int, int, int, int]] = []
    samples = SUPERSAMPLE * SUPERSAMPLE
    for row in range(size):
        for column in range(size):
            tile = bar = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    x = (column + (sx + 0.5) / SUPERSAMPLE) * 32.0 / size
                    y = (row + (sy + 0.5) / SUPERSAMPLE) * 32.0 / size
                    if _inside_tile(x, y):
                        tile += 1
                        if _inside_bar(x, y):
                            bar += 1
            if not tile:
                pixels.append((0, 0, 0, 0))
                continue
            mix = bar / tile
            rgb = tuple(round(a + (b - a) * mix) for a, b in zip(ACCENT, ON_ACCENT))
            pixels.append((*rgb, round(255 * tile / samples)))
    return pixels


def _bmp_entry(size: int, pixels: list[tuple[int, int, int, int]]) -> bytes:
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = []
    for row in reversed(range(size)):
        rows.append(b"".join(bytes((b, g, r, a)) for r, g, b, a in pixels[row * size:(row + 1) * size]))
    mask_stride = ((size + 31) // 32) * 4
    return header + b"".join(rows) + b"\x00" * (mask_stride * size)


def _png_entry(size: int, pixels: list[tuple[int, int, int, int]]) -> bytes:
    raw = b"".join(
        b"\x00" + b"".join(bytes(p) for p in pixels[row * size:(row + 1) * size]) for row in range(size)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def write_icon(path: Path) -> None:
    images = []
    for size in SIZES:
        pixels = render(size)
        images.append((size, _png_entry(size, pixels) if size >= 128 else _bmp_entry(size, pixels)))
    offset = 6 + 16 * len(images)
    directory = struct.pack("<HHH", 0, 1, len(images))
    blobs = b""
    for size, data in images:
        dimension = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    path.write_bytes(directory + blobs)


def numeric_version(version: str) -> tuple[int, int, int, int]:
    """Map a PEP 440 release such as 0.2.0rc1 to a Windows FILEVERSION tuple."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(?:a|b|rc)(\d+)|\.dev(\d+))?", version)
    if not match:
        raise ValueError(f"unsupported version string: {version}")
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    return major, minor, patch, int(match.group(4) or match.group(5) or 0)


def display_version(version: str) -> str:
    """0.2.0rc1 -> 0.2.0-rc1, matching the installer and artifact names."""
    return re.sub(r"(\d)(a|b|rc)(\d+)$", r"\1-\2\3", version).replace(".dev", "-dev")


def write_version_file(path: Path, version: str, *, internal_name: str, description: str) -> None:
    numbers = numeric_version(version)
    shown = display_version(version)
    strings = {
        "CompanyName": "stickleetoto",
        "FileDescription": description,
        "FileVersion": shown,
        "InternalName": internal_name,
        "LegalCopyright": "Copyright 2026 stickleetoto. Apache-2.0.",
        "OriginalFilename": f"{internal_name}.exe",
        "ProductName": "BIO Community Edition",
        "ProductVersion": shown,
    }
    string_structs = ",\n".join(f"        StringStruct({key!r}, {value!r})" for key, value in strings.items())
    path.write_text(
        "# UTF-8\n"
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,\n"
        "                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('040904B0', [\n"
        f"{string_structs}\n"
        "      ])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="directory for generated assets")
    parser.add_argument("--version", required=True, help="PEP 440 version, e.g. 0.2.0rc1")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    write_icon(args.output / "bio-ce.ico")
    write_version_file(args.output / "gui-version.txt", args.version, internal_name="BIO-CE",
                       description="BIO Community Edition desktop memory manager")
    write_version_file(args.output / "mcp-version.txt", args.version, internal_name="BIO-CE-MCP",
                       description="BIO Community Edition read-only MCP server")
    print(display_version(args.version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
