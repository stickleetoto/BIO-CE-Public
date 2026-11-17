# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Design tokens and ttk styling for the BIO CE desktop UI.

Every color, font, and spacing value used by the UI comes from this module so
the look stays consistent. Spacing values are logical pixels at 100% Windows
scaling; use :meth:`Theme.px` to convert them for the current DPI. Font sizes
are points, which Tk already scales with the display DPI.
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from bio_ce.ui.i18n import language


@dataclass(frozen=True, slots=True)
class Palette:
    """Graphite dark palette. Text colors meet WCAG AA on ``surface``."""

    # Background layers (POLISH §2.3): the window, then cards, then the drawer, menus and notices one layer brighter,
    # then fields. rc1's layers were 1.08-1.23 apart from the window, so areas told apart only by 1 px lines.
    bg: str = "#0f1013"
    sidebar: str = "#17191d"
    surface: str = "#202328"
    surface_raised: str = "#282c33"
    surface_alt: str = "#2d3139"
    surface_hover: str = "#343943"
    surface_active: str = "#3c424d"
    border: str = "#2b2f36"
    border_strong: str = "#4a505c"
    text: str = "#e6e8eb"
    text_secondary: str = "#a6acb5"
    text_muted: str = "#969da7"
    text_disabled: str = "#5d636c"
    accent: str = "#3b6fd4"
    accent_hover: str = "#4a7cdf"
    accent_pressed: str = "#3263c2"
    accent_text: str = "#8aaef5"
    on_accent: str = "#ffffff"
    selection: str = "#253655"
    chip_border: str = "#35508a"  # a chosen space chip (POLISH §2.2)
    focus: str = "#8aaef5"
    success: str = "#5cbf8f"
    success_bg: str = "#1a2e25"
    warning: str = "#e2ac4c"
    warning_bg: str = "#33291a"
    danger: str = "#ef7a73"
    danger_bg: str = "#3a2022"
    danger_solid: str = "#b83b36"
    danger_solid_hover: str = "#c8453f"
    danger_solid_pressed: str = "#a3332f"
    info: str = "#8aaef5"
    info_bg: str = "#1e2a3f"


def raised(colors: Palette) -> Palette:
    """The palette for a raised panel (the drawer, POLISH §2.3): its "surface" is ``surface_raised``, so a panel built
    with it reads as one layer above the cards beside it."""
    from dataclasses import replace

    return replace(colors, surface=colors.surface_raised)


SPACE_XS = 4
SPACE_S = 8
SPACE_M = 12
SPACE_L = 16
SPACE_XL = 24
SPACE_XXL = 32

SIDEBAR_WIDTH = 232
SIDEBAR_COMPACT_WIDTH = 60
SIDEBAR_COMPACT_BELOW = 1000
READING_MAX_WIDTH = 760
# v0.4.4 §3.3 (100% scale): from CENTER_FROM window width the pages keep to CONTENT_MAX_WIDTH, centred, so a big
# screen has no long lines or one-sided empty space; from RECENT_TWO_COLUMNS_FROM the dashboard's recent memories
# use two columns.
CONTENT_MAX_WIDTH = 1960
CENTER_FROM = 2200
RECENT_TWO_COLUMNS_FROM = 1600

_FONT_CHOICES = {
    "body": (("Segoe UI Variable Text", "Segoe UI"), 10, "normal"),
    "body_strong": (("Segoe UI Variable Text Semibold", "Segoe UI Semibold"), 10, "normal"),
    "reading": (("Segoe UI Variable Text", "Segoe UI"), 11, "normal"),
    "caption": (("Segoe UI Variable Small", "Segoe UI"), 9, "normal"),
    "caption_strong": (("Segoe UI Variable Small Semibol", "Segoe UI Semibold"), 9, "normal"),
    "section": (("Segoe UI Variable Text Semibold", "Segoe UI Semibold"), 12, "normal"),
    "title": (("Segoe UI Variable Display Semib", "Segoe UI Semibold"), 15, "normal"),
    "display": (("Segoe UI Variable Display Semib", "Segoe UI Semibold"), 20, "normal"),
    "stat": (("Segoe UI Variable Display Semib", "Segoe UI Semibold"), 24, "normal"),
    "brand": (("Segoe UI Variable Display Semib", "Segoe UI Semibold"), 14, "normal"),
    "mono": (("Cascadia Mono", "Consolas", "Courier New"), 9, "normal"),
}
_ICON_FAMILIES = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
_STRONG_FONTS = {"body_strong", "caption_strong", "section", "title", "display", "stat", "brand"}

# Segoe Fluent Icons / Segoe MDL2 Assets code points (shared by both fonts).
ICONS = {
    "dashboard": "",
    "memories": "",
    "connections": "",
    "settings": "",
    "add": "",
    "search": "",
    "edit": "",
    "history": "",
    "retract": "",
    "refresh": "",
    "copy": "",
    "folder": "",
    "close": "",
    "check": "",
    "success": "",
    "error": "",
    "warning": "",
    "info": "",
    "lock": "",
    "shield": "",
    "terminal": "",
    "diagnostics": "",
    "backup": "",
    "restore": "",
    "document": "",
    "keyboard": "",
    "back": "",
    "chevron_down": "",
    "chevron_right": "",
    "dot": "",
}


class Theme:
    """Fonts, DPI scale, and ttk styles bound to one Tk interpreter."""

    def __init__(self, root: tk.Misc, palette: Palette | None = None) -> None:
        self.root = root
        self.colors = palette or Palette()
        self.scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
        families = set(tkfont.families(root))
        missing = tkfont.Font(root=root, family="BIO CE missing font probe", size=10).actual("family")

        def available(family: str) -> bool:
            # Localized Windows lists some families under translated names, so also test resolution.
            return family in families or tkfont.Font(root=root, family=family, size=10).actual("family") != missing

        # Tk cannot use Windows font linking, so CJK text falls back to an arbitrary font. One family for all text
        # renders mixed scripts evenly: Malgun Gothic in both app languages (owner decision Q7: memories in English
        # Windows often hold Korean), or the Windows UI font of a Japanese or Chinese Windows in the English app.
        cjk_family = next((choice for choice in text_font_families(language()) if available(choice)), None)
        self.text_family = cjk_family
        self.fonts: dict[str, tkfont.Font] = {}
        for name, (choices, size, weight) in _FONT_CHOICES.items():
            if cjk_family is not None and name != "mono":
                family, weight = cjk_family, "bold" if name in _STRONG_FONTS else weight
            else:
                family = next((choice for choice in choices if available(choice)), "TkDefaultFont")
            self.fonts[name] = tkfont.Font(root=root, family=family, size=size, weight=weight)
        icon_family = next((choice for choice in _ICON_FAMILIES if available(choice)), None)
        self.has_icons = icon_family is not None
        self.icon_fonts: dict[str, tkfont.Font] = {}
        if icon_family is not None:
            for name, size in (("small", 9), ("normal", 11), ("large", 15), ("hero", 28)):
                self.icon_fonts[name] = tkfont.Font(root=root, family=icon_family, size=size)
        self.style = ttk.Style(root)
        self._scrollbar_styles: dict[str, str] = {}
        self._configure_ttk()
        root.configure(background=self.colors.bg)
        root.option_add("*Font", self.fonts["body"])
        root.option_add("*TCombobox*Listbox.font", self.fonts["body"])

    def px(self, value: float) -> int:
        """Convert logical pixels at 100% scaling to device pixels."""
        return int(round(value * self.scale))

    def font(self, name: str) -> tkfont.Font:
        return self.fonts[name]

    def icon(self, name: str) -> str:
        return ICONS[name] if self.has_icons else ""

    def icon_font(self, size: str = "normal") -> tkfont.Font | None:
        return self.icon_fonts.get(size)

    def scrollbar_style(self, trough: str) -> str:
        """Return a thin, arrowless vertical scrollbar style for one background."""
        if trough in self._scrollbar_styles:
            return self._scrollbar_styles[trough]
        name = f"T{len(self._scrollbar_styles)}.BIO.Vertical.TScrollbar"
        c = self.colors
        self.style.layout(
            name,
            [("Vertical.Scrollbar.trough", {
                "sticky": "ns",
                "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
            })],
        )
        self.style.configure(
            name,
            troughcolor=trough,
            background=c.border_strong,
            bordercolor=trough,
            lightcolor=c.border_strong,
            darkcolor=c.border_strong,
            arrowsize=self.px(9),
            gripcount=0,
            relief="flat",
        )
        self.style.map(
            name,
            background=[("pressed", c.text_muted), ("active", c.text_disabled)],
            lightcolor=[("pressed", c.text_muted), ("active", c.text_disabled)],
            darkcolor=[("pressed", c.text_muted), ("active", c.text_disabled)],
        )
        self._scrollbar_styles[trough] = name
        return name

    def _configure_ttk(self) -> None:
        c = self.colors
        style = self.style
        style.theme_use("clam")
        style.configure(
            ".",
            background=c.bg,
            foreground=c.text,
            fieldbackground=c.surface_alt,
            bordercolor=c.border,
            lightcolor=c.surface,
            darkcolor=c.surface,
            troughcolor=c.surface_alt,
            focuscolor=c.focus,
            selectbackground=c.selection,
            selectforeground=c.text,
            insertcolor=c.text,
            font=self.fonts["body"],
        )
        style.configure("TFrame", background=c.bg)

        style.layout("BIO.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "BIO.Treeview",
            background=c.surface,
            fieldbackground=c.surface,
            foreground=c.text,
            bordercolor=c.surface,
            lightcolor=c.surface,
            darkcolor=c.surface,
            rowheight=self.px(34),
            font=self.fonts["body"],
            indent=0,
        )
        style.map(
            "BIO.Treeview",
            background=[("selected", "focus", c.selection), ("selected", c.surface_active)],
            foreground=[("selected", c.text), ("disabled", c.text_disabled)],
        )
        style.configure(
            "BIO.Treeview.Heading",
            background=c.surface,
            foreground=c.text_muted,
            bordercolor=c.surface,
            lightcolor=c.surface,
            darkcolor=c.surface,
            relief="flat",
            font=self.fonts["caption_strong"],
            padding=(self.px(10), self.px(6)),
        )
        style.map("BIO.Treeview.Heading", background=[("active", c.surface)], relief=[("pressed", "flat")])
        style.configure("BIO.Treeview.Item", padding=(self.px(10), 0))

        style.configure(
            "BIO.Horizontal.TProgressbar",
            troughcolor=c.surface_alt,
            background=c.accent_text,
            bordercolor=c.surface_alt,
            lightcolor=c.accent_text,
            darkcolor=c.accent_text,
            thickness=self.px(3),
        )
        style.configure(
            "BIO.TCombobox",
            fieldbackground=c.surface_alt,
            background=c.surface_alt,
            foreground=c.text,
            arrowcolor=c.text_secondary,
            bordercolor=c.border_strong,
            lightcolor=c.surface_alt,
            darkcolor=c.surface_alt,
            padding=(self.px(8), self.px(4)),
        )
        style.map(
            "BIO.TCombobox",
            fieldbackground=[("disabled", c.surface), ("readonly", c.surface_alt)],
            background=[("disabled", c.surface), ("active", c.surface_active), ("readonly", c.surface_alt)],
            foreground=[("disabled", c.text_disabled), ("readonly", c.text)],
            selectbackground=[("readonly", c.surface_alt)],
            selectforeground=[("readonly", c.text)],
            arrowcolor=[("disabled", c.text_disabled)],
        )
        style.configure("BIO.TPanedwindow", background=c.bg)
        style.configure("Sash", sashthickness=self.px(SPACE_M), gripcount=0, background=c.bg, bordercolor=c.bg,
                        lightcolor=c.bg, darkcolor=c.bg)


def text_font_families(app_language: str | None = None) -> tuple[str, ...]:
    """The text font candidates (v0.4.4, owner decision Q7): Malgun Gothic for the Korean and the English app, so
    Korean memory text never falls back to an arbitrary font; in the English app on a Japanese or Chinese Windows,
    that Windows UI font first (Malgun Gothic after it). The theme is made before the app reads a language the user
    chose, so a Korean app on a Japanese or Chinese Windows gets the Windows font (known limitation)."""
    windows = cjk_ui_fonts()
    if app_language != "ko" and windows and windows != ("Malgun Gothic",):
        return windows + ("Malgun Gothic",)
    return ("Malgun Gothic",)


def cjk_ui_fonts() -> tuple[str, ...]:
    """UI font candidates for a Korean, Japanese, or Chinese Windows user, else ()."""
    if sys.platform != "win32":
        return ()
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        language_ids = (int(kernel32.GetUserDefaultUILanguage()), int(kernel32.GetUserDefaultLCID()) & 0xFFFF)
    except Exception:
        return ()
    for language_id in language_ids:
        primary, sublanguage = language_id & 0x3FF, language_id >> 10
        if primary == 0x12:
            return ("Malgun Gothic",)
        if primary == 0x11:
            return ("Yu Gothic UI", "Meiryo UI")
        if primary == 0x04:
            simplified = sublanguage in (0x02, 0x04)
            return ("Microsoft YaHei UI",) if simplified else ("Microsoft JhengHei UI",)
    return ()


def enable_windows_dpi_awareness() -> None:
    """Opt the process into system DPI awareness so Tk renders crisply.

    Must run before the first ``tk.Tk()``. Failures are ignored because the
    UI still works when Windows bitmap-scales it.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def apply_window_chrome(window: tk.Misc, colors: Palette) -> None:
    """Ask Windows 11 for a dark title bar that matches the sidebar color."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        window.update_idletasks()
        hwnd = wintypes.HWND(int(window.wm_frame(), 16))
        dwm = ctypes.windll.dwmapi
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, pre-20H1)
            if dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0:
                break
        caption = colors.sidebar.lstrip("#")
        colorref = ctypes.c_int(int(caption[4:6] + caption[2:4] + caption[0:2], 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), ctypes.sizeof(colorref))
    except Exception:
        pass


def app_icon(window: tk.Misc, colors: Palette) -> tk.PhotoImage | None:
    """Draw a small monochrome mark (stacked memory cards) for the window icon."""
    try:
        size = 32
        image = tk.PhotoImage(master=window, width=size, height=size)
        image.put(colors.accent, to=(2, 2, 30, 30))
        for corner_x, corner_y in ((2, 2), (29, 2), (2, 29), (29, 29)):
            image.transparency_set(corner_x, corner_y, True)
        for top in (9, 15, 21):
            right = 24 if top != 21 else 18
            image.put(colors.on_accent, to=(8, top, right, top + 3))
        return image
    except tk.TclError:
        return None


__all__ = [
    "ICONS",
    "Palette",
    "raised",
    "READING_MAX_WIDTH",
    "SIDEBAR_COMPACT_BELOW",
    "SIDEBAR_COMPACT_WIDTH",
    "SIDEBAR_WIDTH",
    "SPACE_L",
    "SPACE_M",
    "SPACE_S",
    "SPACE_XL",
    "SPACE_XS",
    "SPACE_XXL",
    "Theme",
    "app_icon",
    "apply_window_chrome",
    "cjk_ui_fonts",
    "enable_windows_dpi_awareness",
]
