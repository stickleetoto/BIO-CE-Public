# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Text shown to the user, by key, in English or Korean (v0.4.4 U0).

``t("key", name=value)`` returns the current language's text with ``{name}`` filled in. A text that depends on a
count is a dict of forms, ``{"one": …, "other": …}``; pass ``count=`` and the form is chosen (Korean has only
``other``). A key missing in Korean falls back to English, and a key missing in both returns the key itself, so a
gap shows up on screen instead of failing; the tests make every key present in both languages.

Only the desktop app's text goes through here. What AI hosts read stays English and is not translated: MCP tool
names and descriptions, server instructions, the memory skill, and session-hook context.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from bio_ce.ui.i18n import en, ko

LANGUAGES = {"en": en.STRINGS, "ko": ko.STRINGS}
NAMES = {"en": "English", "ko": "한국어"}
AUTO = "auto"

_current = "en"


def detect_language() -> str:
    """The Windows display language: "ko" for Korean, otherwise "en". ``BIO_CE_UI_LANGUAGE`` (en or ko) overrides it,
    for support and for tests that must not depend on the PC's language."""
    forced = os.environ.get("BIO_CE_UI_LANGUAGE", "").strip().lower()
    if forced in LANGUAGES:
        return forced
    if sys.platform != "win32":
        return "en"
    chosen = setup_language()
    if chosen is not None:
        return chosen
    try:
        import ctypes

        language_id = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    except Exception:  # noqa: BLE001 - no Windows API: English
        return "en"
    return "ko" if language_id & 0x3FF == 0x12 else "en"


SETUP_LANGUAGE_KEY = r"Software\BIO CE"  # HKCU; the installer writes InstallLanguage (v0.4.4)
_SETUP_LANGUAGES = {"korean": "ko", "english": "en"}


def setup_language() -> str | None:
    """The language chosen in the installer ("ko" or "en"), or None: what "auto" uses before the Windows language,
    so the app first speaks the language the user picked in setup. Reads only."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETUP_LANGUAGE_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, "InstallLanguage")
    except OSError:
        return None
    return _SETUP_LANGUAGES.get(str(value).strip().lower())


def resolve(choice: str | None) -> str:
    """A saved choice ("auto", "en", "ko", or nothing) as the language to show."""
    if choice in LANGUAGES:
        return str(choice)
    return detect_language()


def set_language(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else "en"


def language() -> str:
    return _current


def _form(value: Any, count: Any) -> str:
    if isinstance(value, dict):
        if count is not None and "one" in value and count == 1:
            return value["one"]
        return value.get("other") or next(iter(value.values()))
    return value


def t(key: str, **values: Any) -> str:
    """The text for ``key`` in the current language, with ``{name}`` placeholders filled in."""
    value = LANGUAGES[_current].get(key)
    if value is None:
        value = en.STRINGS.get(key)
    if value is None:
        return key
    text = _form(value, values.get("count"))
    return text.format(**values) if values else text


__all__ = ["AUTO", "LANGUAGES", "NAMES", "detect_language", "language", "resolve", "set_language", "t"]
