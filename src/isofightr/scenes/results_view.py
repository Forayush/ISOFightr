"""The victory screen, at the ring.

Plan note "13 - Game Modes UI and Flow" ("Results screen", decisions D-061 and D-072). The
match ends where it was set up: on the Isle, everyone drops onto their spot, the winners (all
of a winning team) in their victory animation and the others dimmed, twice battle size. The
banner drops in with a bounce and its letters wave, in the winner's colours; confetti falls;
a plate under each fighter slides up with their place, their numbers and bars that grow; the
awards pop in as chips under the banner; four buttons lead on (rematch, character select,
stage select, main menu), usable from the first tick. What is where at each tick is
:mod:`isofightr.scenes.results_model`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from isofightr.config import AUDIO_VICTORY_SONG, NATIVE_H, NATIVE_W
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes import results_model as model
from isofightr.scenes.menu_world_model import (
    DROP_TICKS,
    LAND_TICKS,
    RING_SPOTS,
    STATIONS,
    Mood,
    StandIn,
    rest_pose,
    screen_point,
)
from isofightr.scenes.menus import MenuView
from isofightr.scenes.results_model import spot_of
from isofightr.scenes.setup import MatchSetup, result_awards, results_table
from isofightr.sim.match import Match
from isofightr.ui import font, kit_art, results_art, select_art, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import (
    Button,
    Gauge,
    SlideGroup,
    TextLabel,
    picture_texture,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

BANNER_CENTRE_Y = 322
SUB_BOTTOM = 284
AWARD_BOTTOM = 262
AWARD_HEIGHT = 16
AWARD_GAP = 6
BUTTON_BOTTOM = 24
BUTTON_SIZE = (148, 22)
BUTTON_GAP = 8
BUTTONS = (
    ("rematch", "REMATCH", "swords"),
    ("characters", "CHARACTERS", "team"),
    ("stages", "STAGES", "stage"),
    ("menu", "MAIN MENU", "arrow_left"),
)
"""The buttons, left to right: key, caption, icon."""
PODIUM = rest_pose(STATIONS["podium"])
SPOTS: tuple[tuple[int, int], ...] = tuple(screen_point(PODIUM, x, y) for x, y in RING_SPOTS)
"""Where each ring spot is on the screen with the camera at the podium."""
PLATE_WIDTH = 148
PLATE_HEIGHT = 56
PLATE_BOTTOM = 56
"""The plate under each fighter: place, name, numbers."""
HIDDEN = NATIVE_H
"""How far below its place a plate waits for its turn; an award waits as far to the side."""


class ResultsView(MenuView):
    """Who won, where everyone placed, the numbers, and what to do next."""

    music = AUDIO_VICTORY_SONG
    music_loops = False

    station = "podium"
    surface = theme.STONE

    def __init__(
        self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup, match: Match
    ) -> None:
        """Build the whole screen from the finished match; :meth:`refresh` animates it."""
        super().__init__(pixel_buffer, flow)
        self.setup = setup
        self.match = match
        self.table_lines = results_table(match)
        """The results as the old table's text lines (kept for tools and tests)."""
        self.award_lines = result_awards(match)
        self.standings = model.standings(match)
        self.rows = model.stat_rows(match)
        self.awards = model.awards(match)
        self.cursor = 0
        result = match.result
        colors = [fighter.color_index for fighter in match.fighters]
        self.ramps = [theme.player_ramp(color) for color in colors]
        self.winner_ramp = theme.EMPTY_RAMP if result is None else self.ramps[result.winner]
        self.players = len(match.fighters)
        self._winners: list[StandIn] = []
        """The winners' fighters at the ring, once they have dropped onto their spots."""

        ui = self.ui
        self._confetti = [arcade.Sprite() for _ in range(model.CONFETTI_PIECES)]
        for sprite in self._confetti:
            sprite.visible = False
            ui.panels.append(sprite)
        self._add_plates()
        self._add_awards()
        self._add_banner()
        self.buttons: dict[str, Button] = {}
        total = len(BUTTONS) * BUTTON_SIZE[0] + (len(BUTTONS) - 1) * BUTTON_GAP
        left = (NATIVE_W - total) // 2
        for index, (key, caption, icon) in enumerate(BUTTONS):
            rect = Rect(left + index * (BUTTON_SIZE[0] + BUTTON_GAP), BUTTON_BOTTOM, *BUTTON_SIZE)
            self.buttons[key] = Button(ui, rect, caption, icon)
        self.footer("{stick}: choose   {attack}: pick   {special}: character select")
        self.refresh()

    # --- building --------------------------------------------------------------------------

    def _spot(self, player: int) -> tuple[int, int]:
        return SPOTS[spot_of(player, self.players)]

    def _add_banner(self) -> None:
        """Add the banner's letters (one sprite each, over everything) and the line under
        it."""
        letters = results_art.banner_letters(model.banner_text(self.match), self.winner_ramp)
        x = (NATIVE_W - results_art.banner_width(letters)) // 2
        self._letters: list[tuple[arcade.Sprite, float]] = []
        ramp = self.winner_ramp
        for index, (picture, advance) in enumerate(letters):
            if picture is not None:
                character = model.banner_text(self.match)[index]
                texture = picture_texture(
                    ("results-letter", character, ramp), lambda picture=picture: picture
                )
                sprite = arcade.Sprite(texture)
                sprite.center_x = x + texture.width / 2
                self.ui.text.append(sprite)
                self._letters.append((sprite, texture.height / 2))
            x += advance
        self.sub = self.ui.write(
            model.sub_text(self.match), NATIVE_W // 2, SUB_BOTTOM, TextSize.TEXT, theme.WHITE,
            "centre", shadow=True,
        )  # fmt: skip

    def _add_awards(self) -> None:
        """The awards: a row of chips under the banner, each popping in on its turn."""
        ui = self.ui
        self._award_groups: list[SlideGroup] = []
        texts = [f"{award.title}: {award.name}" for award in self.awards]
        widths = [
            theme.ICON_SIZE + 3 * theme.GAP + font.text_width(t, TextSize.TEXT) for t in texts
        ]
        left = (NATIVE_W - sum(widths) - AWARD_GAP * max(len(widths) - 1, 0)) // 2
        for award, text, width in zip(self.awards, texts, widths, strict=True):
            ramp = self.ramps[award.player]
            with SlideGroup(ui) as group:
                ui.picture(
                    ("results-award", width, ramp),
                    lambda width=width, ramp=ramp: kit_art.block(
                        width, AWARD_HEIGHT, (theme.WHITE, theme.WHITE, ramp[1], theme.INK), 2
                    ),
                    left,
                    AWARD_BOTTOM,
                )
                ui.icon(award.icon, left + theme.GAP, AWARD_BOTTOM + 3, ramp[2])
                ui.write(
                    text, left + theme.ICON_SIZE + 2 * theme.GAP, AWARD_BOTTOM + 1,
                    TextSize.TEXT, theme.INK, shadow=False,
                )  # fmt: skip
            self._award_groups.append(group)
            left += width + AWARD_GAP

    def _add_plates(self) -> None:
        """A plate under each fighter: place and name on a bar in their colours, then their
        knockouts, falls and longest combo, and bars of the damage dealt and taken."""
        ui = self.ui
        self._row_groups: list[SlideGroup] = []
        self._row_parts: list[tuple[Gauge, Gauge, TextLabel, TextLabel, TextLabel]] = []
        winners = {standing.player for standing in self.standings if standing.winner}
        for row in self.rows:
            ramp = self.ramps[row.player]
            centre = self._spot(row.player)[0]
            plate = Rect(centre - PLATE_WIDTH // 2, PLATE_BOTTOM, PLATE_WIDTH, PLATE_HEIGHT)
            left, right = plate.left + 6, plate.right - 6
            winner = row.player in winners
            with SlideGroup(ui) as group:
                ui.picture(
                    ("results-plate", PLATE_WIDTH, PLATE_HEIGHT, ramp, winner),
                    lambda ramp=ramp, winner=winner: select_art.podium_plate(
                        PLATE_WIDTH, PLATE_HEIGHT, ramp, ready=winner
                    ),
                    plate.left,
                    plate.bottom,
                )
                ui.write(
                    f"{row.place}  {row.name}", left, plate.top - 15, TextSize.BODY, theme.INK,
                    shadow=False,
                )  # fmt: skip
                ui.write("DEALT", left, plate.bottom + 21, TextSize.SMALL, theme.ASH, shadow=False)
                ui.write("TAKEN", left, plate.bottom + 10, TextSize.SMALL, theme.ASH, shadow=False)
                dealt = Gauge(ui, Rect(left + 28, plate.bottom + 21, 64, 8), 0.0, ramp[1])
                taken = Gauge(ui, Rect(left + 28, plate.bottom + 10, 64, 8), 0.0, theme.DUST)
            counts = ui.write("", left, plate.top - 24, TextSize.SMALL, theme.INK, shadow=False)
            dealt_text = ui.write(
                "", right, plate.bottom + 19, TextSize.BODY, theme.INK, "right", shadow=False
            )
            taken_text = ui.write(
                "", right, plate.bottom + 8, TextSize.BODY, theme.ASH, "right", shadow=False
            )
            self._row_groups.append(group)
            self._row_parts.append((dealt, taken, counts, dealt_text, taken_text))

    # --- input -----------------------------------------------------------------------------

    @property
    def selected(self) -> str:
        """The key of the button under the cursor."""
        return BUTTONS[self.cursor][0]

    def act(self, device: str, action: MenuAction) -> None:
        """Move along the buttons, pick one, or go back to character select."""
        if action is MenuAction.LEFT:
            self.cursor = (self.cursor - 1) % len(BUTTONS)
        elif action is MenuAction.RIGHT:
            self.cursor = (self.cursor + 1) % len(BUTTONS)
        elif action is MenuAction.CONFIRM:
            self.choose(self.selected)
        elif action is MenuAction.BACK:
            self.back()

    def on_hide_view(self) -> None:
        """Clear the ring for whoever is next."""
        self.world.clear_ring()

    def choose(self, key: str) -> None:
        """Play again with the same settings, or go and change them."""
        if key == "rematch":
            self.flow.begin_match(self.setup)
        elif key == "stages":
            self.flow.show_stage_select(self.setup)
        elif key == "menu":
            self.flow.show_main_menu()
        else:
            self.flow.show_character_select(self.setup)

    def back(self) -> None:
        """Back to character select."""
        self.flow.show_character_select(self.setup)

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the button under the mouse."""
        for index, (key, _, _) in enumerate(BUTTONS):
            if self.buttons[key].rect.contains(x, y):
                self.cursor = index
                return True
        return False

    # --- drawing ---------------------------------------------------------------------------

    def refresh(self) -> None:
        """Show everything as it is at this tick."""
        tick = self.tick_count
        for index, (key, _, _) in enumerate(BUTTONS):
            self.buttons[key].focus(index == self.cursor)
        drop = model.banner_offset(tick)
        for index, (sprite, half) in enumerate(self._letters):
            sprite.center_y = BANNER_CENTRE_Y + drop + model.letter_offset(tick, index) + (half % 1)
        self.sub.alpha = 255 if tick >= model.BANNER_TICKS else 0
        self._refresh_ring(tick)
        self._refresh_confetti(tick)
        for index, (group, parts) in enumerate(zip(self._row_groups, self._row_parts, strict=True)):
            self._refresh_row(tick, index, group, parts)
        for index, group in enumerate(self._award_groups):
            shown = model.award_shown(tick, index)
            group.offset(model.award_pop(tick, index) if shown else -NATIVE_W, 0)

    def _refresh_ring(self, tick: int) -> None:
        """Drop everyone onto their spot in their turn (the winners first); once landed,
        the winners celebrate and the others stand dimmed."""
        world = self.world
        for standing in self.standings:
            spot = spot_of(standing.player, self.players)
            world.pads[spot] = self.ramps[standing.player]
            if not model.step_shown(tick, standing.order):
                continue
            fighter = self.match.fighters[standing.player]
            bank = world.bank(fighter.character.id)
            count = 1 if bank is None else len(bank.sprite_set.costumes)
            costume = self.setup.costume_of(standing.player, count)
            stand_in = world.ring[spot]
            if stand_in is None:
                stand_in = world.stand(spot, fighter.character.id, costume, fighter.color_index)
                if standing.winner:
                    self._winners.append(stand_in)
            if stand_in.mood is Mood.DROP_IN and world.ticks - stand_in.since >= (
                DROP_TICKS + LAND_TICKS
            ):
                world.mood(spot, Mood.WIN if standing.winner else Mood.LOST)

    def _refresh_confetti(self, tick: int) -> None:
        colours = results_art.confetti_colours(self.winner_ramp)
        falling = self.match.result is not None
        for sprite, (x, y, colour, wide) in zip(self._confetti, model.confetti(tick), strict=True):
            sprite.visible = falling
            if not falling:
                continue
            rgb = colours[colour % len(colours)]
            sprite.texture = picture_texture(
                ("results-confetti", rgb, wide),
                lambda rgb=rgb, wide=wide: results_art.confetti_piece(rgb, wide),
            )
            sprite.position = (x + 0.5, y)

    def _refresh_row(
        self,
        tick: int,
        index: int,
        group: SlideGroup,
        parts: tuple[Gauge, Gauge, TextLabel, TextLabel, TextLabel],
    ) -> None:
        row = self.rows[index]
        dealt, taken, counts, dealt_text, taken_text = parts
        shown = model.row_shown(tick, index)
        # The plates rise into place from below (the model's slide, turned upright).
        group.offset(0, -model.row_offset(tick, index) if shown else -HIDDEN)
        fill = model.row_fill(tick, index)
        dealt.value = row.dealt_share * fill
        taken.value = row.taken_share * fill
        resting = shown and model.row_offset(tick, index) == 0
        for label in (counts, dealt_text, taken_text):
            label.visible = resting
        if not resting:
            return
        kos = model.counted(tick, index, row.kos)
        falls = model.counted(tick, index, row.falls)
        combo = model.counted(tick, index, row.combo)
        counts.text = f"KO {kos}   FALL {falls}   COMBO {combo}"
        dealt_text.text = f"{model.counted(tick, index, row.dealt)}%"
        taken_text.text = f"{model.counted(tick, index, row.taken)}%"

    def shown(self) -> set[str]:
        """What is on screen now (see :func:`results_model.visible`)."""
        return model.visible(self.tick_count, len(self.rows), len(self.awards))
