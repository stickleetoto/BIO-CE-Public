# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""English text of the desktop app, by key. Every key here is also in ``ko.py`` (tests check)."""

STRINGS: dict[str, object] = {
    # Navigation
    "nav.dashboard": "Dashboard",
    "nav.memories": "Memories",
    "nav.connections": "Connections",
    "nav.settings": "Settings",
    # Spaces (display names; hosts keep the machine names "General" and "Personal")
    "space.general": "General",
    "space.personal": "Personal",
    "space.all": "All spaces",
    # Common words
    "common.cancel": "Cancel",
    "common.close": "Close",
    "common.save": "Save",
    "common.undo": "Undo",
    "common.items": {"one": "{count} item", "other": "{count} items"},
    "common.memories": {"one": "{count} memory", "other": "{count} memories"},
    # Settings: language
    "settings.language.title": "Language",
    "settings.language.auto": "Same as Windows",
    "settings.language.note": "The text of this app. What AI apps read from BIO CE stays in English.",
    # Settings: automatic backups
    "settings.backups.keep": "Keep the latest {count} automatic backups",
}
