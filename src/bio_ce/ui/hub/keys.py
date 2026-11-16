# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Keys of the memory screen (v0.4.4 F3): E edit, M move, Delete delete, Esc close the drawer, Ctrl+Z undo the
waiting delete, Ctrl+S save, Ctrl+E edit, Ctrl+H history. Single letters never act while the user types in a box.
They are listed, with the window's other keys, in ``bio_ce.ui.shortcuts``."""

from __future__ import annotations

import tkinter as tk

from bio_ce.ui.hub.data import MEMORIES
from bio_ce.ui.i18n import t

TYPING_CLASSES = {"Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox"}


class HubKeys:
    def __init__(self, hub) -> None:
        self.hub = hub
        self.app = hub.app
        root = self.app.root
        for sequence, action in (("<KeyPress-e>", self.edit), ("<KeyPress-E>", self.edit),
                                 ("<KeyPress-m>", self.move), ("<KeyPress-M>", self.move),
                                 ("<Delete>", self.delete), ("<Escape>", self.escape),
                                 ("<Control-z>", self.undo), ("<Control-s>", self.save),
                                 ("<Control-e>", self.edit_any), ("<Control-h>", self.history)):
            root.bind(sequence, lambda event, a=action: self._run(event, a), add="+")

    def typing(self) -> bool:
        try:
            widget = self.app.root.focus_get()
        except (KeyError, tk.TclError):
            return False
        return widget is not None and widget.winfo_class() in TYPING_CLASSES

    def _run(self, _event, action) -> str | None:
        if self.app.current is not self.hub or self.app.root.grab_current() is not None:
            return None
        action()
        return "break"

    def _memory_items(self):
        return [item for item in self.hub.chosen_items() if item.state == MEMORIES]

    def edit(self) -> None:
        if not self.typing():
            self.edit_any()

    def edit_any(self) -> None:
        hub = self.hub
        if hub.drawer.editing:
            return
        items = self._memory_items()
        if len(items) == 1:
            hub.edit_item(items[0])
        elif hub.drawer.mode == MEMORIES:
            hub.drawer.start_edit()
        else:
            self.app.notify("info", t("hub.select_first"))

    def move(self) -> None:
        if self.typing():
            return
        items = self.hub.chosen_items()
        if items:
            card = self.hub.grid.cards.get(self.hub.focus_key or "") or self.hub.drawer.move_button
            self.hub.move_menu(items, card)

    def delete(self) -> None:
        if not self.typing():
            items = self.hub.chosen_items()
            if items:
                self.hub.delete_items(items)

    def escape(self) -> None:
        hub = self.hub
        if self.typing():
            return  # the box handles Esc itself (the form cancels, the search box clears)
        if hub.drawer_open:
            if hub.drawer.editing:
                hub.drawer.editor.cancel_edit()
            else:
                hub.close_drawer()

    def undo(self) -> None:
        if self.typing():
            return
        if self.app.pending.undo():
            self.hub.refresh()

    def save(self) -> None:
        if self.hub.drawer_open and self.hub.drawer.editing:
            self.hub.drawer.editor.save_memory()

    def history(self) -> None:
        if self.hub.drawer.mode == MEMORIES:
            self.hub.show_history()


__all__ = ["HubKeys", "TYPING_CLASSES"]
