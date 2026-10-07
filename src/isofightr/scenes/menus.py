"""The menu scenes: title, main menu, rules, settings, character select, stage select, results.

Plan note "13 - Game Modes UI and Flow" ("Screen flow", "Character select screen",
"Settings"). Every scene is driven by every connected device through
:class:`isofightr.ui.menu.MenuInput`: move with the stick, attack or jump to confirm, special
or shield to go back. Enter and Escape also confirm and go back, as the WASD keyboard.
Scenes ask the :class:`~isofightr.scenes.flow.GameFlow` to move on.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import arcade

from isofightr.config import (
    AUDIO_MENU_SONG,
    AUDIO_VICTORY_SONG,
    NATIVE_H,
    NATIVE_W,
)
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.input.devices import KEYBOARD_PREFIX
from isofightr.input.keyboard import KeyLatch
from isofightr.render import placeholder_art as art
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.pixel_scale import window_to_native
from isofightr.render.sprite_bank import SpriteBank
from isofightr.scenes.setup import (
    TEAM_NAMES,
    MatchSetup,
    result_awards,
    results_table,
)
from isofightr.scenes.ticked_view import TickedView
from isofightr.settings import (
    CAMERA_ZOOMS,
    KEYBOARD_SOLO,
    SCALES,
    SHAKE_STEPS,
    VOLUME_MAX,
    Settings,
)
from isofightr.sim.input_frame import Dir8
from isofightr.sim.match import Match
from isofightr.ui import kit_art, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.hints import device_labels, hint_text
from isofightr.ui.menu import MENU_SOUNDS, Menu, MenuAction, MenuInput, MenuItem
from isofightr.ui.pixel_font import GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas
from isofightr.ui.widgets import (
    HIGHLIGHT,
    MUTED,
    TextBlock,
    TextLabel,
    UiLayer,
    centred_left,
    picture_texture,
    text_bottom,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

VICTORY_ANIM = "victory"
VICTORY_FACING = Dir8.S
"""The winner faces the camera."""
VICTORY_SCALE = 2
VICTORY_LEFT = 44
VICTORY_SPACING = 56
VICTORY_BOTTOM = 96
KEY_CONFIRM = arcade.key.ENTER
KEY_BACK = arcade.key.ESCAPE
KEYBOARD_DEVICE = KEYBOARD_PREFIX + KEYBOARD_SOLO
"""The device Enter and Escape act as."""
MOUSE_LEFT = arcade.MOUSE_BUTTON_LEFT
MOUSE_RIGHT = arcade.MOUSE_BUTTON_RIGHT
TITLE_SCALE = 4
HEADING_SCALE = 2
HEADING_BOTTOM = NATIVE_H - 60
ROW_CAPACITY = 52
FADE_TICKS = 10
"""A scene fades in from black over this many ticks."""
BLINK_TICKS = 30
ON_OFF = ("off", "on")


class MenuView(TickedView):
    """Base of the menu scenes: polls every device each tick and draws one UI layer."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Create an empty scene with its own input devices."""
        super().__init__(pixel_buffer, flow.max_ticks)
        self.flow = flow
        self.hub = flow.hub()
        self.menu_input = MenuInput()
        self.ui = UiLayer(GlyphAtlas())
        self._keys = KeyLatch()
        self._key_actions: list[MenuAction] = []
        self._clicks: list[tuple[int, int]] = []
        self.fade_ticks = FADE_TICKS
        self.backdrop = flow.backdrop()
        self.dim: arcade.SpriteList[arcade.Sprite] | None = arcade.SpriteList()
        """A veil over the backdrop so plain text reads on it; ``None`` for scenes that
        put their text on panels."""
        self.dim.append(
            arcade.Sprite(
                picture_texture(
                    ("dim", NATIVE_W, NATIVE_H),
                    lambda: art.build_panel(
                        NATIVE_W, NATIVE_H, theme.DIM_OVERLAY, theme.DIM_OVERLAY
                    ),
                ),
                center_x=NATIVE_W / 2,
                center_y=NATIVE_H / 2,
            )
        )
        self.active_device = KEYBOARD_DEVICE
        """The device that acted last: the footer shows its controls."""
        self._footer_template = ""
        self._footer_device = ""
        self._footer: TextLabel | None = None

    def heading(self, text: str) -> None:
        """Add the scene's heading (the old look, for screens not yet rebuilt)."""
        self.ui.centred(text, HEADING_BOTTOM, HIGHLIGHT, HEADING_SCALE)

    def header(self, text: str, icon: str | None = None) -> None:
        """Add the title bar across the top of a rebuilt screen (decision D-061)."""
        bar = Rect(0, NATIVE_H - theme.HEADER_HEIGHT, NATIVE_W, theme.HEADER_HEIGHT)
        self.ui.picture(
            ("header", NATIVE_W),
            lambda: art.build_panel(bar.width, bar.height, theme.PANEL_DEEP, theme.PANEL_DEEP),
            bar.left,
            bar.bottom,
        )
        self.ui.picture(("header-rule", NATIVE_W), lambda: kit_art.divider(NATIVE_W), 0, bar.bottom)
        left = theme.MARGIN
        if icon is not None and self.ui.icon(icon, left, bar.bottom + 8, theme.HEADING):
            left += theme.ICON_SIZE + theme.GAP + 2
        self.ui.write(
            text, left, text_bottom(bar, TextSize.DISPLAY), TextSize.DISPLAY, theme.HEADING
        )

    def footer(self, template: str) -> None:
        """Set the hint line at the bottom. ``{attack}``, ``{special}``, ``{grab}``,
        ``{stick}`` and the other action names are replaced by the real controls of the
        device that acted last."""
        self._footer_template = template
        if self._footer is None:
            strip = Rect(0, 0, NATIVE_W, theme.FOOTER_HEIGHT)
            self.ui.picture(
                ("footer", NATIVE_W),
                lambda: art.build_panel(
                    NATIVE_W, theme.FOOTER_HEIGHT, theme.PANEL_DEEP, theme.PANEL_DEEP
                ),
                0,
                0,
            )
            self._footer = self.ui.write_in(strip, "", TextSize.BODY, theme.TEXT_MUTED)
        self._footer_device = ""
        self._sync_footer()

    def _sync_footer(self) -> None:
        if self._footer is None or self._footer_device == self.active_device:
            return
        self._footer_device = self.active_device
        labels = device_labels(self.flow.settings, self.active_device)
        self._footer.text = hint_text(self._footer_template, labels)

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """Track held keys; Enter and Escape confirm and go back."""
        self._keys.press(symbol)
        if symbol == KEY_CONFIRM:
            self._key_actions.append(MenuAction.CONFIRM)
        elif symbol == KEY_BACK:
            self._key_actions.append(MenuAction.BACK)

    # --- mouse (an extra: everything also works without it) --------------------------------

    def native_point(self, x: float, y: float) -> tuple[int, int] | None:
        """Return the native pixel under a window position, or ``None`` on the letterbox."""
        return window_to_native(x, y, self.window_viewport(), self.window.get_pixel_ratio())

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        """Moving the mouse moves the cursor to whatever it is over."""
        spot = self.native_point(x, y)
        if spot is not None:
            self.hover(*spot)

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        """A left click confirms what is under the mouse; a right click goes back. Both act
        on the next tick, as the keyboard, so they are handled in one place."""
        spot = self.native_point(x, y)
        if button == MOUSE_RIGHT:
            self._key_actions.append(MenuAction.BACK)
        elif button == MOUSE_LEFT and spot is not None:
            self._clicks.append(spot)

    def hover(self, x: int, y: int) -> bool:
        """Move the cursor to the thing at a native pixel. Returns whether there is one (a
        click only confirms then). Override in scenes."""
        return False

    def click(self, x: int, y: int) -> None:
        """Handle a left click at a native pixel: by default, confirm whatever is there.
        Scenes whose widgets care where they are clicked (steppers) override this."""
        if self.hover(x, y):
            self.audio.play(MENU_SOUNDS[MenuAction.CONFIRM])
            self.act(KEYBOARD_DEVICE, MenuAction.CONFIRM)

    def on_key_release(self, symbol: int, modifiers: int) -> None:
        """Stop tracking a released key."""
        self._keys.release(symbol)

    music = AUDIO_MENU_SONG
    """The song a menu scene plays (it carries on from scene to scene)."""
    music_loops = True

    def on_show_view(self) -> None:
        """Start (or keep) the scene's music."""
        self.audio.play_music(self.music, self.music_loops)

    def tick(self) -> None:
        """Hand this tick's menu actions to :meth:`act`, then refresh the text."""
        frames = self.hub.frames(self._keys.keys())
        self._keys.end_tick()
        devices = list(frames)
        extras = self.hub.menu_extras(devices)
        self.hub.end_tick()
        fired = self.menu_input.update([frames[device] for device in devices], extras)
        self.flow.menu_ticks += 1
        for action in self._key_actions:
            if self.window.current_view is self:
                self.audio.play(MENU_SOUNDS[action])
                self.active_device = KEYBOARD_DEVICE
                self.act(KEYBOARD_DEVICE, action)
        self._key_actions = []
        for spot in self._clicks:
            if self.window.current_view is self:
                self.active_device = KEYBOARD_DEVICE
                self.click(*spot)
        self._clicks = []
        for device, actions in zip(devices, fired, strict=True):
            for action in MenuAction:
                if action in actions and self.window.current_view is self:
                    if MENU_SOUNDS[action]:
                        self.audio.play(MENU_SOUNDS[action])
                    self.active_device = device
                    self.act(device, action)
        if self.window.current_view is self:
            self._sync_footer()
            self.refresh()

    def act(self, device: str, action: MenuAction) -> None:
        """Handle one menu action from one device. Override in scenes."""

    def refresh(self) -> None:
        """Update labels from the scene's state. Override in scenes."""

    def on_draw(self) -> None:
        """Draw the scene at native resolution, then upscale it to the window."""
        self.clear()
        with self.pixel_buffer.drawing(theme.BACKGROUND):
            self.backdrop.draw(self.flow.menu_ticks)
            if self.dim is not None:
                self.dim.draw(pixelated=True)
            self.ui.draw()
            self.draw_fade()
        self.blit_to_window()


class MenuListView(MenuView):
    """A scene that is one vertical menu in the middle of the screen, shared by every device."""

    def __init__(
        self,
        pixel_buffer: PixelBuffer,
        flow: GameFlow,
        title: str,
        menu: Menu,
        rows_top: int = HEADING_BOTTOM - 30,
    ) -> None:
        """Build the heading and the menu rows, whose first row hangs under ``rows_top``."""
        super().__init__(pixel_buffer, flow)
        self.menu = menu
        self.heading(title)
        left = centred_left(ROW_CAPACITY)
        self.rows = TextBlock(self.ui, left, rows_top, len(menu.items), ROW_CAPACITY)
        self.refresh()

    def act(self, device: str, action: MenuAction) -> None:
        """Navigate; hand confirmed items to :meth:`choose` and back to :meth:`back`."""
        if action is MenuAction.BACK:
            self.back()
            return
        before = [item.index for item in self.menu.items]
        chosen = self.menu.apply(action)
        if chosen is not None:
            self.choose(chosen)
        elif before != [item.index for item in self.menu.items]:
            self.changed()

    def choose(self, key: str) -> None:
        """An action item was confirmed. Override in scenes."""

    def changed(self) -> None:
        """A setting changed. Override in scenes."""

    def back(self) -> None:
        """Back was pressed. Override in scenes."""

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the row under the mouse."""
        row = self.rows.row_at(x, y)
        if row is None or row >= len(self.menu.items):
            return False
        self.menu.cursor = row
        return True

    def refresh(self) -> None:
        """Show the menu rows."""
        self.rows.set_lines(self.menu.lines(), self.menu.cursor)


class SettingsView(MenuListView):
    """Video, audio and control settings. Every change is applied and saved at once."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the rows from the current settings."""
        settings = flow.settings
        volumes = tuple(str(level) for level in range(VOLUME_MAX + 1))
        menu = Menu(
            [
                _setting(
                    "scale",
                    "Window scale",
                    [f"{scale}x" for scale in SCALES],
                    SCALES,
                    settings.scale,
                ),
                MenuItem("fullscreen", "Fullscreen", ON_OFF, int(settings.fullscreen)),
                _setting(
                    "screen_shake",
                    "Screen shake",
                    [f"{step}%" for step in SHAKE_STEPS],
                    SHAKE_STEPS,
                    settings.screen_shake,
                ),
                MenuItem("master_volume", "Master volume", volumes, settings.master_volume),
                MenuItem("music_volume", "Music volume", volumes, settings.music_volume),
                MenuItem("sfx_volume", "Effects volume", volumes, settings.sfx_volume),
                MenuItem("controls", "Controls: keyboard and gamepad..."),
                _setting(
                    "camera_zoom",
                    "Camera zoom",
                    ["static", "stepped 2x"],
                    CAMERA_ZOOMS,
                    settings.camera_zoom,
                ),
                MenuItem(
                    "reduce_flashing", "Reduce flashing", ON_OFF, int(settings.reduce_flashing)
                ),
                MenuItem("defaults", "Reset everything to defaults"),
                MenuItem("back", "Back"),
            ]
        )
        super().__init__(pixel_buffer, flow, "SETTINGS", menu)
        self.footer("{stick}: row and value   {attack}: pick   {special}: back")

    def changed(self) -> None:
        """Apply and save the row that changed."""
        menu = self.menu
        self.flow.update_settings(
            replace(
                self.flow.settings,
                scale=SCALES[menu.item("scale").index],
                fullscreen=bool(menu.item("fullscreen").index),
                screen_shake=SHAKE_STEPS[menu.item("screen_shake").index],
                master_volume=menu.item("master_volume").index,
                music_volume=menu.item("music_volume").index,
                sfx_volume=menu.item("sfx_volume").index,
                camera_zoom=CAMERA_ZOOMS[menu.item("camera_zoom").index],
                reduce_flashing=bool(menu.item("reduce_flashing").index),
            )
        )

    def choose(self, key: str) -> None:
        """Open the controls screen, reset, or leave."""
        if key == "controls":
            self.flow.show_controls(self.flow.show_settings)
        elif key == "defaults":
            # Video, audio and accessibility only: the controls and the rules have their
            # own DEFAULT buttons.
            kept = self.flow.settings
            self.flow.update_settings(
                Settings(
                    slot_devices=kept.slot_devices,
                    rules=kept.rules,
                    keys=kept.keys,
                    alt_keys=kept.alt_keys,
                    pads=kept.pads,
                    deadzone=kept.deadzone,
                )
            )
            self.flow.show_settings()
        else:
            self.back()

    def back(self) -> None:
        """Back to the main menu."""
        self.flow.show_main_menu()


def _setting[T](
    key: str, label: str, names: list[str], values: tuple[T, ...], value: T
) -> MenuItem:
    """Return a setting row whose choices stand for ``values``, with ``value`` selected."""
    index = values.index(value) if value in values else 0
    return MenuItem(key, label, tuple(names), index)


class ResultsView(MenuListView):
    """Placements and stats after a match; rematch or go back to character select."""

    STATS_TOP = HEADING_BOTTOM - 20
    music = AUDIO_VICTORY_SONG
    music_loops = False
    _victory_feet: list[tuple[int, int]]

    def __init__(
        self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup, match: Match
    ) -> None:
        """Build the table from the finished match."""
        self.setup = setup
        self._victory_feet = []
        menu = Menu([MenuItem("rematch", "Rematch"), MenuItem("back", "Back to character select")])
        lines = results_table(match)
        awards = result_awards(match)
        line_height = GLYPH_HEIGHT + 2
        awards_top = self.STATS_TOP - (len(lines) + 1) * line_height
        rows_top = awards_top - (len(awards) + 1) * line_height
        super().__init__(pixel_buffer, flow, winner_text(match), menu, rows_top)
        self.table_lines = lines
        self.award_lines = awards
        table = TextBlock(self.ui, centred_left(len(lines[0])), self.STATS_TOP, len(lines), 80)
        table.set_lines(lines)
        if awards:
            block = TextBlock(self.ui, centred_left(len(lines[0])), awards_top, len(awards), 80)
            block.set_lines(awards)
            for label in block.labels:
                label.color = MUTED
        self._winners = self._victory_sprites(match)

    def _victory_sprites(self, match: Match) -> list[tuple[SpriteBank, int, arcade.Sprite]]:
        """A sprite for each winner that has a ``victory`` animation, down the left side."""
        result = match.result
        if result is None:
            return []
        sprites = []
        for place, player in enumerate(result.winners):
            fighter = match.fighters[player]
            try:
                sprite_set = load_sprite_set(fighter.character.id)
            except SpriteSheetError:
                sprite_set = None
            if sprite_set is None or VICTORY_ANIM not in sprite_set.anims:
                continue
            bank = SpriteBank(sprite_set)
            costume = self.setup.costume_of(player, len(sprite_set.costumes))
            sprite = self.ui.image(bank.texture(VICTORY_ANIM, 0, VICTORY_FACING, costume), 0, 0)
            sprite.scale = VICTORY_SCALE
            sprites.append((bank, costume, sprite))
            self._victory_feet.append((VICTORY_LEFT + place * VICTORY_SPACING, VICTORY_BOTTOM))
        return sprites

    def refresh(self) -> None:
        """Show the menu rows and step the winners' victory animations."""
        super().refresh()
        for (bank, costume, sprite), (feet_x, feet_y) in zip(
            getattr(self, "_winners", []), self._victory_feet, strict=False
        ):
            info = bank.sprite_set.anims[VICTORY_ANIM]
            pose = info.pose_at(self.tick_count + 1)
            rect = bank.frame(VICTORY_ANIM, pose, VICTORY_FACING)
            sprite.texture = bank.texture(VICTORY_ANIM, pose, VICTORY_FACING, costume)
            sprite.scale = VICTORY_SCALE
            sprite.position = (
                feet_x + (rect.width / 2 - rect.pivot_x) * VICTORY_SCALE,
                feet_y + (rect.pivot_y - rect.height / 2) * VICTORY_SCALE,
            )

    def choose(self, key: str) -> None:
        """Play again with the same settings, or change them."""
        if key == "rematch":
            self.flow.begin_match(self.setup)
        else:
            self.flow.show_character_select(self.setup)

    def back(self) -> None:
        """Back to character select."""
        self.flow.show_character_select(self.setup)


def winner_text(match: Match) -> str:
    """Return the results heading: the winning player, or the winning team."""
    result = match.result
    if result is None:
        return "NO CONTEST"
    if match.rules.teams is not None:
        team = match.fighters[result.winner].team
        return f"{TEAM_NAMES[team % len(TEAM_NAMES)].upper()} TEAM WINS!"
    return f"PLAYER {result.winner + 1} WINS!"
