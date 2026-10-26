# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""PyInstaller entry point for the stdio-only read-only MCP executable."""

from bio_ce.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
