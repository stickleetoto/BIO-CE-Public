# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""The unified memory screen (v0.4.4 §2.2): memories, the inbox, suggestions, and reviews on one page.

The search box is always on top, then the space chips (a filter that works with every state, and the targets of a
drag), then the state tabs with their counts, then cards in as many columns as the window allows. A card opens the
drawer; on a wide window (1600 px and more at 100%) the drawer pushes the cards aside, on a narrower one it lies over
them (owner decision Q2).
"""

from __future__ import annotations

import tkinter as tk

from bio_ce.engine.contract import EngineUnavailable, MemoryView, UnsupportedCapability
from bio_ce.ui.dialogs import HistoryDialog
from bio_ce.ui.format import format_timestamp, preview
from bio_ce.ui.hub.actions import HubActions
from bio_ce.ui.hub.cards import CardGrid
from bio_ce.ui.hub.common import (
    GAP,
    columns_for,
    control_of,
    drawer_width,
    fitting_columns,
    in_space,
    menu_style,
    space_label,
)
from bio_ce.ui.hub.data import (
    ALL_SPACES,
    INBOX,
    MEMORIES,
    RETRACTED,
    REVIEWS,
    STATES,
    SUGGESTIONS,
    HubData,
    HubItem,
)
from bio_ce.ui.hub import filters
from bio_ce.ui.hub.dragdrop import DragController
from bio_ce.ui.hub.drawer import Drawer
from bio_ce.ui.hub.filters import FilterBar
from bio_ce.ui.hub.keys import HubKeys
from bio_ce.ui.hub.quick import QuickAdd, SelectionBar, copy_items
from bio_ce.ui.hub.reviews import ReviewsView
from bio_ce.ui.hub.suggestions import SuggestionsView
from bio_ce.ui.i18n import t
from bio_ce.ui.pages import Page
from bio_ce.ui.theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from bio_ce.ui.widgets import Button, Card, EmptyState, FlowFrame, ScrollFrame, SearchBox, WrapLabel, section_label

TAB_KEYS = {MEMORIES: "hub.tab.memories", INBOX: "hub.tab.inbox", SUGGESTIONS: "hub.tab.suggestions",
            REVIEWS: "hub.tab.reviews"}


class HubPage(Page):
    key = "memories"
    nav_key = "memories"
    SEARCH_DELAY_MS = 300

    def __init__(self, app, master) -> None:
        super().__init__(app, master)
        theme, c = self.theme, self.colors
        self.data = HubData(app)
        self.do = HubActions(self)  # what the buttons do (``self.actions`` is the shell's header frame)
        self.drag = DragController(self)
        self.state = MEMORIES
        self.space_filter = ALL_SPACES
        self.counts: dict[str, int] = {state: 0 for state in STATES}
        self.items: list[HubItem] = []
        self.selected_keys: set[str] = set()
        self.open_key: str | None = None
        self.focus_key: str | None = None
        self.drop_highlight: set[str] = set()
        self.drop_over: str | None = None
        self._search_after: str | None = None
        self._spaces: list = []
        self._drawer_shown = False
        self.full_swap = False  # the drawer has the whole body (too narrow for a rail beside it)
        self._rail = False  # the list is a narrow rail beside the drawer: quick add and filters step aside

        # Toolbar: search, Add, Import…, Export… -------------------------------------------------------------
        toolbar = tk.Frame(self, background=c.bg)
        toolbar.pack(fill="x", pady=(0, theme.px(SPACE_L)))  # between areas 16, within an area 8 (POLISH §2.4)
        self.query = tk.StringVar(master=self)
        self.export_button = Button(toolbar, theme, t("hub.export"), variant="secondary",
                                    command=app.export_memories, tooltip=t("hub.export_tip"))
        self.export_button.pack(side="right", padx=(theme.px(SPACE_S), 0))
        self.import_button = Button(toolbar, theme, t("hub.import"), variant="secondary",
                                    command=lambda: app.show_page("import"), tooltip=t("hub.import_tip"))
        self.import_button.pack(side="right", padx=(theme.px(SPACE_S), 0))
        self.add_button = Button(toolbar, theme, t("hub.add"), icon="add", variant="primary",
                                 command=self.new_memory, tooltip=t("hub.add_tip"))
        self.add_button.pack(side="right", padx=(theme.px(SPACE_S), 0))
        app.gate(self.add_button, "create")
        app.gate(self.import_button, "create")
        app.gate(self.export_button, "browse")
        self.search = SearchBox(toolbar, theme, self.query, t("hub.search"), on_clear=self.refresh)
        self.search.pack(side="left", fill="x", expand=True)
        self.search.entry.bind("<Return>", lambda _e: self._search_now())
        self.search.entry.bind("<KP_Enter>", lambda _e: self._search_now())
        self.search.entry.bind("<Down>", lambda _e: self.focus_first_card())
        self.query.trace_add("write", lambda *_: self._schedule_search())

        # Space chips and state tabs ---------------------------------------------------------------------------
        self.chip_row = FlowFrame(self, gap=theme.px(SPACE_XS), background=c.bg)
        self.chip_row.pack(fill="x", pady=(0, theme.px(SPACE_S)))
        self.chip_caption = self.chip_row.add(tk.Label(self.chip_row, text=t("hub.space"), background=c.bg,
                                                       font=theme.font("caption_strong"), foreground=c.text_muted))
        self.chips: dict[str, Button] = {}
        # The tabs, then the folded filters and the sort (POLISH §3.3). They are the last item of the tabs' flow, so
        # on a narrow window or with wide text they go to the next line instead of squeezing the tabs into several
        # (the memory screen ran out of height for the drawer with 1.5× fonts).
        self.tab_bar = tk.Frame(self, background=c.bg)
        self.tab_bar.pack(fill="x")
        self.tab_row = FlowFrame(self.tab_bar, gap=theme.px(SPACE_XS), background=c.bg)
        self.tab_row.pack(side="left", fill="x", expand=True)
        self.tab_tools = tk.Frame(self.tab_row, background=c.bg)
        self.filter_toggle = Button(self.tab_tools, theme, t("hub.filter.toggle"), variant="chip", padx=10, pady=3,
                                    command=self.toggle_filters)
        self.filter_clear = Button(self.tab_tools, theme, t("hub.filter.clear"), variant="link",
                                   command=lambda: self.filter_bar.clear())
        self._filters_open = False
        # A line under the tabs ends the header part of the screen (POLISH §2.4): header → 16 → content.
        self.tab_rule = tk.Frame(self, height=1, background=c.border)
        self.tab_rule.pack(fill="x", pady=(0, theme.px(SPACE_L)))
        self.tabs: dict[str, Button] = {}
        for state in STATES:
            self.tabs[state] = self.tab_row.add(Button(self.tab_row, theme, t(TAB_KEYS[state]), variant="tab",
                                                       padx=10, command=lambda s=state: self.show_state(s)))
        # Retracted memories: a view reached from here, not a fifth tab (decision logged in the U1+U2 report).
        self.retracted_tab = self.tab_row.add(Button(self.tab_row, theme, t("hub.tab.retracted"), variant="link",
                                                     command=lambda: self.show_state(RETRACTED),
                                                     tooltip=t("hub.retracted.tip")))
        self.tab_row.set_visible(self.retracted_tab, False)
        self.result_label = self.tab_row.add(tk.Label(self.tab_row, text="", font=theme.font("caption"),
                                                      background=c.bg, foreground=c.text_muted))
        self.tab_row.add(self.tab_tools)

        # Content and drawer ------------------------------------------------------------------------------------
        self.body = tk.Frame(self, background=c.bg)
        self.body.pack(fill="both", expand=True)
        self.content = tk.Frame(self.body, background=c.bg)
        self.content.pack(side="left", fill="both", expand=True)
        self.drawer = Drawer(self.body, self)

        self.cards_view = tk.Frame(self.content, background=c.bg)
        # Above the cards (v0.4.4 U4): quick add (F5, Memories tab), filters and sort (F4), and the bar for several
        # chosen cards (F7).
        self.tools = tk.Frame(self.cards_view, background=c.bg)
        self.tools.pack(fill="x")
        self.quick_add = QuickAdd(self.tools, self)
        self.filter_bar = FilterBar(self.tools, app, lambda _view: self.refresh(), sort_parent=self.tab_tools)
        self.selection_bar = SelectionBar(self.tools, self)
        self._anchor_key: str | None = None
        self.cleanup = Card(self.cards_view, theme, padding=SPACE_L)
        section_label(self.cleanup.body, theme, t("hub.cleanup.title")).pack(fill="x")
        WrapLabel(self.cleanup.body, t("hub.cleanup.note"), font=theme.font("caption"),
                  foreground=c.text_secondary).pack(fill="x", pady=(theme.px(SPACE_XS), 0))
        self.cleanup_rows = tk.Frame(self.cleanup.body, background=c.surface)
        self.cleanup_rows.pack(fill="x", pady=(theme.px(SPACE_S), 0))
        self.scroll = ScrollFrame(self.cards_view, theme)
        self.grid = CardGrid(self.scroll.body, self)
        self.grid.pack(fill="x")
        self.empty_all = EmptyState(
            self.cards_view, theme, icon="memories", title=t("hub.empty.title"), message=t("hub.empty.message"),
            actions=((t("hub.add"), self.new_memory, "primary"),
                     (t("hub.empty.restore"), app.restore_database, "secondary")))
        self.no_results = EmptyState(self.cards_view, theme, icon="search", title=t("hub.empty.no_match"),
                                     message=t("hub.empty.no_match_message"),
                                     actions=((t("hub.empty.clear"), self.search.clear, "secondary"),))
        self.empty_space = EmptyState(self.cards_view, theme, icon="memories", title=t("hub.empty.space"),
                                      message=t("hub.empty.space_message"),
                                      actions=((t("hub.add"), self.new_memory, "primary"),))
        self.empty_inbox = EmptyState(self.cards_view, theme, icon="memories", title=t("hub.empty.inbox"),
                                      message=t("hub.empty.inbox_message"),
                                      actions=((t("hub.empty.open_connections"),
                                                lambda: app.show_page("connections"), "secondary"),
                                               (t("hub.import"), lambda: app.show_page("import"), "secondary")))
        self.empty_retracted = EmptyState(self.cards_view, theme, icon="retract", title=t("hub.retracted.empty"),
                                          message=t("hub.retracted.empty_message"),
                                          actions=((t("hub.retracted.back"), lambda: self.show_state(MEMORIES),
                                                    "secondary"),))
        self.suggestions = SuggestionsView(self.content, self)
        self.reviews = ReviewsView(self.content, self)
        self.keys = HubKeys(self)
        self.bind("<Configure>", lambda _e: self.after_idle(self.relayout), add="+")

    # Shell ------------------------------------------------------------------------------------------------------

    @property
    def title(self) -> str:  # type: ignore[override]
        return t("nav.memories")

    @property
    def subtitle(self) -> str:  # type: ignore[override]
        return t("hub.subtitle")

    def heading(self) -> tuple[str, str]:
        return self.title, self.subtitle

    def focus_default(self) -> None:
        if self.drawer_open and self.drawer.editing:
            self.drawer.editor.focus_default()
        else:
            self.search.focus_set()

    def confirm_leave(self) -> bool:
        return not self.drawer.editing or self.drawer.editor.confirm_leave()

    # Data -------------------------------------------------------------------------------------------------------

    def _schedule_search(self) -> None:
        if self._search_after is not None:
            self.after_cancel(self._search_after)
        self._search_after = self.after(self.SEARCH_DELAY_MS, self._search_now)

    def _search_now(self) -> str:
        if self._search_after is not None:
            self.after_cancel(self._search_after)
            self._search_after = None
        self.refresh()
        return "break"

    def refresh(self, select: str | None = None) -> None:
        super().refresh()
        if self._search_after is not None:
            self.after_cancel(self._search_after)
            self._search_after = None
        self._render_chips()
        engine_ok = True
        try:
            self.app.memory_engine()
        except (EngineUnavailable, UnsupportedCapability):
            engine_ok = False  # never another engine's memories in place of the selected one
            self.app.notify("error", t("hub.engine_down"), title=t("hub.engine_down_title"))
        try:
            self.counts = self.data.counts(self.space_filter)
        except (EngineUnavailable, UnsupportedCapability):
            if engine_ok:
                self.app.notify("error", t("hub.engine_down"), title=t("hub.engine_down_title"))
            self.counts = {state: 0 for state in STATES}
        except Exception:  # noqa: BLE001 - a count must never break the screen
            self.app.notify("error", t("hub.read_failed"), title=t("hub.read_failed_title"))
            self.counts = {state: 0 for state in STATES}
        for state, button in self.tabs.items():
            count = self.counts.get(state, 0)
            button.set_text(f"{t(TAB_KEYS[state])} {count:,}")
            button.set_variant("tab_selected" if state == self.state else "tab")
        retracted = self.data.retracted_count(self.space_filter)
        self.retracted_tab.set_text(f"{t('hub.tab.retracted')} {retracted:,}")
        self.tab_row.set_visible(self.retracted_tab, bool(retracted) or self.state == RETRACTED)
        self.retracted_tab.set_variant("tab_selected" if self.state == RETRACTED else "link")
        self.tab_row.relayout()
        for view in (self.cards_view, self.suggestions, self.reviews):
            view.pack_forget()
        query = self.query.get().strip()
        if self.state in (MEMORIES, INBOX, RETRACTED):
            self.cards_view.pack(fill="both", expand=True)
            try:
                found = self.data.items(self.state, self.space_filter, query)
                view = self.filter_bar.view
                self.items = filters.apply(found, view, filters.facts_for(self.app, found, view))
            except Exception:  # noqa: BLE001
                self.items = []
            self.selected_keys &= {item.key for item in self.items}
            self._show_tools()
            self.grid.set_items(self.items)
            self._render_cleanup()
            self._empty_states(query)
            for card in self.grid.card_list():
                card.set_state(selected=card.key in self.selected_keys, opened=card.key == self.open_key)
        elif self.state == SUGGESTIONS:
            self.items = []
            self.suggestions.pack(fill="both", expand=True)
            self.suggestions.refresh()
        else:
            self.reviews.pack(fill="both", expand=True)
            self.items = self.data.items(REVIEWS, self.space_filter, query)
            self.reviews.refresh(self.items)
        if query:
            self.result_label.configure(text=t("hub.results", count=len(self.items), query=preview(query, 40)))
        else:
            self.result_label.configure(text="")
        self._keep_drawer(select)
        self.after_idle(self.relayout)

    def _empty_states(self, query: str) -> None:
        for state in (self.empty_all, self.no_results, self.empty_space, self.empty_inbox, self.empty_retracted):
            state.pack_forget()
        if self.items:
            self.scroll.pack(fill="both", expand=True)
            return
        self.scroll.pack_forget()
        if query or filters.is_filtered(self.filter_bar.view):
            chosen = self.no_results
        elif self.state == RETRACTED:
            chosen = self.empty_retracted
        elif self.state == INBOX:
            chosen = self.empty_inbox
        elif self.space_filter == ALL_SPACES:
            chosen = self.empty_all
        else:
            chosen = self.empty_space
        chosen.pack(fill="both", expand=True)

    def _keep_drawer(self, select: str | None) -> None:
        if select is not None:
            item = next((i for i in self.items if i.item_id == select), None)
            if item is not None:
                self.open_item(item, force=True)
                return
        if not self.drawer_open or self.drawer.editing:
            return
        item = next((i for i in self.items if i.key == self.open_key), None)
        if item is None:
            self.close_drawer(force=True)
        else:
            self._show_in_drawer(item)  # re-read so it never shows a stale revision

    def _show_in_drawer(self, item: HubItem) -> bool:
        if item.state == MEMORIES:
            return self.drawer.show_memory(item)
        if item.state == RETRACTED:
            return self.drawer.show_retracted(item)
        return self.drawer.show_inbox(item)

    def _render_chips(self) -> None:
        spaces = list(self.app.spaces())
        ids = [ALL_SPACES] + [space.space_id for space in spaces]
        if [s.space_id for s in self._spaces] != ids[1:] or not self.chips:
            for chip in self.chips.values():
                chip.destroy()
            self.chips = {}
            for space_id, label in [(ALL_SPACES, t("space.all"))] + [(s.space_id, self._chip_label(s))
                                                                    for s in spaces]:
                chip = Button(self.chip_row, self.theme, label, variant="chip", padx=10, pady=3,
                              command=lambda sid=space_id: self.set_space_filter(sid))
                chip.space_id = space_id  # type: ignore[attr-defined]
                self.chips[space_id] = self.chip_row.add(chip)
        self._spaces = spaces
        if self.space_filter not in self.chips:
            self.space_filter = ALL_SPACES
        self.show_drop_targets(self.drop_highlight, over=self.drop_over)

    def _chip_label(self, space) -> str:
        label = space_label(space)
        return t("hub.chip.personal", space=label) if space.is_personal else label

    def _render_cleanup(self) -> None:
        theme, c = self.theme, self.colors
        for child in self.cleanup_rows.winfo_children():
            child.destroy()
        hidden = self.app.pending.hidden()
        proposals = [p for p in self.app.cleanup_proposals() if f"cleanup:{p['item_id']}" not in hidden]
        if self.state != INBOX or not proposals or not self.app.allowed("review").enabled:
            self.cleanup.pack_forget()
            return
        self.cleanup.pack(fill="x", pady=(0, theme.px(SPACE_M)), before=self.scroll)
        for proposal in proposals:
            row = tk.Frame(self.cleanup_rows, background=c.surface)
            row.pack(fill="x", pady=(theme.px(2), 0))
            due = format_timestamp(proposal.get("due_at") or "") if proposal.get("due_at") else t("hub.cleanup.soon")
            tk.Label(row, text=t("hub.cleanup.row", count=len(proposal["memory_ids"]), due=due),
                     font=theme.font("body"), background=c.surface, foreground=c.text, anchor="w").pack(side="left")
            Button(row, theme, t("hub.cleanup.discard_now"), variant="link",
                   command=lambda p=proposal: self.do.discard_proposal(p)).pack(side="right")
            Button(row, theme, t("hub.cleanup.keep"), variant="link",
                   command=lambda p=proposal: self.do.keep_proposal(p)).pack(side="right")

    # Layout -----------------------------------------------------------------------------------------------------

    def window_width(self) -> int:
        try:
            return int(self.winfo_toplevel().winfo_width())
        except tk.TclError:
            return 0

    def relayout(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        window = self.window_width()
        if window <= 1:
            return
        if self._drawer_shown:
            self._place_drawer(window)
        if self.full_swap:
            return
        if self._drawer_shown:
            # The list's width as §1.2 computes it, not as measured: measured, it is still the old width until Tk
            # has laid out the drawer, and the columns would change twice (the flicker §1.4 avoids).
            area = self.body.winfo_width() - int(self.drawer.cget("width")) - self.theme.px(GAP)
        else:
            area = self.scroll.canvas.winfo_width() if self.scroll.winfo_ismapped() else self.content.winfo_width()
        wanted = columns_for(window, self.theme)
        if area > 1:
            wanted = min(wanted, fitting_columns(area, self.theme))
        self.grid.layout(wanted)

    def _place_drawer(self, window: int) -> None:
        """Beside the list at every width (POLISH §1): the list keeps a rail, the drawer takes the rest up to its
        maximum; a body too narrow for both shows the drawer alone with "← List" (no size shows the drawer over the
        cards). The list is laid out again only when this changes something (§1.4: no flicker between cards)."""
        body = self.body.winfo_width()
        if body <= 1:
            body = self.window_width()
        width = drawer_width(body, window, self.theme)
        swap = width is None
        if swap != self.full_swap:
            self.full_swap = swap
            if swap:
                self.content.pack_forget()
            elif not self.content.winfo_manager():
                self.content.pack(side="left", fill="both", expand=True)
            self.drawer.show_back(swap)
        self.drawer.pack_propagate(False)
        if swap:
            if self.drawer.winfo_manager() == "pack":
                self.drawer.pack_configure(fill="both", expand=True, padx=0)
            else:
                self.drawer.pack(side="right", fill="both", expand=True)
        else:
            if int(self.drawer.cget("width")) != width:
                self.drawer.configure(width=width)
            if self.drawer.winfo_manager() != "pack":
                self.drawer.pack(side="right", fill="y", padx=(self.theme.px(GAP), 0), before=self.content)
            else:
                self.drawer.pack_configure(fill="y", expand=False, padx=(self.theme.px(GAP), 0))
        self._show_rail_tools()

    def _show_rail_tools(self) -> None:
        """While the drawer is open and the list is narrower than 520, quick add and the filters step aside; their
        values stay and they come back when the drawer closes (§1.5). The chips and tabs stay: dragging onto a chip
        still works."""
        rail = self._drawer_shown and not self.full_swap and \
            self.body.winfo_width() - int(self.drawer.cget("width")) - self.theme.px(GAP) < self.theme.px(520)
        if rail != self._rail:
            self._rail = rail
            if rail:
                for part in (self.quick_add, self.filter_bar):
                    part.pack_forget()
                self._shrink_empty_tools()
            else:
                self._show_tools()

    @property
    def drawer_open(self) -> bool:
        return self._drawer_shown

    def drawer_overlaps(self) -> bool:
        """True when the open drawer covers any part of the cards' area on screen (it never should, §1)."""
        if not self._drawer_shown or self.full_swap:
            return False
        try:
            self.update_idletasks()
            if not (self.drawer.winfo_ismapped() and self.content.winfo_ismapped()):
                return False
            left, right = self.content.winfo_rootx(), self.content.winfo_rootx() + self.content.winfo_width()
            d_left, d_right = self.drawer.winfo_rootx(), self.drawer.winfo_rootx() + self.drawer.winfo_width()
        except tk.TclError:
            return False
        return d_left < right and left < d_right

    def _show_drawer(self) -> None:
        self._drawer_shown = True
        self._place_drawer(max(self.window_width(), 1))
        self.after_idle(self.relayout)

    def close_drawer(self, force: bool = False) -> bool:
        if not self._drawer_shown:
            return True
        if not force and self.drawer.editing and not self.drawer.editor.confirm_leave():
            return False
        self._drawer_shown = False
        self.drawer.pack_forget()
        self.drawer.mode = None
        if self.full_swap:
            self.full_swap = False
            self.drawer.show_back(False)
            self.content.pack(side="left", fill="both", expand=True)
        self._show_rail_tools()
        old, self.open_key = self.open_key, None
        card = self.grid.cards.get(old) if old else None
        if card is not None:
            card.set_state(opened=False)
            card.focus_set()
        self.after_idle(self.relayout)
        return True

    def close_drawer_for(self, ids) -> None:
        if self.drawer.item is not None and self.drawer.item.item_id in set(ids):
            self.close_drawer(force=True)

    # Tabs and spaces --------------------------------------------------------------------------------------------

    def show_state(self, state: str) -> None:
        if state == self.state and not self.stale:
            return
        if self.drawer_open and not self.close_drawer():
            return
        self.state = state
        self.selected_keys = set()
        self.refresh()

    def set_space_filter(self, space_id: str) -> None:
        if space_id == self.space_filter:
            return
        if not self.app.require_action("browse"):
            return
        if self.drawer_open and not self.close_drawer():
            return
        self.space_filter = space_id
        if space_id != ALL_SPACES:
            self.app.set_space(space_id, refresh=False)  # new memories go to the chosen space
        self.selected_keys = set()
        self.refresh()

    def filter_space(self):
        return next((s for s in self.app.spaces() if s.space_id == self.space_filter), None)

    # Cards ------------------------------------------------------------------------------------------------------

    def item_of(self, card_or_key) -> HubItem | None:
        key = card_or_key if isinstance(card_or_key, str) else card_or_key.key
        return next((item for item in self.items if item.key == key), None)

    def _show_tools(self) -> None:
        """Quick add on the Memories tab, the filters where they apply, and the bar for several chosen cards."""
        theme = self.theme
        for part in (self.quick_add, self.filter_bar, self.selection_bar):
            part.pack_forget()
        if self.state == MEMORIES and self.app.allowed("create").enabled and not self._rail:
            self.quick_add.pack(fill="x", pady=(0, theme.px(SPACE_S)))
        if self.state in filters.FILTERED_STATES and not self._rail and self._filters_open:
            self.filter_bar.pack(fill="x", pady=(0, theme.px(SPACE_S)))
        self._render_filter_toggle()
        self._update_selection_bar()
        self._shrink_empty_tools()

    def toggle_filters(self) -> None:
        """"Filters ▾" opens the four filters above the cards and closes them (not remembered, POLISH §3.0 R5)."""
        self._filters_open = not self._filters_open
        self._show_tools()

    def _render_filter_toggle(self) -> None:
        """The folded filters never hide that they apply (R2): "Filters 2" in the accent color, and Clear."""
        shown = self.state in filters.FILTERED_STATES
        for part in (self.filter_toggle, self.filter_clear, self.filter_bar.sort_pair):
            part.pack_forget()
        self.tab_row.set_visible(self.tab_tools, shown)
        if shown:
            count = filters.active_count(self.filter_bar.view)
            arrow = "▴" if self._filters_open else "▾"
            label = t("hub.filter.toggle_count", count=count) if count else t("hub.filter.toggle")
            self.filter_toggle.set_text(f"{label} {arrow}")
            self.filter_toggle.set_variant("chip_selected" if count else "chip")
            self.filter_toggle.pack(side="left", padx=(self.theme.px(SPACE_M), 0))
            if count and not self._filters_open:
                self.filter_clear.pack(side="left", padx=(self.theme.px(SPACE_XS), 0))
            self.filter_bar.sort_pair.pack(side="left", padx=(self.theme.px(SPACE_M), 0))
        self.tab_row.relayout()

    def _shrink_empty_tools(self) -> None:
        # Tk keeps a frame at its last size when its last child is removed: an empty band stayed above the cards.
        if not self.tools.pack_slaves():
            self.tools.configure(height=1)

    def _update_selection_bar(self) -> None:
        chosen = [item for item in (self.item_of(key) for key in self.selected_keys) if item is not None]
        if self.selection_bar.show_for(chosen):
            if not self.selection_bar.winfo_manager():
                self.selection_bar.pack(fill="x", pady=(0, self.theme.px(SPACE_S)))
        elif self.selection_bar.winfo_manager():
            self.selection_bar.pack_forget()
            self._shrink_empty_tools()

    def clear_selection(self) -> None:
        self.selected_keys = set()
        for card in self.grid.card_list():
            card.set_state(selected=False)
        self._update_selection_bar()

    def card_clicked(self, card, *, toggle: bool = False, extend: bool = False) -> None:
        if extend and self._anchor_key in self.grid.cards:  # Shift+click: every card from the last one clicked
            order = [other.key for other in self.grid.card_list()]
            start, end = sorted((order.index(self._anchor_key), order.index(card.key)))
            self.selected_keys |= set(order[start:end + 1])
            for other in self.grid.card_list():
                other.set_state(selected=other.key in self.selected_keys)
            self._update_selection_bar()
            return
        self._anchor_key = card.key
        if toggle:
            self.toggle_select(card)
            return
        self.selected_keys = {card.key}
        for other in self.grid.card_list():
            other.set_state(selected=other.key in self.selected_keys)
        self._update_selection_bar()
        if self.open_key == card.key and self.drawer_open and not self.drawer.editing:
            self.close_drawer()
            return
        self.open_card(card)

    def toggle_select(self, card) -> None:
        if card.key in self.selected_keys:
            self.selected_keys.discard(card.key)
        else:
            self.selected_keys.add(card.key)
        card.set_state(selected=card.key in self.selected_keys)
        self._update_selection_bar()

    def card_focused(self, card) -> None:
        self.focus_key = card.key

    def open_card(self, card) -> bool:
        return self.open_item(card.item)

    def open_item(self, item: HubItem, *, force: bool = False) -> bool:
        if self.drawer.editing and not force and not self.drawer.editor.confirm_leave():
            return False
        if not self._show_in_drawer(item):
            return False
        old = self.grid.cards.get(self.open_key) if self.open_key else None
        if old is not None:
            old.set_state(opened=False)
        self.open_key = item.key
        card = self.grid.cards.get(item.key)
        if card is not None:
            card.set_state(opened=True)
        self._show_drawer()
        return True

    def move_focus(self, card, step) -> None:
        cards = self.grid.card_list()
        if card not in cards:
            return
        index = cards.index(card)
        delta = {"up": -self.grid.columns, "down": self.grid.columns}.get(step, step)
        target = index + int(delta)
        if 0 <= target < len(cards):
            cards[target].focus_set()
            self.scroll.scroll_to_widget(cards[target])

    def focus_first_card(self) -> str:
        cards = self.grid.card_list()
        if cards:
            cards[0].focus_set()
        return "break"

    def chosen_items(self) -> list[HubItem]:
        """The selected cards, else the focused one, else the one open in the drawer."""
        keys = list(self.selected_keys) or [key for key in (self.focus_key, self.open_key) if key]
        items = [self.item_of(key) for key in keys]
        return [item for item in items if item is not None]

    def drag_items(self, card) -> list[HubItem]:
        if card.key in self.selected_keys and len(self.selected_keys) > 1:
            return self.chosen_items()
        return [card.item]

    # Actions from cards and keys -------------------------------------------------------------------------------

    def forget_item(self, item: HubItem) -> bool:
        """Forget completely: a retracted memory with what it said last, a current one with its current revision."""
        if item.state == RETRACTED:
            return self.do.forget(item, item.record.last)
        if item.state == MEMORIES and self.open_item(item):
            return self.do.forget(item, self.drawer.record)
        return False

    def delete_items(self, items: list[HubItem]) -> bool:
        if len(items) == 1 and items[0].key in self.selected_keys and len(self.selected_keys) > 1:
            items = self.chosen_items()
        return self.do.delete(items)

    def edit_item(self, item: HubItem) -> None:
        if self.open_item(item):
            self.drawer.start_edit()

    def move_targets(self, items: list[HubItem]) -> list:
        sources = {item.space.space_id for item in items if item.space is not None}
        return [space for space in self.app.spaces() if not (sources == {space.space_id})]

    def move_menu(self, items: list[HubItem], anchor) -> tk.Menu | None:
        if len(items) == 1 and items[0].key in self.selected_keys and len(self.selected_keys) > 1:
            items = self.chosen_items()
        if not items or not self.app.require_action("edit"):
            return None
        targets = self.move_targets(items)
        if not targets:
            self.app.notify("info", t("hub.move.nowhere"), title=t("hub.move.nowhere_title"))
            return None
        menu = tk.Menu(self, **menu_style(self.theme))
        for space in targets:
            menu.add_command(label=space_label(space), command=lambda s=space: self.do.move(items, s))
        try:
            menu.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())
        except tk.TclError:
            pass
        return menu

    def context_menu(self, items: list[HubItem]) -> tk.Menu:
        style = menu_style(self.theme)
        menu = tk.Menu(self, **style)
        single = "normal" if len(items) == 1 else "disabled"
        allowed = self.app.allowed
        if items and items[0].state == INBOX:
            menu.add_command(label=t("hub.card.to_memories"), command=lambda: self.do.to_memories(items[0]),
                             state=single if allowed("review").enabled else "disabled")
        else:
            menu.add_command(label=t("hub.card.edit"), command=lambda: self.edit_item(items[0]),
                             state=single if allowed("edit").enabled else "disabled")
            menu.add_command(label=t("hub.drawer.history"), command=lambda: (
                self.open_item(items[0]) and self.drawer.open_history()),
                state=single if allowed("history").enabled else "disabled")
        spaces = tk.Menu(menu, **style)
        for space in self.move_targets(items):
            spaces.add_command(label=space_label(space), command=lambda s=space: self.do.move(items, s))
        menu.add_cascade(label=t("hub.menu.move_to"), menu=spaces,
                         state="normal" if items and spaces.index("end") is not None and allowed("edit").enabled
                         else "disabled")
        if items and all(item.state in (MEMORIES, INBOX) for item in items):
            menu.add_command(label=t("hub.copy"), command=lambda: copy_items(self.app, items))
        menu.add_separator()
        delete = t("hub.card.discard") if items and items[0].state == INBOX else t("hub.card.delete")
        menu.add_command(label=delete, command=lambda: self.do.delete(items),
                         state="normal" if items else "disabled")
        if items and items[0].state == MEMORIES and hasattr(self.app.service, "forget"):
            menu.add_command(label=t("hub.drawer.forget"), state=single,
                             command=lambda: self.open_item(items[0]) and self.do.forget(
                                 self.drawer.item, self.drawer.record))
        return menu

    def context_menu_at(self, card, event) -> None:
        if card.key not in self.selected_keys:
            self.selected_keys = {card.key}
            for other in self.grid.card_list():
                other.set_state(selected=other.key in self.selected_keys)
        menu = self.context_menu(self.chosen_items() or [card.item])
        x = event.x_root if event is not None else card.winfo_rootx() + self.theme.px(20)
        y = event.y_root if event is not None else card.winfo_rooty() + self.theme.px(20)
        try:
            menu.tk_popup(x, y)
        except tk.TclError:
            pass

    # Drag and drop --------------------------------------------------------------------------------------------

    def drop_targets(self, items: list[HubItem]) -> set[str]:
        if not items or any(item.state not in (MEMORIES, INBOX) for item in items):
            return set()
        return {space.space_id for space in self.move_targets(items) if space.space_id in self.chips}

    def show_drop_targets(self, targets: set[str], *, over: str | None = None) -> None:
        self.drop_highlight, self.drop_over = set(targets), over
        for space_id, chip in self.chips.items():
            if targets:
                chip.set_variant("primary" if space_id == over else "secondary" if space_id in targets else "chip")
                chip.set_enabled(space_id in targets)
            else:
                chip.set_enabled(True)
                chip.set_variant("chip_selected" if space_id == self.space_filter else "chip")

    def chip_at(self, x: int, y: int) -> str | None:
        try:
            widget = self.winfo_containing(x, y)
        except (KeyError, tk.TclError):
            return None
        while widget is not None:
            space_id = getattr(widget, "space_id", None)
            if space_id is not None and widget in self.chips.values():
                return space_id
            widget = widget.master
        return None

    def drop(self, items: list[HubItem], space_id: str) -> int | None:
        target = next((s for s in self.app.spaces() if s.space_id == space_id), None)
        if target is None:
            return None
        return self.do.move(items, target)

    # New, saved, history ---------------------------------------------------------------------------------------

    def new_memory(self) -> None:
        if not self.app.require_action("create"):
            return
        if self.drawer.editing and self.drawer.editor.editing is None and self.drawer_open:
            self.drawer.editor.focus_default()
            return
        if self.drawer.editing and not self.drawer.editor.confirm_leave():
            return
        if self.app.current is not self:
            self.app.show_page("memories")
        space = self.filter_space() or self.app.current_space()
        old = self.grid.cards.get(self.open_key) if self.open_key else None
        if old is not None:
            old.set_state(opened=False)
        self.open_key = None
        self.drawer.start_new(space)
        self._show_drawer()

    def editor_closed(self) -> None:
        """Cancel in the form: back to the memory it edited, or closed for a new one."""
        item = self.drawer.item
        if self.drawer.mode == "edit" and item is not None:
            self.drawer.show_memory(item)
        else:
            self.close_drawer(force=True)

    def memory_saved(self, saved: MemoryView, *, created: bool, space) -> None:
        self.query.set("")
        if self.state != MEMORIES:
            self.state = MEMORIES
        self.app.data_changed()
        self.refresh(select=saved.memory_id)
        title = t("hub.saved.new") if created else t("hub.saved.revision", number=saved.revision_number)
        self.app.notify("success", t("hub.saved.where", title=preview(saved.title, 60), space=space_label(space)),
                        title=title)

    def open_memory(self, memory_id: str) -> None:
        if self.drawer.editing and not self.drawer.editor.confirm_leave():
            return
        self.state = MEMORIES
        self.query.set("")
        self.refresh(select=memory_id)

    def select(self, memory_id: str) -> None:
        self.open_memory(memory_id)

    def show_history(self) -> HistoryDialog | None:
        record, item = self.drawer.record, self.drawer.item
        if record is None or item is None:
            self.app.notify("info", t("hub.select_first"))
            return None
        if not self.app.require_action("history"):
            return None
        try:
            with in_space(self.app, item.space):
                revisions = self.app.memory_engine().history(record.memory_id)
        except Exception:  # noqa: BLE001
            self.app.notify("error", t("hub.drawer.history_failed"), title=t("hub.drawer.history_failed_title"))
            return None
        proposal = self.suggestion_result_of(item)
        undo = (lambda: self.suggestions.undo([proposal])) if proposal is not None else None
        self.history_dialog = HistoryDialog(self, self.theme, revisions, undo=undo).show()
        return self.history_dialog

    def suggestion_result_of(self, item: HubItem | None) -> int | None:
        service = self.suggestions.curation()
        if service is None or item is None or item.space is None:
            return None
        try:
            return service.result_of(item.space.curated, item.item_id)
        except Exception:  # noqa: BLE001
            return None

    def merge_proposal_of(self, item: HubItem) -> int | None:
        revision = item.record
        if revision is None or not revision.source.metadata.get("merged_from") or item.space is None:
            return None
        service = self.suggestions.curation()
        if service is None:
            return None
        return service.result_of(item.space.inbox, item.item_id)

    @property
    def selected(self) -> MemoryView | None:
        return self.drawer.record if self.drawer.mode == MEMORIES or self.drawer.mode == "edit" else None

    @property
    def control(self):
        return control_of(self.app)


__all__ = ["HubPage", "TAB_KEYS"]
