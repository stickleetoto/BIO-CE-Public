# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Find user-facing text written directly in the desktop UI code (test helper, v0.4.4).

A string literal in ``src/bio_ce/ui`` (outside ``i18n/``, not a docstring) counts when it reads like text for a
person: it starts with a capital letter or contains a space, and it is not a style name, event, colour, font, or
path. The count may only go down while the UI moves to ``t()`` keys; at the end only an allowlist remains.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

UI = Path(__file__).resolve().parents[1] / "src" / "bio_ce" / "ui"
_NOT_TEXT = re.compile(
    r"^(<.*>|#[0-9a-fA-F]{3,8}|[A-Za-z]+\.[A-Za-z.]+|[\w-]+\.(py|md|txt|sqlite3|json|zip|exe|ico|png)"
    r"|BIO\.[\w.]+|TkDefaultFont|TkHeadingFont|Segoe .*|Cascadia .*|Consolas|Courier New|Malgun Gothic|Yu Gothic UI|"
    r"Meiryo UI|Microsoft .*|맑은 고딕|%[YmdHM].*|[A-Z_]+|[A-Z]:\\.*)$")


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _code_strings(tree: ast.AST) -> set[int]:
    """Strings that are code, not text: the names in ``__all__`` and quoted type annotations."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__"
                                                for target in node.targets):
            ids |= {id(element) for element in ast.walk(node.value)}
        annotations = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.append(node.returns)
            arguments = node.args
            annotations += [arg.annotation for arg in (*arguments.posonlyargs, *arguments.args,
                                                       *arguments.kwonlyargs, arguments.vararg, arguments.kwarg)
                            if arg is not None]
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        for annotation in annotations:
            if annotation is not None:
                ids |= {id(part) for part in ast.walk(annotation)}
    return ids


def scan_source(source: str, name: str = "<source>") -> list[tuple[str, int, str]]:
    """The text literals in one module's source (``ui_literals`` runs this on every UI module)."""
    tree = ast.parse(source)
    skip = _docstrings(tree) | _code_strings(tree)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in skip:
            continue
        text = node.value.strip()
        if len(text) < 2 or not re.search(r"[A-Za-z가-힣]", text) or _NOT_TEXT.match(text):
            continue
        if text[0].isupper() or " " in text:
            found.append((name, node.lineno, text))
    return found


def ui_literals() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(UI.rglob("*.py")):
        if "i18n" in path.parts or path.name == "service_text.py":  # translation tables: English on purpose
            continue
        found += scan_source(path.read_text(encoding="utf-8"), str(path.relative_to(UI)))
    return found


def used_keys() -> set[str]:
    keys = set()
    for path in UI.rglob("*.py"):
        if "i18n" in path.parts:
            continue
        keys |= set(re.findall(r"\bt\(\s*\"([a-z0-9_.]+)\"", path.read_text(encoding="utf-8")))
    return keys


__all__ = ["scan_source", "ui_literals", "used_keys"]
