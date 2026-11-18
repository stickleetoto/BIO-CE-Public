# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Cards of the unified memory screen (v0.4.4 §2.2, §3.1): an elided one-line title, two lines of text, the space and
time, and Edit / Move / Delete buttons that show while the pointer is on the card or the card has keyboard focus."""

from __future__ import annotations

import tkinter as tk

from bio_ce.ui.format import body_without_title
from bio_ce.ui.hub.common import space_label, when
from bio_ce.ui.hub.data import INBOX, MEMORIES, RETRACTED
from bio_ce.ui.i18n import t
from bio_ce.ui.theme import SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import Button, ClampLabel, ElideLabel, pointer_inside, surface_of

PAGE = 60  # cards made at once; "Show more" adds the next ones (hundreds of Tk cards are slow to build)


class HubCard(tk.Frame):
    """One memory or inbox item. ``hub`` handles clicks, keys, and drags (see page.py and dragdrop.py)."""

    def __init__(self, master: tk.Misc, hub, item) -> None:
        theme, c = hub.theme, hub.colors
        super().__init__(master, background=c.surface, highlightthickness=theme.px(1),
                         highlightbackground=c.border, highlightcolor=c.focus, takefocus=1, cursor="hand2")
        self.hub = hub
        self.theme = theme
        self.item = item
        self.selected = False
        self.opened = False
        body = tk.Frame(self, background=c.surface)
        body.pack(fill="both", expand=True, padx=theme.px(SPACE_M), pady=theme.px(SPACE_M))
        self.body = body
        self.title_label = ElideLabel(body, text=item.title or t("hub.card.untitled"),
                                      font=theme.font("body_strong"), background=c.surface, foreground=c.text,
                                      width=1)
        self.title_label.pack(fill="x")
        # The title once: a body that repeats it shows only the rest, or nothing (rc3, owner 2026-11-18).
        shown = " ".join(body_without_title(item.title, item.text).split())
        self.text_label = ClampLabel(body, theme, text=shown or t("hub.card.no_text"),
                                     max_lines=2, font=theme.font("caption"), foreground=c.text_secondary)
        if shown or not (item.text or "").strip():
            self.text_label.pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        meta = space_label(item.space)  # the same name as the chips and the drawer (rc3)
        stamp = when(item.when)
        if item.state == RETRACTED and stamp:
            stamp = t("hub.retracted.when", when=stamp)
        self.meta_label = ElideLabel(body, text=f"{meta} · {stamp}" if stamp else meta, font=theme.font("caption"),
                                     background=c.surface, foreground=c.text_muted, width=1)
        self.meta_label.pack(fill="x", pady=(theme.px(SPACE_XS), 0))

        # Hover / focus buttons, over the card's top right corner.
        self.bar = tk.Frame(self, background=c.surface)
        if item.state == RETRACTED:  # only "Forget completely" (owner decision 2026-11-16)
            specs = (("forget", t("hub.drawer.forget"), lambda: hub.forget_item(item)),)
        elif item.state == INBOX:
            specs =(("to_memories", t("hub.card.to_memories"), lambda: hub.do.to_memories(item)),
                     ("move", t("hub.card.move"), lambda: hub.move_menu([item], self)),
                     ("delete", t("hub.card.discard"), lambda: hub.delete_items([item])))
        else:
            specs = (("edit", t("hub.card.edit"), lambda: hub.edit_item(item)),
                     ("move", t("hub.card.move"), lambda: hub.move_menu([item], self)),
                     ("delete", t("hub.card.delete"), lambda: hub.delete_items([item])))
        self.buttons: dict[str, Button] = {}
        for key, text, command in specs:
            button = Button(self.bar, theme, text, variant="danger_subtle" if key in ("delete", "forget")
                            else "secondary",
                            command=command, size="small")
            button.pack(side="left", padx=(theme.px(SPACE_XS), 0))
            self.buttons[key] = button
        gates = {"edit": "edit", "move": "edit", "delete": "retract" if item.state == MEMORIES else "review",
                 "to_memories": "review", "forget": "retract"}
        for key, button in self.buttons.items():
            hub.app.gate(button, gates[key])

        for part in (self, body, self.title_label, self.text_label, self.meta_label):
            part.bind("<Enter>", lambda _e: self.show_buttons(True), add="+")
            part.bind("<Leave>", lambda _e: self._left(), add="+")
            part.bind("<ButtonPress-1>", lambda e: hub.drag.press(self, e), add="+")
            part.bind("<B1-Motion>", lambda e: hub.drag.motion(e), add="+")
            part.bind("<ButtonRelease-1>", lambda e: hub.drag.release(self, e), add="+")
            part.bind("<Button-3>", lambda e: hub.context_menu_at(self, e), add="+")
        self.bind("<FocusIn>", lambda _e: (self.show_buttons(True), hub.card_focused(self)), add="+")
        self.bind("<FocusOut>", lambda _e: self._left(), add="+")
        self.bind("<Return>", lambda _e: (hub.open_card(self), "break")[1])
        self.bind("<KP_Enter>", lambda _e: (hub.open_card(self), "break")[1])
        self.bind("<space>", lambda _e: (hub.toggle_select(self), "break")[1])
        for key, step in (("<Left>", -1), ("<Right>", 1), ("<Up>", "up"), ("<Down>", "down")):
            self.bind(key, lambda _e, s=step: (hub.move_focus(self, s), "break")[1])
        self.bind("<Shift-F10>", lambda _e: (hub.context_menu_at(self, None), "break")[1])
        self.bind("<App>", lambda _e: (hub.context_menu_at(self, None), "break")[1])
        self._paint()

    @property
    def key(self) -> str:
        return self.item.key

    def buttons_shown(self) -> bool:
        return bool(self.bar.winfo_manager())

    def show_buttons(self, show: bool) -> None:
        if show:
            if not self.bar.winfo_manager():
                self.bar.place(relx=1.0, x=-self.theme.px(SPACE_S), y=self.theme.px(SPACE_XS), anchor="ne")
                self.bar.lift()
        elif self.bar.winfo_manager():
            self.bar.place_forget()

    def _left(self) -> None:
        try:
            focused = self.focus_get() is self
        except (KeyError, tk.TclError):
            focused = False
        if not focused and not pointer_inside(self):
            self.show_buttons(False)

    def set_state(self, *, selected: bool | None = None, opened: bool | None = None) -> None:
        if selected is not None:
            self.selected = selected
        if opened is not None:
            self.opened = opened
        self._paint()

    def set_drop_dim(self, dim: bool) -> None:
        self.configure(cursor="fleur" if dim else "hand2")

    def _paint(self) -> None:
        c = self.theme.colors
        # The opened card keeps the selection background too, so the eye follows it when the list makes room for
        # the drawer (POLISH §1.4).
        fill = c.selection if (self.selected or self.opened) else c.surface
        border = c.accent if (self.opened or self.selected) else c.border
        self.configure(highlightbackground=border, background=fill)
        for part in (self.body, self.title_label, self.text_label, self.meta_label, self.bar):
            part.configure(background=fill)


class CardGrid(tk.Frame):
    """Cards in as many columns as the width allows (§3.3); only the first ``PAGE`` are made until "Show more"."""

    def __init__(self, master: tk.Misc, hub) -> None:
        super().__init__(master, background=surface_of(master))
        self.hub = hub
        self.items: list = []
        self.cards: dict[str, HubCard] = {}
        self.columns = 1
        self.limit = PAGE
        self.grid_area = tk.Frame(self, background=surface_of(master))
        self.grid_area.pack(fill="x")
        self.more_button = Button(self, hub.theme, "", variant="subtle", command=self.show_more)

    def set_items(self, items: list, *, keep_limit: bool = False) -> None:
        for card in self.cards.values():
            card.destroy()
        self.cards = {}
        self.items = list(items)
        if not keep_limit:
            self.limit = PAGE
        for item in self.items[:self.limit]:
            self.cards[item.key] = HubCard(self.grid_area, self.hub, item)
        self.layout(self.columns, force=True)
        rest = len(self.items) - len(self.cards)
        if rest > 0:
            self.more_button.set_text(t("hub.show_more", count=min(rest, PAGE)))
            if not self.more_button.winfo_manager():
                self.more_button.pack(fill="x", pady=(self.hub.theme.px(SPACE_M), 0))
        else:
            self.more_button.pack_forget()

    def show_more(self) -> None:
        self.limit += PAGE
        self.set_items(self.items, keep_limit=True)

    def layout(self, columns: int, *, force: bool = False) -> None:
        if columns == self.columns and not force:
            return
        gap = self.hub.theme.px(SPACE_M)
        for index in range(max(self.columns, columns, 4)):
            self.grid_area.columnconfigure(index, weight=0, uniform="")
        self.columns = max(1, columns)
        for index, card in enumerate(self.cards.values()):
            row, column = divmod(index, self.columns)
            card.grid(row=row, column=column, sticky="nsew", padx=(0 if column == 0 else gap, 0),
                      pady=(0 if row == 0 else gap, 0))
        for column in range(self.columns):
            self.grid_area.columnconfigure(column, weight=1, uniform="card")

    def card_list(self) -> list[HubCard]:
        return list(self.cards.values())


__all__ = ["CardGrid", "HubCard", "PAGE"]
