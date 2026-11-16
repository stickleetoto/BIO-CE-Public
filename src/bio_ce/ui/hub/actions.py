# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""What the buttons of the unified memory screen do (v0.4.4 §3.1, §3.2, §4).

Every delete is still one of the allowed ones and goes through the existing services: retracting a memory and
discarding inbox items. They wait eight seconds for Undo (``app.pending``) instead of asking first; until then
nothing is deleted. Moves run at once (after the automatic backup) and their Undo moves the items back.
"""

from __future__ import annotations

from bio_ce.core.models import MemoryNotFoundError, RevisionConflictError
from bio_ce.engine.contract import EngineUnavailable, WriteStatus
from bio_ce.ui.format import preview
from bio_ce.ui.hub.common import control_of, in_space, space_label
from bio_ce.ui.hub.data import INBOX, MEMORIES, HubItem
from bio_ce.ui.i18n import t


def by_space(items: list[HubItem]) -> list[tuple[object, list[HubItem]]]:
    groups: dict[str, tuple[object, list[HubItem]]] = {}
    for item in items:
        key = item.space.space_id if item.space is not None else ""
        groups.setdefault(key, (item.space, []))[1].append(item)
    return list(groups.values())


class HubActions:
    def __init__(self, hub) -> None:
        self.hub = hub
        self.app = hub.app

    @property
    def control(self):
        return control_of(self.app)

    # Delete (retract a memory, discard inbox items) -------------------------------------------------------------

    def delete(self, items: list[HubItem]) -> bool:
        items = [item for item in items if item.state in (MEMORIES, INBOX)]
        if not items:
            self.app.notify("info", t("hub.select_first"))
            return False
        if items[0].state == MEMORIES:
            return self.retract(items)
        return self.discard(items)

    def retract(self, items: list[HubItem]) -> bool:
        if not self.app.require_action("retract"):
            return False
        try:
            engine = self.app.memory_engine()
        except EngineUnavailable:
            self.app.notify("error", t("hub.delete.engine_down"), title=t("hub.engine_down_title"))
            return False
        targets = []  # (item, revision id) read now: a memory changed meanwhile is not deleted
        kept = 0
        for space, group in by_space(items):
            with in_space(self.app, space):
                for item in group:
                    try:
                        targets.append((item, engine.get(item.item_id).revision_id))
                    except MemoryNotFoundError:
                        continue
                    try:
                        kept += self.app.service.kept_count(item.item_id)
                    except Exception:  # noqa: BLE001 - only changes the wording
                        pass
        if not targets:
            self.hub.refresh()
            return False

        def run() -> None:
            done, changed = 0, 0
            for item, revision_id in targets:
                try:
                    with in_space(self.app, item.space):
                        outcome = engine.retract(item.item_id, expected_revision_id=revision_id)
                except (RevisionConflictError, MemoryNotFoundError):
                    changed += 1
                    continue
                except Exception:  # noqa: BLE001 - shown below
                    self.app.notify("error", t("hub.delete.failed"), title=t("hub.delete.failed_title"))
                    break
                if outcome.status is WriteStatus.CONFLICT or not outcome.persisted:
                    changed += 1
                    continue
                done += 1
            if changed:
                self.app.notify("warning", t("hub.delete.changed", count=changed), title=t("hub.delete.changed_title"))
            self.app.data_changed()

        first = targets[0][0]
        message = (t("hub.delete.one", title=preview(first.title, 50)) if len(targets) == 1
                   else t("hub.delete.many", count=len(targets)))
        message += " " + t("hub.delete.not_erase")
        if kept:
            message += " " + t("hub.delete.kept", count=kept)
        self.hub.close_drawer_for([item.item_id for item, _rev in targets])
        self.app.pending.defer([item.item_id for item, _rev in targets], run, message=message,
                               title=t("hub.delete.title"), on_undo=self.hub.refresh)
        self.hub.refresh()
        return True

    def discard(self, items: list[HubItem]) -> bool:
        control = self.control
        if control is None or not self.app.require_action("review"):
            return False
        kept = 0
        for space, group in by_space(items):
            with in_space(self.app, space):
                for item in group:
                    try:
                        kept += self.app.service.kept_count(item.item_id, inbox=True)
                    except Exception:  # noqa: BLE001
                        pass
        groups = [(space, [item.item_id for item in group]) for space, group in by_space(items)]

        def run() -> None:
            deleted, complete = 0, True
            for space, ids in groups:
                try:
                    with in_space(self.app, space):
                        result = self.app.service.discard_inbox(control, ids)
                except Exception:  # noqa: BLE001
                    self.app.notify("error", t("hub.discard.failed"), title=t("hub.discard.failed_title"))
                    self.app.data_changed()
                    return
                deleted += result.deleted
                complete = complete and result.completed
            self.finished_discard(deleted, complete)

        message = (t("hub.discard.one", title=preview(items[0].title, 50)) if len(items) == 1
                   else t("hub.discard.many", count=len(items)))
        if kept:  # a merged item: what was merged into it is kept until now, so the merge could be undone
            message += " " + t("hub.discard.kept", count=kept)
        message += " " + t("hub.discard.erase")
        ids = [item.item_id for item in items]
        self.hub.close_drawer_for(ids)
        self.app.pending.defer(ids, run, message=message, title=t("hub.discard.title"), on_undo=self.hub.refresh)
        self.hub.refresh()
        return True

    def finished_discard(self, count: int, completed: bool) -> None:
        if not completed:
            self.app.notify("info", t("hub.discard.finishing", count=count), title=t("hub.discard.finishing_title"))
            self.app.schedule_cleanup_retry()
        self.app.refresh_badges()
        self.app.data_changed()

    # Move between spaces ---------------------------------------------------------------------------------------

    def move(self, items: list[HubItem], target) -> int | None:
        """Move memories (or inbox items) to ``target`` the way Move… always did: automatic backup first. The
        notice's Undo moves them back, again after a backup."""
        if not items:
            return None
        inbox = items[0].state == INBOX
        moved_total = 0
        undo_groups = []
        for space, group in by_space(items):
            if space is not None and space.space_id == target.space_id:
                continue
            ids = [item.item_id for item in group]
            moved = self.app.move_memories(ids, target, inbox=inbox, source=space, notify=False)
            if moved is None:
                return None
            moved_total += moved
            undo_groups.append((space, ids))
        if not moved_total:
            return 0
        self.app.notify("success", t("hub.move.done", count=moved_total, space=space_label(target)),
                        title=t("hub.move.title"),
                        action=(t("common.undo"), lambda: self.move_back(undo_groups, target, inbox)))
        return moved_total

    def move_back(self, groups, target, inbox: bool) -> int:
        back = 0
        for space, ids in groups:
            if space is None:
                continue
            moved = self.app.move_memories(ids, space, inbox=inbox, source=target, notify=False)
            back += moved or 0
        self.app.notify("success", t("hub.move.undone", count=back), title=t("hub.move.undone_title"))
        return back

    # Inbox → memories --------------------------------------------------------------------------------------------

    def to_memories(self, item: HubItem) -> bool:
        control = self.control
        if item.state != INBOX or control is None or not self.app.require_action("review"):
            return False
        edited = self.app.edit_before_saving(title=item.title, content=item.text or "",
                                             reason=t("hub.inbox.edit_reason"))
        if edited is None:
            return False
        title, content = edited
        with in_space(self.app, item.space):
            update = self.app.service.similar_curated(title, content)
        if update is not None:
            if self.app.confirm(title=t("hub.inbox.update_title"), message=t("hub.inbox.update_message"),
                                quote=update.title, confirm_text=t("hub.inbox.update_button"),
                                cancel_text=t("hub.inbox.add_new_button")):
                pass
            elif self.app.confirm(title=t("hub.inbox.add_new_title"), message=t("hub.inbox.add_new_message"),
                                  quote=title, confirm_text=t("hub.inbox.add_new_button")):
                update = None
            else:
                return False
        try:
            with in_space(self.app, item.space):
                self.app.service.move_inbox(control, item.item_id, title=title, content=content, update=update)
        except Exception as exc:  # noqa: BLE001 - shown to the user (a secret is refused with its reason)
            self.app.notify("error", str(exc) or t("hub.inbox.move_failed"), title=t("hub.inbox.move_failed_title"))
            return False
        self.hub.close_drawer_for([item.item_id])
        self.app.data_changed()
        self.app.notify("success", t("hub.inbox.moved", title=preview(title, 50)), title=t("hub.inbox.moved_title"))
        return True

    # Clean-up proposals (Keep / Discard now) ----------------------------------------------------------------------

    def keep_proposal(self, proposal: dict) -> bool:
        control = self.control
        if control is None or not self.app.require_action("review"):
            return False
        try:
            control.keep_items(int(proposal["item_id"]))
        except Exception as exc:  # noqa: BLE001
            self.app.notify("error", str(exc), title=t("hub.cleanup.not_kept"))
            return False
        self.app.notify("success", t("hub.cleanup.kept", count=len(proposal["memory_ids"])),
                        title=t("hub.cleanup.kept_title"))
        self.app.refresh_badges()
        self.hub.refresh()
        return True

    def discard_proposal(self, proposal: dict) -> bool:
        control = self.control
        if control is None or not self.app.require_action("review"):
            return False

        def run() -> None:
            try:
                deleted = self.app.service.discard_proposal(control, proposal)
            except Exception:  # noqa: BLE001
                self.app.notify("error", t("hub.discard.failed"), title=t("hub.discard.failed_title"))
                return
            waiting = bool(control.curation_items(statuses=("cleanup_pending",)))
            self.finished_discard(deleted, not waiting)

        count = len(proposal["memory_ids"])
        self.app.pending.defer(list(proposal["memory_ids"]) + [f"cleanup:{proposal['item_id']}"], run,
                               message=t("hub.discard.many", count=count) + " " + t("hub.discard.erase"),
                               title=t("hub.discard.title"), on_undo=self.hub.refresh)
        self.hub.refresh()
        return True

    # Forget completely (D1, v0.4.4 §7.1) ---------------------------------------------------------------------

    def forget(self, item: HubItem | None, record) -> bool:
        """Forget completely (v0.4.4 §7.1): erase a memory (current or retracted) with every earlier revision, the
        inbox items kept for it, and the reviews about it. No Undo notice; a confirmation that says so instead.

        ``record`` is the memory's current revision, or for a retracted memory what it said before the retraction
        (``DesktopMemoryService.forget(current, control=…)``, D1)."""
        control = self.control
        if item is None or record is None or not hasattr(self.app.service, "forget") \
                or not self.app.require_action("retract"):
            return False
        try:
            with in_space(self.app, item.space):
                kept = self.app.service.kept_count(record.memory_id)
        except Exception:  # noqa: BLE001 - only changes the wording
            kept = 0
        points = [t("hub.forget.point_files"), t("hub.forget.point_no_undo"), t("hub.forget.point_backups"),
                  t("hub.forget.point_hosts"), t("hub.forget.point_drive")]
        if kept:
            points.insert(1, t("hub.forget.point_kept", count=kept))
        if not self.app.confirm(title=t("hub.forget.title"), message=t("hub.forget.message"), quote=record.title,
                                points=tuple(points), confirm_text=t("hub.forget.button"), danger=True):
            return False
        self.app.pending.flush()  # a waiting delete runs first, so it can't run on a forgotten memory later
        try:
            with in_space(self.app, item.space):
                result = self.app.service.forget(record, control=control)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.app.notify("error", str(exc) or t("hub.forget.failed"), title=t("hub.forget.failed_title"))
            self.app.data_changed()
            return False
        self.hub.close_drawer_for([record.memory_id])
        self.app.data_changed()
        if getattr(result, "completed", True):
            self.app.notify("success", t("hub.forget.done", title=preview(record.title, 50)),
                            title=t("hub.forget.done_title"))
        else:  # another process holds an older snapshot: the erase finishes on the next clean-up pass
            self.app.notify("info", t("hub.forget.pending", title=preview(record.title, 50)),
                            title=t("hub.forget.pending_title"))
            self.app.schedule_cleanup_retry()
        return True


__all__ = ["HubActions", "by_space"]
