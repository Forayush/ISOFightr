"""The menu scenes: title, main menu, rules, settings, character select, stage select, results.

Plan note "13 - Game Modes UI and Flow" ("Screen flow", "Character select screen",
"Settings"). Every scene is driven by every connected device through
:class:`isofightr.ui.menu.MenuInput`: move with the stick, attack or jump to confirm, special
or shield to go back. Enter and Escape also confirm and go back, as the WASD keyboard.
Scenes ask the :class:`~isofightr.scenes.flow.GameFlow` to move on.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import arcade

from isofightr.config import (
    AUDIO_MENU_SONG,
    AUDIO_VICTORY_SONG,
    CPU_DEFAULT_LEVEL,
    CPU_MAX_LEVEL,
    CPU_MIN_LEVEL,
    MAX_PLAYERS,
    NATIVE_H,
    NATIVE_W,
    WINDOW_TITLE,
)
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.input.devices import KEYBOARD_PREFIX, DeviceHub
from isofightr.input.keyboard import KeyLatch
from isofightr.render import placeholder_art as art
from isofightr.render.fighter_look import costume_index
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.pixel_scale import window_to_native
from isofightr.render.sprite_bank import SpriteBank
from isofightr.scenes.setup import (
    RANDOM_STAGE,
    TEAM_NAMES,
    MatchSetup,
    can_start,
    result_awards,
    results_table,
    training_setup,
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
        self.hub = DeviceHub(flow.settings)
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

    def on_hide_view(self) -> None:
        """Release the controllers when the scene goes away."""
        self.hub.close()

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


class TitleView(MenuView):
    """The title screen: any confirm goes to the main menu."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the title."""
        super().__init__(pixel_buffer, flow)
        self.ui.centred(WINDOW_TITLE.upper(), NATIVE_H // 2 + 20, HIGHLIGHT, TITLE_SCALE)
        self.ui.centred("an isometric platform fighter", NATIVE_H // 2 - 4, MUTED)
        self.prompt = self.ui.centred("press ATTACK or ENTER", NATIVE_H // 2 - 60)

    def act(self, device: str, action: MenuAction) -> None:
        """Start on confirm."""
        if action is MenuAction.CONFIRM:
            self.flow.show_main_menu()

    def refresh(self) -> None:
        """Blink the prompt."""
        on = (self.tick_count // BLINK_TICKS) % 2 == 0
        self.prompt.text = "press ATTACK or ENTER" if on else ""


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


class MainMenuView(MenuListView):
    """Versus, Training, Rules, Settings, Quit."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the main menu."""
        menu = Menu(
            [
                MenuItem("versus", "Versus"),
                MenuItem("training", "Training"),
                MenuItem("rules", "Rules"),
                MenuItem("controls", "Controls"),
                MenuItem("settings", "Settings"),
                MenuItem("quit", "Quit"),
            ]
        )
        super().__init__(pixel_buffer, flow, "MAIN MENU", menu)
        self.footer("{stick}: move   {attack}: pick   {special}: back")

    def choose(self, key: str) -> None:
        """Go where the item says."""
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

    def back(self) -> None:
        """Back to the title."""
        self.flow.show_title()


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


@dataclass(slots=True)
class Slot:
    """One player slot on the character select screen."""

    device: str = ""
    """The device that joined this slot ("" = empty)."""
    character: int = 0
    team: int = 0
    ready: bool = False
    row: int = 0
    """Which of the slot's rows its cursor is on: 0 character, then team (a person) or level
    and team (a CPU)."""
    cpu: int = 0
    """CPU level (0 = a person's slot)."""
    owner: str = ""
    """For a CPU slot: the device of the player who added it and sets it up."""

    @property
    def taken(self) -> bool:
        """Whether someone, or a CPU, plays in this slot."""
        return bool(self.device) or self.cpu > 0

    def clear(self) -> None:
        """Empty the slot."""
        self.device, self.ready, self.row, self.cpu, self.owner = "", False, 0, 0, ""


class CharacterSelectView(MenuView):
    """Up to four players join with their own device, pick a character (and a team), and
    press confirm when ready. The match goes on to stage select once everyone is ready.

    A device that has not joined joins the first free slot with confirm. Back un-readies,
    then leaves the slot; with nobody joined it goes back to the main menu. Slots remember
    their device between visits and between sessions.

    A joined player adds a CPU to the first free slot with grab (plan note 13: player type
    Human/CPU/Off and CPU level per slot) and then sets it up: left and right change the row,
    up and down move between character, level and team, confirm goes back to the player's
    own slot and back removes the CPU. CPUs are always ready, and leave with their player.
    """

    PANEL_BOTTOM = 70
    PANEL_HEIGHT = 170
    PANEL_ROWS = 5
    PANEL_CAPACITY = 24
    BUST_SCALE = 2
    BUST_CENTRE_Y = PANEL_BOTTOM + 36

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup) -> None:
        """Build four slot panels and rejoin the devices that were here last time."""
        super().__init__(pixel_buffer, flow)
        self.setup = setup
        self.character_ids = tuple(list_character_ids())
        self.character_names = tuple(
            load_character(name).display_name for name in self.character_ids
        )
        self.slots = [Slot(team=index % len(TEAM_NAMES)) for index in range(MAX_PLAYERS)]
        self.focus: dict[str, int] = {}
        """For a player editing one of their CPUs: which slot."""
        self.message = ""
        for index, device in enumerate(flow.settings.slot_devices):
            if device and self.hub.connected(device) and not self._slot_of(device):
                self.slots[index].device = device
        for index, name in enumerate(setup.characters[:MAX_PLAYERS]):
            if name in self.character_ids:
                self.slots[index].character = self.character_ids.index(name)
        if not setup.training:
            for index, level in enumerate(setup.cpus[:MAX_PLAYERS]):
                owner = next((slot.device for slot in self.slots if slot.device), "")
                if level > 0 and owner and not self.slots[index].taken:
                    self.slots[index].cpu, self.slots[index].owner = level, owner
        for index, team in enumerate(setup.teams[:MAX_PLAYERS]):
            self.slots[index].team = team

        self.heading("TRAINING: CHARACTER" if setup.training else "VERSUS: CHOOSE YOUR FIGHTER")
        width = NATIVE_W // MAX_PLAYERS
        self._panels = []
        for index in range(MAX_PLAYERS):
            left = index * width + 6
            self.ui.panel(left, self.PANEL_BOTTOM, width - 12, self.PANEL_HEIGHT)
            self._panels.append(
                TextBlock(
                    self.ui,
                    left + 8,
                    self.PANEL_BOTTOM + self.PANEL_HEIGHT - 8,
                    self.PANEL_ROWS,
                    self.PANEL_CAPACITY,
                    spacing=6,
                )
            )
        self._busts: list[arcade.Sprite] = []
        blank = arcade.Texture(art.build_panel(1, 1, (0, 0, 0, 0), (0, 0, 0, 0)))
        for index in range(MAX_PLAYERS):
            bust = self.ui.image(blank, 0, 0)
            bust.scale = self.BUST_SCALE
            bust.position = (index * width + width / 2, self.BUST_CENTRE_Y)
            bust.visible = False
            self._busts.append(bust)
        self._banks: dict[str, SpriteBank | None] = {}
        self._status = self.ui.label(centred_left(70), self.PANEL_BOTTOM - 26, 70, MUTED)
        hint = "" if setup.training else "   {grab}: add CPU"
        self.footer(f"{{attack}}: join / ready   {{stick}}: change{hint}   {{special}}: back")
        self.refresh()

    def _bank(self, character_id: str) -> SpriteBank | None:
        if character_id not in self._banks:
            try:
                sprite_set = load_sprite_set(character_id)
            except SpriteSheetError:
                sprite_set = None
            self._banks[character_id] = None if sprite_set is None else SpriteBank(sprite_set)
        return self._banks[character_id]

    def _show_bust(self, index: int, slot: Slot) -> None:
        """Show the slot's character in the costume it will wear, if it has art."""
        bust = self._busts[index]
        bank = self._bank(self.character_ids[slot.character]) if slot.taken else None
        team_play = self._rows() == 2
        color = slot.team if team_play else index
        texture = None
        if bank is not None:
            costumes = len(bank.sprite_set.costumes)
            texture = bank.portrait("bust", costume_index(color, team_play, costumes))
        bust.visible = texture is not None
        if texture is not None and bust.texture is not texture:
            bust.texture = texture

    def _slot_of(self, device: str) -> Slot | None:
        return next((slot for slot in self.slots if slot.device == device), None)

    @property
    def joined(self) -> list[Slot]:
        """The slots that have a player or a CPU, packed in order: slot order is player
        order."""
        return [slot for slot in self.slots if slot.taken]

    @property
    def people(self) -> list[Slot]:
        """The slots that people joined."""
        return [slot for slot in self.slots if slot.device]

    def _rows(self) -> int:
        return 2 if self.setup.team_play and not self.setup.training else 1

    def _free_slot(self) -> Slot | None:
        return next((free for free in self.slots if not free.taken), None)

    def act(self, device: str, action: MenuAction) -> None:
        """Join, navigate the device's own slot (or a CPU it added), toggle ready, add or
        remove a CPU, or leave."""
        slot = self._slot_of(device)
        if slot is None:
            if action is MenuAction.CONFIRM:
                free = self._free_slot()
                if free is not None:
                    free.clear()
                    free.device = device
            elif action is MenuAction.BACK and not self.people:
                self.flow.show_main_menu()
            return
        if action is MenuAction.EXTRA and not slot.ready and not self.setup.training:
            self._add_cpu(device)
            return
        focused = self.focus.get(device)
        if focused is not None and self.slots[focused].owner == device:
            self._edit_cpu(device, self.slots[focused], action)
            return
        self.focus.pop(device, None)
        if action is MenuAction.BACK:
            if slot.ready:
                slot.ready = False
            else:
                slot.clear()
                for cpu in self.slots:
                    if cpu.owner == device:
                        cpu.clear()
            return
        if action is MenuAction.CONFIRM:
            slot.ready = True
            self._maybe_start()
            return
        if slot.ready:
            return
        if action in (MenuAction.UP, MenuAction.DOWN):
            slot.row = (slot.row + 1) % self._rows()
        elif action in (MenuAction.LEFT, MenuAction.RIGHT):
            step = -1 if action is MenuAction.LEFT else 1
            if slot.row == 0:
                slot.character = (slot.character + step) % len(self.character_ids)
            else:
                slot.team = (slot.team + step) % len(TEAM_NAMES)

    def _add_cpu(self, owner: str) -> None:
        """Put a CPU in the first free slot and let ``owner`` set it up."""
        free = self._free_slot()
        if free is None:
            return
        index = self.slots.index(free)
        free.clear()
        free.cpu, free.owner = CPU_DEFAULT_LEVEL, owner
        free.character = index % len(self.character_ids)
        self.focus[owner] = index

    def _edit_cpu(self, owner: str, cpu: Slot, action: MenuAction) -> None:
        """Set up a CPU: character, level and (in team play) team."""
        rows = 3 if self._rows() == 2 else 2
        if action is MenuAction.BACK:
            cpu.clear()
            self.focus.pop(owner, None)
        elif action is MenuAction.CONFIRM:
            self.focus.pop(owner, None)
        elif action in (MenuAction.UP, MenuAction.DOWN):
            cpu.row = (cpu.row + (1 if action is MenuAction.DOWN else -1)) % rows
        elif action in (MenuAction.LEFT, MenuAction.RIGHT):
            step = -1 if action is MenuAction.LEFT else 1
            if cpu.row == 0:
                cpu.character = (cpu.character + step) % len(self.character_ids)
            elif cpu.row == 1:
                span = CPU_MAX_LEVEL - CPU_MIN_LEVEL + 1
                cpu.cpu = (cpu.cpu - CPU_MIN_LEVEL + step) % span + CPU_MIN_LEVEL
            else:
                cpu.team = (cpu.team + step) % len(TEAM_NAMES)

    def current_setup(self) -> MatchSetup:
        """Return the setup as the joined slots have it now. Training adds a dummy as
        player 2 when only one player has joined."""
        joined = self.joined
        characters = [self.character_ids[slot.character] for slot in joined]
        devices = [slot.device for slot in joined]
        teams = [slot.team for slot in joined]
        cpus = [slot.cpu for slot in joined]
        if self.setup.training and len(joined) == 1:
            characters.append(characters[0])
            devices.append("")
            teams.append(1)
            cpus.append(0)
        return replace(
            self.setup,
            characters=tuple(characters),
            devices=tuple(devices),
            teams=tuple(teams),
            cpus=tuple(cpus) if any(cpus) else (),
        )

    def _maybe_start(self) -> None:
        people = self.people
        if not people or not all(slot.ready for slot in people):
            return
        setup = self.current_setup()
        self.message = can_start(setup, len(self.joined))
        if self.message:
            for slot in people:
                slot.ready = False
            return
        remembered = tuple(slot.device for slot in self.slots)
        self.flow.update_settings(replace(self.flow.settings, slot_devices=remembered))
        self.flow.show_stage_select(setup)

    def refresh(self) -> None:
        """Redraw the four panels. A slot whose controller was unplugged is emptied."""
        for slot in self.slots:
            if slot.device and not self.hub.connected(slot.device):
                for cpu in self.slots:
                    if cpu.owner == slot.device:
                        cpu.clear()
                slot.clear()
        teams = self._rows() == 2
        editing = {index: owner for owner, index in self.focus.items()}
        for index, (slot, panel) in enumerate(zip(self.slots, self._panels, strict=True)):
            self._show_bust(index, slot)
            if slot.cpu:
                marks = [">" if index in editing and slot.row == row else " " for row in range(3)]
                lines = [
                    f"P{index + 1}  CPU",
                    f"{marks[0]} < {self.character_names[slot.character]} >",
                    f"{marks[1]} < level {slot.cpu} >",
                    f"{marks[2]} < {TEAM_NAMES[slot.team]} team >" if teams else "",
                    "special: remove" if index in editing else "",
                ]
                panel.set_lines(lines)
                continue
            if not slot.device:
                hint = "" if self.setup.training else "or GRAB: add CPU"
                panel.set_lines([f"P{index + 1}", "", "press ATTACK", "to join", hint])
                continue
            here = not slot.ready and slot.device not in self.focus
            marks = [">" if slot.row == row and here else " " for row in range(2)]
            lines = [
                f"P{index + 1}",
                self.hub.name(slot.device),
                f"{marks[0]} < {self.character_names[slot.character]} >",
                f"{marks[1]} < {TEAM_NAMES[slot.team]} team >" if teams else "",
                "READY" if slot.ready else "attack when ready",
            ]
            panel.set_lines(lines, len(lines) - 1 if slot.ready else None)
        self._status.text = self.message
        if self.message:
            self._status.move_to(centred_left(len(self.message)), self.PANEL_BOTTOM - 26)


class StageSelectView(MenuView):
    """Pick a stage from rows of thumbnails, or a random one."""

    COLUMNS = 3
    ROW_HEIGHT = 128
    FIRST_LABEL_BOTTOM = 172
    THUMBNAIL_GAP = 14
    THUMBNAIL_MAX = (186, 96)

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup) -> None:
        """Build a thumbnail and a name for every stage."""
        super().__init__(pixel_buffer, flow)
        self.setup = setup
        self.stage_ids = [*list_stage_ids(), RANDOM_STAGE]
        self.cursor = self.stage_ids.index(setup.stage) if setup.stage in self.stage_ids else 0
        self.heading("CHOOSE A STAGE")
        self.footer("{stick}: stage   {attack}: fight   {special}: back")
        columns = min(self.COLUMNS, len(self.stage_ids))
        slot = NATIVE_W // columns
        self._names = []
        self._frames = []
        for index, stage_id in enumerate(self.stage_ids):
            row, column = divmod(index, columns)
            left = column * slot
            label_bottom = self.FIRST_LABEL_BOTTOM - row * self.ROW_HEIGHT
            thumb_bottom = label_bottom + self.THUMBNAIL_GAP
            if stage_id == RANDOM_STAGE:
                name = "Random"
                mark = self.ui.label(
                    left + centred_left(1, TITLE_SCALE, slot),
                    thumb_bottom + 30,
                    1,
                    MUTED,
                    TITLE_SCALE,
                )
                mark.text = "?"
            else:
                stage = load_stage(stage_id)
                name = stage.display_name
                picture = art.build_stage_thumbnail(stage, *self.THUMBNAIL_MAX)
                texture = arcade.Texture(picture)
                self.ui.image(texture, left + (slot - texture.width) // 2, thumb_bottom)
            label = self.ui.label(
                left + centred_left(len(name), width=slot), label_bottom, len(name) + 2
            )
            label.text = name
            self._names.append(label)
            frame = self.ui.panel(
                left + 4,
                label_bottom - 6,
                slot - 8,
                self.ROW_HEIGHT - 6,
                (0, 0, 0, 0),
                art.PANEL_BORDER,
            )
            self._frames.append(frame)
        self.refresh()

    @property
    def selected(self) -> str:
        """The stage id under the cursor."""
        return self.stage_ids[self.cursor]

    def act(self, device: str, action: MenuAction) -> None:
        """Move the cursor, start the match, or go back."""
        if action is MenuAction.LEFT:
            self.cursor = (self.cursor - 1) % len(self.stage_ids)
        elif action is MenuAction.RIGHT:
            self.cursor = (self.cursor + 1) % len(self.stage_ids)
        elif action in (MenuAction.UP, MenuAction.DOWN):
            step = -self.COLUMNS if action is MenuAction.UP else self.COLUMNS
            if 0 <= self.cursor + step < len(self.stage_ids):
                self.cursor += step
        elif action is MenuAction.CONFIRM:
            self.flow.start_battle(replace(self.setup, stage=self.selected))
        elif action is MenuAction.BACK:
            self.flow.show_character_select(self.setup)

    def refresh(self) -> None:
        """Frame and highlight the stage under the cursor."""
        for index, (label, frame) in enumerate(zip(self._names, self._frames, strict=True)):
            label.color = HIGHLIGHT if index == self.cursor else MUTED
            frame.visible = index == self.cursor


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
        team_play = match.rules.teams is not None
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
            costume = costume_index(fighter.color_index, team_play, len(sprite_set.costumes))
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
            self.flow.start_battle(self.setup)
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
