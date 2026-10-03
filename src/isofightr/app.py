"""Window creation and view routing.

Implements the window half of "Native resolution and pixel-perfect scaling" in the plan note
"03 - Isometric World and Rendering". Scene flow (title, menus, results) arrives in M6; until
then the window opens straight into :class:`~isofightr.scenes.battle.BattleView`.
"""

import logging
from collections.abc import Sequence
from pathlib import Path

import arcade
import pyglet

from isofightr.config import (
    DEFAULT_WINDOW_SCALE,
    NATIVE_H,
    NATIVE_W,
    TICK_SECONDS,
    WINDOW_TITLE,
)
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes.battle import BattleView
from isofightr.scenes.flow import GameFlow
from isofightr.scenes.test_pattern import TestPatternView
from isofightr.settings import load_settings, settings_path
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.replay import Replay
from isofightr.sim.stage import Stage

LOG = logging.getLogger(__name__)

# Importing arcade switches pyglet to "stretch" DPI scaling, where window sizes are logical and
# the OS display scale (125%, 150%...) stretches the framebuffer by a fractional factor. That
# breaks integer upscaling, so ask for real pixels: a 1280x720 window is 1280x720 pixels.
# Must run before the window is created.
pyglet.options.dpi_scaling = "real"

LETTERBOX_COLOR = arcade.color.BLACK
FULLSCREEN_TOGGLE_KEY = arcade.key.F11
REAL_PIXEL_RATIO = 1.0


class GameWindow(arcade.Window):
    """The game window: owns the native-resolution :class:`PixelBuffer` that views draw into."""

    def __init__(
        self,
        scale: int = DEFAULT_WINDOW_SCALE,
        fullscreen: bool = False,
        visible: bool = True,
    ) -> None:
        """Open a window sized to ``scale`` times the native resolution.

        Multisample antialiasing is off: it would soften the pixel art for no benefit.
        """
        super().__init__(
            width=NATIVE_W * scale,
            height=NATIVE_H * scale,
            title=WINDOW_TITLE,
            fullscreen=fullscreen,
            resizable=True,
            antialiasing=False,
            vsync=True,
            center_window=True,
            visible=visible,
            update_rate=TICK_SECONDS,
            draw_rate=TICK_SECONDS,
        )
        self.background_color = LETTERBOX_COLOR
        self.pixel_buffer = PixelBuffer(self)
        if self.get_pixel_ratio() != REAL_PIXEL_RATIO:
            LOG.warning(
                "Window pixel ratio is %s, not 1: the pixel-art upscale may not be crisp.",
                self.get_pixel_ratio(),
            )

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """Window-level hotkeys that work in every view."""
        if symbol == FULLSCREEN_TOGGLE_KEY:
            self.set_fullscreen(not self.fullscreen)


def run(
    stage: Stage | None,
    characters: Sequence[CharacterDef],
    seed: int = 0,
    scale: int | None = None,
    fullscreen: bool = False,
    max_ticks: int | None = None,
    training: bool = False,
    menus: bool = False,
    record: Path | None = None,
    cpus: Sequence[int] = (),
) -> None:
    """Open the game window and block until it closes.

    Args:
        stage: the stage to play on, or ``None`` to show the pixel test pattern instead.
        characters: one character per player, in player order.
        seed: the match seed.
        scale: integer upscale of the native buffer for the windowed size; ``None`` uses
            the saved setting.
        fullscreen: start fullscreen (the saved setting can also ask for it); the buffer
            is integer-scaled and letterboxed.
        max_ticks: close automatically after this many simulation ticks (smoke runs).
        training: start in training mode (players 2 to 4 are dummies).
        menus: start at the title screen and let the menus set up matches; ``stage`` and
            ``characters`` are then ignored.
        record: save every match as a replay file (the path, then ``-2``, ``-3``...).
        cpus: CPU level per player (0 = a person), for a match started without the menus.
    """
    path = settings_path()
    settings = load_settings(path)
    window = GameWindow(scale=scale or settings.scale, fullscreen=fullscreen or settings.fullscreen)
    view: arcade.View
    if menus:
        flow = GameFlow(
            window, window.pixel_buffer, seed, max_ticks, record, settings, settings_path=path
        )
        flow.show_title()
        arcade.run()
        return
    if stage is None:
        view = TestPatternView(window.pixel_buffer, max_ticks=max_ticks)
    else:
        view = BattleView(
            window.pixel_buffer,
            stage,
            characters,
            seed,
            max_ticks=max_ticks,
            training=training,
            record=record,
            cpus=cpus,
        )
    window.show_view(view)
    arcade.run()


def run_replay(
    replay: Replay,
    scale: int = DEFAULT_WINDOW_SCALE,
    fullscreen: bool = False,
    max_ticks: int | None = None,
) -> None:
    """Open the game window and play a replay back. Blocks until the window closes."""
    window = GameWindow(scale=scale, fullscreen=fullscreen)
    view = BattleView(
        window.pixel_buffer,
        load_stage(replay.stage),
        [load_character(name) for name in replay.characters],
        replay.seed,
        max_ticks=max_ticks,
        rules=replay.rules,
        replay=replay,
    )
    window.show_view(view)
    arcade.run()
