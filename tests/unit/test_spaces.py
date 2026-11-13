# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Space naming and resolution rules (pure functions, synthetic names and folders)."""

from __future__ import annotations

import unittest

from bio_ce.spaces import (
    GENERAL_SPACE_ID,
    REASON_AMBIGUOUS,
    REASON_UNKNOWN,
    RESOLVED_DEFAULT,
    RESOLVED_EXACT,
    RESOLVED_FALLBACK,
    Space,
    folder_key,
    normalize_folder,
    resolve_folder,
    resolve_space,
    slugify,
)


GENERAL = Space(GENERAL_SPACE_ID, "general", "bio-ce-personal", "General")
ALPHA = Space("a1", "project", "project:alpha", "Alpha")
ALPHA_TWO = Space("a2", "project", "project:alpha-2", "alpha")  # same display name, other case
BETA = Space("b1", "project", "project:beta-app", "Beta App")
OLD = Space("o1", "project", "project:old", "Old", archived_at="2026-11-01")
SPACES = (GENERAL, ALPHA, BETA, OLD)


class SlugTests(unittest.TestCase):
    def test_slug_rules(self):
        self.assertEqual(slugify("Beta App!"), "beta-app")
        self.assertEqual(slugify("  회의 노트 / 2026 "), "회의-노트-2026")
        self.assertEqual(slugify("***"), "space")
        self.assertEqual(len(slugify("x" * 200)), 64)
        self.assertEqual(slugify("Alpha", taken={"alpha"}), "alpha-2")
        self.assertEqual(slugify("Alpha", taken={"alpha", "alpha-2"}), "alpha-3")
        self.assertEqual(len(slugify("y" * 200, taken={"y" * 64})), 64)


class SpaceArgumentTests(unittest.TestCase):
    def test_exact_id_name_any_case_and_slug(self):
        self.assertEqual(resolve_space(SPACES, "b1").space, BETA)
        self.assertEqual(resolve_space(SPACES, "beta app").space, BETA)
        self.assertEqual(resolve_space(SPACES, "beta-app").space, BETA)
        self.assertEqual(resolve_space(SPACES, "project:beta-app").space, BETA)
        self.assertEqual(resolve_space(SPACES, "Beta App").how, RESOLVED_EXACT)

    def test_omitted_means_general_without_a_fallback_note(self):
        resolution = resolve_space(SPACES, None)
        self.assertEqual((resolution.space, resolution.how, resolution.reason), (GENERAL, RESOLVED_DEFAULT, None))
        self.assertNotIn("space_resolution_reason", resolution.as_result())

    def test_ambiguous_and_unknown_fall_back_to_general_with_the_reason(self):
        ambiguous = resolve_space((*SPACES, ALPHA_TWO), "ALPHA")
        self.assertEqual((ambiguous.space, ambiguous.how, ambiguous.reason),
                         (GENERAL, RESOLVED_FALLBACK, REASON_AMBIGUOUS))
        unknown = resolve_space(SPACES, "gamma")
        self.assertEqual((unknown.space, unknown.reason), (GENERAL, REASON_UNKNOWN))
        self.assertEqual(unknown.as_result()["space_resolution"], RESOLVED_FALLBACK)

    def test_archived_spaces_are_not_resolved(self):
        self.assertEqual(resolve_space(SPACES, "old").reason, REASON_UNKNOWN)


class FolderTests(unittest.TestCase):
    def test_normalization_ignores_case_slashes_and_trailing_separators(self):
        self.assertEqual(normalize_folder("C:/Work/App/"), normalize_folder(r"c:\work\app"))
        self.assertEqual(folder_key("C:/Work/App/"), folder_key(r"C:\WORK\app"))
        self.assertEqual(normalize_folder("C:\\"), "c:\\")

    def test_deepest_linked_folder_wins(self):
        links = [("a1", folder_key(r"C:\work")), ("b1", folder_key(r"C:\work\beta"))]
        self.assertEqual(resolve_folder(SPACES, links, r"C:\work\beta\src\ui").space, BETA)
        self.assertEqual(resolve_folder(SPACES, links, r"C:\work\gamma").space, ALPHA)
        self.assertEqual(resolve_folder(SPACES, links, r"D:\elsewhere").how, RESOLVED_DEFAULT)
        self.assertEqual(resolve_folder(SPACES, links, None).space, GENERAL)

    def test_two_spaces_on_the_same_folder_mean_general(self):
        links = [("a1", folder_key(r"C:\work")), ("b1", folder_key(r"C:\work"))]
        resolution = resolve_folder(SPACES, links, r"C:\work\x")
        self.assertEqual((resolution.space, resolution.reason), (GENERAL, REASON_AMBIGUOUS))

    def test_archived_space_links_are_ignored(self):
        links = [("o1", folder_key(r"C:\old")), ("a1", folder_key("C:\\"))]
        self.assertEqual(resolve_folder(SPACES, links, r"C:\old\x").space, ALPHA)


if __name__ == "__main__":
    unittest.main()
