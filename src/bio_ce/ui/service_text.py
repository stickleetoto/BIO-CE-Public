# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Service messages in the app's language (v0.4.4 U5).

The services (store, control file, importer, connections, policy) explain refusals and failures in English, and
the MCP server passes those texts to AI tools, which must keep reading English. The screens show some of them
(``str(exc)``, a policy or importer reason). ``say(text)`` gives such a text in the app's language: in English the
text itself; in Korean the translation of the template it matches, with its values filled in. A text no template
matches is shown as it is. ``tests/unit/test_service_text.py`` checks that every message a screen can show has a
template (or is listed as never shown).

Decision (2026-11-17, logged): the screen side translates, instead of reason codes in every service, so the
services and the MCP replies stay as they are.
"""

from __future__ import annotations

import re

from bio_ce.ui.i18n import language, t

# (English template with {name} placeholders, text key). The English template is the service text exactly.
TEMPLATES: tuple[tuple[str, str], ...] = (
)

_compiled: list[tuple[re.Pattern[str], str]] | None = None


def _pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{\w+\})", template)
    regex = "".join(f"(?P<{part[1:-1]}>.+?)" if re.fullmatch(r"\{\w+\}", part) else re.escape(part)
                    for part in parts)
    return re.compile(regex + r"\Z", re.DOTALL)


def _templates() -> list[tuple[re.Pattern[str], str]]:
    global _compiled
    if _compiled is None:
        _compiled = [(_pattern(template), key) for template, key in TEMPLATES]
    return _compiled


def translate(text: str) -> str | None:
    """The text in the app's language when a template matches it, else None."""
    for pattern, key in _templates():
        match = pattern.match(text)
        if match:
            return t(key, **match.groupdict())
    return None


def say(text: object) -> str:
    """A service message (or exception) as the screens show it: in the app's language where BIO CE knows it."""
    value = str(text)
    if language() == "en" or not value:
        return value
    whole = translate(value.strip())
    if whole is not None:
        return whole
    # Messages joined by the screens ("reason; reason") or followed by a second sentence the service added.
    pieces = [translate(piece.strip()) or piece.strip() for piece in value.split("; ")]
    return "; ".join(pieces)
