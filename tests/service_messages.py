# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The English messages the services can hand to a screen (v0.4.4 U5): exception texts raised outside the UI, and
the reasons the memory policy and the importer give. Read from the source, so a new message can't be missed."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bio_ce"
# Only AI tools read these (MCP replies, hook output, engine adapters for hosts); they stay English, untranslated.
HOST_ONLY = {"mcp_server.py", "mcp_entry.py", "host_hooks.py", "memory_skill.py"}
REASON_SOURCES = {"memory_policy.py", "importer.py", "curation.py"}


def _text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for index, value in enumerate(node.values):
            if isinstance(value, ast.Constant):
                out.append(str(value.value))
            else:
                out.append(f"{{v{index}}}")
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _text(node.left), _text(node.right)
        if left is not None or right is not None:
            return (left if left is not None else "{v}") + (right if right is not None else "{v}")
    return None


def _looks_like_a_sentence(text: str) -> bool:
    letters = text.replace("{", "").replace("}", "")
    return " " in letters.strip() and any(ch.isalpha() for ch in letters)


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def presentation_texts() -> list[tuple[str, int, str]]:
    """What the screens show about engines (Settings' engine card, action notes): every text in
    engine/presentation.py, and the Community engine's status message and database label (self-check 2026-11-17:
    the engine card stayed English in the Korean app)."""
    found = []
    path = SRC / "engine" / "presentation.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):  # an f-string counts whole, not its literal pieces
            skip |= {id(part) for part in node.values}
        if isinstance(node, ast.Assign) and any(getattr(target, "id", "") == "__all__" for target in node.targets):
            skip |= {id(part) for part in ast.walk(node.value)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.JoinedStr)) and id(node) not in skip:
            value = _text(node)
            if value and value[:1].isupper() and any(ch.isalpha() for ch in value):
                found.append((path.name, node.lineno, value))
    path = SRC / "engine" / "community.py"
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "EngineStatus" and len(node.args) > 2:
            value = _text(node.args[2])
            if value and _looks_like_a_sentence(value):
                found.append((path.name, node.lineno, value))
        if isinstance(node, ast.keyword) and node.arg == "database_label":
            value = _text(node.value)
            if value:
                found.append((path.name, node.value.lineno, value))
    return found


def service_messages() -> list[tuple[str, int, str]]:
    """(file, line, English text with {vN} for the parts filled in at run time)."""
    found = presentation_texts()
    for path in sorted(SRC.rglob("*.py")):
        if "ui" in path.relative_to(SRC).parts or path.name in HOST_ONLY:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            text = None
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                text = _text(node.exc.args[0])
            elif path.name in REASON_SOURCES and isinstance(node, ast.Call) and node.args:
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name == "Decision" and len(node.args) > 1 and isinstance(node.args[1], ast.Tuple):
                    for element in node.args[1].elts:
                        value = _text(element)
                        if value and _looks_like_a_sentence(value):
                            found.append((path.name, element.lineno, value))
                elif name == "append" and isinstance(getattr(node.func, "value", None), ast.Attribute) and \
                        getattr(node.func.value, "attr", "") == "reasons":
                    text = _text(node.args[0])
                elif name == "_set" and len(node.args) > 2 and isinstance(node.args[2], ast.Tuple):  # importer
                    for element in node.args[2].elts:
                        value = _text(element)
                        if value and _looks_like_a_sentence(value):
                            found.append((path.name, element.lineno, value))
            elif path.name in REASON_SOURCES and isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
                # item.state, item.reasons = STATE, ("reason",)
                for element in node.value.elts:
                    if isinstance(element, ast.Tuple):
                        for inner in element.elts:
                            value = _text(inner)
                            if value and _looks_like_a_sentence(value):
                                found.append((path.name, inner.lineno, value))
            if text and _looks_like_a_sentence(text):
                found.append((path.name, node.lineno, text))
    return found
