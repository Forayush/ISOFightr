"""The Rules screen and its random-stage-pool list.

Plan note "13 - Game Modes UI and Flow" ("Rules settings", decision D-061, wireframe
``m13_wf_rules.png``): one row per rule with an icon, a ``< value >`` stepper and an ON/OFF
switch, and DEFAULT and BACK underneath. What a row does is in
:mod:`isofightr.scenes.rules_model`; this module draws the rows and passes input on. Every
change is kept and saved at once (:meth:`GameFlow.set_rules`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from isofightr.config import NATIVE_W
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes import rules_model
from isofightr.scenes.menus import MenuView
from isofightr.scenes.rules_model import ROW_KEYS, RULE_ROWS
from isofightr.ui import kit_art, theme
from isofightr.ui.focus import FocusMap, Rect
from isofightr.ui.font import TextSize
from isofightr.ui.kit_art import Look
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import Button, Checkbox, Picture, Stepper, Toggle, add_panel

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

ROW_HEIGHT = 18
ROW_GAP = 1
PANEL = Rect(48, 86, NATIVE_W - 96, len(RULE_ROWS) * ROW_HEIGHT + 2 * theme.GAP)
STEPPER_WIDTH = 92
SWITCH_WIDTH = 52
BUTTONS_BOTTOM = 56
HELP_BOTTOM = 26
POOL, DEFAULT, BACK = "pool", "default", "back"
BOTTOM_KEYS = (POOL, DEFAULT, BACK)
"""The buttons under the rows, left to right."""
STEPS = {MenuAction.LEFT: -1, MenuAction.RIGHT: 1}


class RulesView(MenuView):
    """The versus rules. Up and down pick a row, left and right step its value, confirm flips
    its switch; DEFAULT puts every rule back."""

    def __init__(
        self,
        pixel_buffer: PixelBuffer,
        flow: GameFlow,
        on_back: Callable[[], None] | None = None,
        cursor: str = ROW_KEYS[0],
    ) -> None:
        """Build the rows from the flow's current versus setup.

        Args:
            pixel_buffer: the native render target.
            flow: the router; it holds the setup and saves the rules.
            on_back: where BACK goes (the main menu if not given).
            cursor: the row or button the cursor starts on.
        """
        super().__init__(pixel_buffer, flow)
        self.dim = None
        self.setup = flow.setup
        self.on_back = on_back or flow.show_main_menu
        self.cursor = cursor if cursor in (*ROW_KEYS, *BOTTOM_KEYS) else ROW_KEYS[0]
        self.header("RULES", "gear")
        add_panel(self.ui, PANEL)

        self.rects: dict[str, Rect] = {}
        self._rows: dict[str, Picture] = {}
        self._steppers: dict[str, Stepper] = {}
        self._switches: dict[str, Toggle] = {}
        self._labels = {}
        inner_left, inner_width = PANEL.left + theme.GAP, PANEL.width - 2 * theme.GAP
        switch_left = inner_left + inner_width - SWITCH_WIDTH - theme.GAP
        stepper_left = switch_left - STEPPER_WIDTH - theme.GAP
        for index, row in enumerate(RULE_ROWS):
            bottom = PANEL.top - theme.GAP - (index + 1) * ROW_HEIGHT
            rect = Rect(inner_left, bottom, inner_width, ROW_HEIGHT - ROW_GAP)
            self.rects[row.key] = rect
            self._rows[row.key] = Picture(self.ui, rect)
            self.ui.icon(row.icon, rect.left + theme.GAP, bottom + 2, theme.TEXT)
            label_box = Rect(rect.left + theme.ICON_SIZE + theme.GAP, bottom, 300, rect.height)
            self._labels[row.key] = self.ui.write_in(label_box, row.label, align="left")
            well = Rect(0, bottom + 1, 0, rect.height - 2)
            if row.has_value:
                self._steppers[row.key] = Stepper(
                    self.ui, Rect(stepper_left, well.bottom, STEPPER_WIDTH, well.height)
                )
            if row.has_switch:
                self._switches[row.key] = Toggle(
                    self.ui, Rect(switch_left, well.bottom, SWITCH_WIDTH, well.height)
                )

        height = theme.BUTTON_HEIGHT
        self.buttons = {
            POOL: Button(self.ui, Rect(PANEL.left, BUTTONS_BOTTOM, 250, height), "", "dice"),
            DEFAULT: Button(
                self.ui, Rect(PANEL.left + 262, BUTTONS_BOTTOM, 132, height), "DEFAULT",
                look=Look.DANGER,
            ),
            BACK: Button(self.ui, Rect(PANEL.right - 138, BUTTONS_BOTTOM, 138, height), "BACK"),
        }  # fmt: skip
        self.rects |= {key: button.rect for key, button in self.buttons.items()}
        self.focus_map = FocusMap(self.rects)
        strip = Rect(PANEL.left, HELP_BOTTOM, PANEL.width, 20)
        add_panel(self.ui, strip, theme.PANEL_DEEP, theme.PANEL_LIGHT, theme.SMALL_CORNER)
        self.help = self.ui.write_in(strip, "", TextSize.BODY, theme.FOG)
        self.footer("{stick}: row and value   {attack}: on / off   {special}: back   mouse: click")
        self.refresh()

    # --- input -----------------------------------------------------------------------------

    def set(self, setup: object) -> None:
        """Take a changed setup: keep it and save its rules."""
        from isofightr.scenes.setup import MatchSetup

        assert isinstance(setup, MatchSetup)
        if setup != self.setup:
            self.setup = setup
            self.flow.set_rules(setup)

    def act(self, device: str, action: MenuAction) -> None:
        """Move the cursor, change the row under it, or press a button."""
        if action is MenuAction.BACK:
            self.on_back()
        elif action in (MenuAction.UP, MenuAction.DOWN):
            self._move(1 if action is MenuAction.DOWN else -1)
        elif self.cursor in BOTTOM_KEYS:
            if action in STEPS:
                index = BOTTOM_KEYS.index(self.cursor) + STEPS[action]
                self.cursor = BOTTOM_KEYS[min(max(index, 0), len(BOTTOM_KEYS) - 1)]
            elif action is MenuAction.CONFIRM:
                self._press(self.cursor)
        elif action in STEPS:
            row = rules_model.row(self.cursor)
            if row.has_value:
                self.set(rules_model.step_row(self.setup, row.key, STEPS[action]))
            else:
                self.set(rules_model.toggle_row(self.setup, row.key))
        elif action is MenuAction.CONFIRM:
            self.set(rules_model.toggle_row(self.setup, self.cursor))

    def _move(self, step: int) -> None:
        """Up and down go through the rows, then the buttons, and wrap."""
        if self.cursor in BOTTOM_KEYS:
            self.cursor = ROW_KEYS[0] if step > 0 else ROW_KEYS[-1]
            return
        index = ROW_KEYS.index(self.cursor) + step
        if index < 0:
            self.cursor = BACK
        elif index >= len(ROW_KEYS):
            self.cursor = POOL
        else:
            self.cursor = ROW_KEYS[index]

    def _press(self, button: str) -> None:
        if button == POOL:
            self.flow.show_random_pool(self.on_back)
        elif button == DEFAULT:
            self.set(rules_model.with_default_rules(self.setup))
            self.audio.play("ui_pick")
        else:
            self.on_back()

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the row or button under the mouse."""
        key = self.focus_map.at(x, y)
        if key is None:
            return False
        self.cursor = key
        return True

    def click(self, x: int, y: int) -> None:
        """A click on a stepper's left or right half steps it; on a switch, or anywhere else
        on a row, it flips the switch; on a button it presses it."""
        if not self.hover(x, y):
            return
        self.audio.play("ui_select")
        key = self.cursor
        if key in BOTTOM_KEYS:
            self._press(key)
            return
        stepper = self._steppers.get(key)
        if stepper is not None and stepper.rect.contains(x, y):
            step = 1 if x >= stepper.rect.left + stepper.rect.width // 2 else -1
            self.set(rules_model.step_row(self.setup, key, step))
        else:
            self.set(rules_model.toggle_row(self.setup, key))

    # --- drawing ---------------------------------------------------------------------------

    def refresh(self) -> None:
        """Show every row's value and switch, the cursor, and the help line."""
        setup = self.setup
        for row in RULE_ROWS:
            focused = row.key == self.cursor
            rect = self.rects[row.key]
            self._rows[row.key].show(
                ("rule-row", rect.width, rect.height, focused),
                lambda rect=rect, focused=focused: kit_art.list_row(
                    rect.width, rect.height, focused
                ),
            )
            on = rules_model.row_on(setup, row.key)
            self._labels[row.key].color = theme.FOCUS_GLOW if focused else theme.TEXT
            if row.key in self._steppers:
                stepper = self._steppers[row.key]
                stepper.set(rules_model.row_value(setup, row.key), focused)
                # A value whose switch is off is not in force: show it dimmed.
                if on is False:
                    stepper.label.color = theme.TEXT_DIM
            if row.key in self._switches:
                self._switches[row.key].set(bool(on), focused)
        stages = list_stage_ids()
        pooled = len(setup.pool(stages))
        self.buttons[POOL].label.text = f"RANDOM STAGE POOL  {pooled}/{len(stages)}"
        for key, button in self.buttons.items():
            button.focus(key == self.cursor)
        self.help.text = self.help_text()

    def help_text(self) -> str:
        """Return the line under the buttons: what the thing under the cursor does."""
        if self.cursor == POOL:
            return "Choose which stages RANDOM may pick."
        if self.cursor == DEFAULT:
            return "Put every rule back to the game's defaults."
        if self.cursor == BACK:
            return "The rules are saved as you change them."
        if self.cursor in ("time", "stock") and self.setup.time_on and self.setup.stock_on:
            return "Both on: when time runs out, most stocks wins, then least damage."
        return rules_model.row(self.cursor).help


class RandomPoolView(MenuView):
    """The stages "Random" may pick: a tick box per stage. At least one stays ticked."""

    ROW = 20
    WIDTH = 260

    def __init__(
        self, pixel_buffer: PixelBuffer, flow: GameFlow, on_back: Callable[[], None] | None = None
    ) -> None:
        """List every stage with its tick box."""
        super().__init__(pixel_buffer, flow)
        self.dim = None
        self.setup = flow.setup
        self.on_back = on_back
        self.stages = list_stage_ids()
        self.header("RANDOM STAGE POOL", "dice")
        height = len(self.stages) * self.ROW + 2 * theme.GAP
        left = (NATIVE_W - self.WIDTH) // 2
        panel = Rect(left, 310 - height, self.WIDTH, height)
        add_panel(self.ui, panel)
        self.rects: dict[str, Rect] = {}
        self._rows: dict[str, Picture] = {}
        self._boxes: dict[str, Checkbox] = {}
        self._labels = {}
        for index, stage_id in enumerate(self.stages):
            bottom = panel.top - theme.GAP - (index + 1) * self.ROW
            rect = Rect(left + theme.GAP, bottom, self.WIDTH - 2 * theme.GAP, self.ROW - ROW_GAP)
            self.rects[stage_id] = rect
            self._rows[stage_id] = Picture(self.ui, rect)
            self._boxes[stage_id] = Checkbox(self.ui, rect.left + theme.GAP, bottom + 4)
            name = load_stage(stage_id).display_name
            box = Rect(rect.left + 20, bottom, rect.width - 20, rect.height)
            self._labels[stage_id] = self.ui.write_in(box, name, align="left")
        self.back_button = Button(
            self.ui, Rect(left, panel.bottom - 34, self.WIDTH, theme.BUTTON_HEIGHT), "BACK"
        )
        self.rects[BACK] = self.back_button.rect
        self.order = [*self.stages, BACK]
        self.cursor = self.order[0]
        self.focus_map = FocusMap(self.rects)
        self.footer("{stick}: stage   {attack}: in / out   {special}: back")
        self.refresh()

    def act(self, device: str, action: MenuAction) -> None:
        """Move, tick or untick, or leave."""
        if action is MenuAction.BACK:
            self.leave()
        elif action in (MenuAction.UP, MenuAction.DOWN):
            step = 1 if action is MenuAction.DOWN else -1
            self.cursor = self.order[(self.order.index(self.cursor) + step) % len(self.order)]
        elif action is MenuAction.CONFIRM:
            if self.cursor == BACK:
                self.leave()
                return
            changed = rules_model.toggle_pool(self.setup, self.cursor, self.stages)
            if changed == self.setup:
                self.audio.play("ui_back")  # the last stage cannot be taken out
            else:
                self.setup = changed
                self.flow.set_rules(changed)

    def leave(self) -> None:
        """Back to the rules, with the cursor on the pool button."""
        self.flow.show_rules(self.on_back, POOL)

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the stage or button under the mouse."""
        key = self.focus_map.at(x, y)
        if key is None:
            return False
        self.cursor = key
        return True

    def refresh(self) -> None:
        """Show the ticks and the cursor."""
        pool = self.setup.pool(self.stages)
        for stage_id in self.stages:
            focused = stage_id == self.cursor
            rect = self.rects[stage_id]
            self._rows[stage_id].show(
                ("rule-row", rect.width, rect.height, focused),
                lambda rect=rect, focused=focused: kit_art.list_row(
                    rect.width, rect.height, focused
                ),
            )
            self._boxes[stage_id].set(stage_id in pool, focused)
            self._labels[stage_id].color = theme.FOCUS_GLOW if focused else theme.TEXT
        self.back_button.focus(self.cursor == BACK)
