# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Drag cards onto a space chip to move them (v0.4.4 §3.1). Only the chips they can go to light up; a drop takes the
same path as Move (automatic backup first, then a notice whose Undo moves them back)."""

from __future__ import annotations

import tkinter as tk

from bio_ce.ui.i18n import t
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS

THRESHOLD = 6  # px at 100% the pointer must travel before a press becomes a drag


class DragController:
    def __init__(self, hub) -> None:
        self.hub = hub
        self._card = None
        self._start: tuple[int, int] | None = None
        self.items: list = []
        self.targets: set[str] = set()
        self.dragging = False
        self._ghost: tk.Toplevel | None = None
        self._over: str | None = None

    # Mouse events -----------------------------------------------------------------------------------------------

    def press(self, card, event) -> None:
        self._card = card
        self._start = (int(event.x_root), int(event.y_root))
        self.dragging = False

    def motion(self, event) -> None:
        if self._card is None or self._start is None:
            return
        x, y = int(event.x_root), int(event.y_root)
        if not self.dragging:
            limit = self.hub.theme.px(THRESHOLD)
            if abs(x - self._start[0]) < limit and abs(y - self._start[1]) < limit:
                return
            if not self.begin(self.hub.drag_items(self._card)):
                self._card = None
                return
        self._move_ghost(x, y)
        self.hover(self.hub.chip_at(x, y))

    def release(self, card, event) -> None:
        if not self.dragging:
            self._card = None
            state = int(getattr(event, "state", 0))
            self.hub.card_clicked(card, toggle=bool(state & 0x0004), extend=bool(state & 0x0001))  # Ctrl / Shift
            return
        self.finish(self.hub.chip_at(int(event.x_root), int(event.y_root)))

    # The drag itself (also driven directly by tests) ----------------------------------------------------------

    def begin(self, items: list) -> bool:
        """Start dragging ``items``; lights up the chips they can be dropped on. False when there is none."""
        targets = self.hub.drop_targets(items)
        if not items or not targets or not self.hub.app.allowed("edit").enabled:
            return False
        self.items = list(items)
        self.targets = targets
        self.dragging = True
        self.hub.show_drop_targets(targets)
        return True

    def hover(self, space_id: str | None) -> None:
        over = space_id if space_id in self.targets else None
        if over != self._over:
            self._over = over
            self.hub.show_drop_targets(self.targets, over=over)

    def finish(self, space_id: str | None) -> int | None:
        """Drop on ``space_id`` (a chip) or nowhere. Returns how many moved, or None when nothing was dropped."""
        items, targets = self.items, self.targets
        self.cancel()
        if space_id is None or space_id not in targets:
            return None
        return self.hub.drop(items, space_id)

    def cancel(self) -> None:
        self.dragging = False
        self._card = None
        self._over = None
        self.items, self.targets = [], set()
        if self._ghost is not None:
            try:
                self._ghost.destroy()
            except tk.TclError:
                pass
            self._ghost = None
        self.hub.show_drop_targets(set())

    def _move_ghost(self, x: int, y: int) -> None:
        theme, c = self.hub.theme, self.hub.colors
        if self._ghost is None:
            ghost = tk.Toplevel(self.hub)
            ghost.wm_overrideredirect(True)
            ghost.configure(background=c.accent)
            tk.Label(ghost, text=t("hub.drag.label", count=len(self.items)), font=theme.font("caption_strong"),
                     background=c.surface_alt, foreground=c.text, padx=theme.px(SPACE_S), pady=theme.px(SPACE_XS)).pack(
                padx=1, pady=1)
            self._ghost = ghost
        try:
            self._ghost.wm_geometry(f"+{x + theme.px(SPACE_L)}+{y + theme.px(SPACE_M)}")
        except tk.TclError:
            pass


__all__ = ["DragController", "THRESHOLD"]
