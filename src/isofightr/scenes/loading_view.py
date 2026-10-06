"""The loading screen: who fights whom and where, shown while the match is built.

Plan note "13 - Game Modes UI and Flow" (decision D-061, wireframe ``m13_wf_loading.png``;
it supersedes D-041's "no loading screen"). Between stage select and the battle the players'
portraits slide in from the sides around a VS, over the stage's name and picture, a
gameplay tip, and a progress bar. The bar is real: the screen builds the match in steps
(the stage, each character's sprites in the costume it will wear, then the battle scene)
and the bar shows how many are done. It stays at least a second so it can be read, can be
skipped once everything is ready, and goes on by itself soon after.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import arcade

from isofightr.config import NATIVE_W
from isofightr.data.character_loader import load_character
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.data.stage_loader import load_stage
from isofightr.render import placeholder_art as art
from isofightr.render.fighter_look import costume_index
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.sprite_bank import SpriteBank
from isofightr.scenes.battle import BattleView
from isofightr.scenes.menus import MenuView
from isofightr.scenes.setup import MatchSetup
from isofightr.sim.character_def import CharacterDef
from isofightr.ui import kit_art, theme
from isofightr.ui.anim import ease_out, slide
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.hints import device_labels
from isofightr.ui.menu import MenuAction
from isofightr.ui.tips import TIPS, tip_at
from isofightr.ui.widgets import Gauge, SlideGroup, add_panel, picture_texture

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

LOG = logging.getLogger(__name__)

MIN_TICKS = 60
"""The screen stays at least this long, so it can be read."""
AUTO_TICKS = 150
"""It goes on by itself after this long (once the match is ready)."""
SLIDE_TICKS = 24
"""The fighter cards slide in from the sides over this many ticks."""
CARD_BOTTOM = 152
CARD_HEIGHT = 166
CARD_MAX_WIDTH = 190
CARD_GAP = 10
CARD_MARGIN = 20
BUST_SCALE = 3
"""A character without hero art gets its 30 px bust, three times as big."""
ART_BOTTOM = 22
"""Height of a card's art's feet above the card's bottom: just behind the name plate's top."""
STAGE_SIZE = (150, 70)
"""The stage picture's size in native pixels."""
STAGE_BOTTOM = 66
BAR = Rect(120, 44, 400, 9)
TIP_BOTTOM = 24


@dataclass(frozen=True, slots=True)
class MatchPlan:
    """Everything the flow has decided about the next match."""

    setup: MatchSetup
    stage_id: str
    """The stage to play on (a "random" choice is already resolved)."""
    seed: int
    record: Path | None


def player_costume(setup: MatchSetup, player: int, costumes: int) -> int:
    """Return the costume a player will wear in the match a setup starts."""
    team_play = setup.team_play and bool(setup.teams) and not setup.training
    color = setup.teams[player] if team_play and player < len(setup.teams) else player
    return costume_index(color, team_play, costumes)


def player_tag(setup: MatchSetup, player: int) -> str:
    """Return the line over a player's card: ``P1``, or ``P2  CPU 5``."""
    level = setup.cpus[player] if player < len(setup.cpus) else 0
    return f"P{player + 1}  CPU {level}" if level > 0 else f"P{player + 1}"


def card_rects(count: int) -> list[Rect]:
    """Return where the fighter cards rest. Two fighters stand at the sides with the VS
    between them; three or four share the width evenly."""
    count = max(count, 1)
    if count <= 2:
        left = CARD_MARGIN + 20
        rects = [Rect(left, CARD_BOTTOM, CARD_MAX_WIDTH, CARD_HEIGHT)]
        if count == 2:
            rects.append(
                Rect(NATIVE_W - left - CARD_MAX_WIDTH, CARD_BOTTOM, CARD_MAX_WIDTH, CARD_HEIGHT)
            )
        return rects
    width = (NATIVE_W - 2 * CARD_MARGIN - (count - 1) * CARD_GAP) // count
    return [
        Rect(CARD_MARGIN + index * (width + CARD_GAP), CARD_BOTTOM, width, CARD_HEIGHT)
        for index in range(count)
    ]


class LoadingView(MenuView):
    """Builds the match a step a tick while it shows who is about to fight."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, plan: MatchPlan) -> None:
        """Lay the screen out. Nothing slow happens here: the work is done tick by tick."""
        super().__init__(pixel_buffer, flow)
        self.dim = None
        self.plan = plan
        self.battle: BattleView | None = None
        """The finished battle scene, once every step is done."""
        self.stage = load_stage(plan.stage_id)
        setup = plan.setup
        self._characters: list[CharacterDef] = []
        self._banks: dict[str, SpriteBank] = {}
        self.steps_done = 0
        distinct = list(dict.fromkeys(setup.characters))
        self.steps_total = 1 + 2 * len(distinct) + 1
        """Load the data; per character open its sheets, then colour its costumes; build
        the battle."""
        self._work = self._steps(distinct)
        self.first_tip = flow.matches_started % len(TIPS)

        ui = self.ui
        self.cards: list[tuple[SlideGroup, int]] = []
        self._busts: dict[int, arcade.Sprite] = {}
        self._art_spots: dict[int, tuple[int, int]] = {}
        """Where each card's art stands: centre x and the y of its feet."""
        rects = card_rects(len(setup.characters))
        for player, rect in enumerate(rects):
            color = theme.player_color(self._color_of(player))
            with SlideGroup(ui) as group:
                add_panel(ui, rect, theme.PANEL_FILL, theme.with_alpha(color, 255))
                strip = Rect(rect.left + 1, rect.top - 17, rect.width - 2, 16)
                ui.picture(
                    ("card-strip", strip.width, color),
                    lambda strip=strip, color=color: kit_art.filled(
                        kit_art.shape_mask(
                            strip.width, strip.height, theme.CORNER, (True,) + (False,) * 3
                        ),
                        color,
                    ),
                    strip.left,
                    strip.bottom,
                )
                ui.write_in(
                    strip, player_tag(setup, player), TextSize.BODY, theme.TEXT_ON_FOCUS,
                    shadow=False,
                )  # fmt: skip
                bust = arcade.Sprite(center_x=rect.left + rect.width // 2, center_y=rect.bottom)
                bust.visible = False
                ui.panels.append(bust)
                self._busts[player] = bust
                self._art_spots[player] = (rect.left + rect.width // 2, rect.bottom + ART_BOTTOM)
                plate = Rect(rect.left + 6, rect.bottom + 6, rect.width - 12, 20)
                add_panel(ui, plate, theme.PANEL_DEEP, theme.PANEL_LIGHT, theme.SMALL_CORNER)
                name = load_character(setup.characters[player]).display_name.upper()
                ui.write_in(plate, name, TextSize.TITLE)
            from_left = rect.left + rect.width / 2 < NATIVE_W / 2
            self.cards.append((group, -(rect.right + 8) if from_left else NATIVE_W - rect.left + 8))

        middle = NATIVE_W // 2
        if len(rects) == 2:
            ui.write("VS", middle, CARD_BOTTOM + CARD_HEIGHT // 2 - 8, TextSize.DISPLAY,
                     theme.HEADING, "centre")  # fmt: skip
        width, height = STAGE_SIZE
        frame = Rect(middle - width // 2 - 4, STAGE_BOTTOM, width + 8, height + 8 + 16)
        add_panel(ui, frame)
        stage = self.stage
        ui.image(
            picture_texture(
                ("stage-thumbnail", stage.id, width, height),
                lambda: art.build_stage_thumbnail(stage, width, height),
            ),
            frame.left + 4,
            frame.bottom + 4,
        )
        ui.write_in(
            Rect(frame.left, frame.top - 17, frame.width, 16), stage.display_name.upper(),
            TextSize.BODY, theme.HEADING,
        )  # fmt: skip
        add_panel(
            ui, Rect(BAR.left - 60, TIP_BOTTOM - 4, BAR.width + 120, BAR.top - TIP_BOTTOM + 16),
            theme.PANEL_DEEP, theme.PANEL_LIGHT, theme.SMALL_CORNER,
        )  # fmt: skip
        self.bar = Gauge(ui, BAR)
        self.tip = ui.write("", middle, TIP_BOTTOM, TextSize.BODY, theme.FOG, "centre")
        self.status = ui.write(
            "", BAR.right, BAR.top + 3, TextSize.SMALL, theme.TEXT_MUTED, "right"
        )
        self.footer("{attack}: start")
        self.refresh()

    def _color_of(self, player: int) -> int:
        setup = self.plan.setup
        team_play = setup.team_play and bool(setup.teams) and not setup.training
        return setup.teams[player] if team_play and player < len(setup.teams) else player

    # --- the work ----------------------------------------------------------------------------

    def _steps(self, distinct: list[str]) -> Iterator[None]:
        """Build the match, yielding after each step the progress bar counts."""
        setup = self.plan.setup
        self._characters = [load_character(name) for name in setup.characters]
        yield
        for name in distinct:
            try:
                sprite_set = load_sprite_set(name)
            except SpriteSheetError as error:
                LOG.error("%s: sprites not loaded: %s", name, error)
                sprite_set = None
            if sprite_set is not None:
                self._banks[name] = SpriteBank(sprite_set)
            self._show_busts(name)
            yield
            bank = self._banks.get(name)
            if bank is not None:
                costumes = len(bank.sprite_set.costumes)
                for player, character in enumerate(setup.characters):
                    if character == name:
                        bank.warm(player_costume(setup, player, costumes))
            yield
        self.battle = BattleView(
            self.pixel_buffer,
            self.stage,
            self._characters,
            seed=self.plan.seed,
            max_ticks=self.flow.max_ticks,
            training=setup.training,
            rules=setup.rules(),
            flow=self.flow,
            setup=setup,
            record=self.plan.record,
            banks=self._banks,
        )
        yield

    def _show_busts(self, name: str) -> None:
        """Put a character's portrait on its players' cards once its sheets are open."""
        bank = self._banks.get(name)
        if bank is None:
            return
        setup = self.plan.setup
        for player, character in enumerate(setup.characters):
            if character != name or player not in self._busts:
                continue
            costume = player_costume(setup, player, len(bank.sprite_set.costumes))
            sprite = self._busts[player]
            hero = bank.portrait("hero", costume)
            texture = hero or bank.portrait("bust", costume)
            if texture is None:
                continue
            # Hero art is shown as drawn, standing on the name plate; a character that only
            # has the small bust gets it enlarged.
            x, base = self._art_spots[player]
            sprite.scale = 1 if hero is not None else BUST_SCALE
            sprite.texture = texture
            height = texture.height * (1 if hero is not None else BUST_SCALE)
            group = self.cards[player][0]
            group.place(sprite, x + (texture.width % 2) / 2, base + height / 2)
            sprite.visible = True

    @property
    def ready(self) -> bool:
        """Whether the match is built."""
        return self.battle is not None

    @property
    def progress(self) -> float:
        """How much of the work is done, 0 to 1."""
        return min(self.steps_done / self.steps_total, 1.0)

    # --- flow --------------------------------------------------------------------------------

    def tick(self) -> None:
        """Do one step of the work (after the first frame has been shown), then run the
        menu; go on by itself once ready and the time is up."""
        if self.tick_count > 1 and not self.ready:
            try:
                next(self._work)
            except StopIteration:
                pass
            else:
                self.steps_done += 1
        super().tick()
        if self.window.current_view is self and self.ready and self.tick_count >= AUTO_TICKS:
            self.go()

    def act(self, device: str, action: MenuAction) -> None:
        """Confirm starts the match once it is ready and the screen has been up a moment."""
        if action is MenuAction.CONFIRM and self.ready and self.tick_count >= MIN_TICKS:
            self.go()

    def hover(self, x: int, y: int) -> bool:
        """A click anywhere is a confirm."""
        return True

    def go(self) -> None:
        """Show the battle."""
        assert self.battle is not None
        self.flow.show_battle(self.battle)

    def refresh(self) -> None:
        """Slide the cards in, fill the bar and show the tip."""
        tick = self.tick_count
        for group, start in self.cards:
            group.offset(slide(tick, 0, SLIDE_TICKS, start, 0, ease_out), 0)
        self.bar.value = self.progress
        skippable = self.ready and tick >= MIN_TICKS
        self.status.text = "READY" if skippable else ("LOADING" if not self.ready else "")
        self.status.color = theme.ON if skippable else theme.TEXT_MUTED
        self.tip.text = tip_at(
            self.first_tip, tick, device_labels(self.flow.settings, self.active_device)
        )
