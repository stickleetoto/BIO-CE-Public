# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0
# BIO CE-7 candidate modification: licensing/provenance header added; behavior unchanged.

"""Command-line entry point for the BIO CE preview."""

from __future__ import annotations

import argparse
from pathlib import Path

from bio_ce.demo import run_demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bio-ce", description="BIO Community Edition tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="run the synthetic-only local memory demonstration")
    commands.add_parser("desktop", help="open the Windows local memory manager")
    seed = commands.add_parser(
        "seed-synthetic-mcp-demo",
        help="create a fresh SQLite database containing only the fixed synthetic MCP fixture",
    )
    seed.add_argument("--db", required=True, help="new SQLite file path; existing paths are refused")
    mcp = commands.add_parser(
        "mcp-stdio",
        help="run the MCP stdio server for one exact local scope",
    )
    mcp.add_argument("--db", required=True, help="existing BIO CE SQLite database")
    mcp.add_argument("--project", help="exact project scope; required without --connection, "
                     "otherwise it must match the connection's scope")
    mcp.add_argument("--namespace", help="exact namespace scope; required without --connection, "
                     "otherwise it must match the connection's scope")
    mcp.add_argument(
        "--connection",
        help="connection created by the desktop app; its token is read from BIO_CE_CONNECTION_TOKEN. "
             "Without it the server is read-only.",
    )
    hook = commands.add_parser("hook", help="host session hook: print BIO CE context for Codex or Claude Code")
    hook.add_argument("event", choices=("session-start", "user-prompt"))
    hook.add_argument("--host", required=True, choices=("codex", "claude"))
    hook.add_argument("--db", required=True)
    hook.add_argument("--connection", required=True)
    hook.add_argument("--token", required=True)
    hook.add_argument("--project", help="optional; must match the connection's scope")
    hook.add_argument("--namespace", help="optional; must match the connection's scope")
    args = parser.parse_args(argv)
    if args.command == "hook":
        import io
        import sys

        from bio_ce.host_hooks import HookRequest, run_hook

        request = HookRequest(args.event, args.host, Path(args.db), args.connection, args.token,
                              args.project, args.namespace)
        stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace") if sys.stdin else None
        stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
        try:
            return run_hook(request, stdin, stdout)
        finally:
            stdout.detach()
    if args.command == "demo":
        return run_demo()
    if args.command == "desktop":
        from bio_ce.desktop import run_desktop

        return run_desktop()
    if args.command == "seed-synthetic-mcp-demo":
        from bio_ce.demo_fixture import (
            DEMO_NAMESPACE,
            DEMO_PROJECT,
            seed_synthetic_mcp_demo,
        )

        revisions = seed_synthetic_mcp_demo(args.db)
        print(
            f"Seeded {len(revisions)} synthetic memories in "
            f"project={DEMO_PROJECT!r}, namespace={DEMO_NAMESPACE!r}."
        )
        return 0
    if args.command == "mcp-stdio":
        from bio_ce.mcp_server import run_mcp_stdio

        if args.connection is None and (args.project is None or args.namespace is None):
            parser.error("mcp-stdio needs --project and --namespace unless --connection is given")

        return run_mcp_stdio(
            args.db, project=args.project, namespace=args.namespace, connection_id=args.connection
        )
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
