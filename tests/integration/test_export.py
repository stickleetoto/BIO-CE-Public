# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 D: exporting memories as "[date] - content" (synthetic data only)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from bio_ce.auto_memory import AUTO_SOURCE_TYPE
from bio_ce.control_store import ControlStore, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.exporter import ExportOptions, ExportRefused, build_export, export_line, write_export
from bio_ce.importer import EXISTS, ImportPlanner, ImportService, parse_text
from bio_ce.inbox import discard_inbox_items
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


GENERAL = MemoryScope("bio-ce-personal", "default")
GENERAL_INBOX = MemoryScope("bio-ce-personal", "default.inbox")
USER = SourceProvenance("user-entered", "test")
HOST = SourceProvenance(AUTO_SOURCE_TYPE, "codex:test", {"host": "codex"})
NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def imported(source: str, **dates) -> SourceProvenance:
    return SourceProvenance("user-imported", f"import:{source}", {"import_source": source, **dates})


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-export-")
        self.folder = Path(self.temp.name)
        self.database = self.folder / "data" / "memories.sqlite3"
        self.store = SQLiteMemoryStore(self.database)
        self.control = ControlStore(control_database_for(self.database))
        self.control.set_personal_enabled(True)
        self.alpha = self.control.create_space("Alpha")
        self.spaces = (*self.control.spaces(), PERSONAL_SPACE)

    def tearDown(self) -> None:
        self.store.close()
        self.control.close()
        self.temp.cleanup()

    def export(self, *space_ids: str, personal_allowed: bool = True, **options) -> list[str]:
        result = build_export(self.store, self.spaces, ExportOptions(space_ids, **options),
                              personal_allowed=personal_allowed, now=NOW)
        return [line for line in result.text.splitlines() if line.startswith("[")]

    def test_dates_follow_the_rules_for_made_and_imported_memories(self):
        made = self.store.add(GENERAL, title="Editor", content="The user edits in helix.", source=USER,
                              recorded_at="2024-05-01T09:00:00Z")
        self.store.revise(GENERAL, made.memory_id, expected_revision_id=made.revision_id, title="Editor",
                          content="The user edits in helix with a dark theme.", source=USER,
                          recorded_at="2026-01-02T09:00:00Z")
        self.store.add(GENERAL, title="Tea", content="Likes tea.", source=imported("chatgpt", said_at="2023-03-04",
                                                                                  claimed_date="2025-06-30"))
        self.store.add(GENERAL, title="Rain", content="Likes rain.", source=imported("claude", said_at="2023-03",
                                                                                    said_at_precision="month"))
        self.store.add(GENERAL, title="Jazz", content="Likes jazz.", source=imported("other",
                                                                                    claimed_date="2025-06-30"))
        lines = self.export("general")
        self.assertIn("[2024-05-01] - Editor: The user edits in helix with a dark theme.", lines)  # first save, latest text
        self.assertIn("[2023-03-04] - Tea: Likes tea.", lines)  # said_at, not the claimed date
        self.assertIn("[2023-03] - Rain: Likes rain.", lines)
        self.assertIn("[unknown] - Jazz: Likes jazz.", lines)  # a claimed date is not used as the date
        claimed = self.export("general", include_claimed=True)
        self.assertIn("[unknown] - Jazz: Likes jazz. (claimed 2025-06-30)", claimed)
        self.assertIn("[2023-03-04] - Tea: Likes tea.", claimed)  # confirmed: no tail

    def test_filters_for_spaces_stage_sources_and_dates(self):
        self.store.add(GENERAL, title="Units", content="Prefers metric units.", source=USER,
                       recorded_at="2025-02-01T00:00:00Z")
        self.store.add(GENERAL, title="Hosted", content="Deploys with a script.", source=HOST,
                       recorded_at="2025-03-01T00:00:00Z")
        self.store.add(GENERAL, title="Tea", content="Likes tea.", source=imported("chatgpt", said_at="2025-04-02"))
        self.store.add(GENERAL_INBOX, title="Inbox note", content="Maybe likes chess.", source=HOST,
                       recorded_at="2025-05-01T00:00:00Z")
        self.store.add(self.alpha.curated, title="Alpha", content="Alpha builds nightly.", source=USER,
                       recorded_at="2025-06-01T00:00:00Z")
        self.assertEqual(len(self.export("general")), 3)
        self.assertEqual(len(self.export("general", include_inbox=True)), 4)
        self.assertEqual(len(self.export("general", self.alpha.space_id)), 4)
        self.assertEqual(self.export("general", sources=frozenset({"chatgpt"})), ["[2025-04-02] - Tea: Likes tea."])
        self.assertEqual(self.export("general", sources=frozenset({"ai_host"})),
                         ["[2025-03-01] - Hosted: Deploys with a script."])
        self.assertEqual(len(self.export("general", sources=frozenset({"user"}))), 1)
        ranged = self.export("general", self.alpha.space_id, date_from="2025-03-01", date_to="2025-04-30")
        self.assertEqual(sorted(ranged), ["[2025-03-01] - Hosted: Deploys with a script.",
                                          "[2025-04-02] - Tea: Likes tea."])
        with self.assertRaises(ExportRefused):
            self.export()
        with self.assertRaises(ExportRefused):
            self.export("general", sources=frozenset())

    def test_personal_needs_the_users_tick_and_retracted_or_unsorted_items_never_leave(self):
        self.store.add(PERSONAL_SPACE.curated, title="Clinic", content="The user's clinic is on Elm Street.",
                       source=USER)
        with self.assertRaises(ExportRefused):
            self.export("personal", personal_allowed=False)
        self.assertEqual(len(self.export("personal")), 1)
        gone = self.store.add(GENERAL, title="Old phone", content="The user's old phone model.", source=USER)
        self.store.retract(GENERAL, gone.memory_id, expected_revision_id=gone.revision_id, source=USER)
        dropped = self.store.add(GENERAL_INBOX, title="Dropped", content="A discarded inbox note.", source=HOST)
        discard_inbox_items(self.store, self.control, GENERAL_INBOX, [dropped.memory_id])
        self.control.enqueue_review(host="codex", connection_id=None, kind="create", title="Queued",
                                    content="A queued proposal.", review_reason="test")
        text = build_export(self.store, self.spaces, ExportOptions(("general",), include_inbox=True),
                            personal_allowed=True, now=NOW).text
        for word in ("Old phone", "discarded inbox note", "queued proposal"):
            self.assertNotIn(word, text)
        self.assertTrue(text.startswith("<!-- BIO CE export, 2026-11-20, spaces: General; stage: curated and inbox"))

    def test_title_and_content_joining(self):
        same = self.store.add(GENERAL, title="Likes tea", content="Likes tea in the morning.", source=USER)
        other = self.store.add(GENERAL, title="Morning", content="Line one.\nLine two.", source=USER)
        self.assertTrue(export_line(same, None, include_claimed=False).endswith("- Likes tea in the morning."))
        self.assertTrue(export_line(other, None, include_claimed=False).endswith("- Morning: Line one. Line two."))

    def test_never_overwrites_a_file(self):
        target = self.folder / "export.md"
        write_export(target, "first")
        with self.assertRaises(ExportRefused):
            write_export(target, "second")
        self.assertEqual(target.read_text(encoding="utf-8"), "first")

    def test_exported_file_imported_back_is_all_already_there(self):
        self.store.add(GENERAL, title="Units", content="Prefers metric units.", source=USER)
        self.store.add(GENERAL, title="Morning", content="Drinks tea every morning before work.", source=USER)
        self.store.add(GENERAL, title="Jazz", content="Likes jazz.", source=imported("claude",
                                                                                     claimed_date="2025-01-01"))
        target = write_export(self.folder / "roundtrip.md", build_export(
            self.store, self.spaces, ExportOptions(("general",), include_claimed=True), personal_allowed=True,
            now=NOW).text)
        parsed = parse_text(target.read_text(encoding="utf-8"))
        self.assertEqual(len(parsed.entries), 3)
        self.assertEqual(len(parsed.source_notes), 1)  # the header comment is a note, not a memory
        jazz = next(entry for entry in parsed.entries if entry.content == "Jazz: Likes jazz.")
        self.assertEqual(jazz.claimed_date, "2025-01-01")
        preview = ImportPlanner(self.store, self.spaces).preview(parsed, source="other", destination="general")
        self.assertEqual([item.state for item in preview.items], [EXISTS] * 3)
        self.assertFalse(preview.ready())
        with self.assertRaises(Exception):
            ImportService(self.store, self.control, self.spaces).commit(preview)


if __name__ == "__main__":
    unittest.main()
