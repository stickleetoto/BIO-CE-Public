# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""rc3 (owner, 2026-11-18): every screen takes button sizes, spacing, and text sizes from one token table
(bio_ce/ui/theme.py) and nothing else.

Refused in src/bio_ce/ui: a spacing written as a number (``theme.px(6)``; a hairline of 1 and dimensions of 40 and
more, such as a dialog's width, are not spacing), a token with a number added (``SPACE_M - 2``), a button given its
own padding or text size instead of a ``size``, and a font given a point size outside theme.py. Positive controls
show each rule catches what it is for."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

UI = Path(__file__).resolve().parents[2] / "src" / "bio_ce" / "ui"
LARGEST_SPACING = 40  # from here on a number is a dimension (a width, a height), not a gap


def problems_in(source: str, name: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            called = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if called == "px" and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, (int, float)) and 1 < node.args[0].value < LARGEST_SPACING:
                found.append(f"{name}:{node.lineno}: px({node.args[0].value}) — use a SPACE_* token")
            if called in ("Button", "IconButton"):
                for keyword in node.keywords:
                    if keyword.arg in ("padx", "pady", "font"):
                        found.append(f"{name}:{node.lineno}: {called}({keyword.arg}=…) — use size=")
            if called == "Font" and name != "theme.py":
                for keyword in node.keywords:
                    if keyword.arg == "size" and isinstance(keyword.value, (ast.Constant, ast.UnaryOp)):
                        found.append(f"{name}:{node.lineno}: Font(size=…) — use a text size from the theme")
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            sides = (node.left, node.right)
            if any(isinstance(side, ast.Name) and side.id.startswith("SPACE_") for side in sides) \
                    and any(isinstance(side, ast.Constant) and isinstance(side.value, (int, float)) for side in sides):
                found.append(f"{name}:{node.lineno}: {ast.unparse(node)} — a token with a number added")
    return found


class UiTokenTests(unittest.TestCase):
    def test_screens_use_only_the_token_table(self):
        found = []
        for path in sorted(UI.rglob("*.py")):
            if "i18n" in path.parts:
                continue
            found += problems_in(path.read_text(encoding="utf-8"), str(path.relative_to(UI)).replace("\\", "/"))
        newline = chr(10)
        self.assertEqual(found, [], f"{len(found)} sizes written in place of a token:{newline}" + newline.join(found))

    def test_positive_controls(self):
        self.assertTrue(problems_in("theme.px(6)", "x.py"))
        self.assertTrue(problems_in("theme.px(SPACE_M - 2)", "x.py"))
        self.assertTrue(problems_in("Button(m, theme, 'Go', padx=9)", "x.py"))
        self.assertTrue(problems_in("tkfont.Font(size=9)", "x.py"))
        for allowed in ("theme.px(1)", "theme.px(560)", "theme.px(SPACE_M)", "Button(m, theme, 'Go', size='small')"):
            with self.subTest(allowed):
                self.assertEqual(problems_in(allowed, "x.py"), [])


if __name__ == "__main__":
    unittest.main()
