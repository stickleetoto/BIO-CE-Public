# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""v0.4.4 §2.3: the Reviews tab. A change shows the current memory beside the proposal with the differences marked;
when they hardly share a topic, a warning says it may be a different fact and "Add as a new memory" becomes the
default (nothing is overwritten by accident). Approve leaves an Undo; Reject waits for Undo like a delete."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from bio_ce.control_store import MODE_AUTO_MEMORY
from bio_ce.core.models import MemoryNotFoundError
from bio_ce.desktop import AppDataPaths, BIOCEDesktop, DesktopMemoryService
from bio_ce.spaces import PERSONAL_SPACE
from bio_ce.ui.hub.data import REVIEWS
from bio_ce.ui.hub.reviews import different_fact, word_diff
from tests.integration.test_auto_memory_ui import FakeManagedConnections
from tests.tk_support import new_tk_root

FAKE_KEY = "sk-proj-" + "Zx7Qw2Er9Ty4Ui8Op3As6Df1Gh5Jk0Lz"  # synthetic, not a real credential (as test_inbox_collect)


class DiffTests(unittest.TestCase):
    def test_word_diff_marks_removed_and_added_words(self):
        left, right = word_diff("The user drinks two cups.", "The user drinks one cup and tea.")
        self.assertEqual("".join(text for text, _tag in left), "The user drinks two cups.")
        self.assertEqual("".join(text for text, _tag in right), "The user drinks one cup and tea.")
        self.assertIn(("two", "del"), left)
        self.assertTrue(any(tag == "add" and "tea" in text for text, tag in right))
        self.assertEqual(word_diff("same text", "same text"), ([("same text", None)], [("same text", None)]))

    def test_a_different_topic_is_flagged_and_the_same_topic_is_not(self):
        self.assertTrue(different_fact("Bike\nThe user rides a bike on weekends.",
                                       "Notes\nThe user writes meeting notes in Markdown."))
        self.assertFalse(different_fact("Coffee\nThe user drinks two cups of coffee every morning.",
                                        "Coffee\nThe user drinks one cup of coffee every morning."))


class HubReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-hub-reviews-")
        self.paths = AppDataPaths.under(self.temp.name)
        self.service = DesktopMemoryService(self.paths.user_database)
        self.connections = FakeManagedConnections(self.paths.user_database)
        self.control = self.connections.control
        self.control.set_mode(self.connections.grant.connection_id, MODE_AUTO_MEMORY)
        self.control.set_personal_enabled(True)
        self.bike = self.service.add(title="Bike", content="The user rides a bike on weekends.", source_ref="test")
        self.coffee = self.service.add(title="Coffee", content="The user drinks two cups of coffee every morning.",
                                       source_ref="test")
        common = dict(host="codex", connection_id=self.connections.grant.connection_id, review_reason="test")
        self.different = self.control.enqueue_review(
            kind="update", title="Notes", content="The user writes meeting notes in Markdown.",
            memory_id=self.bike.memory_id, expected_revision_id=self.bike.revision_id, **common)
        self.same = self.control.enqueue_review(
            kind="update", title="Coffee", content="The user drinks one cup of coffee every morning.",
            memory_id=self.coffee.memory_id, expected_revision_id=self.coffee.revision_id, **common)
        self.new = self.control.enqueue_review(kind="create", title="Work folder",
                                               content="The work folder is on drive D.", **common)
        self.personal = self.control.enqueue_review(
            kind="create", title="Tea", content="The user drinks green tea.", **common,
            metadata={"project": PERSONAL_SPACE.curated.project, "namespace": PERSONAL_SPACE.curated.namespace})
        self.root = new_tk_root()
        self.app = BIOCEDesktop(self.root, self.service, self.paths, self.connections)
        self.root.after_cancel(self.app._maintenance_after)
        self.app.open_state(REVIEWS)
        self.root.update()
        self.hub = self.app.memories
        self.view = self.hub.reviews

    def tearDown(self) -> None:
        self.app.tasks.wait(10)
        self.app.editor.load(None)
        self.app.close()
        self.connections.close()
        self.temp.cleanup()

    def card(self, review_id):
        return next(card for card in self.view.review_cards if card.review_id == review_id)

    def item(self, review_id):
        return next(item for item in self.view.items if item.item_id == str(review_id))

    def test_a_different_fact_warns_and_defaults_to_adding_a_new_memory(self):
        card = self.card(self.different)
        self.assertTrue(card.different_fact)
        self.assertEqual(card.default, "as_new")
        self.assertEqual([button.text for button in card.buttons],
                         ["Add as a new memory", "Change anyway", "Edit and approve…", "Reject"])
        self.assertEqual(card.buttons[0].variant, "primary")
        same = self.card(self.same)  # positive control: the same topic is an ordinary change
        self.assertFalse(same.different_fact)
        self.assertEqual([button.text for button in same.buttons],
                         ["Change", "Add as a new memory", "Edit and approve…", "Reject"])
        texts = [w for w in _walk(self.view) if w.winfo_class() == "Text"]
        tagged = {tag for text in texts for tag in ("add", "del") if text.tag_ranges(tag)}
        self.assertEqual(tagged, {"add", "del"}, "the differences are marked")
        self.assertIn("Not changed yet", same.status_text)

    def test_add_as_new_keeps_the_current_memory(self):
        self.assertTrue(self.view.approve(self.item(self.different), as_new=True))
        self.assertEqual(self.service.read(self.bike.memory_id).content, self.bike.content)  # not overwritten
        self.assertIn("Notes", {revision.title for revision in self.service.list()})
        self.assertEqual(self.control.review(self.different).status != "pending", True)
        self.assertNotIn(str(self.different), {item.item_id for item in self.view.items})

    def test_approving_a_change_can_be_undone_from_its_notice(self):
        with patch.object(self.app, "notify") as notice:
            self.assertTrue(self.view.approve(self.item(self.same)))
        self.assertEqual(self.service.read(self.coffee.memory_id).content,
                         "The user drinks one cup of coffee every morning.")
        label, undo = notice.call_args.kwargs["action"]
        self.assertEqual(label, "Undo")
        self.assertTrue(undo())
        current = self.service.read(self.coffee.memory_id)
        self.assertEqual(current.content, self.coffee.content)  # the earlier text, as a new revision
        self.assertEqual(current.revision_number, 3)

    def test_approving_a_new_memory_can_be_undone(self):
        with patch.object(self.app, "notify") as notice:
            self.assertTrue(self.view.approve(self.item(self.new)))
        created = next(r for r in self.service.list() if r.title == "Work folder")
        _label, undo = notice.call_args.kwargs["action"]
        self.assertTrue(undo())
        with self.assertRaises(MemoryNotFoundError):
            self.service.read(created.memory_id)

    def test_a_review_for_personal_is_saved_in_personal_and_follows_the_space_filter(self):
        self.hub.set_space_filter("general")
        self.assertNotIn(str(self.personal), {item.item_id for item in self.view.items})
        self.hub.set_space_filter("personal")
        self.assertEqual([item.item_id for item in self.view.items], [str(self.personal)])
        self.view.approve(self.item(self.personal))
        self.service.use_space(PERSONAL_SPACE.curated)
        self.assertEqual([revision.title for revision in self.service.list()], ["Tea"])

    def test_reject_waits_for_undo_and_then_closes_the_review(self):
        self.assertTrue(self.view.reject(self.item(self.new)))
        self.assertNotIn(str(self.new), {item.item_id for item in self.view.items})
        self.assertEqual(self.control.review(self.new).status, "pending", "nothing is recorded yet")
        self.assertTrue(self.app.pending.undo())
        self.assertIn(str(self.new), {item.item_id for item in self.view.items})  # back after Undo
        self.view.reject(self.item(self.new))
        self.app.pending.flush()
        self.assertEqual(self.control.review(self.new).status, "rejected")
        self.assertEqual(self.service.count(), 2, "a rejection changes no memory")

    def test_a_retraction_request_asks_first_and_offers_no_undo(self):
        retract = self.control.enqueue_review(kind="retract", title=self.bike.title, content=None,
                                              memory_id=self.bike.memory_id,
                                              expected_revision_id=self.bike.revision_id, host="codex",
                                              connection_id=self.connections.grant.connection_id,
                                              review_reason="retraction always needs the user's approval")
        self.hub.refresh()
        self.assertEqual([b.text for b in self.card(retract).buttons], ["Retract memory", "Reject"])
        with patch.object(self.app, "confirm", return_value=False):
            self.assertFalse(self.view.approve(self.item(retract)))
        self.assertEqual(self.service.read(self.bike.memory_id).title, "Bike")
        with patch.object(self.app, "confirm", return_value=True), patch.object(self.app, "notify") as notice:
            self.assertTrue(self.view.approve(self.item(retract)))
        self.assertIsNone(notice.call_args.kwargs.get("action"))
        with self.assertRaises(MemoryNotFoundError):
            self.service.read(self.bike.memory_id)

    def test_a_secret_is_refused_when_added_as_new(self):
        secret = self.control.enqueue_review(
            kind="update", title="Key", content="The deploy key is " + FAKE_KEY + ".",
            memory_id=self.bike.memory_id, expected_revision_id=self.bike.revision_id, host="codex",
            connection_id=self.connections.grant.connection_id, review_reason="test")
        self.hub.refresh()
        with patch.object(self.app, "notify") as notice:
            self.assertFalse(self.view.approve(self.item(secret), as_new=True))
        self.assertEqual(notice.call_args.args[0], "warning")
        self.assertNotIn("Key", {revision.title for revision in self.service.list()})


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


if __name__ == "__main__":
    unittest.main()
