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

from isofightr.config import MAX_PLAYERS, NATIVE_H, NATIVE_W, WINDOW_TITLE
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.input.devices import KEYBOARD_PREFIX, DeviceHub, key_name
from isofightr.render import placeholder_art as art
from isofightr.render.fighter_look import costume_index
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.sprite_bank import SpriteBank
from isofightr.scenes.setup import (
    LAUNCH_RATES,
    RANDOM_STAGE,
    TEAM_NAMES,
    MatchSetup,
    Mode,
    can_start,
    results_table,
    training_setup,
)
from isofightr.scenes.ticked_view import TickedView
from isofightr.settings import (
    CAMERA_ZOOMS,
    DEADZONES,
    GAMEPAD_PRESETS,
    KEYBOARD_ACTIONS,
    KEYBOARD_ARROWS,
    KEYBOARD_SOLO,
    SCALES,
    SHAKE_STEPS,
    VOLUME_MAX,
    Settings,
)
from isofightr.sim.match import Match
from isofightr.ui.menu import Menu, MenuAction, MenuInput, MenuItem
from isofightr.ui.pixel_font import GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas
from isofightr.ui.widgets import HIGHLIGHT, MUTED, TextBlock, UiLayer, centred_left

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

KEY_CONFIRM = arcade.key.ENTER
KEY_BACK = arcade.key.ESCAPE
KEYBOARD_DEVICE = KEYBOARD_PREFIX + KEYBOARD_SOLO
"""The device Enter and Escape act as."""
BACKGROUND = (30, 40, 86, 255)
TITLE_SCALE = 4
HEADING_SCALE = 2
HEADING_BOTTOM = NATIVE_H - 60
ROW_CAPACITY = 52
FOOTER_BOTTOM = 10
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
        self._held_keys: set[int] = set()
        self._key_actions: list[MenuAction] = []
        black = arcade.Texture(art.build_panel(NATIVE_W, NATIVE_H, art.INK, art.INK))
        self._fade = arcade.Sprite(black, center_x=NATIVE_W / 2, center_y=NATIVE_H / 2)
        self._fade_layer: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._fade_layer.append(self._fade)

    def heading(self, text: str) -> None:
        """Add the scene's heading."""
        self.ui.centred(text, HEADING_BOTTOM, HIGHLIGHT, HEADING_SCALE)

    def footer(self, text: str) -> None:
        """Add the hint line at the bottom."""
        self.ui.centred(text, FOOTER_BOTTOM, MUTED)

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """Track held keys; Enter and Escape confirm and go back."""
        self._held_keys.add(symbol)
        if symbol == KEY_CONFIRM:
            self._key_actions.append(MenuAction.CONFIRM)
        elif symbol == KEY_BACK:
            self._key_actions.append(MenuAction.BACK)

    def on_key_release(self, symbol: int, modifiers: int) -> None:
        """Stop tracking a released key."""
        self._held_keys.discard(symbol)

    def on_hide_view(self) -> None:
        """Release the controllers when the scene goes away."""
        self.hub.close()

    def tick(self) -> None:
        """Hand this tick's menu actions to :meth:`act`, then refresh the text."""
        frames = self.hub.frames(self._held_keys)
        devices = list(frames)
        fired = self.menu_input.update([frames[device] for device in devices])
        for action in self._key_actions:
            if self.window.current_view is self:
                self.act(KEYBOARD_DEVICE, action)
        self._key_actions = []
        for device, actions in zip(devices, fired, strict=True):
            for action in MenuAction:
                if action in actions and self.window.current_view is self:
                    self.act(device, action)
        if self.window.current_view is self:
            self.refresh()

    def act(self, device: str, action: MenuAction) -> None:
        """Handle one menu action from one device. Override in scenes."""

    def refresh(self) -> None:
        """Update labels from the scene's state. Override in scenes."""

    def on_draw(self) -> None:
        """Draw the scene at native resolution, then upscale it to the window."""
        self.clear()
        fade = max(0.0, 1.0 - self.tick_count / FADE_TICKS)
        self._fade.alpha = round(255 * fade)
        with self.pixel_buffer.drawing(BACKGROUND):
            self.ui.draw()
            if fade > 0:
                self._fade_layer.draw(pixelated=True)
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
                MenuItem("settings", "Settings"),
                MenuItem("quit", "Quit"),
            ]
        )
        super().__init__(pixel_buffer, flow, "MAIN MENU", menu)
        self.footer("stick: move   attack: pick   special: back")

    def choose(self, key: str) -> None:
        """Go where the item says."""
        if key == "versus":
            self.flow.show_character_select(self.flow.setup)
        elif key == "training":
            self.flow.show_character_select(training_setup())
        elif key == "rules":
            self.flow.show_rules()
        elif key == "settings":
            self.flow.show_settings()
        else:
            self.window.close()

    def back(self) -> None:
        """Back to the title."""
        self.flow.show_title()


class RulesView(MenuListView):
    """The versus rules: mode, stocks or minutes, teams, friendly fire and the optional rules."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the rows from the flow's current versus setup."""
        setup = flow.setup
        self.setup = setup
        modes = tuple(mode.value.title() for mode in Mode)
        rates = tuple(f"{rate:g}x" for rate in LAUNCH_RATES)
        rate = LAUNCH_RATES.index(setup.launch_rate) if setup.launch_rate in LAUNCH_RATES else 2
        menu = Menu(
            [
                MenuItem("mode", "Mode", modes, list(Mode).index(setup.mode)),
                MenuItem("count", ""),
                MenuItem("teams", "Teams", ON_OFF, int(setup.team_play)),
                MenuItem("friendly_fire", "Friendly fire", ON_OFF, int(setup.friendly_fire)),
                MenuItem("launch_rate", "Launch rate", rates, rate),
                MenuItem("parry", "Parry", ON_OFF, int(setup.parry)),
                MenuItem(
                    "helpless",
                    "Helpless after a directional air dodge",
                    ON_OFF,
                    int(setup.air_dodge_helpless),
                ),
                MenuItem("back", "Back"),
            ]
        )
        super().__init__(pixel_buffer, flow, "RULES", menu)
        self.footer("up/down: row   left/right: change   special: back")

    def act(self, device: str, action: MenuAction) -> None:
        """The stocks/minutes row counts up and down instead of cycling choices."""
        on_count = self.menu.selected.key == "count"
        if on_count and action in (MenuAction.LEFT, MenuAction.RIGHT, MenuAction.CONFIRM):
            self.setup = self.setup.with_count(-1 if action is MenuAction.LEFT else 1)
            return
        super().act(device, action)

    def changed(self) -> None:
        """Copy the rows back into the setup."""
        menu = self.menu
        self.setup = replace(
            self.setup,
            mode=list(Mode)[menu.item("mode").index],
            team_play=bool(menu.item("teams").index),
            friendly_fire=bool(menu.item("friendly_fire").index),
            launch_rate=LAUNCH_RATES[menu.item("launch_rate").index],
            parry=bool(menu.item("parry").index),
            air_dodge_helpless=bool(menu.item("helpless").index),
        )

    def choose(self, key: str) -> None:
        """ "Back" leaves, keeping the rules."""
        self.back()

    def back(self) -> None:
        """Keep the rules and go back to the main menu."""
        self.flow.setup = self.setup
        self.flow.show_main_menu()

    def refresh(self) -> None:
        """Show the rows; the count row shows stocks or minutes for the current mode."""
        self.menu.item("count").label = f"< {self.setup.count_label} >"
        super().refresh()


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
                _setting(
                    "gamepad_preset",
                    "Gamepad layout",
                    ["right stick = up/down", "bumpers = up/down, right stick = smash"],
                    GAMEPAD_PRESETS,
                    settings.gamepad_preset,
                ),
                _setting(
                    "deadzone",
                    "Stick deadzone",
                    [f"{zone:.2f}" for zone in DEADZONES],
                    DEADZONES,
                    settings.deadzone,
                ),
                MenuItem("keys_solo", "Keys: keyboard (WASD)..."),
                MenuItem("keys_arrows", "Keys: keyboard (arrows)..."),
                _setting(
                    "camera_zoom",
                    "Camera zoom",
                    ["static", "stepped 2x"],
                    CAMERA_ZOOMS,
                    settings.camera_zoom,
                ),
                MenuItem("defaults", "Reset everything to defaults"),
                MenuItem("back", "Back"),
            ]
        )
        super().__init__(pixel_buffer, flow, "SETTINGS", menu)
        self.footer("left/right: change   attack: pick   special: back")

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
                gamepad_preset=GAMEPAD_PRESETS[menu.item("gamepad_preset").index],
                deadzone=DEADZONES[menu.item("deadzone").index],
                camera_zoom=CAMERA_ZOOMS[menu.item("camera_zoom").index],
            )
        )

    def choose(self, key: str) -> None:
        """Open a rebinding screen, reset, or leave."""
        if key == "keys_solo":
            self.flow.show_rebind(KEYBOARD_SOLO)
        elif key == "keys_arrows":
            self.flow.show_rebind(KEYBOARD_ARROWS)
        elif key == "defaults":
            self.flow.update_settings(Settings(slot_devices=self.flow.settings.slot_devices))
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


class RebindView(MenuListView):
    """Rebind one keyboard layout: pick an action, then press the key for it."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, layout: str) -> None:
        """Build one row per action of the layout."""
        self.layout = layout
        self.waiting_for: str | None = None
        items = [MenuItem(action, "") for action in KEYBOARD_ACTIONS]
        items += [MenuItem("defaults", "Reset these keys"), MenuItem("back", "Back")]
        title = "KEYS: WASD KEYBOARD" if layout == KEYBOARD_SOLO else "KEYS: ARROWS KEYBOARD"
        super().__init__(pixel_buffer, flow, title, Menu(items), HEADING_BOTTOM - 14)
        self.footer("attack: rebind, then press the new key   special: back")

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """While waiting for a key, the next key press is the new binding (Escape cancels)."""
        if self.waiting_for is None:
            super().on_key_press(symbol, modifiers)
            return
        action, self.waiting_for = self.waiting_for, None
        name = key_name(symbol)
        if symbol != KEY_BACK and name:
            self.flow.update_settings(self.flow.settings.with_key(self.layout, action, name))
            self.hub.close()
            self.hub = DeviceHub(self.flow.settings)
        self.menu_input.reset()

    def act(self, device: str, action: MenuAction) -> None:
        """Ignore the devices while waiting for a key."""
        if self.waiting_for is None:
            super().act(device, action)

    def choose(self, key: str) -> None:
        """Start waiting for a key, reset the layout, or leave."""
        if key == "defaults":
            self.flow.update_settings(self.flow.settings.with_default_keys(self.layout))
            self.hub.close()
            self.hub = DeviceHub(self.flow.settings)
        elif key == "back":
            self.back()
        else:
            self.waiting_for = key
            self._key_actions = []

    def back(self) -> None:
        """Back to the settings."""
        self.flow.show_settings()

    def refresh(self) -> None:
        """Show each action with its key, or a prompt while waiting."""
        keys = self.flow.settings.keys[self.layout]
        for action in KEYBOARD_ACTIONS:
            shown = "press a key..." if action == self.waiting_for else (keys[action] or "-")
            self.menu.item(action).label = f"{action.replace('_', ' '):<12} {shown}"
        super().refresh()


@dataclass(slots=True)
class Slot:
    """One player slot on the character select screen."""

    device: str = ""
    """The device that joined this slot ("" = empty)."""
    character: int = 0
    team: int = 0
    ready: bool = False
    row: int = 0
    """Which of the slot's rows its cursor is on: 0 character, 1 team."""


class CharacterSelectView(MenuView):
    """Up to four players join with their own device, pick a character (and a team), and
    press confirm when ready. The match goes on to stage select once everyone is ready.

    A device that has not joined joins the first free slot with confirm. Back un-readies,
    then leaves the slot; with nobody joined it goes back to the main menu. Slots remember
    their device between visits and between sessions.
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
        self.message = ""
        for index, device in enumerate(flow.settings.slot_devices):
            if device and self.hub.connected(device) and not self._slot_of(device):
                self.slots[index].device = device
        for index, name in enumerate(setup.characters[:MAX_PLAYERS]):
            if name in self.character_ids:
                self.slots[index].character = self.character_ids.index(name)
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
        self.footer("attack: join / ready   left/right: change   special: un-ready / leave")
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
        bank = self._bank(self.character_ids[slot.character]) if slot.device else None
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
        """The slots that have a player, packed in order: slot order is player order."""
        return [slot for slot in self.slots if slot.device]

    def _rows(self) -> int:
        return 2 if self.setup.team_play and not self.setup.training else 1

    def act(self, device: str, action: MenuAction) -> None:
        """Join, navigate the device's own slot, toggle ready, or leave."""
        slot = self._slot_of(device)
        if slot is None:
            if action is MenuAction.CONFIRM:
                free = next((free for free in self.slots if not free.device), None)
                if free is not None:
                    free.device, free.ready, free.row = device, False, 0
            elif action is MenuAction.BACK and not self.joined:
                self.flow.show_main_menu()
            return
        if action is MenuAction.BACK:
            if slot.ready:
                slot.ready = False
            else:
                slot.device = ""
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

    def current_setup(self) -> MatchSetup:
        """Return the setup as the joined slots have it now. Training adds a dummy as
        player 2 when only one player has joined."""
        joined = self.joined
        characters = [self.character_ids[slot.character] for slot in joined]
        devices = [slot.device for slot in joined]
        teams = [slot.team for slot in joined]
        if self.setup.training and len(joined) == 1:
            characters.append(characters[0])
            devices.append("")
            teams.append(1)
        return replace(
            self.setup,
            characters=tuple(characters),
            devices=tuple(devices),
            teams=tuple(teams),
        )

    def _maybe_start(self) -> None:
        joined = self.joined
        if not joined or not all(slot.ready for slot in joined):
            return
        setup = self.current_setup()
        self.message = can_start(setup, len(joined))
        if self.message:
            for slot in joined:
                slot.ready = False
            return
        remembered = tuple(slot.device for slot in self.slots)
        self.flow.update_settings(replace(self.flow.settings, slot_devices=remembered))
        self.flow.show_stage_select(setup)

    def refresh(self) -> None:
        """Redraw the four panels. A slot whose controller was unplugged is emptied."""
        for slot in self.slots:
            if slot.device and not self.hub.connected(slot.device):
                slot.device, slot.ready = "", False
        teams = self._rows() == 2
        for index, (slot, panel) in enumerate(zip(self.slots, self._panels, strict=True)):
            self._show_bust(index, slot)
            if not slot.device:
                panel.set_lines([f"P{index + 1}", "", "press ATTACK", "to join"])
                continue
            marks = [">" if slot.row == row and not slot.ready else " " for row in range(2)]
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
    """Pick a stage from a row of thumbnails, or a random one."""

    THUMBNAIL_BOTTOM = 110

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup) -> None:
        """Build a thumbnail and a name for every stage."""
        super().__init__(pixel_buffer, flow)
        self.setup = setup
        self.stage_ids = [*list_stage_ids(), RANDOM_STAGE]
        self.cursor = self.stage_ids.index(setup.stage) if setup.stage in self.stage_ids else 0
        self.heading("CHOOSE A STAGE")
        self.footer("left/right: stage   attack: fight   special: back")
        slot = NATIVE_W // len(self.stage_ids)
        self._names = []
        self._frames = []
        for index, stage_id in enumerate(self.stage_ids):
            left = index * slot
            if stage_id == RANDOM_STAGE:
                name = "Random"
                mark = self.ui.label(
                    left + centred_left(1, TITLE_SCALE, slot),
                    self.THUMBNAIL_BOTTOM + 40,
                    1,
                    MUTED,
                    TITLE_SCALE,
                )
                mark.text = "?"
            else:
                stage = load_stage(stage_id)
                name = stage.display_name
                texture = arcade.Texture(art.build_stage_thumbnail(stage))
                self.ui.image(
                    texture, left + (slot - texture.width) // 2, self.THUMBNAIL_BOTTOM + 20
                )
            label = self.ui.label(
                left + centred_left(len(name), width=slot), self.THUMBNAIL_BOTTOM, len(name) + 2
            )
            label.text = name
            self._names.append(label)
            frame = self.ui.panel(
                left + 4, self.THUMBNAIL_BOTTOM - 8, slot - 8, 150, (0, 0, 0, 0), art.PANEL_BORDER
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

    def __init__(
        self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup, match: Match
    ) -> None:
        """Build the table from the finished match."""
        self.setup = setup
        menu = Menu([MenuItem("rematch", "Rematch"), MenuItem("back", "Back to character select")])
        lines = results_table(match)
        rows_top = self.STATS_TOP - (len(lines) + 2) * (GLYPH_HEIGHT + 2)
        super().__init__(pixel_buffer, flow, winner_text(match), menu, rows_top)
        self.table_lines = lines
        table = TextBlock(self.ui, centred_left(len(lines[0])), self.STATS_TOP, len(lines), 80)
        table.set_lines(lines)

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
