"""The victory screen.

Plan note "13 - Game Modes UI and Flow" ("Results screen", decision D-061 item 10, wireframe
``m13_wf_results.png``): the banner drops in with a bounce and its letters wave, in the
winner's colours; the winner (every member of a winning team) stands in the victory-pose
hero art on the top step of a podium under a spotlight, the others on lower steps by
placement as their idle sprites, dimmed; confetti in the winner's colour falls; the stats
slide in row by row with bars that grow and numbers that count up; the awards appear one by
one; and four buttons lead on (rematch, character select, stage select, main menu), usable
from the first tick. What is where at each tick is :mod:`isofightr.scenes.results_model`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import arcade

from isofightr.config import AUDIO_VICTORY_SONG, NATIVE_W
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.sprite_bank import SpriteBank, Tint
from isofightr.scenes import results_model as model
from isofightr.scenes.menus import MenuView
from isofightr.scenes.setup import MatchSetup, result_awards, results_table
from isofightr.sim.input_frame import Dir8
from isofightr.sim.match import Match
from isofightr.ui import results_art, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import (
    Button,
    Gauge,
    Picture,
    SlideGroup,
    TextLabel,
    add_panel,
    picture_texture,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

BANNER_CENTRE_Y = 322
SUB_BOTTOM = 280
AWARDS = Rect(8, 56, 160, 232)
STATS = Rect(468, 56, 164, 232)
ROW_HEIGHT = 50
AWARD_HEIGHT = 44
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
SPOTLIGHT = (150, 236)
IDLE_ANIM = "idle"
IDLE_SCALE = 2
"""The others' game sprites are doubled, to stand beside the winner's hero art."""
FACING = Dir8.S
HIDDEN = NATIVE_W
"""Offset that puts a row or an award off the screen until its turn."""


class ResultsView(MenuView):
    """Who won, where everyone placed, the numbers, and what to do next."""

    music = AUDIO_VICTORY_SONG
    music_loops = False

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
        self._banks: dict[str, SpriteBank | None] = {}
        self._winners: list[tuple[SpriteBank, int, arcade.Sprite]] = []
        """The winners' sprites on the top step: ``(bank, costume, sprite)``."""
        self._stand: list[tuple[model.Standing, Picture, arcade.Sprite | None, TextLabel]] = []
        self._idle: list[tuple[SpriteBank, int, arcade.Sprite, model.Standing]] = []

        ui = self.ui
        winners = [standing for standing in self.standings if standing.winner]
        if winners:
            centre = sum(standing.x for standing in winners) // len(winners)
            top = model.PODIUM_BASE + winners[0].height
            ui.picture(
                ("results-spotlight", *SPOTLIGHT),
                lambda: results_art.spotlight(*SPOTLIGHT),
                centre - SPOTLIGHT[0] // 2,
                top,
            )
        for standing in self.standings:
            self._add_step(standing)
        self._confetti = [arcade.Sprite() for _ in range(model.CONFETTI_PIECES)]
        for sprite in self._confetti:
            sprite.visible = False
            ui.panels.append(sprite)
        self._add_awards()
        self._add_stats()
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

    def _bank(self, character_id: str) -> SpriteBank | None:
        if character_id not in self._banks:
            try:
                sprite_set = load_sprite_set(character_id)
            except SpriteSheetError:
                sprite_set = None
            self._banks[character_id] = None if sprite_set is None else SpriteBank(sprite_set)
        return self._banks[character_id]

    def _add_step(self, standing: model.Standing) -> None:
        """Add a podium step, its placement tag and whoever stands on it."""
        ui = self.ui
        ramp = self.ramps[standing.player]
        width, height = model.STEP_WIDTH, standing.height
        rect = Rect(standing.x - width // 2, model.PODIUM_BASE, width, height + width // 2)
        step = Picture(ui, rect)
        step.show(
            ("results-step", width, height, ramp),
            lambda: results_art.podium_step(width, height, ramp),
        )
        fighter = self.match.fighters[standing.player]
        bank = self._bank(fighter.character.id)
        sprite: arcade.Sprite | None = None
        if bank is not None:
            costume = self.setup.costume_of(standing.player, len(bank.sprite_set.costumes))
            hero = bank.portrait("hero_win", costume) if standing.winner else None
            if hero is not None:
                sprite = arcade.Sprite(hero)
                self._winners.append((bank, costume, sprite))
            elif IDLE_ANIM in bank.sprite_set.anims:
                tint = Tint.NORMAL if standing.winner else Tint.DIM
                sprite = arcade.Sprite(bank.texture(IDLE_ANIM, 0, FACING, costume, tint))
                sprite.scale = IDLE_SCALE
                self._idle.append((bank, costume, sprite, standing))
                if standing.winner:
                    self._winners.append((bank, costume, sprite))
            if sprite is not None:
                ui.panels.append(sprite)
        place = model.PLACE_NAMES[min(standing.place, len(model.PLACE_NAMES) - 1)].upper()
        tag = ui.write(place, standing.x, model.PODIUM_BASE + 3, TextSize.BODY, ramp[0], "centre")
        self._stand.append((standing, step, sprite, tag))

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
            model.sub_text(self.match), NATIVE_W // 2, SUB_BOTTOM, TextSize.BODY, theme.FOG,
            "centre",
        )  # fmt: skip

    def _add_awards(self) -> None:
        ui = self.ui
        add_panel(ui, AWARDS)
        left, top = AWARDS.left + theme.PAD, AWARDS.top
        ui.icon("crown", left, top - 18, theme.HEADING)
        ui.write("AWARDS", left + 16, top - 20, TextSize.TITLE, theme.HEADING)
        self._award_groups: list[SlideGroup] = []
        for index, award in enumerate(self.awards):
            y = top - 34 - index * AWARD_HEIGHT
            ramp = self.ramps[award.player]
            with SlideGroup(ui) as group:
                ui.icon(award.icon, left, y - 12, theme.FOCUS)
                ui.write(award.title.upper(), left + 16, y - 12, TextSize.BODY, theme.FOCUS)
                ui.write(award.name.upper(), left + 16, y - 25, TextSize.BODY, ramp[0])
                ui.write(award.value.upper(), left + 16, y - 36, TextSize.SMALL, theme.TEXT_MUTED)
            self._award_groups.append(group)
        if not self.awards:
            ui.write("NONE THIS TIME", left, top - 46, TextSize.BODY, theme.TEXT_MUTED)
        bottom = AWARDS.bottom + theme.PAD
        ui.icon("stage", left, bottom + 13, theme.TEXT_MUTED)
        stage = self.match.stage.display_name.upper()
        ui.write(stage, left + 16, bottom + 13, TextSize.BODY, theme.TEXT_MUTED)
        ui.icon("clock", left, bottom - 1, theme.TEXT_MUTED)
        ui.write(model.match_length(self.match), left + 16, bottom, TextSize.BODY, theme.TEXT_MUTED)

    def _add_stats(self) -> None:
        ui = self.ui
        add_panel(ui, STATS)
        left, top = STATS.left + theme.PAD, STATS.top
        ui.icon("score", left, top - 18, theme.HEADING)
        ui.write("RESULTS", left + 16, top - 20, TextSize.TITLE, theme.HEADING)
        self._row_groups: list[SlideGroup] = []
        self._row_parts: list[tuple[Gauge, Gauge, TextLabel, TextLabel, TextLabel]] = []
        right = STATS.right - theme.PAD
        for index, row in enumerate(self.rows):
            y = top - 28 - index * ROW_HEIGHT
            ramp = self.ramps[row.player]
            with SlideGroup(ui) as group:
                ui.picture(
                    ("results-place", 24, 11, ramp),
                    lambda ramp=ramp: results_art.place_plate(24, 11, ramp),
                    left,
                    y - 12,
                )
                ui.write(row.place, left + 12, y - 10, TextSize.SMALL, theme.INK, "centre",
                         shadow=False)  # fmt: skip
                ui.write(row.name, left + 28, y - 12, TextSize.BODY, ramp[0])
                ui.write("DEALT", left, y - 33, TextSize.SMALL, theme.TEXT_MUTED)
                ui.write("TAKEN", left, y - 44, TextSize.SMALL, theme.TEXT_MUTED)
                dealt = Gauge(ui, Rect(left + 26, y - 34, 78, 8), 0.0, ramp[1])
                taken = Gauge(ui, Rect(left + 26, y - 45, 78, 8), 0.0, theme.DUST)
            counts = ui.write("", left, y - 23, TextSize.SMALL, theme.TEXT)
            dealt_text = ui.write("", right, y - 35, TextSize.BODY, theme.TEXT, "right")
            taken_text = ui.write("", right, y - 46, TextSize.BODY, theme.TEXT_MUTED, "right")
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
        self._refresh_podium(tick)
        self._refresh_confetti(tick)
        for index, (group, parts) in enumerate(zip(self._row_groups, self._row_parts, strict=True)):
            self._refresh_row(tick, index, group, parts)
        for index, group in enumerate(self._award_groups):
            shown = model.award_shown(tick, index)
            group.offset(model.award_pop(tick, index) if shown else -HIDDEN, 0)

    def _refresh_podium(self, tick: int) -> None:
        for standing, step, sprite, tag in self._stand:
            shown = model.step_shown(tick, standing.order)
            lift = model.step_offset(tick, standing.order)
            rect = step.rect
            step.sprite.visible = shown
            step.sprite.center_y = rect.bottom + rect.height / 2 + lift
            tag.visible = shown
            tag.move_to(standing.x, model.PODIUM_BASE + 3 + lift)
            if sprite is None:
                continue
            sprite.visible = shown
            feet_y = model.PODIUM_BASE + standing.height + model.STEP_WIDTH // 4 + lift
            idle = next((entry for entry in self._idle if entry[2] is sprite), None)
            if idle is None:
                texture = sprite.texture
                sprite.position = (
                    standing.x + (texture.width % 2) / 2,
                    feet_y + texture.height / 2,
                )
                continue
            bank, costume, _, _ = idle
            pose = bank.sprite_set.anims[IDLE_ANIM].pose_at(tick + 1)
            frame = bank.frame(IDLE_ANIM, pose, FACING)
            tint = Tint.NORMAL if standing.winner else Tint.DIM
            sprite.texture = bank.texture(IDLE_ANIM, pose, FACING, costume, tint)
            sprite.scale = IDLE_SCALE
            sprite.position = (
                standing.x + (frame.width / 2 - frame.pivot_x) * IDLE_SCALE,
                feet_y + (frame.pivot_y - frame.height / 2) * IDLE_SCALE,
            )

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
        group.offset(model.row_offset(tick, index) if shown else HIDDEN, 0)
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
        counts.text = f"KO  {kos}    FALL  {falls}    COMBO  {combo}"
        dealt_text.text = f"{model.counted(tick, index, row.dealt)}%"
        taken_text.text = f"{model.counted(tick, index, row.taken)}%"

    def shown(self) -> set[str]:
        """What is on screen now (see :func:`results_model.visible`)."""
        return model.visible(self.tick_count, len(self.rows), len(self.awards))
