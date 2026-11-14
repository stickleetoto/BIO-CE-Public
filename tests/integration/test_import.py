# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.3 B: importing memories from another AI (synthetic data only).

Covers the input formats (design R2 2.1), dates that are claimed but not trusted (12.1), source notes and
unreadable lines (12.2, REVIEW_R2 1 and 4), sensitive labels (12.3), the per-entry checks, commit in chunks of 100,
interruption and retry, undo (REVIEW_R2 2), and timing for 1,000 entries.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from bio_ce.control_store import ControlStore, ControlStoreError, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.importer import (
    BATCH_DUPLICATE,
    CONFLICT,
    EXISTS,
    INSTRUCTION,
    NEW,
    PATH_REVIEW,
    SECRET,
    TOO_LONG,
    ImportPlanner,
    ImportRejected,
    ImportService,
    make_title,
    parse_date,
    parse_text,
    read_import_file,
    same_date_warning,
)
from bio_ce.inbox import inbox_scope
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.storage.sqlite_store import SQLiteMemoryStore


GENERAL = MemoryScope("bio-ce-personal", "default")
USER = SourceProvenance("user-entered", "test")

# The shape Claude's import prompt asks another AI for, with the extras real answers add (synthetic content).
CLAUDE_PROMPT_ANSWER = """Here are the memories I have about you, formatted as requested:

```
[2025-01-12] - Prefers concise answers with code examples first.
[2025-02-03] - Works as a data engineer at a logistics startup.
[unknown] - Uses Neovim with a custom Lua config.
[2025-03] - Is learning Japanese and practices every morning.
- [2025-04-18] - Building a personal finance tracker called Ledgerly.
  It uses SQLite and a small Flask API.
[] - Prefers metric units.
```

This is the complete set of memories I have stored. I don't have any other saved details about you.
"""


class ParseTests(unittest.TestCase):
    def test_every_entry_shape_in_the_format_table(self):
        text = "\n".join([
            "[2025-03-14] - Base format entry.",
            "- [2025-03-15] - Dash list entry.",
            "* [2025-03-16] - Star list entry.",
            "1. [2025-03-17] - Numbered entry.",
            "[unknown] - Unknown date entry.",
            "[] - Empty brackets entry.",
            "[날짜 없음] - Korean no-date entry.",
            "[n/a] - Not available entry.",
            "- Plain list entry without a date.",
            "## Projects",
            "[2025-03-18] - First line of a long entry",
            "  continues on the next line.",
            "random sentence between entries",
            "[2025-03-19] - Last entry.",
        ])
        result = parse_text(text)
        contents = [entry.content for entry in result.entries]
        self.assertEqual(contents, [
            "Base format entry.", "Dash list entry.", "Star list entry.", "Numbered entry.", "Unknown date entry.",
            "Empty brackets entry.", "Korean no-date entry.", "Not available entry.",
            "Plain list entry without a date.", "First line of a long entry continues on the next line.",
            "Last entry."])
        dates = [entry.claimed_date for entry in result.entries]
        self.assertEqual(dates, ["2025-03-14", "2025-03-15", "2025-03-16", "2025-03-17", None, None, None, None, None,
                                 "2025-03-18", "2025-03-19"])
        self.assertEqual(result.entries[9].section, "Projects")
        self.assertIsNone(result.entries[0].section)
        self.assertEqual(result.unreadable, ((13, "random sentence between entries"),))
        self.assertEqual(result.source_notes, ())

    def test_ten_date_formats_and_unreadable_dates(self):
        cases = {
            "2025-03-14": ("2025-03-14", "day"), "2025/03/14": ("2025-03-14", "day"),
            "2025.03.14": ("2025-03-14", "day"), "March 14, 2025": ("2025-03-14", "day"),
            "14 Mar 2025": ("2025-03-14", "day"), "2025년 3월 14일": ("2025-03-14", "day"),
            "2025-03": ("2025-03", "month"), "2025년 3월": ("2025-03", "month"),
            "Mar 2025": ("2025-03", "month"), "2025-03-14T10:22:00Z": ("2025-03-14", "day"),
            "14th March 2025": ("2025-03-14", "day"),
        }
        for text, wanted in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_date(text), wanted)
        for text in ("2025-13-01", "someday", "1850-01-01", "unknown", "", "알 수 없음"):
            with self.subTest(text=text):
                self.assertEqual(parse_date(text), (None, None))
        (entry,) = parse_text("[sometime in spring] - Started running.").entries
        self.assertIsNone(entry.claimed_date)
        self.assertEqual(entry.date_text, "sometime in spring")  # kept as claimed_date_text on commit

    def test_claude_prompt_answer_notes_outside_the_code_block(self):
        result = parse_text(CLAUDE_PROMPT_ANSWER)
        self.assertEqual(len(result.entries), 6)
        self.assertEqual(result.entries[4].content,
                         "Building a personal finance tracker called Ledgerly. It uses SQLite and a small Flask API.")
        self.assertEqual(result.entries[3].claimed_precision, "month")
        self.assertEqual([text for _n, text in result.source_notes], [
            "Here are the memories I have about you, formatted as requested:",
            "This is the complete set of memories I have stored. I don't have any other saved details about you."])
        self.assertEqual(result.unreadable, ())

    def test_meta_lines_inside_a_list_are_source_notes_not_memories(self):
        text = "\n".join([
            "확인 범위: 저장된 기억 전체",
            "[2025-01-01] - 사용자는 아침에 운동한다.",
            "- 참고: 날짜가 없는 항목은 대화 날짜로 채웠습니다.",
            "[2025-01-02] - 사용자는 커피보다 차를 좋아한다.",
            "- Note: dates were filled in from the conversation.",
            "이상입니다.",
        ])
        result = parse_text(text)
        self.assertEqual([e.content for e in result.entries], ["사용자는 아침에 운동한다.", "사용자는 커피보다 차를 좋아한다."])
        self.assertEqual(len(result.source_notes), 4)
        self.assertEqual(result.unreadable, ())

    def test_export_tails_are_read_back(self):
        (claimed, imported) = parse_text("[unknown] - Likes tea. (claimed 2024-05-06)\n"
                                         "[2025-01-02] - Likes jazz. (imported 2026-11-20)").entries
        self.assertEqual((claimed.content, claimed.claimed_date), ("Likes tea.", "2024-05-06"))
        self.assertEqual((imported.content, imported.claimed_date), ("Likes jazz.", "2025-01-02"))

    def test_titles_and_file_reading_limits(self):
        self.assertEqual(make_title("Short one. Second sentence."), "Short one.")
        self.assertLessEqual(len(make_title("word " * 60)), 80)
        with tempfile.TemporaryDirectory() as folder:
            utf8 = Path(folder) / "a.md"
            utf8.write_bytes("\ufeff[2025-01-01] - 한글 항목".encode("utf-8"))
            self.assertEqual(read_import_file(utf8), ("[2025-01-01] - 한글 항목", "UTF-8"))
            legacy = Path(folder) / "b.txt"
            legacy.write_bytes("[2025-01-01] - 한글 항목".encode("cp949"))
            self.assertEqual(read_import_file(legacy)[1], "CP949")
            big = Path(folder) / "c.md"
            big.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
            with self.assertRaises(ImportRejected):
                read_import_file(big)
            with self.assertRaises(ImportRejected):
                read_import_file(Path(folder) / "d.json")


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-import-")
        self.database = Path(self.temp.name) / "data" / "memories.sqlite3"
        self.store = SQLiteMemoryStore(self.database)
        self.control = ControlStore(control_database_for(self.database))
        self.control.set_personal_enabled(True)
        self.alpha = self.control.create_space("Alpha")
        self.spaces = (*self.control.spaces(), PERSONAL_SPACE)
        self.planner = ImportPlanner(self.store, self.spaces, profile=r"C:\Users\someone")
        self.service = ImportService(self.store, self.control, self.spaces)

    def tearDown(self) -> None:
        self.store.close()
        self.control.close()
        self.temp.cleanup()

    def preview(self, text: str, destination: str | None = "personal", source: str = "chatgpt"):
        return self.planner.preview(parse_text(text), source=source, destination=destination)


class PreviewTests(_Fixture):
    def test_no_destination_means_nothing_can_be_imported(self):
        preview = self.preview("[2025-01-01] - Likes tea.", destination=None)
        self.assertFalse(preview.ready())
        with self.assertRaises(ImportRejected):
            self.service.commit(preview)
        self.assertEqual(self.store.inbox_items(), [])  # positive control below shows a commit does write
        self.planner.set_destination(preview, [preview.items[0].key], "personal")
        self.assertTrue(preview.ready())
        self.assertEqual(self.service.commit(preview).to_inbox, 1)

    def test_dates_are_claimed_until_the_user_confirms_them(self):
        preview = self.preview("[2025-01-01] - Likes tea.\n[unknown] - Likes jazz.\n[2025-02] - Likes rain.")
        tea, jazz, rain = preview.items
        self.assertEqual((tea.claimed_date, tea.said_at), ("2025-01-01", None))
        self.assertEqual(self.planner.confirm_dates(preview, [tea.key, jazz.key], how="preview-item"), 1)
        self.assertEqual((tea.said_at, tea.said_at_confirmed), ("2025-01-01", "preview-item"))
        self.assertIsNone(jazz.said_at)
        self.planner.set_date(preview, rain.key, "2024-12-24")
        self.assertEqual((rain.said_at, rain.said_at_confirmed), ("2024-12-24", "edited"))
        with self.assertRaises(ValueError):
            self.planner.set_date(preview, rain.key, "next week")
        result = self.service.commit(preview)
        stored = {revision.content: revision.source.metadata
                  for revision in self.store.list_current(PERSONAL_SPACE.inbox, limit=10)}
        self.assertEqual(stored["Likes tea."]["said_at"], "2025-01-01")
        self.assertNotIn("said_at", stored["Likes jazz."])
        self.assertNotIn("claimed_date", stored["Likes jazz."])
        self.assertEqual(stored["Likes jazz."]["imported_at"], self.control.import_batch(result.batch_id)["created_at"])
        self.assertEqual(stored["Likes rain."]["claimed_date"], "2025-02")
        self.assertEqual(stored["Likes rain."]["claimed_date_precision"], "month")
        self.assertEqual(stored["Likes rain."]["said_at"], "2024-12-24")
        for metadata in stored.values():
            self.assertEqual(metadata["import_source"], "chatgpt")

    def test_same_date_warning_at_twenty_and_at_half(self):
        def lines(same: int, other: int) -> str:
            rows = [f"[2025-06-30] - Same date entry number {n}." for n in range(same)]
            rows += [f"[2024-01-{n + 1:02d}] - Other date entry number {n}." for n in range(other)]
            return "\n".join(rows)

        self.assertEqual(self.preview(lines(19, 30)).same_date_warning, ())
        self.assertEqual(self.preview(lines(20, 30)).same_date_warning, ("2025-06-30",))
        self.assertEqual(self.preview(lines(4, 5)).same_date_warning, ())
        flagged = self.preview(lines(5, 5))
        self.assertEqual(flagged.same_date_warning, ("2025-06-30",))
        offered = self.planner.bulk_confirmable(flagged)
        self.assertEqual(len(offered), 5)  # the suspicious date is left out of "confirm all"
        self.assertEqual(same_date_warning([]), ())

    def test_secret_long_entry_is_blocked_as_secret_and_never_stored_or_shown(self):
        token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        long_text = "The user's deploy key is " + token + ". " + "filler words " * 200
        self.assertGreater(len(long_text), 2500)
        preview = self.preview(f"[2025-01-01] - {long_text}\n[2025-01-02] - Likes tea.")
        secret, tea = preview.items
        self.assertEqual(secret.state, SECRET)  # not "too long": secrets come first
        self.assertFalse(secret.checked)
        self.assertNotIn(token, secret.display_content)
        self.planner.set_checked(preview, [secret.key], True)
        self.assertFalse(secret.checked)  # a blocked entry can't be checked
        self.service.commit(preview)
        self.store.checkpoint()
        self.assertNotIn(token.encode(), self.database.read_bytes())
        self.assertNotIn(token.encode(), self.control.path.read_bytes())
        self.assertEqual(tea.state, NEW)  # positive control: the other entry was stored

    def test_instructions_are_blocked_until_rewritten_and_long_entries_until_shortened(self):
        preview = self.preview("[2025-01-01] - From now on, always answer in Korean.\n"
                               f"[2025-01-02] - {'Long entry text. ' * 140}")
        instruction, long_entry = preview.items
        self.assertEqual(instruction.state, INSTRUCTION)
        self.assertEqual(long_entry.state, TOO_LONG)
        self.planner.edit(preview, instruction.key, "The user prefers answers in Korean.")
        self.assertEqual((instruction.state, instruction.checked), (NEW, True))
        self.planner.edit(preview, long_entry.key, "A shortened entry about the long topic.")
        self.assertEqual(long_entry.state, NEW)

    def test_existing_memories_are_skipped_and_different_ones_go_to_review(self):
        current = self.store.add(PERSONAL_SPACE.curated, title="Coffee", content="The user drinks two cups of coffee "
                                 "every morning before work.", source=USER)
        preview = self.preview("[2025-01-01] - The user drinks two cups of coffee every morning before work.\n"
                               "[2025-01-02] - The user drinks green tea every morning instead of coffee before work.\n"
                               "[2025-01-03] - Plays the cello on weekends.")
        same, differs, fresh = preview.items
        self.assertEqual((same.state, same.checked, same.match_id), (EXISTS, False, current.memory_id))
        self.assertEqual((differs.state, differs.checked, differs.match_id), (CONFLICT, True, current.memory_id))
        self.assertEqual(fresh.state, NEW)
        result = self.service.commit(preview)
        self.assertEqual((result.to_inbox, result.to_review), (1, 1))
        review = self.control.reviews()[0]
        self.assertEqual((review.kind, review.memory_id, review.expected_revision_id),
                         ("update", current.memory_id, current.revision_id))
        self.assertEqual(self.store.read(PERSONAL_SPACE.curated, current.memory_id).revision_id,
                         current.revision_id)  # nothing was overwritten
        self.assertEqual(preview.summary()["exists"], 1)

    def test_sensitive_labels_set_the_default_check_by_destination(self):
        text = "\n".join([
            "[2025-01-01] - 사용자는 2023년에 허리 디스크 진단을 받았다.",
            "[2025-01-02] - 사용자는 2019년에 육군 병장으로 전역했다.",
            "[2025-01-03] - 사용자는 가상대학교 컴퓨터공학과를 졸업했다.",
            "[2025-01-04] - 사용자의 어머니는 가상시청에서 근무한다.",
            "[2025-01-05] - 사용자의 연봉은 협상 중이다.",
            "[2025-01-06] - Prefers tabs over spaces.",
        ])
        personal = self.preview(text, destination="personal")
        self.assertEqual([item.sensitive for item in personal.items],
                         [("health",), ("military",), ("school",), ("family",), ("other",), ()])
        self.assertTrue(all(item.checked for item in personal.items))
        general = self.preview(text, destination="general")
        self.assertEqual([item.checked for item in general.items], [False] * 5 + [True])
        self.assertEqual(general.summary()["sensitive"], 5)
        keys = [item.key for item in general.items]
        self.planner.set_checked(general, [keys[0]], True)  # the user's own choice
        self.planner.set_destination(general, keys, self.alpha.space_id)
        self.assertEqual([item.checked for item in general.items], [True, False, False, False, False, True])
        self.planner.set_destination(general, keys[1:3], "personal")
        self.assertEqual([item.checked for item in general.items], [True, True, True, False, False, True])

    def test_paths_need_review_outside_personal_and_project_names_get_a_hint(self):
        text = (r"[2025-01-01] - Keeps the Alpha design notes in D:\Work\Alpha\notes." + "\n"
                "[2025-01-02] - Leads the Alpha rewrite this year.")
        general = self.preview(text, destination="general")
        self.assertEqual(general.items[0].state, PATH_REVIEW)
        personal = self.preview(text, destination="personal")
        self.assertEqual(personal.items[0].state, NEW)
        self.assertEqual(personal.items[1].project_hint, "Alpha")
        result = self.service.commit(general)
        self.assertEqual(result.to_review, 1)
        review = self.control.reviews()[0]
        self.assertEqual((review.kind, review.metadata["namespace"]), ("create", "default.inbox"))

    def test_repeated_entries_in_one_batch(self):
        preview = self.preview("[2025-01-01] - Likes tea.\n[2025-01-02] - likes  TEA.\n[2025-01-03] - Likes jazz.")
        self.assertEqual([item.state for item in preview.items], [NEW, BATCH_DUPLICATE, NEW])
        self.planner.set_destination(preview, [preview.items[1].key], "general")
        self.assertEqual(preview.items[1].state, NEW)  # a different destination is not a repeat

    def test_counts_by_space_and_destination_validation(self):
        preview = self.preview("[2025-01-01] - Likes tea.\n[2025-01-02] - Likes jazz.\n[2025-01-03] - Likes rain.")
        self.planner.set_destination(preview, [preview.items[2].key], self.alpha.space_id)
        names = {space.space_id: space.display_name for space in self.spaces}
        self.assertEqual(preview.counts_by_space(names), {"Personal": 2, "Alpha": 1})
        with self.assertRaises(ValueError):
            self.planner.set_destination(preview, [preview.items[0].key], "nowhere")
        with self.assertRaises(ValueError):
            self.preview("[2025-01-01] - Likes tea.", source="gemini")


class CommitAndUndoTests(_Fixture):
    def many(self, count: int) -> str:
        return "\n".join(f"[2025-{(n % 12) + 1:02d}-{(n % 28) + 1:02d}] - Synthetic imported fact number {n} about "
                         f"topic {n * 7919 % 100003}." for n in range(count))

    def test_a_thousand_entries_preview_and_save_within_the_targets(self):
        text = self.many(1000)
        # A realistic destination: 1,000 memories already there, so every entry is really compared.
        self.store.add_many([(PERSONAL_SPACE.curated, f"Hike {n}", f"Weekend hiking route {n * 13 % 701} has a steep "
                              "ridge, so the user packs extra water and checks every fact twice.", USER)
                             for n in range(1000)])
        started = time.perf_counter()
        preview = self.preview(text)
        preview_seconds = time.perf_counter() - started
        started = time.perf_counter()
        result = self.service.commit(preview)
        save_seconds = time.perf_counter() - started
        print(f"\n[timing] 1,000 entries: preview {preview_seconds:.2f} s, save {save_seconds:.2f} s")
        self.assertLess(preview_seconds, 10.0)
        self.assertLess(save_seconds, 30.0)
        self.assertEqual((result.status, result.to_inbox), ("complete", 1000))
        self.assertEqual(self.store.count_current(PERSONAL_SPACE.inbox), 1000)
        usage = self.control.inbox_usage()
        created = self.control.import_batch(result.batch_id)["created_at"]
        self.assertTrue(all(row["first_seen"] == created for row in usage.values()))

    def test_an_interrupted_import_is_partial_and_a_retry_finishes_without_copies(self):
        preview = self.preview(self.many(250))
        first = self.service.commit(preview, fail_after_chunks=2)
        self.assertEqual((first.status, first.to_inbox), ("partial", 200))
        self.assertEqual(self.control.import_batch(first.batch_id)["status"], "partial")
        second = self.service.commit(preview, batch_id=first.batch_id)
        self.assertEqual((second.status, second.to_inbox), ("complete", 250))
        self.assertEqual(self.store.count_current(PERSONAL_SPACE.inbox), 250)

    def test_batches_store_no_file_names_and_the_audit_has_counts_only(self):
        preview = self.preview("[2025-01-01] - Likes tea.\n[2025-01-02] - Likes jazz.")
        result = self.service.commit(preview)
        with closing(sqlite3.connect(self.control.path)) as raw:
            row = raw.execute("SELECT * FROM import_batches").fetchone()
            columns = [d[0] for d in raw.execute("SELECT * FROM import_batches").description]
        self.assertNotIn("file", " ".join(columns))
        self.assertNotIn("Likes tea", repr(row))
        entry = [e for e in self.control.recent_activity() if e.action == "import"][0]
        self.assertIsNone(entry.title)
        self.assertEqual(entry.detail["inbox"], 2)
        self.assertEqual(self.control.import_batches()[0]["batch_id"], result.batch_id)

    def test_undo_removes_what_is_still_in_the_inbox_and_keeps_what_was_sorted(self):
        preview = self.preview("[2025-01-01] - Undo marker zebra tea.\n[2025-01-02] - Undo marker zebra jazz.\n"
                               "[2025-01-03] - Undo marker zebra rain.")
        current = self.store.add(PERSONAL_SPACE.curated, title="Rain", content="The user likes rain on the roof at "
                                 "night when reading.", source=USER)
        conflict = self.planner.preview(parse_text("[2025-01-04] - The user likes rain on the window at night when "
                                                   "sleeping."), source="claude", destination="personal")
        self.assertEqual(conflict.items[0].state, CONFLICT)
        first = self.service.commit(preview)
        review = self.service.commit(conflict)
        kept_id = [r for r in self.store.list_current(PERSONAL_SPACE.inbox, limit=10)
                   if r.content == "Undo marker zebra jazz."][0].memory_id
        # The user already sorted one entry: it becomes a curated memory, the inbox copy is gone.
        self.store.add(PERSONAL_SPACE.curated, title="Jazz", content="Undo marker zebra jazz.", source=USER)
        from bio_ce.inbox import discard_inbox_items
        discard_inbox_items(self.store, self.control, inbox_scope(PERSONAL_SPACE.curated), [kept_id])
        outcome = self.service.undo(first.batch_id)
        self.assertEqual(outcome, {"removed": 2, "kept": 1, "reviews_closed": 0})
        self.assertEqual(self.store.list_current(PERSONAL_SPACE.inbox, limit=10), ())
        self.store.checkpoint()
        self.assertNotIn(b"zebra tea", self.database.read_bytes())
        self.assertNotIn(b"zebra rain", self.database.read_bytes())
        self.assertIn("Jazz", {r.title for r in self.store.list_current(PERSONAL_SPACE.curated, limit=10)})
        closed = self.service.undo(review.batch_id)
        self.assertEqual(closed["reviews_closed"], 1)
        self.assertEqual(self.control.reviews(), ())
        self.assertEqual(self.store.read(PERSONAL_SPACE.curated, current.memory_id).revision_id, current.revision_id)
        with self.assertRaises(ImportRejected):
            self.service.undo(first.batch_id)
        with self.assertRaises(ControlStoreError):
            self.service.undo("imp_missing")


if __name__ == "__main__":
    unittest.main()
