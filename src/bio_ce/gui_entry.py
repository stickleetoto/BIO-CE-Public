# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""PyInstaller entry point for the Windows desktop application."""

from bio_ce.desktop import run_desktop


if __name__ == "__main__":
    raise SystemExit(run_desktop())
