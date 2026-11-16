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
from bio_ce.curation import (
    MERGE,
    PROMOTE,
    UPDATE_EXISTING,
    CurationError,
    CurationService,
    kept_scope,
    merge_draft,
    merge_extras,
)
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
        # v0.4.4 §9.1: the draft is the most detailed item, not all sentences joined; the rest is offered apart.
        self.assertEqual(suggestion.draft_content, "The team deploys on Fridays. Hotfixes can ship any day.")
        self.assertEqual(merge_extras(self.service.originals(suggestion), suggestion.draft_content),
                         ["Releases need a tag."])
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

    def test_items_that_only_share_their_opening_words_are_not_merged(self):
        """GUI check C (2026-11-15): imported memories all start alike ("사용자는 …"), and two different facts
        (morning running, tabs over spaces) were suggested as one. Positive control: a real repeat still merges."""
        lines = ("시험용: 사용자는 아침에 30분 달리기를 한다.", "시험용: 사용자는 탭보다 스페이스를 선호한다.",
                 "시험용: 사용자는 회의록을 마크다운으로 쓴다.", "시험용: 사용자는 주말에 자전거를 탄다.",
                 "시험용: 사용자는 한국어 답변을 선호한다.")
        for line in lines:
            self.inbox(line, line)  # imported items: the title is the text
        self.assertEqual(self.service.find(now=NOW), 0, [s.memory_ids for s in self.service.suggestions()])
        self.inbox("시험용: 사용자는 매일 아침 30분 달리기를 한다.", "시험용: 사용자는 매일 아침 30분 달리기를 한다.")
        self.assertEqual(self.service.find(now=NOW), 1)
        (suggestion,) = self.service.suggestions()
        self.assertEqual(suggestion.action, MERGE)
        self.assertIn("달리기", suggestion.draft_content)
        self.assertNotIn("스페이스", suggestion.draft_content)

    def test_an_item_that_only_shares_its_opening_words_does_not_suggest_an_update(self):
        self.store.add(PERSONAL_SPACE.curated, title="사용자는 탭보다 스페이스를 선호한다.",
                       content="사용자는 탭보다 스페이스를 선호한다.", source=SourceProvenance("user-entered", "test"))
        for line in ("사용자는 다크 테마를 선호한다.", "사용자는 한국어 답변을 선호한다."):  # scored 0.75 and 0.62
            self.inbox(line, line, scope=PERSONAL_SPACE.inbox)
        self.assertEqual(self.service.find(now=NOW), 0, [s.action for s in self.service.suggestions()])
        self.inbox("사용자는 코드에서 탭보다 스페이스 네 칸을 선호한다.", "사용자는 코드에서 탭보다 스페이스 네 칸을 선호한다.",
                   scope=PERSONAL_SPACE.inbox)
        self.assertEqual(self.service.find(now=NOW), 1)  # positive control: an item that adds to it is suggested
        (suggestion,) = self.service.suggestions()
        self.assertEqual(suggestion.action, UPDATE_EXISTING)

    # Undo (owner request 2026-11-15: approving never deletes the originals; a wrong approval can be undone) -----

    def kept(self, scope: MemoryScope = INBOX) -> list[str]:
        return sorted(revision.memory_id for revision in self.store.list_current(kept_scope(scope), limit=100))

    def test_a_merge_keeps_the_originals_and_undo_brings_everything_back(self):
        old = self.inbox("Deploys", "The team deploys on Fridays. Releases need a tag.", recorded=day(2))
        new = self.inbox("Deploys", "The team deploys on Fridays.", recorded=day(1))
        self.service.find(now=NOW)
        (suggestion,) = self.service.suggestions()
        merged = self.service.approve(suggestion.proposal_id, content="WRONG MERGE")
        self.assertEqual(merged.memory_id, new.memory_id)
        self.assertEqual(self.titles(INBOX), ["Deploys"])  # one item in the inbox ...
        self.assertEqual(self.kept(), [old.memory_id])  # ... and the other kept aside, not deleted
        self.assertEqual(self.store.read(kept_scope(INBOX), old.memory_id).revision_id, old.revision_id)
        self.assertEqual(self.service.result_of(INBOX, new.memory_id), suggestion.proposal_id)

        restored = self.service.undo(suggestion.proposal_id)
        self.assertEqual(self.kept(), [])
        now_old = self.store.read(INBOX, old.memory_id)
        now_new = self.store.read(INBOX, new.memory_id)
        self.assertEqual((now_old.revision_id, now_old.content), (old.revision_id, old.content))  # untouched
        self.assertEqual((now_new.title, now_new.content), (new.title, new.content))  # its text before the merge
        self.assertEqual(restored.memory_id, new.memory_id)
        self.assertEqual(len(self.store.history(INBOX, new.memory_id)), 3)  # the wrong merge stays in History
        self.assertEqual(self.control.curation_proposal(suggestion.proposal_id)["status"], "rejected")
        self.assertEqual(self.service.find(now=NOW), 0)  # an undone suggestion is not made again

    def test_undoing_an_update_restores_the_memory_and_the_inbox_item(self):
        current = self.store.add(GENERAL, title="Coffee", content="The user drinks two cups of coffee every morning.",
                                 source=SourceProvenance("user-entered", "test"))
        item = self.inbox("Coffee", "The user now drinks one cup of coffee every morning and green tea after lunch.")
        self.service.find(now=NOW)
        (suggestion,) = self.service.suggestions()
        self.service.approve(suggestion.proposal_id, content="WRONG UPDATE")
        self.assertEqual(self.store.read(GENERAL, current.memory_id).content, "WRONG UPDATE")
        self.assertEqual(self.kept(), [item.memory_id])
        self.assertEqual(self.service.result_of(GENERAL, current.memory_id), suggestion.proposal_id)
        self.service.undo(suggestion.proposal_id)
        self.assertEqual(self.store.read(GENERAL, current.memory_id).content, current.content)
        self.assertEqual(self.store.read(INBOX, item.memory_id).revision_id, item.revision_id)
        self.assertEqual(self.kept(), [])

    def test_undoing_a_keep_retracts_the_new_memory_and_restores_the_items(self):
        first = self.inbox("Tabs", "The user prefers tabs over spaces in Go code.", recorded=day(5))
        again = self.inbox("Tabs", "The user prefers tabs over spaces in Go code.", recorded=day(1))
        self.service.find(now=NOW)
        (suggestion,) = self.service.suggestions()
        kept = self.service.approve(suggestion.proposal_id)
        self.assertEqual(self.titles(GENERAL), ["Tabs"])
        self.service.undo(suggestion.proposal_id)
        self.assertEqual(self.titles(GENERAL), [])  # retracted (hidden everywhere) ...
        self.assertIn(kept.memory_id, [row[0] for row in self.store.inventory()])  # ... but not deleted
        self.assertEqual(self.titles(INBOX), ["Tabs", "Tabs"])
        self.assertEqual({self.store.read(INBOX, m.memory_id).revision_id for m in (first, again)},
                         {first.revision_id, again.revision_id})

    def test_undo_changes_nothing_when_the_result_was_edited_afterwards(self):
        current = self.store.add(GENERAL, title="Coffee", content="The user drinks two cups of coffee every morning.",
                                 source=SourceProvenance("user-entered", "test"))
        self.inbox("Coffee", "The user now drinks one cup of coffee every morning and green tea after lunch.")
        self.service.find(now=NOW)
        (suggestion,) = self.service.suggestions()
        updated = self.service.approve(suggestion.proposal_id)
        edited = self.store.revise(GENERAL, current.memory_id, expected_revision_id=updated.revision_id,
                                   title="Coffee", content="Edited by the user later.",
                                   source=SourceProvenance("user-entered", "bio-ce-desktop"))
        self.assertIsNone(self.service.result_of(GENERAL, current.memory_id))
        with self.assertRaises(CurationError):
            self.service.undo(suggestion.proposal_id)
        self.assertEqual(self.store.read(GENERAL, current.memory_id).revision_id, edited.revision_id)
        self.assertEqual(len(self.kept()), 1)  # still kept aside, nothing moved

    def test_kept_originals_are_out_of_sight_and_never_expire(self):
        a = self.inbox("Deploys", "The team deploys on Fridays after the stand-up.")
        b = self.inbox("Deploys", "The team deploys on Fridays after the stand-up meeting.")
        self.service.find(now=NOW)
        (suggestion,) = self.service.suggestions()
        merged = self.service.approve(suggestion.proposal_id)
        aside = ({a.memory_id, b.memory_id} - {merged.memory_id}).pop()
        listed = {memory_id for memory_id, _project, _namespace, _created in self.store.inbox_items()}
        self.assertNotIn(aside, listed)  # the inbox expiry only looks at inbox items
        self.assertIn(merged.memory_id, listed)  # positive control
        self.assertEqual([hit.memory_id for hit in self.store.search(INBOX, "stand-up", limit=10)],
                         [merged.memory_id])
        with self.assertRaises(Exception):
            self.store.move(kept_scope(INBOX), GENERAL, [aside])  # kept items only go back to their inbox

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
        self.assertEqual(outcome, {"approved": 2, "skipped": 1,
                                   "ids": [suggestion.proposal_id for suggestion in suggestions[1:]]})
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

    def test_the_merge_draft_is_the_more_detailed_item(self):
        """GUI check K11 (2026-11-16): a merge joined both sentences. Now the one that says more is the draft, and
        a sentence only the other has is offered apart (none here: the shorter says nothing the longer doesn't)."""
        short = self.inbox("회의록", "시험용: 사용자는 회의록을 마크다운으로 쓴다.", recorded=day(1))
        long = self.inbox("회의록", "시험용: 사용자는 회의록을 마크다운으로 쓰고 매주 금요일에 팀과 공유한다.", recorded=day(2))
        title, content = merge_draft([short, long])
        self.assertEqual(content, long.content)  # older but more detailed
        self.assertEqual(merge_extras([short, long], content), [])
        title, content = merge_draft([long, short])  # order doesn't matter
        self.assertEqual(content, long.content)

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
