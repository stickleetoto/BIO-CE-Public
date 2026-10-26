# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import unittest

import bio_ce


REPOSITORY = Path(__file__).resolve().parents[2]
PACKAGING = REPOSITORY / "packaging"
sys.path.insert(0, str(PACKAGING))
import build_assets  # noqa: E402


def _inno_compiler() -> Path | None:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


class VersionAndAssetTests(unittest.TestCase):
    def test_package_metadata_and_module_version_match(self):
        project = tomllib.loads((REPOSITORY / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["version"], bio_ce.__version__)
        self.assertEqual(build_assets.display_version("0.2.0rc1"), "0.2.0-rc1")
        self.assertEqual(build_assets.numeric_version("0.2.0rc1"), (0, 2, 0, 1))
        self.assertEqual(build_assets.numeric_version("0.2.0"), (0, 2, 0, 0))
        with self.assertRaises(ValueError):
            build_assets.numeric_version("0.2")

    def test_generated_icon_is_a_valid_multi_size_ico(self):
        with tempfile.TemporaryDirectory(prefix="bio-ce-assets-") as scratch:
            output = Path(scratch)
            self.assertEqual(build_assets.main(["--output", str(output), "--version", bio_ce.__version__]), 0)
            data = (output / "bio-ce.ico").read_bytes()
            reserved, kind, count = struct.unpack_from("<HHH", data)
            self.assertEqual((reserved, kind), (0, 1))
            sizes = set()
            for index in range(count):
                width, height, _, _, planes, bits, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * index)
                self.assertEqual((planes, bits), (1, 32))
                self.assertLessEqual(offset + length, len(data))
                sizes.add(width or 256)
            self.assertTrue({16, 32, 48, 256} <= sizes)
            again = Path(scratch) / "again"
            build_assets.main(["--output", str(again), "--version", bio_ce.__version__])
            self.assertEqual((again / "bio-ce.ico").read_bytes(), data, "icon output must be deterministic")
            version_text = (output / "gui-version.txt").read_text(encoding="utf-8")
            self.assertIn(f"filevers={build_assets.numeric_version(bio_ce.__version__)}", version_text)
            self.assertIn("'BIO Community Edition'", version_text)


class RuntimeNoticeTests(unittest.TestCase):
    def test_vendored_cpython_notices_are_verbatim_and_cover_linked_libraries(self):
        import collect_runtime_notices as notices

        data = notices.CPYTHON_INCORPORATED.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), notices.CPYTHON_INCORPORATED_SHA256)
        text = data.decode("utf-8")
        for component in ("OpenSSL", "expat", "libffi", "zlib", "libmpdec"):
            self.assertRegex(text, rf"(?m)^{component}$")


class InnoScriptPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = (PACKAGING / "BIO-CE.iss").read_text(encoding="utf-8-sig")

    def setting(self, name: str) -> str:
        match = re.search(rf"^{name}=(.*)$", self.script, re.MULTILINE)
        self.assertIsNotNone(match, name)
        return match.group(1).strip()

    def test_per_user_install_without_elevation(self):
        self.assertEqual(self.setting("PrivilegesRequired"), "lowest")
        self.assertNotIn("PrivilegesRequiredOverridesAllowed", self.script)
        self.assertEqual(self.setting("DefaultDirName"), r"{userpf}\BIO-CE")
        self.assertEqual(self.setting("ArchitecturesInstallIn64BitMode"), "x64compatible")
        self.assertNotIn("{commonpf}", self.script)
        self.assertNotIn("HKLM", self.script)

    def test_user_data_is_only_removed_after_explicit_interactive_opt_in(self):
        self.assertEqual(self.script.count("DelTree("), 1)
        code = self.script.split("[Code]", 1)[1]
        uninstall = code.split("procedure CurUninstallStepChanged", 1)[1]
        self.assertIn("not UninstallSilent()", uninstall)
        self.assertIn("MB_YESNO or MB_DEFBUTTON2", uninstall)
        self.assertLess(uninstall.index("IDYES"), uninstall.index("DelTree("))
        self.assertNotIn("[UninstallDelete]", self.script)
        for line in self.script.split("[InstallDelete]", 1)[1].split("[Files]", 1)[0].splitlines():
            if line.startswith("Type:"):
                self.assertIn("{app}", line)
                self.assertIn("Check: IsBioCeInstallDir", line)
                self.assertNotIn("localappdata", line.lower())

    def test_setup_detects_the_running_desktop_app(self):
        from bio_ce.desktop import INSTANCE_MUTEX_NAME

        self.assertEqual(self.setting("AppMutex"), INSTANCE_MUTEX_NAME)
        self.assertEqual(self.setting("CloseApplications"), "yes")

    def test_program_folder_cannot_overlap_the_data_folder(self):
        self.assertIn("function PrepareToInstall", self.script)
        self.assertIn("OverlapsDataRoot(ExpandConstant('{app}'))", self.script)

    def test_legacy_powershell_installer_is_gone(self):
        for name in ("install.ps1", "install.cmd", "uninstall.ps1"):
            self.assertFalse((PACKAGING / name).exists(), name)
        build = (PACKAGING / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertNotIn("iexpress", build.lower())
        self.assertNotIn("ExecutionPolicy", build)
        self.assertIn("Universal CRT DLLs were bundled", build)

    def test_script_compiles_with_inno_setup(self):
        compiler = _inno_compiler()
        if compiler is None:
            self.skipTest("Inno Setup 6 is not installed")
        with tempfile.TemporaryDirectory(prefix="bio-ce-iscc-") as scratch:
            root = Path(scratch)
            payload = root / "payload"
            (payload / "MCP").mkdir(parents=True)
            (payload / "BIO-CE.exe").write_bytes(b"synthetic gui placeholder")
            (payload / "MCP" / "BIO-CE-MCP.exe").write_bytes(b"synthetic mcp placeholder")
            build_assets.write_icon(root / "test.ico")
            completed = subprocess.run(
                [
                    str(compiler), "/Q", "/DAppVersion=0.0.0-test", "/DNumericVersion=0.0.0.0",
                    f"/DPayloadDir={payload}", f"/DOutputDir={root / 'out'}", f"/DIconFile={root / 'test.ico'}",
                    "/DOutputBaseFilename=BIO-CE-Setup-compile-test", str(PACKAGING / "BIO-CE.iss"),
                ],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=180, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue((root / "out" / "BIO-CE-Setup-compile-test.exe").is_file())


if __name__ == "__main__":
    unittest.main()
