"""The front of the game: the boot splash, the title screen and the main menu.

Plan note "13 - Game Modes UI and Flow" ("Screen flow", decision D-061, wireframes
``m13_wf_title.png`` and ``m13_wf_mainmenu.png``). The title shows the logo over a floating
island where the fighters stand idling; the main menu is a column of buttons, each with an
icon and a line saying what it leads to, beside a preview of the one under the cursor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from isofightr import __version__
from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.character_loader import list_character_ids
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes import controls_model, rules_model
from isofightr.scenes.diorama import PAD_GRID, PAD_SPOTS, Diorama
from isofightr.scenes.menus import KEYBOARD_DEVICE, MenuView
from isofightr.scenes.setup import training_setup
from isofightr.scenes.ticked_view import TickedView
from isofightr.ui import kit_art, theme
from isofightr.ui.anim import blink, bounce, pulse, slide
from isofightr.ui.focus import FocusMap, Rect
from isofightr.ui.font import TextSize
from isofightr.ui.hints import device_labels, hint_text
from isofightr.ui.kit_art import Look
from isofightr.ui.logo import build_logo
from isofightr.ui.menu import Menu, MenuAction, MenuItem
from isofightr.ui.pixel_text import GlyphAtlas
from isofightr.ui.widgets import (
    Picture,
    UiLayer,
    add_panel,
    icon_texture,
    picture_texture,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

LOGO_BOTTOM = 268
"""Where the logo rests on the title screen (its bottom edge, native pixels, y up)."""
LOGO_DROP_TICKS = 36
"""The logo falls into place and bounces over this many ticks."""
LOGO_BOB_TICKS = 180
ISLAND_SPOT = (NATIVE_W // 2, 150)
"""Where the middle of the title island's top is drawn."""
PROMPT_BOTTOM = 44
PROMPT_BLINK_TICKS = 50
MAX_TITLE_FIGHTERS = 4
BOOT_TICKS = 2
"""The splash is drawn once, then the work of opening the devices starts."""

BUTTON_LEFT = 24
BUTTON_WIDTH = 248
BUTTON_HEIGHT = 36
BUTTON_PITCH = 41
BUTTONS_TOP = 322
PREVIEW = Rect(288, 44, 336, 278)
PREVIEW_SPOT = (PREVIEW.left + PREVIEW.width // 2, PREVIEW.bottom + 96)
"""Where a preview's island is drawn."""
LINE_HEIGHT = 14

MENU_ENTRIES: tuple[tuple[str, str, str, str], ...] = (
    ("versus", "VERSUS", "2 to 4 players, people or CPUs", "team"),
    ("training", "TRAINING", "practise with a dummy", "stage"),
    ("rules", "RULES", "stocks, time, launch rate...", "gear"),
    ("controls", "CONTROLS", "keyboard and gamepad", "controller"),
    ("settings", "SETTINGS", "video, sound, accessibility", "speaker"),
    ("quit", "QUIT", "close the game", "cross"),
)
"""Key, caption, what it leads to, and icon of each main menu button, top to bottom."""


def logo_texture() -> arcade.Texture:
    """Return the logo's texture (built once)."""
    return picture_texture(("logo",), build_logo)


class BootView(TickedView):
    """The first thing on screen: the logo, at once, while the input devices are opened
    (asking Windows for its controllers takes most of a second). Then the title."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Make the logo; nothing slow."""
        super().__init__(pixel_buffer, flow.max_ticks)
        self.flow = flow
        self.sprites: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        texture = logo_texture()
        self.sprites.append(
            arcade.Sprite(
                texture, center_x=NATIVE_W / 2, center_y=NATIVE_H / 2 + texture.height / 2
            )
        )

    def tick(self) -> None:
        """Once the splash has been drawn, go on to the title (which opens the devices)."""
        if self.tick_count >= BOOT_TICKS:
            self.flow.show_title()

    def on_draw(self) -> None:
        """Draw the logo on the menu's night colour."""
        self.clear()
        with self.pixel_buffer.drawing(theme.BACKGROUND):
            self.sprites.draw(pixelated=True)
        self.blit_to_window()


class TitleView(MenuView):
    """The title screen: any confirm goes to the main menu."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the logo, the island and the prompt."""
        super().__init__(pixel_buffer, flow)
        self.dim = None
        texture = logo_texture()
        self.logo = arcade.Sprite(texture)
        self.ui.panels.append(self.logo)
        self.ui.write(
            "an isometric platform fighter",
            NATIVE_W // 2,
            LOGO_BOTTOM - 20,
            TextSize.BODY,
            theme.FOG,
            "centre",
        )
        self.prompt = self.ui.write(
            "", NATIVE_W // 2, PROMPT_BOTTOM, TextSize.TITLE, theme.TEXT, "centre"
        )
        self.ui.write(
            f"v{__version__}", NATIVE_W - theme.PAD, theme.PAD, TextSize.SMALL, theme.TEXT_DIM,
            "right",
        )  # fmt: skip
        self.island = Diorama(pixel_buffer, list_character_ids()[:MAX_TITLE_FIGHTERS])
        self.refresh()

    def act(self, device: str, action: MenuAction) -> None:
        """Start on confirm."""
        if action is MenuAction.CONFIRM:
            self.flow.show_main_menu()

    def hover(self, x: int, y: int) -> bool:
        """A click anywhere starts."""
        return True

    def prompt_text(self) -> str:
        """Return the prompt, naming the confirm control of the device that acted last."""
        labels = device_labels(self.flow.settings, self.active_device)
        confirm = hint_text("{attack}", labels)
        other = "ENTER" if self.active_device.startswith("keyboard") else "START"
        return f"PRESS {confirm.upper()} OR {other}"

    def tick(self) -> None:
        """Run the menu, and let the fighters on the island breathe."""
        self.island.tick()
        super().tick()

    def refresh(self) -> None:
        """Drop the logo in, bob it, and blink the prompt."""
        tick = self.tick_count
        texture = self.logo.texture
        rest = LOGO_BOTTOM + texture.height / 2
        dropped = slide(tick, 0, LOGO_DROP_TICKS, NATIVE_H + texture.height, round(rest), bounce)
        bob = round(pulse(max(tick - LOGO_DROP_TICKS, 0), LOGO_BOB_TICKS) * 2)
        self.logo.position = (NATIVE_W / 2 + (texture.width % 2) / 2, dropped + bob)
        self.prompt.text = self.prompt_text()
        self.prompt.visible = blink(tick, PROMPT_BLINK_TICKS)

    def on_draw(self) -> None:
        """Backdrop, island, then the logo and text over them."""
        self.clear()
        with self.pixel_buffer.drawing(theme.BACKGROUND):
            self.backdrop.draw(self.flow.menu_ticks)
            self.island.draw(*ISLAND_SPOT)
            self.ui.draw()
            self.draw_fade()
        self.blit_to_window()


class MenuButton:
    """A main menu button: an icon, a caption and a line of description."""

    def __init__(self, layer: UiLayer, rect: Rect, caption: str, text: str, icon: str) -> None:
        """Create the button at rest."""
        self.rect = rect
        self.icon_name = icon
        self._body = Picture(layer, rect)
        self._icon = arcade.Sprite(
            icon_texture(icon),
            center_x=rect.left + theme.PAD + theme.ICON_SIZE / 2,
            center_y=rect.bottom + rect.height - 13,
        )
        layer.panels.append(self._icon)
        left = rect.left + theme.PAD + theme.ICON_SIZE + theme.PAD
        self.caption = layer.write(caption, left, rect.bottom + 16, TextSize.TITLE, shadow=False)
        self.text = layer.write(text, left, rect.bottom + 3, TextSize.BODY, shadow=False)
        self._focused: bool | None = None
        self.focus(False)

    def focus(self, focused: bool) -> None:
        """Show the button under the cursor, or at rest."""
        if focused == self._focused:
            return
        self._focused = focused
        look = Look.FOCUS if focused else Look.NORMAL
        width, height = self.rect.width, self.rect.height
        self._body.show(
            ("button", width, height, look), lambda: kit_art.button(width, height, look)
        )
        color = kit_art.text_color(look)
        self.caption.color = color
        self.text.color = theme.TEXT_ON_FOCUS if focused else theme.TEXT_MUTED
        texture = icon_texture(self.icon_name, color)
        if texture is not None:
            self._icon.texture = texture


class MainMenuView(MenuView):
    """Versus, Training, Rules, Controls, Settings, Quit, with a preview of each."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the buttons and a preview page for each."""
        super().__init__(pixel_buffer, flow)
        self.dim = None
        self.menu = Menu([MenuItem(key, caption) for key, caption, _, _ in MENU_ENTRIES])
        self.header("MAIN MENU")
        self.buttons: dict[str, MenuButton] = {}
        for index, (key, caption, text, icon) in enumerate(MENU_ENTRIES):
            rect = Rect(
                BUTTON_LEFT, BUTTONS_TOP - (index + 1) * BUTTON_PITCH, BUTTON_WIDTH, BUTTON_HEIGHT
            )
            self.buttons[key] = MenuButton(self.ui, rect, caption, text, icon)
        self.focus_map = FocusMap({key: button.rect for key, button in self.buttons.items()})
        add_panel(self.ui, PREVIEW)

        characters = list_character_ids()
        self.islands: dict[str, Diorama] = {
            "versus": Diorama(pixel_buffer, characters[:MAX_TITLE_FIGHTERS]),
            "training": Diorama(
                pixel_buffer, characters[:1], PAD_GRID, PAD_SPOTS, tileset="grid", tile="grid"
            ),
        }
        glyphs = GlyphAtlas()
        self.pages: dict[str, UiLayer] = {}
        for key, caption, _, _ in MENU_ENTRIES:
            page = UiLayer(glyphs)
            self.pages[key] = page
            left, top = PREVIEW.left + theme.PAD + 2, PREVIEW.top - 22
            page.write(caption, left, top, TextSize.TITLE, theme.HEADING)
            for row, (line, color) in enumerate(self.preview_lines(key)):
                page.write(line, left, top - 18 - row * LINE_HEIGHT, TextSize.BODY, color)
        self.footer("{stick}: move   {attack}: pick   {special}: back   mouse: click")
        self.refresh()

    def preview_lines(self, key: str) -> list[tuple[str, theme.Rgb]]:
        """Return the text of a button's preview page: lines and their colours."""
        settings, setup = self.flow.settings, self.flow.setup
        plain, muted = theme.TEXT, theme.TEXT_MUTED
        if key == "versus":
            chips = "  ".join(rules_model.rule_chips(setup))
            return [("Join with any keyboard or gamepad.", plain), (chips, muted)]
        if key == "training":
            return [
                ("One fighter and a dummy on the grid.", plain),
                ("Set its damage, make it a CPU, read the move list.", muted),
            ]
        if key == "rules":
            lines = []
            for row in rules_model.RULE_ROWS:
                on = rules_model.row_on(setup, row.key)
                value = rules_model.row_value(setup, row.key)
                state = "" if on is None else ("ON" if on else "OFF")
                shown = f"{value} {state}".strip()
                label = row.label if len(row.label) <= 30 else row.label[:28] + ".."
                lines.append((f"{label:<32}{shown:>10}", plain if on is not False else muted))
            return lines
        if key == "controls":
            device = controls_model.tab_device(settings, 0)
            labels = device_labels(settings, device)
            lines = [(f"Player 1: {controls_model.DEVICE_NAMES[device]}", plain)]
            for action in ("stick", "jump", "attack", "special", "strong", "grab", "shield"):
                name = "MOVE" if action == "stick" else action.upper()
                lines.append((f"{name:<10}{labels.get(action, '')}", muted))
            lines.append(("Every key and button can be rebound.", plain))
            return lines
        if key == "settings":
            return [
                (f"Window scale      {settings.scale}x", muted),
                (f"Fullscreen        {'on' if settings.fullscreen else 'off'}", muted),
                (f"Screen shake      {settings.screen_shake}%", muted),
                (f"Master volume     {settings.master_volume}", muted),
                (f"Music volume      {settings.music_volume}", muted),
                (f"Effects volume    {settings.sfx_volume}", muted),
                (f"Reduce flashing   {'on' if settings.reduce_flashing else 'off'}", muted),
            ]
        return [("See you on the islands.", plain)]

    @property
    def selected(self) -> str:
        """The key of the button under the cursor."""
        return self.menu.selected.key

    def act(self, device: str, action: MenuAction) -> None:
        """Move the cursor, pick a button, or go back to the title."""
        if action is MenuAction.BACK:
            self.flow.show_title()
            return
        chosen = self.menu.apply(action)
        if chosen is not None:
            self.choose(chosen)

    def choose(self, key: str) -> None:
        """Go where the button says."""
        if key == "versus":
            self.flow.show_character_select(self.flow.setup)
        elif key == "training":
            self.flow.show_character_select(training_setup())
        elif key == "rules":
            self.flow.show_rules()
        elif key == "controls":
            self.flow.show_controls()
        elif key == "settings":
            self.flow.show_settings()
        else:
            self.window.close()

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the button under the mouse."""
        key = self.focus_map.at(x, y)
        if key is None:
            return False
        self.menu.cursor = [item.key for item in self.menu.items].index(key)
        return True

    def tick(self) -> None:
        """Run the menu and the preview island that is showing."""
        island = self.islands.get(self.selected)
        if island is not None:
            island.tick()
        super().tick()

    def refresh(self) -> None:
        """Show the cursor."""
        for key, button in self.buttons.items():
            button.focus(key == self.selected)

    def on_draw(self) -> None:
        """Backdrop, buttons and panel, then the preview page and its island."""
        self.clear()
        with self.pixel_buffer.drawing(theme.BACKGROUND):
            self.backdrop.draw(self.flow.menu_ticks)
            self.ui.draw()
            self.pages[self.selected].draw()
            island = self.islands.get(self.selected)
            if island is not None:
                island.draw(*PREVIEW_SPOT)
            self.draw_fade()
        self.blit_to_window()


assert KEYBOARD_DEVICE.startswith("keyboard")
