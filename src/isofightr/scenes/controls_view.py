"""The Controls screen: one interface for rebinding keyboards and gamepads.

Plan note "08 - Controls and Input" (decision D-061, wireframes
``m13_wf_controls_keyboard.png`` and ``m13_wf_controls_gamepad.png``). A tab per player
edits the device that player uses. The device's actions are tiles grouped by purpose; each
tile has a big cap (the primary control) and a small one (the secondary). Pick a cap,
confirm, and the next key or button pressed is bound to it. Caps light up while their
control is held, so a binding can be checked at once. Every change is saved as it is made.

What binding does is in :mod:`isofightr.scenes.controls_model`; this module lays the tiles
out, listens for the new control and draws.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import arcade

from isofightr.config import MAX_PLAYERS, NATIVE_H
from isofightr.input.devices import key_name
from isofightr.input.gamepad import PAD_CONTROLS, held_controls
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes import controls_model as model
from isofightr.scenes.menus import MenuView
from isofightr.settings import Settings
from isofightr.ui import pad_art, theme
from isofightr.ui.anim import blink
from isofightr.ui.focus import FocusMap, Rect
from isofightr.ui.font import TextSize
from isofightr.ui.kit_art import Look
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import (
    Button,
    FocusFrame,
    KeyCap,
    Picture,
    Stepper,
    Tab,
    add_panel,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

COLUMN_LEFTS = (24, 224, 432)
"""Left edge of the screen's three columns of tile groups."""
BAND_TOPS = (318, 202)
"""Top of the upper and the lower band of groups."""
TILE_WIDTH = 56
TILE_GAP = 4
ROW_PITCH = 52
MAIN_HEIGHT = 24
ALT_HEIGHT = 14
TAB_WIDTH = 58
TAB_LEFT = 384
OPTION_LEFT = 96
OPTION_WIDTH = 168
OPTION_HEIGHT = 18
OPTION_PITCH = 22
OPTIONS_BOTTOM = 46
TILES_PANEL = Rect(12, 140, 616, 188)
OPTIONS_PANEL = Rect(12, 40, 258, 96)
INFO = Rect(276, 76, 352, 60)
SIDE = Rect(424, 146, 196, 94)
"""The panel beside the lower band: the live test, or the controller diagram."""
BLINK_TICKS = 30
SLOT_NAMES = ("primary", "secondary")
DEVICE, LAYOUT, STICK, DEADZONE, DEFAULT, BACK = (
    "device",
    "layout",
    "stick",
    "deadzone",
    "default",
    "back",
)
STEPPERS = (DEVICE, LAYOUT, STICK, DEADZONE)
STEPS = {MenuAction.LEFT: -1, MenuAction.RIGHT: 1}
EMPTY_ALT = "+"
"""What an empty secondary cap shows: there is room for one more control."""
LISTENING = "?"


def tile_key(action: str, slot: int) -> str:
    """Return the focus name of one of an action's two caps."""
    return f"{action}:{slot}"


class ControlsView(MenuView):
    """Rebind the device a player uses."""

    def __init__(
        self,
        pixel_buffer: PixelBuffer,
        flow: GameFlow,
        on_back: Callable[[], None] | None = None,
        tab: int = 0,
        cursor: str = "",
    ) -> None:
        """Lay out the tab's device.

        Args:
            pixel_buffer: the native render target.
            flow: the router; it holds and saves the settings.
            on_back: where BACK goes (the main menu if not given).
            tab: the player whose device to show (0 to 3).
            cursor: the focus name to start on (the first tile if empty or unknown).
        """
        super().__init__(pixel_buffer, flow)
        self.dim = None
        self.on_back = on_back
        self.tab = min(max(tab, 0), MAX_PLAYERS - 1)
        self.device = model.tab_device(flow.settings, self.tab)
        self.pad = model.is_pad(self.device)
        self.listening: tuple[str, int] | None = None
        """The cap waiting for a key or button: ``(action, slot)``."""
        self.confirming_default = False
        self.message = ""
        self._held: frozenset[str] = frozenset()
        self._pad_held: frozenset[str] = frozenset()
        self.header("CONTROLS", "controller" if self.pad else "keyboard")
        ui = self.ui

        self.rects: dict[str, Rect] = {}
        self.tabs: list[Tab] = []
        for index in range(MAX_PLAYERS):
            rect = Rect(TAB_LEFT + index * (TAB_WIDTH + 4), NATIVE_H - 24, TAB_WIDTH, 20)
            tab_widget = Tab(
                ui, rect, f"P{index + 1}", theme.player_color(index), index == self.tab
            )
            self.tabs.append(tab_widget)
            self.rects[f"tab:{index}"] = rect

        add_panel(ui, TILES_PANEL)
        self.caps: dict[tuple[str, int], KeyCap] = {}
        for group in model.groups(self.device):
            left, top = COLUMN_LEFTS[group.column], BAND_TOPS[group.band]
            ui.write(group.title, left, top - 8, TextSize.SMALL, theme.TEXT_MUTED)
            for tile in group.tiles:
                x = left + tile.column * (TILE_WIDTH + TILE_GAP)
                tile_top = top - 10 - tile.row * ROW_PITCH
                ui.write(
                    tile.label, x + TILE_WIDTH // 2, tile_top - 8, TextSize.SMALL, align="centre"
                )
                main = Rect(x, tile_top - 10 - MAIN_HEIGHT, TILE_WIDTH, MAIN_HEIGHT)
                self.caps[(tile.action, 0)] = KeyCap(ui, main)
                if tile.fixed:
                    continue
                alt = Rect(x, main.bottom - 1 - ALT_HEIGHT, TILE_WIDTH, ALT_HEIGHT)
                self.caps[(tile.action, 1)] = KeyCap(ui, alt, size=TextSize.BODY)
                self.rects[tile_key(tile.action, 0)] = main
                self.rects[tile_key(tile.action, 1)] = alt

        add_panel(ui, SIDE, theme.PANEL_DEEP, theme.PANEL_LIGHT)
        side_title = "CONTROLLER" if self.pad else "LIVE TEST"
        ui.write(side_title, SIDE.left + theme.PAD, SIDE.top - 12, TextSize.SMALL, theme.TEXT_MUTED)
        self.side_note = ui.write(
            "", SIDE.right - theme.PAD, SIDE.top - 12, TextSize.SMALL, theme.TEXT_MUTED, "right"
        )
        self.diagram: Picture | None = None
        self.live = ui.write_in(SIDE, "", TextSize.TITLE, theme.ON)
        if self.pad:
            width, height = pad_art.PAD_ART_SIZE
            self.diagram = Picture(
                ui, Rect(SIDE.left + (SIDE.width - width) // 2, SIDE.bottom + 2, width, height)
            )

        self.steppers: dict[str, Stepper] = {}
        options = [(DEVICE, "DEVICE")]
        if self.pad:
            options += [(DEADZONE, "DEADZONE"), (STICK, "RIGHT STICK"), (LAYOUT, "LAYOUT")]
        add_panel(
            ui,
            Rect(
                OPTIONS_PANEL.left,
                OPTIONS_PANEL.bottom,
                OPTIONS_PANEL.width,
                len(options) * OPTION_PITCH + 2 * theme.GAP,
            ),
        )
        for index, (key, label) in enumerate(options):
            bottom = OPTIONS_BOTTOM + index * OPTION_PITCH
            ui.write(label, COLUMN_LEFTS[0], bottom + 6, TextSize.SMALL, theme.TEXT_MUTED)
            rect = Rect(OPTION_LEFT, bottom, OPTION_WIDTH, OPTION_HEIGHT)
            self.steppers[key] = Stepper(ui, rect)
            self.rects[key] = rect

        add_panel(ui, INFO, theme.PANEL_DEEP, theme.PANEL_LIGHT)
        text_left = INFO.left + theme.PAD
        self.info_title = ui.write("", text_left, INFO.top - 16, TextSize.BODY, theme.HEADING)
        self.info_lines = [
            ui.write("", text_left, INFO.top - 30 - row * 13, TextSize.BODY, theme.FOG)
            for row in range(3)
        ]
        self.buttons = {
            DEFAULT: Button(
                ui, Rect(424, 46, 96, theme.BUTTON_HEIGHT), "DEFAULT", look=Look.DANGER
            ),
            BACK: Button(ui, Rect(528, 46, 96, theme.BUTTON_HEIGHT), "BACK"),
        }
        self.rects |= {key: button.rect for key, button in self.buttons.items()}
        self.focus_map = FocusMap(self.rects)
        self.tab_frame = FocusFrame(ui)
        first = next(key for key in self.rects if ":" in key and not key.startswith("tab"))
        self.cursor = cursor if cursor in self.rects else first
        self.footer(
            "{stick}: move   {attack}: rebind   {grab}: clear   {special}: back   mouse: click"
        )
        self.refresh()

    # --- settings --------------------------------------------------------------------------

    @property
    def settings(self) -> Settings:
        """The settings being edited (the flow's)."""
        return self.flow.settings

    def apply(self, settings: Settings) -> None:
        """Keep and save changed settings, and use them for this screen's own input."""
        if settings == self.settings:
            return
        self.flow.update_settings(settings)
        self.hub.apply_settings(settings)
        self._footer_device = ""

    def reopen(self, tab: int, cursor: str) -> None:
        """Show the screen again for another tab or device (the tiles differ)."""
        self.flow.show_controls(self.on_back, tab, cursor)

    # --- listening for the new control -----------------------------------------------------

    def focused_tile(self) -> tuple[str, int] | None:
        """Return the ``(action, slot)`` of the cap under the cursor, or ``None``."""
        action, _, slot = self.cursor.partition(":")
        if action == "tab" or not slot.isdigit():
            return None
        return (action, int(slot))

    def start_listening(self) -> None:
        """Wait for the next key or button: it becomes the cap's control."""
        tile = self.focused_tile()
        if tile is None:
            return
        if self.pad and not self.hub.connected(self.device):
            self.message = f"{model.DEVICE_NAMES[self.device]} is not connected: plug it in"
            self.audio.play("ui_back")
            return
        self.listening = tile
        self.message = ""
        self._key_actions = []
        self._clicks = []

    def stop_listening(self, control: str | None) -> None:
        """Bind ``control`` to the waiting cap (``None`` cancels), then carry on. Whatever
        is held is ignored until it is released, so the new control does not also act."""
        tile, self.listening = self.listening, None
        self.menu_input.reset()
        self._key_actions = []
        if tile is None or control is None:
            self.audio.play("ui_back")
            return
        action, slot = tile
        taken_from = model.owner(self.settings, self.device, control)
        self.apply(model.bind(self.settings, self.device, action, slot, control))
        self.audio.play("ui_pick")
        if taken_from is not None and taken_from != action:
            label = model.control_label(control, self.pad)
            self.message = f"{label} was taken from {model.ACTION_NAMES[taken_from]}"
        # A second control went into the first slot if the action had none.
        if not model.bound(self.settings, self.device, action)[1:]:
            self.cursor = tile_key(action, 0)

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """While a cap waits, the next key is its new binding (Escape cancels)."""
        if self.listening is None:
            super().on_key_press(symbol, modifiers)
            return
        self._keys.press(symbol)
        if symbol == arcade.key.ESCAPE:
            self.stop_listening(None)
        elif not self.pad:
            name = key_name(symbol)
            if model.can_bind(self.device, name):
                self.stop_listening(name)
            else:
                self.message = "Enter, Escape and Backspace are fixed: they cannot be bound"
                self.audio.play("ui_back")

    def tick(self) -> None:
        """Read the gamepad's own buttons (for the live test, and for a cap that waits for
        one), then run the menu as usual."""
        state = self.hub.pad_state(self.device) if self.pad else None
        held = frozenset() if state is None else held_controls(state)
        if state is not None and state.start:
            held |= {"start"}
        pressed = held - self._pad_held
        self._pad_held = held
        keys = self._keys.keys()
        self._held = held if self.pad else frozenset(key_name(code) for code in keys)
        if self.pad and self.listening is not None and pressed:
            if "start" in pressed:
                self.stop_listening(None)
            else:
                self.stop_listening(next(name for name in PAD_CONTROLS if name in pressed))
        super().tick()

    # --- input -----------------------------------------------------------------------------

    def act(self, device: str, action: MenuAction) -> None:
        """Move the cursor, start rebinding, clear a cap, change an option, or leave."""
        if self.listening is not None:
            return
        if not (action is MenuAction.CONFIRM and self.cursor == DEFAULT):
            self.confirming_default = False
        if action is MenuAction.BACK:
            self.leave()
        elif action is MenuAction.EXTRA:
            tile = self.focused_tile()
            if tile is not None:
                self.apply(model.unbind(self.settings, self.device, *tile))
                self.message = ""
        elif action in STEPS and self.cursor in STEPPERS:
            self.step(self.cursor, STEPS[action])
        elif action is MenuAction.CONFIRM:
            self.press()
        else:
            self.cursor = self.focus_map.move(self.cursor, action)

    def press(self) -> None:
        """Confirm on whatever the cursor is on."""
        if self.cursor.startswith("tab:"):
            self.reopen(int(self.cursor[4:]), self.cursor)
        elif self.cursor in STEPPERS:
            self.step(self.cursor, 1)
        elif self.cursor == BACK:
            self.leave()
        elif self.cursor == DEFAULT:
            if self.confirming_default:
                self.confirming_default = False
                self.apply(model.with_defaults(self.settings, self.device))
                self.message = f"{model.DEVICE_NAMES[self.device]}: default controls"
                self.audio.play("ui_pick")
            else:
                self.confirming_default = True
        else:
            self.start_listening()

    def step(self, option: str, step: int) -> None:
        """Change one of the steppers under the tiles."""
        self.message = ""
        if option == DEVICE:
            self.apply(model.with_tab_device(self.settings, self.tab, step))
            self.reopen(self.tab, DEVICE)
        elif option == LAYOUT:
            self.apply(model.step_layout(self.settings, self.device, step))
        elif option == STICK:
            self.apply(model.step_right_stick(self.settings, self.device, step))
        elif option == DEADZONE:
            self.apply(model.step_deadzone(self.settings, step))

    def leave(self) -> None:
        """Go back to where the screen was opened from."""
        (self.on_back or self.flow.show_main_menu)()

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on whatever is under the mouse (not while a cap is waiting)."""
        if self.listening is not None:
            return False
        key = self.focus_map.at(x, y)
        if key is None:
            return False
        if key != self.cursor:
            self.confirming_default = False
        self.cursor = key
        return True

    def click(self, x: int, y: int) -> None:
        """A click presses what is under it; on a stepper its left or right half steps it."""
        if not self.hover(x, y):
            return
        self.audio.play("ui_select")
        if self.cursor in STEPPERS:
            rect = self.rects[self.cursor]
            self.step(self.cursor, 1 if x >= rect.left + rect.width // 2 else -1)
        else:
            self.press()

    # --- drawing ---------------------------------------------------------------------------

    def cap_look(self, action: str, slot: int, lit: set[tuple[str, int]]) -> tuple[str, Look]:
        """Return what a cap shows and how."""
        settings, device = self.settings, self.device
        caption = model.tile_label(settings, device, action, slot)
        if action in (model.FIXED_STICK, model.FIXED_PAUSE):
            return caption, Look.LIT if (action, slot) in lit else Look.DISABLED
        if self.listening == (action, slot):
            # The waiting cap flashes between the focus and the lit look.
            return (LISTENING, Look.FOCUS if blink(self.tick_count, BLINK_TICKS) else Look.LIT)
        if (action, slot) in lit:
            return caption, Look.LIT
        if self.cursor == tile_key(action, slot):
            return caption or EMPTY_ALT, Look.FOCUS
        if not caption:
            return EMPTY_ALT, Look.DISABLED
        if caption == model.UNBOUND:
            # Red only where it matters: an action the player cannot do without.
            missing = model.is_missing(settings, device, action)
            return caption, Look.DANGER if missing else Look.DISABLED
        if caption == model.RIGHT_STICK_LABEL:
            return caption, Look.DISABLED
        return caption, Look.NORMAL

    def info(self) -> tuple[str, list[str]]:
        """Return the info panel's title and lines for the screen's state."""
        thing = "BUTTON" if self.pad else "KEY"
        if self.listening is not None:
            action, slot = self.listening
            name = model.ACTION_NAMES[action]
            cancel = "Start or Esc cancels." if self.pad else "Esc cancels."
            return (f"PRESS A {thing}", [f"for {name} ({SLOT_NAMES[slot]}).", cancel])
        if self.confirming_default:
            name = model.DEVICE_NAMES[self.device]
            return (
                "RESET THE CONTROLS?",
                [f"Confirm again to put {name}", "back on its defaults."],
            )
        lines = [
            f"Pick a cap, confirm, press the new {thing.lower()}.",
            f"The small cap is a second {thing.lower()}.",
        ]
        return ("HOW IT WORKS", lines)

    def refresh(self) -> None:
        """Show every cap, the options, the info panel and the live test."""
        settings, device = self.settings, self.device
        lit = model.lit(settings, device, self._held)
        for (action, slot), cap in self.caps.items():
            cap.set(*self.cap_look(action, slot, lit))
        for index, tab in enumerate(self.tabs):
            tab.active = index == self.tab
        self.steppers[DEVICE].set(model.DEVICE_NAMES[device], self.cursor == DEVICE)
        if self.pad:
            pad = settings.pad(model.pad_slot(device))
            self.steppers[LAYOUT].set(model.layout_name(pad), self.cursor == LAYOUT)
            self.steppers[STICK].set(model.STICK_MODE_NAMES[pad.right_stick], self.cursor == STICK)
            self.steppers[DEADZONE].set(f"{settings.deadzone:.2f}", self.cursor == DEADZONE)
        for key, button in self.buttons.items():
            button.focus(key == self.cursor)
        self.buttons[DEFAULT].label.text = "SURE?" if self.confirming_default else "DEFAULT"

        title, lines = self.info()
        self.info_title.text = title
        flashing = self.listening is not None and not blink(self.tick_count, BLINK_TICKS)
        self.info_title.color = theme.TEXT if flashing else theme.HEADING
        warnings = model.warnings(settings, device)
        notes = [(line, theme.FOG) for line in lines]
        if self.message:
            notes.append((self.message, theme.FOCUS_GLOW))
        elif warnings:
            notes.append((warnings[0], theme.DANGER))
        for label, (text, color) in zip(
            self.info_lines, [*notes, ("", theme.FOG)] * 2, strict=False
        ):
            label.text = text
            label.color = color

        tile = self.listening or self.focused_tile()
        marked = frozenset(model.bound(settings, device, tile[0])) if tile else frozenset()
        if self.diagram is not None:
            held = self._held
            self.diagram.show(
                ("pad-diagram", held, marked),
                lambda held=held, marked=marked: pad_art.build_pad(held, marked),
            )
            self.side_note.text = "" if self.hub.connected(device) else "NOT CONNECTED"
            self.side_note.color = theme.DANGER
        else:
            names = sorted(name for name in self._held if name)
            self.live.text = " ".join(model.control_label(name, False) for name in names[:3])
            self.side_note.text = "" if names else "HOLD A KEY: ITS CAP LIGHTS UP"
        if self.cursor.startswith("tab:"):
            self.tab_frame.show(self.rects[self.cursor], self.tick_count)
        else:
            self.tab_frame.hide()
