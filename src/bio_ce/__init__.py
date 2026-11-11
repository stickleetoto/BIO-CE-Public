# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

"""BIO Community Edition: local, auditable synthetic memory primitives."""

__version__ = "0.4.0rc1"


def display_version(version: str | None = None) -> str:
    """The one version form shown everywhere: app, MCP server info, memory skill, installer (0.4.1rc1 -> 0.4.1-rc1)."""
    import re

    return re.sub(r"(\d)(a|b|rc)(\d+)$", r"\1-\2\3", version or __version__).replace(".dev", "-dev")
