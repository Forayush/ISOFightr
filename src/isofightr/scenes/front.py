"""The front of the game: the boot splash, the title screen and the main menu.

Plan note "13 - Game Modes UI and Flow" ("Planned (M21)", decision D-072; first built for
D-061). All three are drawn on the Isle, the piece of the game's world the menus live on:
the title shows the whole island under the logo with the fighters strolling on it, and the
main menu is four block buttons beside it, the camera leaning toward whatever the cursor is
on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from isofightr import __version__
from isofightr.audio.cues import UI_PRESS
from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes import controls_model, rules_model
from isofightr.scenes.menus import KEYBOARD_DEVICE, MenuView
from isofightr.scenes.setup import training_setup
from isofightr.scenes.ticked_view import TickedView
from isofightr.ui import theme
from isofightr.ui.anim import bounce, pulse, slide
from isofightr.ui.focus import FocusMap, Rect
from isofightr.ui.font import TextSize
from isofightr.ui.hints import device_labels, hint_text
from isofightr.ui.kit_art import Look
from isofightr.ui.logo import build_logo
from isofightr.ui.menu import Menu, MenuAction, MenuItem
from isofightr.ui.widgets import BigButton, Button, Sign, picture_texture

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

LOGO_BOTTOM = 276
"""Where the logo rests on the title screen (its bottom edge, native pixels, y up)."""
LOGO_DROP_TICKS = 36
"""The logo falls into place and bounces over this many ticks."""
LOGO_BOB_TICKS = 180
PROMPT = Rect(NATIVE_W // 2 - 104, 18, 208, 27)
"""The title's one button: what to press to start."""
PROMPT_PRESS_TICKS = 90
"""The prompt presses itself every this many ticks: a hint that it is a thing to press."""
BOOT_TICKS = 2
"""The splash is drawn once, then the work of opening the devices and the Isle starts."""
BOOT_SKY = theme.SKY
"""What the splash clears to: the Isle's own sky, so the cloud that follows rises into it."""

BUTTON_LEFT = 20
BUTTON_WIDTH = 196
BUTTON_HEIGHT = 40
BUTTON_PITCH = 48
BUTTONS_TOP = 300
NOTE = Rect(BUTTON_LEFT, 82, BUTTON_WIDTH + 44, 16)
"""The sign under the buttons: a line about the entry under the cursor."""

MENU_ENTRIES: tuple[tuple[str, str, str, str], ...] = (
    ("versus", "VERSUS", "2 to 4 players, people or CPUs", "team"),
    ("training", "TRAINING", "Practise against a dummy", "stage"),
    ("options", "OPTIONS", "Rules, controls, display, sound", "gear"),
    ("quit", "QUIT", "Close the game", "cross"),
)
"""Key, caption, what it leads to, and icon of each main menu button, top to bottom. Four,
not six: rules, controls and settings are the tabs of Options (decision D-072)."""
LEANS: dict[str, tuple[int, int]] = {
    "versus": (0, 6),
    "training": (14, -8),
    "options": (-16, 14),
    "quit": (0, 0),
}
"""How far the camera leans from the plaza for each entry, in world pixels: toward the
ring, the plaza's front, and the workshop at the back."""


def logo_texture() -> arcade.Texture:
    """Return the logo's texture (built once)."""
    return picture_texture(("logo",), build_logo)


class BootView(TickedView):
    """The first thing on screen: the logo, at once, while the input devices are opened and
    the Isle is built (most of a second). Then the title, through the cloud."""

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
        """Once the splash has been drawn, go on to the title (which opens the devices).
        The splash is painted into the buffer first, so the cloud the title opens through
        rises over it whether or not a frame was drawn since."""
        if self.tick_count >= BOOT_TICKS:
            self.paint()
            self.flow.show_title(wipe=True)

    def paint(self) -> None:
        """Paint the logo on the sky into the native buffer."""
        with self.pixel_buffer.drawing(BOOT_SKY):
            self.sprites.draw(pixelated=True)

    def on_draw(self) -> None:
        """Draw the splash, then upscale it to the window."""
        self.clear()
        self.paint()
        self.blit_to_window()


class TitleView(MenuView):
    """The title screen: the logo over the whole Isle; any confirm goes to the main menu."""

    station = "gate"
    surface = theme.STONE

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the logo and the prompt."""
        super().__init__(pixel_buffer, flow)
        texture = logo_texture()
        self.logo = arcade.Sprite(texture)
        self.ui.panels.append(self.logo)
        # Straight on the sky: ink, with no shadow to thicken its thin strokes.
        self.ui.write(
            "an isometric platform fighter",
            NATIVE_W // 2,
            LOGO_BOTTOM - 16,
            TextSize.TEXT,
            theme.INK,
            "centre",
            shadow=False,
        )
        self.prompt = Button(self.ui, PROMPT, "", size=TextSize.TITLE, look=Look.FOCUS)
        self.ui.write(
            f"v{__version__}",
            NATIVE_W - theme.PAD,
            theme.PAD,
            TextSize.SMALL,
            theme.INK,
            "right",
            shadow=False,
        )
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

    def refresh(self) -> None:
        """Drop the logo in, bob it, and let the prompt press itself now and then."""
        tick = self.tick_count
        texture = self.logo.texture
        rest = LOGO_BOTTOM + texture.height / 2
        dropped = slide(tick, 0, LOGO_DROP_TICKS, NATIVE_H + texture.height, round(rest), bounce)
        bob = round(pulse(max(tick - LOGO_DROP_TICKS, 0), LOGO_BOB_TICKS) * 2)
        self.logo.position = (NATIVE_W / 2 + (texture.width % 2) / 2, dropped + bob)
        self.prompt.label.text = self.prompt_text()
        if tick and tick % PROMPT_PRESS_TICKS == 0:
            self.prompt.press(tick)
        self.prompt.settle(tick)


class MainMenuView(MenuView):
    """Versus, Training, Options, Quit: four blocks beside the Isle."""

    station = "plaza"
    surface = theme.STONE

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the buttons and the sign under them."""
        super().__init__(pixel_buffer, flow)
        self.menu = Menu([MenuItem(key, caption) for key, caption, _, _ in MENU_ENTRIES])
        self.header("Main menu")
        self.buttons: dict[str, BigButton] = {}
        for index, (key, caption, text, icon) in enumerate(MENU_ENTRIES):
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
        """Return the line the sign shows for an entry: where things stand, from the game's
        own data, so the menu says something true about what the button leads to."""
        settings, setup = self.flow.settings, self.flow.setup
        if key == "versus":
            return "   ".join(chip.capitalize() for chip in rules_model.rule_chips(setup))
        if key == "training":
            return "Set its damage, make it a CPU, read the move list."
        if key == "options":
            device = controls_model.tab_device(settings, 0)
            return f"Player 1 plays on {controls_model.DEVICE_NAMES[device]}."
        return "See you on the islands."

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
            self.buttons[chosen].press(self.tick_count)
            self.audio.play(UI_PRESS)
            self.choose(chosen)

    def choose(self, key: str) -> None:
        """Go where the button says."""
        if key == "versus":
            self.flow.show_character_select(self.flow.setup)
        elif key == "training":
            self.flow.show_character_select(training_setup())
        elif key == "options":
            self.flow.show_options()
        else:
            self.window.close()

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the button under the mouse."""
        key = self.focus_map.at(x, y)
        if key is None:
            return False
        self.menu.cursor = [item.key for item in self.menu.items].index(key)
        return True

    def refresh(self) -> None:
        """Show the cursor, say a line about what it is on, and lean the camera that way."""
        for key, button in self.buttons.items():
            button.focus(key == self.selected)
            button.settle(self.tick_count)
        self.note.text = self.note_line(self.selected)
        self.world.nudge(*LEANS[self.selected])

    def on_hide_view(self) -> None:
        """Stand the camera straight again for whoever is next."""
        self.world.nudge(0, 0)


assert KEYBOARD_DEVICE.startswith("keyboard")
assert set(LEANS) == {key for key, _, _, _ in MENU_ENTRIES}
