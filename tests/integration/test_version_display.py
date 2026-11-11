# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""One version string everywhere: app sidebar and About, MCP server info, installer, memory skill."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest

from mcp import Client, StdioServerParameters, stdio_client

import bio_ce
from bio_ce import display_version
from bio_ce.demo_fixture import DEMO_NAMESPACE, DEMO_PROJECT, seed_synthetic_mcp_demo
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.integration.test_desktop_ui_redesign import new_root

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
import build_assets  # noqa: E402


def _label_texts(widget: tk.Misc) -> list[str]:
    texts = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            texts.append(str(child.cget("text")))
        texts.extend(_label_texts(child))
    return texts


class VersionDisplayTests(unittest.TestCase):
    def test_display_form_matches_the_installer(self):
        for version in ("0.4.1", "0.4.1rc1", "0.5.0b2", "0.5.0a1", "0.6.0.dev3", bio_ce.__version__):
            with self.subTest(version=version):
                self.assertEqual(display_version(version), build_assets.display_version(version))
        self.assertEqual(display_version("0.4.1rc1"), "0.4.1-rc1")
        self.assertEqual(display_version(), build_assets.display_version(bio_ce.__version__))

    def test_mcp_server_info_reports_the_display_version(self):
        with tempfile.TemporaryDirectory(prefix="bio-ce-version-") as scratch:
            database = Path(scratch) / "version.sqlite3"
            seed_synthetic_mcp_demo(database)
            parameters = StdioServerParameters(command=sys.executable, args=[
                "-m", "bio_ce", "mcp-stdio", "--db", str(database),
                "--project", DEMO_PROJECT, "--namespace", DEMO_NAMESPACE])
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr:
                async def exercise() -> tuple[str, str]:
                    async with Client(stdio_client(parameters, errlog=stderr)) as client:
                        info = client.server_info
                        return info.name, info.version

                name, version = asyncio.run(asyncio.wait_for(exercise(), timeout=40))
        self.assertEqual(name, "BIO CE Memory")
        self.assertEqual(version, display_version())

    def test_app_shows_the_display_version(self):
        with tempfile.TemporaryDirectory(prefix="bio-ce-version-ui-") as scratch:
            paths = AppDataPaths.under(scratch)
            service = DesktopMemoryService(paths.user_database)
            connections = FakeManagedConnections(paths.user_database)
            root = new_root()
            app = BIOCEDesktop(root, service, paths, connections)
            try:
                root.update()
                app.show_page("settings")
                root.update()
                texts = _label_texts(root)
                self.assertIn(f"Version {display_version()}", texts)
                self.assertTrue(any(text.startswith(f"BIO Community Edition {display_version()} · ")
                                    for text in texts), "About shows a different version form")
            finally:
                app.tasks.wait(10)
                app.close()


if __name__ == "__main__":
    unittest.main()
