"""Options: the one place rules, controls and settings are reached from.

Plan note "13 - Game Modes UI and Flow" ("Planned (M21)", decision D-072). The main menu has
four entries; what used to be three more of them (Rules, Controls, Settings) is here, at the
Isle's workshop. Until M21's group 5 gives the pages one shared tab strip, this screen is a
short list of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes import controls_model, rules_model
from isofightr.scenes.menus import MenuView
from isofightr.ui import theme
from isofightr.ui.focus import FocusMap, Rect
from isofightr.ui.menu import Menu, MenuAction, MenuItem
from isofightr.ui.widgets import BigButton, Sign

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

BUTTON_LEFT = 20
BUTTON_WIDTH = 196
BUTTON_HEIGHT = 40
BUTTON_PITCH = 48
BUTTONS_TOP = 300
NOTE = Rect(BUTTON_LEFT, 82, BUTTON_WIDTH + 44, 16)
RULES, CONTROLS, SETTINGS, BACK = "rules", "controls", "settings", "back"
OPTION_ENTRIES: tuple[tuple[str, str, str, str], ...] = (
    (RULES, "RULES", "Stocks, time, launch rate, mechanics", "gear"),
    (CONTROLS, "CONTROLS", "Every key and button, per player", "controller"),
    (SETTINGS, "SETTINGS", "Display, sound, comfort", "speaker"),
    (BACK, "BACK", "To the main menu", "arrow_left"),
)
"""Key, caption, what it leads to, and icon of each entry, top to bottom."""


class OptionsView(MenuView):
    """Rules, Controls, Settings, Back: blocks beside the Isle's workshop."""

    station = "workshop"
    surface = theme.STONE

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, cursor: str = "") -> None:
        """Build the entries; ``cursor`` names the one to start on."""
        super().__init__(pixel_buffer, flow)
        self.menu = Menu([MenuItem(key, caption) for key, caption, _, _ in OPTION_ENTRIES])
        keys = [key for key, _, _, _ in OPTION_ENTRIES]
        if cursor in keys:
            self.menu.cursor = keys.index(cursor)
        self.header("Options", "gear")
        self.buttons: dict[str, BigButton] = {}
        for index, (key, caption, text, icon) in enumerate(OPTION_ENTRIES):
            rect = Rect(
                BUTTON_LEFT, BUTTONS_TOP - index * BUTTON_PITCH - BUTTON_HEIGHT, BUTTON_WIDTH,
                BUTTON_HEIGHT,
            )  # fmt: skip
            self.buttons[key] = BigButton(self.ui, rect, caption, text, icon)
        self.focus_map = FocusMap({key: button.rect for key, button in self.buttons.items()})
        self.note = Sign(self.ui, NOTE)
        self.footer("{stick}: move   {attack}: pick   {special}: back   mouse: click")
        self.refresh()

    def note_line(self, key: str) -> str:
        """Return the line the sign shows for an entry: how things are set now."""
        settings, setup = self.flow.settings, self.flow.setup
        if key == RULES:
            return "   ".join(chip.capitalize() for chip in rules_model.rule_chips(setup))
        if key == CONTROLS:
            device = controls_model.tab_device(settings, 0)
            return f"Player 1 plays on {controls_model.DEVICE_NAMES[device]}."
        if key == SETTINGS:
            shown = "fullscreen" if settings.fullscreen else f"{settings.scale}x window"
            return f"A {shown}, volume {settings.master_volume}."
        return "Nothing is lost: every change is saved as it is made."

    @property
    def selected(self) -> str:
        """The key of the entry under the cursor."""
        return self.menu.selected.key

    def act(self, device: str, action: MenuAction) -> None:
        """Move the cursor, pick an entry, or go back to the main menu."""
        if action is MenuAction.BACK:
            self.flow.show_main_menu()
            return
        chosen = self.menu.apply(action)
        if chosen is not None:
            self.choose(chosen)

    def choose(self, key: str) -> None:
        """Go where the entry says; each comes back here."""
        if key == RULES:
            self.flow.show_rules(lambda: self.flow.show_options(RULES))
        elif key == CONTROLS:
            self.flow.show_controls(lambda: self.flow.show_options(CONTROLS))
        elif key == SETTINGS:
            self.flow.show_settings()
        else:
            self.flow.show_main_menu()

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the entry under the mouse."""
        key = self.focus_map.at(x, y)
        if key is None:
            return False
        self.menu.cursor = [item.key for item in self.menu.items].index(key)
        return True

    def refresh(self) -> None:
        """Show the cursor and the line about what it is on."""
        for key, button in self.buttons.items():
            button.focus(key == self.selected)
        self.note.text = self.note_line(self.selected)
