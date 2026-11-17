# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U0: the app's text by key, in English and Korean."""

from __future__ import annotations

import os
from pathlib import Path
import re
import string
import sys
import tempfile
import unittest
from unittest import mock

from bio_ce.control_store import ControlStore, control_database_for
from bio_ce.ui import i18n
from bio_ce.ui.i18n import en, ko
from tests.i18n_scan import ui_literals, used_keys

# The number of English texts still written directly in the UI. It may only go down (v0.4.4 moves them to keys);
# lower it when a change removes some. At the end of v0.4.4 only an allowlist remains.
LITERAL_BASELINE = 828  # 2026-11-17, v0.4.4 U1+U2 memory screen (was 1139 at the v0.4.3-rc1 UI)


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

    def test_no_new_text_is_written_directly_in_the_ui(self):
        found = ui_literals()
        self.assertGreater(len(found), 0)  # positive control: the scan sees today's literals
        self.assertLessEqual(len(found), LITERAL_BASELINE, "move new UI text to i18n keys")

    def test_the_new_product_name_is_not_in_the_texts(self):
        words = re.compile("(?!)")  # words withheld: checked by hash in a later commit
        for table in (en.STRINGS, ko.STRINGS):
            for value in table.values():
                for form in (value.values() if isinstance(value, dict) else [value]):
                    self.assertIsNone(words.search(form))


if __name__ == "__main__":
    unittest.main()
