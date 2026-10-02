"""The menu scenes: title, main menu, character select, stage select and results.

Plan note "13 - Game Modes UI and Flow" ("Screen flow"). Every scene is driven by the same
per-player input as the game (:class:`isofightr.ui.menu.MenuInput`): move with the stick,
attack or jump to confirm, special or shield to go back. Enter and Escape also confirm and
go back for player 1. Scenes ask the :class:`~isofightr.scenes.flow.GameFlow` to move on.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import arcade

from isofightr.config import NATIVE_H, NATIVE_W, WINDOW_TITLE
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.input.devices import InputSource
from isofightr.render import placeholder_art as art
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes.setup import (
    RANDOM_STAGE,
    MatchSetup,
    Mode,
    results_table,
    training_setup,
)
from isofightr.scenes.ticked_view import TickedView
from isofightr.sim.match import Match
from isofightr.ui.menu import Menu, MenuAction, MenuInput, MenuItem
from isofightr.ui.pixel_font import GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas
from isofightr.ui.widgets import HIGHLIGHT, MUTED, TextBlock, UiLayer, centred_left

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

MENU_PLAYERS = 2
"""Players that can drive the menus (four-player joining arrives in M7)."""
KEY_CONFIRM = arcade.key.ENTER
KEY_BACK = arcade.key.ESCAPE
BACKGROUND = (30, 40, 86, 255)
TITLE_SCALE = 4
HEADING_SCALE = 2
HEADING_BOTTOM = NATIVE_H - 60
ROW_CAPACITY = 44
FOOTER_BOTTOM = 10
FADE_TICKS = 10
"""A scene fades in from black over this many ticks."""
BLINK_TICKS = 30


class MenuView(TickedView):
    """Base of the menu scenes: polls menu input every tick and draws one UI layer."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Create an empty scene with its own input devices."""
        super().__init__(pixel_buffer, flow.max_ticks)
        self.flow = flow
        self.inputs = InputSource(MENU_PLAYERS)
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
        self.inputs.close()

    def tick(self) -> None:
        """Hand this tick's menu actions to :meth:`act`, then refresh the text."""
        actions = self.menu_input.update(self.inputs.poll(self._held_keys))
        for action in self._key_actions:
            self.act(0, action)
        self._key_actions = []
        for player, fired in enumerate(actions):
            for action in MenuAction:
                if action in fired and self.window.current_view is self:
                    self.act(player, action)
        self.refresh()

    def act(self, player: int, action: MenuAction) -> None:
        """Handle one menu action by one player. Override in scenes."""

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

    def act(self, player: int, action: MenuAction) -> None:
        """Start on confirm."""
        if action is MenuAction.CONFIRM:
            self.flow.show_main_menu()

    def refresh(self) -> None:
        """Blink the prompt."""
        on = (self.tick_count // BLINK_TICKS) % 2 == 0
        self.prompt.text = "press ATTACK or ENTER" if on else ""


class MenuListView(MenuView):
    """A scene that is one vertical menu in the middle of the screen."""

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

    def act(self, player: int, action: MenuAction) -> None:
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
    """Versus, Training, Quit."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the main menu."""
        menu = Menu(
            [
                MenuItem("versus", "Versus"),
                MenuItem("training", "Training"),
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
        else:
            self.window.close()

    def back(self) -> None:
        """Back to the title."""
        self.flow.show_title()


class CharacterSelectView(MenuListView):
    """Pick each player's character and the rules, then go on to the stage select.

    One shared list for now; per-player cursors on a portrait grid arrive with four-player
    joining in M7.
    """

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup) -> None:
        """Build the rows from the setup the player came in with."""
        self.setup = setup
        characters = tuple(list_character_ids())
        names = tuple(load_character(name).display_name for name in characters)
        self._characters = characters
        items = [
            MenuItem(f"p{index + 1}", f"Player {index + 1}", names, characters.index(chosen))
            for index, chosen in enumerate(setup.characters)
        ]
        if not setup.training:
            modes = tuple(mode.value.title() for mode in Mode)
            items.append(MenuItem("mode", "Mode", modes, list(Mode).index(setup.mode)))
            items.append(MenuItem("count", ""))
        items.append(MenuItem("next", "Choose stage"))
        title = "TRAINING: CHARACTERS" if setup.training else "VERSUS: CHARACTERS AND RULES"
        super().__init__(pixel_buffer, flow, title, Menu(items))
        self.footer("up/down: row   left/right: change   attack: pick   special: back")

    def act(self, player: int, action: MenuAction) -> None:
        """The stocks/minutes row counts up and down instead of cycling choices."""
        on_count = self.menu.selected.key == "count"
        if on_count and action in (MenuAction.LEFT, MenuAction.RIGHT, MenuAction.CONFIRM):
            self.setup = self.setup.with_count(-1 if action is MenuAction.LEFT else 1)
            return
        super().act(player, action)

    def changed(self) -> None:
        """Copy the rows back into the setup."""
        characters = tuple(
            self._characters[self.menu.item(f"p{index + 1}").index]
            for index in range(len(self.setup.characters))
        )
        mode = self.setup.mode
        if not self.setup.training:
            mode = list(Mode)[self.menu.item("mode").index]
        self.setup = replace(self.setup, characters=characters, mode=mode)

    def choose(self, key: str) -> None:
        """On to the stage select."""
        if key == "next":
            self.flow.show_stage_select(self.setup)

    def back(self) -> None:
        """Back to the main menu, keeping the versus settings."""
        if not self.setup.training:
            self.flow.setup = self.setup
        self.flow.show_main_menu()

    def refresh(self) -> None:
        """Show the rows; the count row shows stocks or minutes for the current mode."""
        if not self.setup.training:
            self.menu.item("count").label = f"< {self.setup.count_label} >"
        super().refresh()


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

    def act(self, player: int, action: MenuAction) -> None:
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
        result = match.result
        winner = "NO CONTEST" if result is None else f"PLAYER {result.winner + 1} WINS!"
        lines = results_table(match)
        rows_top = self.STATS_TOP - (len(lines) + 2) * (GLYPH_HEIGHT + 2)
        super().__init__(pixel_buffer, flow, winner, menu, rows_top)
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
