"""Options: the one place rules, controls and settings live, as tabs.

Plan note "13 - Game Modes UI and Flow" ("Planned (M21)", decision D-072). The main menu has
four entries; what used to be three more of them is here: Rules, Controls, and the settings
split into Display, Sound and Feel. Each tab is its own screen (the rules screen, the
controls screen, :class:`~isofightr.scenes.menus.SettingsView` with one of three pages), all
at the Isle's workshop, all with the same strip of tabs in the title band instead of a
title. Keyboard Tab and a gamepad's Select step to the next tab (fixed buttons, the same on
every page and every device: decision D-078), and a click on a tab opens it; back leaves the
options for the main menu.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from isofightr.config import NATIVE_H
from isofightr.ui import font, kit_art, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import TabStrip, icon_image

if TYPE_CHECKING:
    from isofightr.scenes.menus import MenuView

OPTION_TABS: Final[tuple[str, ...]] = ("rules", "controls", "display", "sound", "feel")
"""The options' tabs, left to right."""
TAB_CAPTIONS: Final[dict[str, str]] = {
    "rules": "RULES",
    "controls": "CONTROLS",
    "display": "DISPLAY",
    "sound": "SOUND",
    "feel": "FEEL",
}
SETTINGS_TABS: Final[tuple[str, ...]] = ("display", "sound", "feel")
"""The tabs that are pages of the settings."""
TAB_HEIGHT: Final[int] = 20
TABS_BOTTOM: Final[int] = NATIVE_H - theme.HEADER_HEIGHT + (theme.HEADER_HEIGHT - TAB_HEIGHT) // 2
TABS_RIGHT_LIMIT: Final[int] = 378
"""The strip ends before here: the controls screen's player tabs start at 384."""
TAB_STEPS: Final[dict[MenuAction, int]] = {MenuAction.NEXT_TAB: 1}
"""The actions that change tab. Only fixed buttons: until D-078 the strong button and the
modifiers did it, but they are keys a player binds (and tests on the Controls page)."""
OPTIONS_TITLE: Final[str] = "OPTIONS"


def add_option_tabs(view: MenuView, tab: str, icon: str = "gear") -> TabStrip:
    """Give an options screen its title band: the icon on a small block, then the strip of
    tabs with ``tab`` as the page on show. Returns the strip (also ``view.option_tabs``)."""
    left = theme.MARGIN
    if icon_image(icon) is not None:
        side = theme.ICON_SIZE + 6
        bottom = NATIVE_H - theme.HEADER_HEIGHT + (theme.HEADER_HEIGHT - side - theme.LIP) // 2
        view.ui.picture(
            ("title-icon-block", side),
            lambda: kit_art.block_button(side, side + theme.LIP, surface=theme.STONE),
            left,
            bottom,
        )
        view.ui.icon(icon, left + 3, bottom + theme.LIP + 3, theme.INK)
        left += side + theme.GAP + 2
    strip = TabStrip(
        view.ui,
        left,
        TABS_BOTTOM,
        [TAB_CAPTIONS[name] for name in OPTION_TABS],
        TAB_HEIGHT,
        theme.STONE,
        TextSize.BODY,
    )
    strip.set(OPTION_TABS.index(tab))
    view.title = OPTIONS_TITLE
    view.option_tab = tab
    view.option_tabs = strip
    return strip


def tabs_width(left: int) -> int:
    """Return where the strip of tabs ends when it starts at ``left``."""
    widths = [
        font.text_width(TAB_CAPTIONS[name], TextSize.BODY) + 2 * theme.PAD + 4
        for name in OPTION_TABS
    ]
    return left + sum(widths) + 2 * (len(widths) - 1)


def option_tab_action(view: MenuView, action: MenuAction) -> bool:
    """Handle the tab button on an options screen: step to the next tab, wrapping round.
    Returns whether the action was one."""
    step = TAB_STEPS.get(action)
    if step is None:
        return False
    index = OPTION_TABS.index(view.option_tab)
    view.audio.play("ui_pick")
    view.flow.show_options(OPTION_TABS[(index + step) % len(OPTION_TABS)])
    return True


def option_tab_click(view: MenuView, x: float, y: float) -> bool:
    """Open the tab under a click on an options screen. Returns whether there was one."""
    strip = getattr(view, "option_tabs", None)
    if strip is None:
        return False
    index = strip.at(x, y)
    if index is None:
        return False
    if OPTION_TABS[index] != view.option_tab:
        view.audio.play("ui_select")
        view.flow.show_options(OPTION_TABS[index])
    return True


def tab_rect(view: MenuView, tab: str) -> Rect:
    """Return where a tab is on an options screen (tests and the mouse)."""
    return view.option_tabs.rects[OPTION_TABS.index(tab)]


assert tabs_width(theme.MARGIN + theme.ICON_SIZE + 6 + theme.GAP + 2) <= TABS_RIGHT_LIMIT
