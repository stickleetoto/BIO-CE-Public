# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 U5: every service message a screen can show has a Korean template (src/bio_ce/ui/service_text.py), and
the English stays exactly what the service says (MCP replies and the English app are unchanged)."""

from __future__ import annotations

import re
import unittest

from bio_ce.ui import i18n, service_text
from bio_ce.ui.i18n import en, ko
from tests.i18n_glossary import violations
from tests.service_messages import service_messages

# Files whose messages never reach a screen as they are, with the reason.
# sqlite_store.py and models.py are not listed whole: quick add shows str(ValidationError) and several screens show
# str(exc) of any exception, so their messages a user can cause have templates; the programming checks are below.
NOT_SHOWN_FILES = {
    "contract.py": "engine contract checks between modules (EngineProtocolError at engine registration)",
    "demo_fixture.py": "the synthetic CLI demo",
}
_PROGRAMMING = "a programming check: the app always passes a valid value here, so no user action can cause it"
# Single messages that never reach a screen, with the reason.
NOT_SHOWN: dict[str, str] = {
    "interrupted for the test": "a test hook in the importer",
    "Community Engine": "an engine's product name: not translated (glossary §3)",
    "BIO Core": "an engine's product name: not translated (glossary §3)",
    # connections.py, control_store.py, inbox.py, community.py
    "host must be codex or claude": _PROGRAMMING + " (the host comes from the app's own host list)",
    "mode must be one of {v1}": _PROGRAMMING + " (the mode comes from the app's radio buttons)",
    "save_mode must be one of {v1}": _PROGRAMMING + " (the saving mode comes from the app's choices)",
    "a connection must be bound to a project and namespace": _PROGRAMMING,
    "invalid review status": _PROGRAMMING,
    "invalid clean-up status": _PROGRAMMING,
    "invalid suggestion status": _PROGRAMMING,
    "a new discard is either pending or being cleaned up": _PROGRAMMING,
    "unknown setting": _PROGRAMMING + " (the setting keys are the app's own)",
    "the app language is auto, en, or ko": _PROGRAMMING + " (the language comes from the Settings choices)",
    "{v0} is one of {v2}": _PROGRAMMING + " (the memory screen's saved view uses its own values)",
    "inbox items are discarded, not forgotten": _PROGRAMMING + " (Forget completely is offered for memories only)",
    "the Community Engine returned an unknown write status": _PROGRAMMING + " (an engine's internal result)",
    "a Community session needs a Community engine binding": _PROGRAMMING + " (MCP server sessions only)",
    # importer.py, backup.py
    "source must be chatgpt, claude, or other": _PROGRAMMING + " (the source comes from the import radio buttons)",
    "keep at least one automatic backup": _PROGRAMMING + " (the control file allows 1 to 100 before this)",
    # models.py: identifiers, timestamps and source metadata are made by BIO CE, not typed by the user
    "memory_id must use mem_ followed by 8-96 safe characters": _PROGRAMMING + " (BIO CE makes the IDs)",
    "revision_id must use rev_ followed by a SHA-256 digest": _PROGRAMMING + " (BIO CE makes the IDs)",
    "{v0} must include a UTC offset": _PROGRAMMING + " (BIO CE makes the timestamps)",
    "{v0} must be an ISO-8601 timestamp": _PROGRAMMING + " (BIO CE makes the timestamps)",
    "{v0} must be text": _PROGRAMMING + " (the screens pass text)",
    "source metadata must be finite JSON data": _PROGRAMMING + " (BIO CE writes the source metadata)",
    "source metadata exceeds 4096 characters": _PROGRAMMING + " (BIO CE writes the source metadata)",
    # sqlite_store.py
    "scope must be a MemoryScope": _PROGRAMMING,
    "valid_until must be later than valid_from": _PROGRAMMING + " (no screen sets validity dates)",
    "scope and source must use BIO CE model types": _PROGRAMMING,
    "limit must be an integer from 1 to 500": _PROGRAMMING,
    "offset must be a non-negative integer": _PROGRAMMING,
    "limit must be an integer from 1 to 50": _PROGRAMMING,
    "memory_ids must be a sequence of IDs": _PROGRAMMING,
    "read_many requires between 1 and 100 memory IDs": _PROGRAMMING,
    "a read-only store cannot prepare a database replacement": _PROGRAMMING + " (the app's store is writable)",
    "an in-memory database cannot be opened read-only": _PROGRAMMING,
    "only inbox items (and inbox items kept for an undo) can be physically deleted; curated memories are retracted":
        _PROGRAMMING + " (Discard is offered for inbox items only)",
    "inbox items are discarded with purge(); erase() is for curated memories": _PROGRAMMING,
    "kept items move only between an inbox and its own kept area": _PROGRAMMING,
    "a move keeps the stage: curated to curated, inbox to inbox": _PROGRAMMING,
    "memory_id already exists": _PROGRAMMING + " (BIO CE makes new IDs)",
}


def sample(text: str) -> str:
    """The text with every filled-in part as "X": {v1} in a collected message, {host} in a template."""
    return re.sub(r"\{\w*\}", "X", text)


class ServiceTextTests(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_language("en")

    def test_every_message_a_screen_can_show_has_a_korean_template(self):
        i18n.set_language("ko")
        missing = []
        for name, line, text in service_messages():
            if name in NOT_SHOWN_FILES or text in NOT_SHOWN:
                continue
            if service_text.translate(sample(text)) is None:
                missing.append(f"{name}:{line}: {text}")
        newline = chr(10)
        self.assertEqual(missing, [], f"{len(missing)} without a template:{newline}" + newline.join(missing))

    def test_the_english_templates_are_the_english_texts(self):
        for template, key in service_text.TEMPLATES:
            with self.subTest(key):
                self.assertIn(key, en.STRINGS)
                self.assertIn(key, ko.STRINGS)
                self.assertEqual(en.STRINGS[key], template)
                self.assertEqual(set(re.findall(r"\{(\w+)\}", template)),
                                 set(re.findall(r"\{(\w+)\}", ko.STRINGS[key])))

    def test_english_shows_the_service_text_itself_and_korean_fills_the_values(self):
        template, key = next((pair for pair in service_text.TEMPLATES if "{" in pair[0]), service_text.TEMPLATES[0])
        text = sample(template).replace("X", "42")
        self.assertEqual(service_text.say(text), text)  # English: unchanged
        i18n.set_language("ko")
        said = service_text.say(text)
        self.assertNotEqual(said, text)
        if "{" in template:
            self.assertIn("42", said)

    def test_positive_control_an_unknown_message_is_reported_and_shown_as_it_is(self):
        i18n.set_language("ko")
        self.assertIsNone(service_text.translate("A message BIO CE has never seen."))
        self.assertEqual(service_text.say("A message BIO CE has never seen."), "A message BIO CE has never seen.")

    def test_reasons_a_screen_joins_are_translated_one_by_one(self):
        joined = "mentions credentials or sensitive identifiers; A message BIO CE has never seen."
        self.assertEqual(service_text.say(joined), joined)
        i18n.set_language("ko")
        self.assertEqual(service_text.say(joined),
                         ko.STRINGS["svc.policy.credentials"] + "; A message BIO CE has never seen.")

    def test_a_narrower_template_wins_over_a_wider_one(self):
        i18n.set_language("ko")
        said = service_text.say("BIO CE could not update Codex's tool approvals in config.toml; it was left unchanged.")
        self.assertEqual(said, ko.STRINGS["svc.conn.approvals_failed"].format(host="Codex", file="config.toml"))
        said = service_text.say("BIO CE could not confirm that Codex's settings were restored. A copy is in C.toml.")
        self.assertEqual(said, ko.STRINGS["svc.conn.codex_restore_copy"].format(path="C.toml"))

    def test_the_korean_service_texts_follow_the_glossary(self):
        keys = {key for _template, key in service_text.TEMPLATES}
        self.assertEqual(violations({k: en.STRINGS[k] for k in keys}, {k: ko.STRINGS[k] for k in keys}), [])


if __name__ == "__main__":
    unittest.main()
