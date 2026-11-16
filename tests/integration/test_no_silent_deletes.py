# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Invariant (owner request, 2026-11-16): no user action physically removes a memory row, except an explicit delete
(Discard, retracting a memory: its kept originals go with it, Undo import, Forget completely: v0.4.4) and the inbox
expiry.

Every action runs on one synthetic database; the memory and revision rows are compared before and after. Restore
replaces the database by design, so every row it removes must be in the backup it makes first. A positive control
runs an action that deletes a row on purpose and expects the check to catch it.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from bio_ce.control_store import ControlStore, control_database_for
from bio_ce.core.models import MemoryScope, SourceProvenance
from bio_ce.desktop import DesktopMemoryService
from bio_ce.exporter import ExportOptions
from bio_ce.importer import parse_text
from bio_ce.inbox import inbox_scope
from bio_ce.spaces import PERSONAL_SPACE

GENERAL = MemoryScope("bio-ce-personal", "default")
INBOX = inbox_scope(GENERAL)
HOST = SourceProvenance("ai-host-auto-memory", "codex:test", {"host": "codex", "stage": "inbox"})


def rows(database: Path) -> dict[str, set[str]]:
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as raw:
        memories = {f"{m}@{ns}" for m, ns in raw.execute("SELECT memory_id, namespace FROM memories")}
        revisions = {r for (r,) in raw.execute("SELECT revision_id FROM revisions")}
    return {"memories": {item.split("@")[0] for item in memories}, "revisions": revisions,
            "placed": memories}


class NoSilentDeletesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="bio-ce-no-silent-deletes-")
        self.root = Path(self.temp.name)
        self.database = self.root / "data" / "memories.sqlite3"
        self.service = DesktopMemoryService(self.database)
        self.control = ControlStore(control_database_for(self.database))
        self.control.set_personal_enabled(True)
        self.violations: list[str] = []

    def tearDown(self) -> None:
        self.service.close()
        self.control.close()
        self.temp.cleanup()

    @property
    def spaces(self):
        return (*self.control.spaces(), PERSONAL_SPACE)

    def curation(self):
        return self.service.curation(self.control, self.spaces)

    def host_saves(self, title: str, content: str) -> str:
        store = self.service._store  # what the MCP server does for a host in collect mode
        revision = store.add(INBOX, title=title, content=content, source=HOST)
        self.control.inbox_seen(revision.memory_id)
        return revision.memory_id

    def check(self, name: str, action, *, deletes: bool = False, restore: bool = False) -> object:
        before = rows(self.database)
        result = action()
        after = rows(self.database)
        gone_memories = before["memories"] - after["memories"]
        gone_revisions = before["revisions"] - after["revisions"]
        if restore:
            backups = sorted((self.database.parent / "backups").glob("auto-before-restore-*.sqlite3"))
            kept = rows(backups[-1]) if backups else {"memories": set(), "revisions": set()}
            gone_memories -= kept["memories"]
            gone_revisions -= kept["revisions"]
        if (gone_memories or gone_revisions) and not deletes:
            self.violations.append(f"{name}: removed {len(gone_memories)} memory rows, {len(gone_revisions)} "
                                   f"revision rows")
        return result

    def every_action(self) -> None:
        check = self.check
        note = check("add a memory", lambda: self.service.add(title="Editor", content="The user edits in helix.",
                                                              source_ref="test"))
        check("edit a memory", lambda: self.service.revise(note, title="Editor", content="The user edits in helix "
                                                           "with a dark theme.", source_ref="test"))
        for title, text in (("Deploys", "The team deploys on Fridays. Releases need a tag."),
                            ("Deploys", "The team deploys on Fridays."),
                            ("Coffee", "The user now drinks one cup of coffee every morning and green tea after "
                                       "lunch."),
                            ("Plants", "The user waters the balcony plants every Sunday morning."),
                            ("Plants", "The user waters the balcony plants every Sunday morning without fail."),
                            ("Invoices", "Invoices go out to clients on the first business day of a month."),
                            ("Invoices", "Invoices go out on the first business day of a month without fail.")):
            check("a host saves to the inbox", lambda t=title, x=text: self.host_saves(t, x))
        check("add a memory", lambda: self.service.add(title="Coffee", content="The user drinks two cups of coffee "
                                                       "every morning.", source_ref="test"))
        check("find suggestions", lambda: self.curation().find())
        found = {s.action: s for s in self.curation().suggestions()}
        merge = next(s for s in self.curation().suggestions() if "Deploys" in s.draft_title)
        check("approve a merge", lambda: self.curation().approve(merge.proposal_id))
        check("undo the merge", lambda: self.curation().undo(merge.proposal_id))
        check("approve an update", lambda: self.curation().approve(found["update_existing"].proposal_id))
        check("undo the update", lambda: self.curation().undo(found["update_existing"].proposal_id))
        rest = [s.proposal_id for s in self.curation().suggestions()]
        check("approve all shown", lambda: self.curation().approve_many(rest[:1]))
        check("reject", lambda: self.curation().reject_many(rest[1:]))
        item = self.host_saves("Ramen", "The user likes miso ramen with extra corn.")
        check("move an inbox item to memories",
              lambda: self.service.move_inbox(self.control, item, title="Ramen", content="The user likes miso ramen "
                                              "with extra corn."))
        target = self.service.add(title="Personal note", content="Something about the user.", source_ref="test")
        check("move a memory to Personal",
              lambda: self.service.move_memories(self.control, [target.memory_id], PERSONAL_SPACE.curated))
        planner = self.service.import_planner(self.spaces, size_limit=2000)
        preview = planner.preview(parse_text("[2025-02-01] - The user speaks Korean.\n[unknown] - The user is "
                                             "left-handed."), source="chatgpt", destination="general")
        batch = check("import", lambda: self.service.import_service(self.control, self.spaces).commit(preview))
        check("export", lambda: self.service.export_text(self.spaces, ExportOptions(space_ids=("general",),
                                                                                    include_inbox=True),
                                                         personal_allowed=True))
        backup = check("create a backup", lambda: self.service.create_backup(self.root / "manual.sqlite3"))
        check("add a memory", lambda: self.service.add(title="After backup", content="Added after the backup.",
                                                       source_ref="test"))
        check("restore a backup", lambda: self.service.restore_backup(backup, control=self.control), restore=True)
        check("turn Personal off", lambda: self.control.set_personal_enabled(False))
        check("turn Personal on", lambda: self.control.set_personal_enabled(True))
        check("the inbox expiry pass", lambda: self.service.run_inbox_expiry(self.control), deletes=True)
        # Explicit deletes: allowed to remove rows.
        check("undo the import", lambda: self.service.import_service(self.control, self.spaces).undo(
            batch.batch_id), deletes=True)
        inbox_now = [revision.memory_id for revision in self.service.inbox()]
        check("discard", lambda: self.service.discard_inbox(self.control, inbox_now[:1]), deletes=True)
        current = self.service.read(note.memory_id)
        check("retract a memory", lambda: self.service.retract(current), deletes=True)
        self.assertIn(note.memory_id, rows(self.database)["memories"])  # retraction never removes the memory itself
        doomed = self.service.add(title="Forget me", content="The user asked BIO CE to forget this.",
                                  source_ref="test")
        check("forget completely", lambda: self.service.forget(doomed, control=self.control), deletes=True)
        self.assertNotIn(doomed.memory_id, rows(self.database)["memories"])  # positive: forgetting removes the row
        (retracted,) = [r for r in self.service.retracted() if r.last.memory_id == note.memory_id]
        check("forget a retracted memory", lambda: self.service.forget(retracted.last, control=self.control),
              deletes=True)
        self.assertNotIn(note.memory_id, rows(self.database)["memories"])

    def test_no_action_removes_a_row_unless_it_is_a_delete(self):
        self.every_action()
        self.assertEqual(self.violations, [], "\n".join(self.violations))

    def test_the_check_catches_an_action_that_deletes_on_purpose(self):
        """Positive control: an ordinary-looking action that purges a row is reported."""
        item = self.host_saves("Doomed", "This inbox item is purged by a careless action.")
        self.check("careless action", lambda: self.service._store.purge(INBOX, [item]))
        self.assertEqual(len(self.violations), 1)
        self.assertIn("careless action: removed 1 memory rows", self.violations[0])


if __name__ == "__main__":
    unittest.main()
