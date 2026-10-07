"""Scene routing: which view the window shows, and what is carried between them.

Plan note "13 - Game Modes UI and Flow" ("Screen flow"): title → main menu → character
select → stage select → battle → results → rematch or back to character select. The flow
also owns the user settings: scenes change them through :meth:`GameFlow.update_settings`,
which applies and saves them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import arcade

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.character_loader import load_character
from isofightr.data.replay_io import numbered
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.input.devices import DeviceHub
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes.battle import BattleView
from isofightr.scenes.controls_view import ControlsView
from isofightr.scenes.front import BootView, MainMenuView, TitleView
from isofightr.scenes.loading_view import LoadingView, MatchPlan
from isofightr.scenes.menus import ResultsView, SettingsView
from isofightr.scenes.rules_model import to_saved, with_saved
from isofightr.scenes.rules_view import RandomPoolView, RulesView
from isofightr.scenes.select_view import CharacterSelectView
from isofightr.scenes.setup import RANDOM_STAGE, MatchSetup
from isofightr.scenes.stage_select_view import StageSelectView
from isofightr.settings import Settings, save_settings
from isofightr.sim.match import Match
from isofightr.sim.rng import Rng
from isofightr.ui.backdrop_layer import MenuBackdrop


class GameFlow:
    """Moves the window from scene to scene and remembers the last versus setup."""

    def __init__(
        self,
        window: arcade.Window,
        pixel_buffer: PixelBuffer,
        seed: int = 0,
        max_ticks: int | None = None,
        record: Path | None = None,
        settings: Settings | None = None,
        settings_path: Path | None = None,
        loading: bool = False,
    ) -> None:
        """Create the router.

        Args:
            window: the game window.
            pixel_buffer: its native-resolution render target.
            seed: seeds the match seeds and random stage picks, so a session is reproducible.
            max_ticks: handed to every scene (smoke runs).
            record: save every versus match as a replay (the path, then ``-2``, ``-3``...).
            settings: the user settings to start with.
            settings_path: where to save settings when they change; ``None`` keeps them in
                memory only (tests).
            loading: show the loading screen before a match the menus start (the game
                does; tests and tools mostly go straight to the battle).
        """
        self.loading = loading
        self.window = window
        self.pixel_buffer = pixel_buffer
        self.max_ticks = max_ticks
        self.record = record
        self.settings = settings or Settings()
        self.settings_path = settings_path
        self.setup = with_saved(MatchSetup(), self.settings.rules)
        """The versus setup: who plays and under which rules (the saved ones to begin with)."""
        self.rng = Rng.seeded(seed)
        self.matches_started = 0
        self.menu_ticks = 0
        """Ticks spent in menus this session: the backdrop drifts on from scene to scene."""
        self._backdrop: MenuBackdrop | None = None
        self._hub: DeviceHub | None = None

    def hub(self) -> DeviceHub:
        """Return the input devices, shared by every scene. Opening them asks the system
        for its controllers, which takes most of a second on Windows: once per session,
        not once per screen. It always carries the current settings."""
        if self._hub is None:
            self._hub = DeviceHub(self.settings)
        elif self._hub.settings is not self.settings:
            self._hub.apply_settings(self.settings)
        return self._hub

    def backdrop(self) -> MenuBackdrop:
        """Return the menu backdrop, shared by every menu scene."""
        if self._backdrop is None:
            self._backdrop = MenuBackdrop()
        return self._backdrop

    # --- settings --------------------------------------------------------------------------

    def update_settings(self, settings: Settings) -> None:
        """Take new settings: apply what affects the window, and save them."""
        previous, self.settings = self.settings, settings
        if settings.fullscreen != previous.fullscreen:
            self.window.set_fullscreen(settings.fullscreen)
        if settings.scale != previous.scale and not settings.fullscreen:
            self.window.set_size(NATIVE_W * settings.scale, NATIVE_H * settings.scale)
        audio = getattr(self.window, "audio", None)
        if audio is not None:
            audio.apply_settings(settings)
        if self.settings_path is not None:
            save_settings(self.settings_path, settings)

    def set_rules(self, setup: MatchSetup) -> None:
        """Take a setup whose rules changed (the Rules screen): keep it and save its rules."""
        self.setup = setup
        saved = to_saved(setup)
        if saved != self.settings.rules:
            self.update_settings(replace(self.settings, rules=saved))

    # --- scenes ----------------------------------------------------------------------------

    def show_boot(self) -> None:
        """Show the logo at once, then the title: what the game starts with."""
        self.window.show_view(BootView(self.pixel_buffer, self))

    def show_title(self) -> None:
        """Go to the title screen."""
        self.window.show_view(TitleView(self.pixel_buffer, self))

    def show_main_menu(self) -> None:
        """Go to the main menu."""
        self.window.show_view(MainMenuView(self.pixel_buffer, self))

    def show_rules(self, on_back: Callable[[], None] | None = None, cursor: str = "") -> None:
        """Go to the versus rules. ``on_back`` says where BACK leads (the main menu if not
        given); ``cursor`` names the row or button to start on."""
        self.window.show_view(RulesView(self.pixel_buffer, self, on_back, cursor))

    def show_random_pool(self, on_back: Callable[[], None] | None = None) -> None:
        """Go to the list of stages "Random" may pick; ``on_back`` is where the rules screen
        it returns to leads."""
        self.window.show_view(RandomPoolView(self.pixel_buffer, self, on_back))

    def show_settings(self) -> None:
        """Go to the settings."""
        self.window.show_view(SettingsView(self.pixel_buffer, self))

    def show_controls(
        self, on_back: Callable[[], None] | None = None, tab: int = 0, cursor: str = ""
    ) -> None:
        """Go to the controls screen: ``tab`` is the player whose device it shows,
        ``on_back`` where BACK leads (the main menu if not given)."""
        self.window.show_view(ControlsView(self.pixel_buffer, self, on_back, tab, cursor))

    def show_character_select(self, setup: MatchSetup) -> None:
        """Go to character select with the given setup."""
        self.window.show_view(CharacterSelectView(self.pixel_buffer, self, setup))

    def show_stage_select(self, setup: MatchSetup) -> None:
        """Go to stage select."""
        if not setup.training:
            self.setup = setup
        self.window.show_view(StageSelectView(self.pixel_buffer, self, setup))

    def plan_match(self, setup: MatchSetup) -> MatchPlan:
        """Decide the next match: remember the setup, pick the stage if it is "random",
        draw the seed and number the recording."""
        if not setup.training:
            self.setup = setup
        stage_id = setup.stage
        if stage_id == RANDOM_STAGE:
            stages = setup.pool(list_stage_ids())
            stage_id = stages[self.rng.below(len(stages))]
        self.matches_started += 1
        record = None if self.record is None else numbered(self.record, self.matches_started)
        return MatchPlan(setup, stage_id, self.rng.next_u32(), record)

    def begin_match(self, setup: MatchSetup) -> None:
        """Start a match the way the menus do (stage select, "Rematch"): through the loading
        screen when it is on, straight into the battle otherwise."""
        if not self.loading:
            self.start_battle(setup)
            return
        self.window.show_view(LoadingView(self.pixel_buffer, self, self.plan_match(setup)))

    def start_battle(self, setup: MatchSetup) -> None:
        """Start a match with the given setup at once, with no loading screen."""
        plan = self.plan_match(setup)
        view = BattleView(
            self.pixel_buffer,
            load_stage(plan.stage_id),
            [load_character(name) for name in setup.characters],
            seed=plan.seed,
            max_ticks=self.max_ticks,
            training=setup.training,
            rules=setup.rules(),
            flow=self,
            setup=setup,
            record=plan.record,
        )
        self.window.show_view(view)

    def show_battle(self, view: BattleView) -> None:
        """Show a battle that is already built (the loading screen's)."""
        self.window.show_view(view)

    def show_results(self, setup: MatchSetup, match: Match) -> None:
        """Go to the results of a finished match."""
        self.window.show_view(ResultsView(self.pixel_buffer, self, setup, match))
