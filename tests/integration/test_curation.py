# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 C: sorting suggestions for the inbox (merge, promote, update a memory) and bulk decisions.

Synthetic data only. Each "no suggestion" check has a positive control that does produce one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from bio_ce.control_store import ControlStore, ControlStoreError, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.curation import MERGE, PROMOTE, UPDATE_EXISTING, CurationError, CurationService, merge_draft
from bio_ce.importer import ImportPlanner, ImportService, parse_text
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


GENERAL = MemoryScope("bio-ce-personal", "default")
INBOX = MemoryScope("bio-ce-personal", "default.inbox")
HOST = SourceProvenance("ai-host-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def day(offset: int) -> str:
    return (NOW - timedelta(days=offset)).isoformat().replace("+00:00", "Z")


class CurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-curation-")
        self.database = Path(self.temp.name) / "data" / "memories.sqlite3"
        self.store = SQLiteMemoryStore(self.database)
        self.control = ControlStore(control_database_for(self.database))
        self.control.set_personal_enabled(True)
        self.spaces = (*self.control.spaces(), PERSONAL_SPACE)
        self.service = CurationService(self.store, self.control, self.spaces)

    def tearDown(self) -> None:
        self.store.close()
        self.control.close()
        self.temp.cleanup()

    def inbox(self, title: str, content: str, *, recorded: str | None = None, scope: MemoryScope = INBOX):
        revision = self.store.add(scope, title=title, content=content, source=HOST, recorded_at=recorded or day(1))
        self.control.inbox_seen(revision.memory_id)
        return revision

    def titles(self, scope: MemoryScope) -> list[str]:
        return sorted(revision.title for revision in self.store.list_current(scope, limit=100))

    def test_near_identical_items_are_merged_into_the_newest(self):
        old = self.inbox("Deploys", "The team deploys on Fridays. Releases need a tag.", recorded=day(2))
        mid = self.inbox("Deploys", "The team deploys on Fridays. Hotfixes can ship any day.", recorded=day(1))
        new = self.inbox("Deploys", "The team deploys on Fridays.", recorded=day(1))
        other = self.inbox("Editor", "The user edits Python in helix with a dark theme.")
        self.assertEqual(self.service.find(now=NOW), 1)
        (suggestion,) = self.service.suggestions()
        self.assertEqual(suggestion.action, MERGE)
        self.assertEqual(set(suggestion.memory_ids), {old.memory_id, mid.memory_id, new.memory_id})
        self.assertNotIn(other.memory_id, suggestion.memory_ids)
        self.assertEqual(suggestion.draft_content.count("The team deploys on Fridays."), 1)
        self.assertIn("Releases need a tag.", suggestion.draft_content)
        self.assertIn("Hotfixes can ship any day.", suggestion.draft_content)
        merged = self.service.approve(suggestion.proposal_id)
        self.assertEqual(merged.memory_id, suggestion.memory_ids[0])
        self.assertEqual(self.titles(INBOX), ["Deploys", "Editor"])
        self.assertEqual(len(merged.source.metadata["merged_from"]), 2)
        self.assertEqual(self.control.curation_proposals(), ())

    def test_the_same_text_on_different_days_is_suggested_for_keeping(self):
        first = self.inbox("Tabs", "The user prefers tabs over spaces in Go code.", recorded=day(5))
        again = self.inbox("Tabs", "The user prefers tabs over spaces in Go code.", recorded=day(1))
        self.assertEqual(self.service.find(now=NOW), 1)
        (suggestion,) = self.service.suggestions()
        self.assertEqual(suggestion.action, PROMOTE)
        kept = self.service.approve(suggestion.proposal_id)
        self.assertEqual(kept.scope, GENERAL)
        self.assertEqual(sorted(kept.source.metadata["from_inbox"]), sorted([first.memory_id, again.memory_id]))
        self.assertEqual(self.titles(INBOX), [])
        self.assertEqual(self.titles(GENERAL), ["Tabs"])

    def test_items_used_often_for_a_week_are_suggested_for_keeping(self):
        used = self.inbox("Cycling", "The user cycles to work on weekdays along the river path.")
        once = self.inbox("Ramen", "The user likes miso ramen with extra corn and butter.")
        self.control.touch_inbox([used.memory_id])
        self.control.touch_inbox([used.memory_id])
        self.control.touch_inbox([once.memory_id])
        self.assertEqual(self.service.find(now=datetime.now(timezone.utc)), 0)  # too early: not a week yet
        self.assertEqual(self.service.find(now=datetime.now(timezone.utc) + timedelta(days=8)), 1)
        (suggestion,) = self.service.suggestions()
        self.assertEqual((suggestion.action, suggestion.memory_ids), (PROMOTE, (used.memory_id,)))

    def test_an_item_close_to_a_memory_suggests_updating_it(self):
        current = self.store.add(GENERAL, title="Coffee", content="The user drinks two cups of coffee every morning.",
                                 source=SourceProvenance("user-entered", "test"))
        item = self.inbox("Coffee", "The user now drinks one cup of coffee every morning and green tea after lunch.")
        self.assertEqual(self.service.find(now=NOW), 1)
        (suggestion,) = self.service.suggestions()
        self.assertEqual((suggestion.action, suggestion.target[0]), (UPDATE_EXISTING, current.memory_id))
        updated = self.service.approve(suggestion.proposal_id, content="The user drinks one cup of coffee every "
                                       "morning and green tea after lunch.")
        self.assertEqual(updated.memory_id, current.memory_id)
        self.assertEqual(len(self.store.history(GENERAL, current.memory_id)), 2)
        self.assertEqual(updated.source.metadata["from_inbox"], [item.memory_id])
        self.assertEqual(self.titles(INBOX), [])

    def test_rejected_groups_are_not_suggested_again_and_changed_items_go_stale(self):
        self.inbox("Deploys", "The team deploys on Fridays after the stand-up.")
        changed = self.inbox("Deploys", "The team deploys on Fridays after the stand-up meeting.")
        self.service.find(now=NOW)
        (first,) = self.service.suggestions()
        self.service.reject(first.proposal_id)
        self.assertEqual(self.service.find(now=NOW), 0)
        with self.assertRaises(ControlStoreError):
            self.service.reject(first.proposal_id)
        self.inbox("Lunch", "The user eats lunch at noon with the platform team.")
        self.inbox("Lunch", "The user eats lunch at noon with the platform team daily.")
        self.assertEqual(self.service.find(now=NOW), 1)  # positive control: a new group is suggested
        (second,) = self.service.suggestions()
        lunch = second.memory_ids[0]
        self.store.revise(INBOX, lunch, expected_revision_id=second.items[0][1], title="Lunch",
                          content="The user skips lunch on Mondays.", source=HOST)
        with self.assertRaises(CurationError):
            self.service.approve(second.proposal_id)
        self.assertEqual(self.control.curation_proposal(second.proposal_id)["status"], "stale")
        self.assertIn("The user skips lunch on Mondays.",
                      [r.content for r in self.store.list_current(INBOX, limit=10)])
        self.assertTrue(changed.memory_id)

    def test_bulk_approval_counts_and_skips_stale_suggestions(self):
        for title, text in (("Plants", "The user waters the balcony plants every Sunday morning."),
                            ("Invoices", "Invoices go out to clients on the first business day of a month."),
                            ("Cat", "The cat gets dry food twice a day and wet food on weekends.")):
            self.inbox(title, text)
            self.inbox(title, text.rstrip(".") + " without fail.")
        self.assertEqual(self.service.find(now=NOW), 3)
        suggestions = self.service.suggestions()
        stale = suggestions[0]
        self.store.revise(INBOX, stale.memory_ids[0], expected_revision_id=stale.items[0][1], title="Changed",
                          content="Changed text about something else entirely.", source=HOST)
        outcome = self.service.approve_many([item.proposal_id for item in suggestions])
        self.assertEqual(outcome, {"approved": 2, "skipped": 1})
        self.assertEqual(self.service.reject_many([stale.proposal_id]), 0)  # stale is not pending

    def test_review_then_promote_an_import_keeps_claimed_dates_unconfirmed(self):
        planner = ImportPlanner(self.store, self.spaces)
        preview = planner.preview(parse_text("[2025-03-14] - The user's blood type is O.\n"
                                             "[unknown] - The user is left-handed."),
                                  source="chatgpt", destination="personal")
        batch = ImportService(self.store, self.control, self.spaces).commit(preview)
        self.inbox("Other", "Something not from this import at all.", scope=PERSONAL_SPACE.inbox)
        self.assertEqual(self.service.promote_batch(batch.batch_id), 2)
        found = self.service.suggestions(batch_id=batch.batch_id)
        self.assertEqual(len(found), 2)
        self.assertEqual(len(self.service.suggestions()), 2)  # the other item was not suggested
        outcome = self.service.approve_many([item.proposal_id for item in found])
        self.assertEqual(outcome["approved"], 2)
        kept = {r.content: r.source.metadata for r in self.store.list_current(PERSONAL_SPACE.curated, limit=10)}
        blood = kept["The user's blood type is O."]
        self.assertEqual((blood["claimed_date"], blood["import_source"]), ("2025-03-14", "chatgpt"))
        self.assertNotIn("said_at", blood)  # a claimed date is never turned into a confirmed one
        refs = {r.source.source_ref for r in self.store.list_current(PERSONAL_SPACE.curated, limit=10)}
        self.assertEqual(refs, {"bio-ce-curation"})
        self.assertEqual([r.title for r in self.store.list_current(PERSONAL_SPACE.inbox, limit=10)], ["Other"])

    def test_keeping_refuses_secrets_and_copies_of_existing_memories(self):
        self.store.add(GENERAL, title="Tabs", content="The user prefers tabs over spaces in Go code.",
                       source=SourceProvenance("user-entered", "test"))
        item = self.inbox("Plan", "The user plans a trip to Jeju in May.")
        self.assertTrue(self.control.add_curation_proposal(
            action=PROMOTE, space_id="general", items=[(item.memory_id, item.revision_id)], target=None,
            draft_title="Plan", draft_content="The user plans a trip to Jeju in May.", reason="test", batch_id=None,
            signature="sig-1"))
        (suggestion,) = self.service.suggestions()
        with self.assertRaises(CurationError):
            self.service.approve(suggestion.proposal_id, content="token = " + "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
        with self.assertRaises(CurationError):
            self.service.approve(suggestion.proposal_id, title="Tabs",
                                 content="The user prefers tabs over spaces in Go code.")
        self.assertEqual(self.control.curation_proposal(suggestion.proposal_id)["status"], "stale")
        self.assertEqual(self.titles(INBOX), ["Plan"])  # nothing was removed

    def test_merge_draft_and_group_limit(self):
        for n in range(10):
            self.inbox("Standup", f"The team holds a standup at nine every weekday morning. Room {n}.")
        self.service.find(now=NOW)
        (suggestion,) = self.service.suggestions()
        self.assertEqual(len(suggestion.items), 8)
        revisions = [self.store.read(INBOX, memory_id) for memory_id in suggestion.memory_ids[:2]]
        title, content = merge_draft(revisions)
        self.assertEqual(title, "Standup")
        self.assertEqual(content.count("The team holds a standup at nine every weekday morning."), 1)


if __name__ == "__main__":
    unittest.main()
