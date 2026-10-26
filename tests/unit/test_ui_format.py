# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from bio_ce.core.models import RevisionKind, ValidationError
from bio_ce.ui.format import (
    file_size,
    format_timestamp,
    host_name,
    middle_ellipsis,
    plural,
    preview,
    relative_time,
    revision_kind_label,
    validation_feedback,
)


class UIFormatTests(unittest.TestCase):
    def test_preview_collapses_whitespace_and_truncates_with_ellipsis(self):
        self.assertEqual(preview("  one\n\n two\tthree  "), "one two three")
        self.assertEqual(preview("abcdefghij", 6), "abcde\u2026")
        self.assertEqual(preview(None), "")

    def test_counts_sizes_and_identifiers_are_readable(self):
        self.assertEqual(plural(1, "memory", "memories"), "1 memory")
        self.assertEqual(plural(1200, "memory", "memories"), "1,200 memories")
        self.assertEqual(file_size(512), "512 bytes")
        self.assertEqual(file_size(1536), "1.5 KB")
        identifier = "rev_" + "a" * 30 + "b" * 34
        shortened = middle_ellipsis(identifier, 21)
        self.assertEqual(len(shortened), 21)
        self.assertTrue(shortened.startswith("rev_"))
        self.assertTrue(shortened.endswith("b" * 10))
        self.assertEqual(middle_ellipsis("short", 21), "short")

    def test_timestamps_render_local_minutes_and_relative_ages(self):
        now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
        stamp = lambda delta: (now - delta).isoformat().replace("+00:00", "Z")  # noqa: E731
        self.assertEqual(relative_time(stamp(timedelta(seconds=10)), now=now), "Just now")
        self.assertEqual(relative_time(stamp(timedelta(minutes=5)), now=now), "5 min ago")
        self.assertEqual(relative_time(stamp(timedelta(hours=3)), now=now), "3 hr ago")
        self.assertEqual(relative_time(stamp(timedelta(days=1, hours=2)), now=now), "Yesterday")
        self.assertEqual(relative_time(stamp(timedelta(days=3)), now=now), "3 days ago")
        self.assertRegex(format_timestamp("2026-10-22T04:10:58.889015Z"), r"^2026-10-2\d \d\d:\d\d$")
        self.assertEqual(format_timestamp(None), "Not set")
        self.assertEqual(relative_time("not a timestamp"), "")

    def test_validation_errors_map_to_fields_and_plain_language(self):
        field, message = validation_feedback(ValidationError("title must not be empty"))
        self.assertEqual(field, "title")
        self.assertIn("title", message.lower())
        field, message = validation_feedback(ValidationError("content exceeds 100000 characters"))
        self.assertEqual(field, "content")
        self.assertIn("100,000", message)
        field, message = validation_feedback(ValidationError("source_ref contains a control character"))
        self.assertEqual(field, "source_ref")
        self.assertIn("control character", message)
        field, message = validation_feedback(ValidationError("scope and source must use BIO CE model types"))
        self.assertIsNone(field)
        self.assertNotIn("scope and source", message)

    def test_labels_for_hosts_and_revision_kinds(self):
        self.assertEqual(host_name("codex"), "Codex CLI")
        self.assertEqual(host_name("claude"), "Claude Code")
        self.assertEqual(revision_kind_label(RevisionKind.ASSERTION), "Created")
        self.assertEqual(revision_kind_label(RevisionKind.REVISION), "Edited")
        self.assertEqual(revision_kind_label(RevisionKind.RETRACTION), "Retracted")


if __name__ == "__main__":
    unittest.main()
