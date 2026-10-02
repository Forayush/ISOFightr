"""Scene routing: which view the window shows, and what is carried between them.

Plan note "13 - Game Modes UI and Flow" ("Screen flow"): title → main menu → character
select → stage select → battle → results → rematch or back to character select.
"""

from __future__ import annotations

from pathlib import Path

import arcade

from isofightr.data.character_loader import load_character
from isofightr.data.replay_io import numbered
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes.battle import BattleView
from isofightr.scenes.menus import (
    CharacterSelectView,
    MainMenuView,
    ResultsView,
    StageSelectView,
    TitleView,
)
from isofightr.scenes.setup import RANDOM_STAGE, MatchSetup
from isofightr.sim.match import Match
from isofightr.sim.rng import Rng


class GameFlow:
    """Moves the window from scene to scene and remembers the last versus setup."""

    def __init__(
        self,
        window: arcade.Window,
        pixel_buffer: PixelBuffer,
        seed: int = 0,
        max_ticks: int | None = None,
        record: Path | None = None,
    ) -> None:
        """Create the router. ``seed`` seeds the match seeds and random stage picks, so a
        session is reproducible; ``max_ticks`` is handed to every scene (smoke runs); with
        ``record`` every versus match is saved as a replay (the path, then ``-2``, ``-3``...)."""
        self.window = window
        self.pixel_buffer = pixel_buffer
        self.max_ticks = max_ticks
        self.record = record
        self.setup = MatchSetup()
        self.rng = Rng.seeded(seed)
        self.matches_started = 0

    def show_title(self) -> None:
        """Go to the title screen."""
        self.window.show_view(TitleView(self.pixel_buffer, self))

    def show_main_menu(self) -> None:
        """Go to the main menu."""
        self.window.show_view(MainMenuView(self.pixel_buffer, self))

    def show_character_select(self, setup: MatchSetup) -> None:
        """Go to character select with the given setup."""
        self.window.show_view(CharacterSelectView(self.pixel_buffer, self, setup))

    def show_stage_select(self, setup: MatchSetup) -> None:
        """Go to stage select."""
        if not setup.training:
            self.setup = setup
        self.window.show_view(StageSelectView(self.pixel_buffer, self, setup))

    def start_battle(self, setup: MatchSetup) -> None:
        """Start a match with the given setup (also used by "Rematch")."""
        if not setup.training:
            self.setup = setup
        stage_id = setup.stage
        if stage_id == RANDOM_STAGE:
            stages = list_stage_ids()
            stage_id = stages[self.rng.below(len(stages))]
        self.matches_started += 1
        view = BattleView(
            self.pixel_buffer,
            load_stage(stage_id),
            [load_character(name) for name in setup.characters],
            seed=self.rng.next_u32(),
            max_ticks=self.max_ticks,
            training=setup.training,
            rules=setup.rules(),
            flow=self,
            setup=setup,
            record=None if self.record is None else numbered(self.record, self.matches_started),
        )
        self.window.show_view(view)

    def show_results(self, setup: MatchSetup, match: Match) -> None:
        """Go to the results of a finished match."""
        self.window.show_view(ResultsView(self.pixel_buffer, self, setup, match))
