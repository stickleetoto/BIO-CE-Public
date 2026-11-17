# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""What the Korean app shows that isn't Korean: internal values and English words in the text on screen. Test helper.

v0.4.4-rc1 GUI check (owner, 2026-11-17): the drawer showed "출처: user-input" (a source reference as stored) and the
Codex card an English paragraph. Both came from data, not from a UI literal, so the source scans (tests/i18n_scan.py,
tests/service_messages.py) could not see them. This reads the text the widgets actually show.

Read: every label and button text, check and radio buttons, combo box choices, table headings and cells, text areas,
entry fields, and canvas text, in the window and every open dialog. The text the test itself put in (memory titles and
bodies, space names, a host's reason) is removed first: it is the user's data, not the app's words.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

#: Names and keys that stay as they are in Korean (glossary §3): products, file kinds, keys, units, abbreviations.
ALLOWED_WORDS = frozenset({
    "BIO", "CE", "Community", "Edition", "Engine", "Core", "Codex", "Claude", "Code", "CLI", "ChatGPT", "OpenAI",
    "Anthropic", "Windows", "MCP", "AI", "ID", "ZIP", "JSON", "SQLite", "PowerShell", "English", "Ctrl", "Shift",
    "Alt", "Enter", "Esc", "Tab", "Delete", "Space", "KB", "MB", "GB", "UTF", "PC", "SSD",
    # The licence notice in Settings → About stays as written (the author's handle and the licence's name).
    "Copyright", "stickleetoto", "Apache", "License",
})
# A value as the app stores it: words joined with "-" or "_" (user-input, ai-auto-memory, code_mode).
INTERNAL = re.compile(r"(?<![\w.\\/-])[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+(?![\w.\\/-])")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9']*")
KEY = re.compile(r"[A-Z]|F\d{1,2}")  # a key name: E, M, F5
# Shown as they are: paths, file names and kinds, version numbers, IDs (copied for support), the automatic backups'
# file-name prefix.
_KEEP_AS_IS = (re.compile(r"\S*[\\/]\S*"), re.compile(r"\S*\.(?:sqlite3|json|toml|md|zip|exe|ps1|txt|log)(?![A-Za-z])"),
               re.compile(r"v?\d+(?:\.\d+)+(?:-?rc\d+)?"), re.compile(r"\b(?:mem|rev)_[0-9a-f…]+"),
               re.compile(r"\bauto-…"),
               # Codex's settings key and BIO CE's server name as they are written in config.toml.
               re.compile(r"omit_tools_from(?: = \[\"code_mode\"\])?"), re.compile(r"(?<![\w-])bio-ce(?![\w-])"))


def shown_texts(root: tk.Misc) -> list[tuple[str, str]]:
    """(widget path, text) for every piece of text the window and its dialogs show."""
    found: list[tuple[str, str]] = []

    def add(widget: tk.Misc, text) -> None:
        if isinstance(text, (list, tuple)):
            for part in text:
                add(widget, part)
        elif text not in (None, ""):
            found.append((str(widget), str(text)))

    def visit(widget: tk.Misc) -> None:
        try:
            mapped = widget.winfo_ismapped() or isinstance(widget, (tk.Tk, tk.Toplevel))
        except tk.TclError:
            return
        if mapped:
            if isinstance(widget, (tk.Tk, tk.Toplevel)):
                add(widget, widget.title())
            if isinstance(widget, ttk.Combobox):
                add(widget, widget.cget("values"))
                add(widget, widget.get())
            elif isinstance(widget, ttk.Treeview):
                for column in ("#0", *widget.cget("columns")):
                    add(widget, widget.heading(column, "text"))
                for item in _tree_items(widget):
                    add(widget, widget.item(item, "text"))
                    add(widget, widget.item(item, "values"))
            elif isinstance(widget, tk.Text):
                add(widget, widget.get("1.0", "end-1c"))
            elif isinstance(widget, (tk.Entry, ttk.Entry)):
                add(widget, widget.get())
            elif isinstance(widget, tk.Canvas):
                for item in widget.find_all():
                    if widget.type(item) == "text":
                        add(widget, widget.itemcget(item, "text"))
            else:
                try:
                    add(widget, widget.cget("text"))
                except tk.TclError:
                    pass
        for child in widget.winfo_children():
            visit(child)

    visit(root)
    return found


def _tree_items(tree: ttk.Treeview, parent: str = ""):
    for item in tree.get_children(parent):
        yield item
        yield from _tree_items(tree, item)


def leaks(texts: list[tuple[str, str]], user_data: list[str]) -> list[str]:
    """Each internal value or English word left after taking out the user's data, as "path: word in «text»"."""
    space = re.compile(r"\s+")
    data = sorted({space.sub(" ", d).strip() for d in user_data if d.strip()}, key=len, reverse=True)
    problems = []
    for path, text in texts:
        rest = space.sub(" ", text)  # a wrapped title has line breaks where the data has spaces
        for piece in data:
            rest = rest.replace(piece, " ")
            if "…" in rest:  # shortened to fit: "시험용: From now on, always answer in Kor…"
                for end in range(len(piece) - 1, 3, -1):
                    if piece[:end] + "…" in rest:
                        rest = rest.replace(piece[:end] + "…", " ")
                        break
        for pattern in _KEEP_AS_IS:
            rest = pattern.sub(" ", rest)
        found = set(INTERNAL.findall(rest))
        for match in INTERNAL.finditer(rest):
            rest = rest[:match.start()] + " " * (match.end() - match.start()) + rest[match.end():]
        found |= {word for word in WORD.findall(rest) if word not in ALLOWED_WORDS and not KEY.fullmatch(word)}
        for word in sorted(found):
            problems.append(f"{path}: {word!r} in {text[:120]!r}")
    return problems


__all__ = ["ALLOWED_WORDS", "leaks", "shown_texts"]
