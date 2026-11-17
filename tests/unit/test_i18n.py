# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U0: the app's text by key, in English and Korean."""

from __future__ import annotations

import os
from pathlib import Path
import string
import sys
import tempfile
import unittest
from unittest import mock

from bio_ce.control_store import ControlStore, control_database_for
from bio_ce.ui import i18n
from bio_ce.ui.i18n import en, ko
from tests.i18n_scan import scan_source, ui_literals, used_keys

# The number of English texts still written directly in the UI. It may only go down (v0.4.4 moves them to keys);
# lower it when a change removes some. At the end of v0.4.4 only an allowlist remains.
# v0.4.4 U5 (design §6.3): no English text is written directly in the UI any more (1,139 at the v0.4.3-rc1 UI).
# What may stay, and why: names, key names, Tk class names, and checks the code makes on its own strings.
_NAMES = "a product or AI tool name: not translated (glossary §3)"
_KEYS = "a key name on the keyboard: not translated (glossary §3)"
_TK = "a Tk widget class name, not text"
ALLOWED: dict[str, str] = {
    "BIO CE": _NAMES, "BIO Community Edition": _NAMES, "ChatGPT": _NAMES, "Claude": _NAMES, "Claude Code": _NAMES,
    "Claude desktop app": "format.HOST_NAMES: the English host name for hosts and logs; screens use host_name()",
    "Codex (CLI · desktop app)": "format.HOST_NAMES: the English host name for hosts and logs; screens use host_name()",
    "Ctrl+1": _KEYS, "Ctrl+2": _KEYS, "Ctrl+3": _KEYS, "Ctrl+4": _KEYS, "Ctrl+1 – Ctrl+4": _KEYS, "Ctrl+F / /": _KEYS,
    "Ctrl+H": _KEYS, "Ctrl+N": _KEYS, "Ctrl+S / Ctrl+Enter": _KEYS, "Ctrl+Z": _KEYS,
    "Ctrl+click / Shift+click / Space": _KEYS, "Delete": _KEYS, "E / Ctrl+E": _KEYS, "Enter": _KEYS, "Esc": _KEYS,
    "F5": _KEYS, "Shift+F10": _KEYS, "Tab / Shift+Tab": _KEYS,
    "Entry": _TK, "Listbox": _TK, "Sash": _TK, "Spinbox": _TK, "TCombobox": _TK, "TEntry": _TK, "TFrame": _TK,
    "TSpinbox": _TK, "Text": _TK, "Treeview": _TK,
    "*.md *.txt *.markdown": "a file-dialog pattern",
    "BIO CE missing font probe": "a font name the theme asks Tk for, to see what Tk falls back to",
    "UI background task did not finish": "an exception for a programming error in the task runner; never shown",
    "the memory changed": "an internal exception the editor catches and turns into its own notice",
    "must not be empty": "format.validation_feedback reads the store's English message; not shown",
    "(\\w+) (must not be empty|exceeds (\\d+) characters|contains a control character)":
        "format.validation_feedback's pattern for the store's English message",
}


def placeholders(value) -> set[str]:
    forms = value.values() if isinstance(value, dict) else [value]
    return {name for form in forms for _text, name, _spec, _conv in string.Formatter().parse(form) if name}


class TextKeyTests(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_language("en")

    def test_both_languages_have_the_same_keys_and_placeholders(self):
        self.assertEqual(set(en.STRINGS) ^ set(ko.STRINGS), set())
        for key, value in en.STRINGS.items():
            with self.subTest(key=key):
                self.assertEqual(placeholders(value), placeholders(ko.STRINGS[key]))
                for table in (en.STRINGS, ko.STRINGS):
                    form = table[key]
                    if isinstance(form, dict):
                        self.assertIn("other", form)
                        self.assertLessEqual(set(form), {"one", "other"})

    def test_every_key_the_code_uses_exists(self):
        self.assertEqual(used_keys() - set(en.STRINGS), set())

    def test_lookup_forms_and_fallbacks(self):
        self.assertEqual(i18n.t("nav.memories"), "Memories")
        self.assertEqual(i18n.t("common.items", count=1), "1 item")
        self.assertEqual(i18n.t("common.items", count=3), "3 items")
        i18n.set_language("ko")
        self.assertEqual(i18n.t("nav.memories"), "기억")
        self.assertEqual(i18n.t("common.items", count=1), "항목 1개")
        self.assertEqual(i18n.t("space.personal"), "개인")
        with mock.patch.dict(ko.STRINGS, {}, clear=False):
            del ko.STRINGS["nav.settings"]
            self.assertEqual(i18n.t("nav.settings"), "Settings")  # missing in Korean: English
        self.assertEqual(i18n.t("no.such.key"), "no.such.key")  # missing everywhere: the key shows
        i18n.set_language("xx")
        self.assertEqual(i18n.language(), "en")

    def test_the_windows_language_picks_the_default(self):
        with mock.patch.dict("os.environ", {"BIO_CE_UI_LANGUAGE": "ko"}):
            self.assertEqual(i18n.detect_language(), "ko")  # the override (tests pin "en" in conftest)
        with mock.patch.object(i18n, "detect_language", return_value="ko"):
            self.assertEqual(i18n.resolve("auto"), "ko")
            self.assertEqual(i18n.resolve(None), "ko")
        self.assertEqual(i18n.resolve("en"), "en")
        self.assertEqual(i18n.resolve("ko"), "ko")

    @unittest.skipUnless(sys.platform == "win32", "the installer's language is in the Windows registry")
    def test_auto_speaks_the_language_chosen_in_setup_first(self):
        """The installer writes HKCU\\Software\\BIO CE\\InstallLanguage; "auto" uses it before the Windows language.
        The registry calls are faked here: the test never reads or writes the real registry."""
        import winreg

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        env = {key: value for key, value in os.environ.items() if key != "BIO_CE_UI_LANGUAGE"}
        for stored, wanted in (("korean", "ko"), ("english", "en"), ("Korean ", "ko"), ("french", None)):
            with self.subTest(stored=stored), mock.patch.object(winreg, "OpenKey", return_value=Key()), \
                    mock.patch.object(winreg, "QueryValueEx", return_value=(stored, winreg.REG_SZ)):
                self.assertEqual(i18n.setup_language(), wanted)
                with mock.patch.dict("os.environ", env, clear=True), \
                        mock.patch("ctypes.windll.kernel32.GetUserDefaultUILanguage", return_value=0x0409):
                    self.assertEqual(i18n.detect_language(), wanted or "en")
        with mock.patch.object(winreg, "OpenKey", side_effect=OSError("no key")):
            self.assertIsNone(i18n.setup_language())  # not installed by setup: the Windows language decides

    def test_the_choice_is_kept_in_the_connection_file(self):
        with tempfile.TemporaryDirectory() as temp:
            control = ControlStore(control_database_for(Path(temp) / "data" / "memories.sqlite3"))
            try:
                self.assertEqual(control.ui_language(), "auto")
                control.set_ui_language("ko")
                self.assertEqual(control.ui_language(), "ko")
                with self.assertRaises(ValueError):
                    control.set_ui_language("fr")
            finally:
                control.close()

    def test_no_text_is_written_directly_in_the_ui(self):
        found = ui_literals()
        left = [f"{name}:{line}: {text!r}" for name, line, text in found if text not in ALLOWED]
        newline = chr(10)
        self.assertEqual(left, [], "move this UI text to i18n keys:" + newline + newline.join(left))
        self.assertEqual(sorted(set(ALLOWED) - {text for _n, _l, text in found}), [],
                         "allowed texts no longer in the UI: remove them from ALLOWED")

    def test_positive_control_text_written_directly_is_found(self):
        source = 'import tkinter as tk\nlabel = tk.Label(text="Save this memory")\n__all__ = ["Label"]\n'
        self.assertEqual([text for _n, _l, text in scan_source(source)], ["Save this memory"])

    def test_the_new_product_name_is_not_in_the_texts(self):
        for table in (en.STRINGS, ko.STRINGS):
            for key, value in table.items():
                for form in (value.values() if isinstance(value, dict) else [value]):
                    self.assertFalse(names_a_withheld_word(form), key)

    def test_positive_control_a_withheld_word_is_found(self):
        # The words are kept out of the repository; only their hashes are here. A made-up word of the same lengths
        # shows the window search runs: with its own hash it is found.
        self.assertTrue(names_a_withheld_word("Hello Zqxwvu.", hashes={_digest("zqxwvu")}))
        self.assertFalse(names_a_withheld_word("Hello world.", hashes={_digest("zqxwvu")}))


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# SHA-256 of the product-name words that must not appear before the name is filed (lower case): two of six letters,
# two of two Hangul syllables. The words themselves are never written in the repository.
WITHHELD_HASHES = frozenset({
    "12ce821ff0d781389a2048d974da029fdeeb7be64e52d64741ac761be367cf68",
    "bb38531e3c05ad48a4453fc62ff9f2957dbf0a9739957fd960b54ec00efec40b",
    "934596c687e410995a0d672503c376ba55d215562ac04840c76b1bce05019873",
    "e84b114c2224cec43a56063e60cd6038866150f985f569744d37ccaa6e6ded88",
})


def names_a_withheld_word(text: str, *, hashes=WITHHELD_HASHES) -> bool:
    """Whether any 2- or 6-character run of ``text`` (lower case) hashes to one of ``hashes``."""
    folded = text.casefold()
    return any(_digest(folded[i:i + size]) in hashes for size in (2, 6) for i in range(len(folded) - size + 1))


if __name__ == "__main__":
    unittest.main()
