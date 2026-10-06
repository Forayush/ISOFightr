"""Capture a scripted battle or a menu screen offscreen as a contact sheet, to review looks.

Plan note "16 - Testing Debug and Tooling" (``capture_scene.py``, decisions D-060 and D-061).
A hidden :class:`~isofightr.app.GameWindow` runs a :class:`~isofightr.scenes.battle.BattleView`
with scripted key presses for player 1 and saves chosen ticks side by side. The match is a
sandbox: fighters may be placed anywhere and given damage, as in the tests.
:func:`capture_screen` does the same for a named screen of the game's flow (title, menus,
character select, the HUD, results...).

Imports ``arcade`` (through the app), so it needs a display.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import arcade
from PIL import Image

from isofightr.app import GameWindow
from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.scenes.battle import BattleView
from isofightr.scenes.flow import GameFlow
from isofightr.scenes.menus import ResultsView
from isofightr.scenes.rules_model import with_saved
from isofightr.scenes.setup import MatchSetup, training_setup
from isofightr.scenes.ui_kit import UiKitView
from isofightr.settings import SavedRules, Settings
from isofightr.sim.input_frame import facing_from_move
from isofightr.sim.math3d import Vec3

PRESS, RELEASE = "@", "!"
SCREENS: tuple[str, ...] = (
    "title",
    "main",
    "rules",
    "pool",
    "controls",
    "controls_pad",
    "charselect",
    "stageselect",
    "results",
    "hud",
    "loading",
    "settings",
    "pause",
    "training",
    "kit",
)
"""The screens :func:`capture_screen` can show."""
ROSTER: tuple[str, ...] = ("rook", "bramble", "zephyr", "mote")
HUD_DAMAGE: tuple[float, ...] = (37.0, 86.0, 142.0, 12.0)
"""Damage the fighters are given for the HUD capture, so the colour ramp shows."""
HUD_CPU_LEVEL = 5
KEYBOARDS: tuple[str, ...] = ("keyboard:solo", "keyboard:arrows", "", "")
OUT_OF_BOUNDS = Vec3(5.0, 5.0, -90.0)
"""Far below any stage: a fighter put here is knocked out on the next tick."""
RESULTS_TICK_LIMIT = 1200


@dataclass(frozen=True, slots=True)
class KeyStep:
    """One scripted key event: a key goes down or up on a tick (the first tick is 1)."""

    key: int
    tick: int
    down: bool


def parse_script(text: str) -> list[KeyStep]:
    """Parse a key script such as ``K@2,K!3,I@2``: ``KEY@tick`` presses and ``KEY!tick``
    releases a key, named as in ``arcade.key`` (``K``, ``I``, ``COMMA``, ``SPACE``...)."""
    steps = []
    for token in (part.strip() for part in text.split(",") if part.strip()):
        mark = PRESS if PRESS in token else RELEASE
        name, _, tick = token.partition(mark)
        code = getattr(arcade.key, name.upper(), None)
        if code is None or not tick.isdigit():
            raise ValueError(f"bad key step {token!r}: expected KEY@tick or KEY!tick")
        steps.append(KeyStep(int(code), int(tick), mark == PRESS))
    return steps


def read_frame(window: GameWindow) -> Image.Image:
    """Return the native-resolution frame the view last drew."""
    data = window.pixel_buffer.framebuffer.read(components=4)
    image = Image.frombytes("RGBA", (NATIVE_W, NATIVE_H), bytes(data))
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def capture(
    window: GameWindow,
    characters: Sequence[str],
    stage: str,
    script: Sequence[KeyStep],
    ticks: Sequence[int],
    positions: Sequence[tuple[float, float, float] | None] = (),
    damage: Sequence[float] = (),
    crop: tuple[int, int, int, int] | None = None,
    scale: int = 1,
    seed: int = 0,
    cpus: Sequence[int] = (),
) -> Image.Image:
    """Run the scripted battle and return the frames at ``ticks`` side by side.

    Args:
        window: a (hidden) game window.
        characters: character id per player.
        stage: stage id.
        script: key events for the keyboard (player 1's keys by default).
        ticks: which ticks to capture, in increasing order.
        positions: where to stand each fighter (``x, y, z``), or ``None`` for its spawn.
        damage: starting damage per player.
        crop: ``left, top, width, height`` in native pixels, applied to every frame.
        scale: integer upscale of the sheet.
        seed: the match seed.
        cpus: CPU level per player (0 = scripted or idle).
    """
    window.switch_to()
    view = BattleView(
        window.pixel_buffer,
        load_stage(stage),
        [load_character(name) for name in characters],
        seed=seed,
        cpus=list(cpus) or None,
    )
    view.show_help = False
    window.show_view(view)
    fighters = view.match.fighters
    for fighter, spot in zip(fighters, positions, strict=False):
        if spot is not None:
            fighter.pos = Vec3(*spot)
    for fighter, percent in zip(fighters, damage, strict=False):
        view.match.set_damage(fighter.player_index, percent)
    if len(fighters) >= 2:
        first, second = fighters[0], fighters[1]
        first.facing = facing_from_move((second.pos - first.pos).xy) or first.facing
        second.facing = facing_from_move((first.pos - second.pos).xy) or second.facing
    view.camera.snap_to([fighter.pos for fighter in fighters])

    return _run(window, script, ticks, crop, scale)


def _run(
    window: GameWindow,
    script: Sequence[KeyStep],
    ticks: Sequence[int],
    crop: tuple[int, int, int, int] | None,
    scale: int,
) -> Image.Image:
    """Tick whatever view the window shows (it may change on the way), feeding it the key
    script, and return the frames at ``ticks`` side by side."""
    frames: list[Image.Image] = []
    wanted = sorted(set(ticks))
    for tick in range(1, (wanted[-1] if wanted else 0) + 1):
        for step in script:
            if step.tick == tick:
                view = window.current_view
                (view.on_key_press if step.down else view.on_key_release)(step.key, 0)
        window.current_view.on_update(TICK_SECONDS)
        if tick in wanted:
            window.current_view.on_draw()
            frame = read_frame(window)
            if crop is not None:
                left, top, width, height = crop
                frame = frame.crop((left, top, left + width, top + height))
            frames.append(frame)
    if not frames:
        raise ValueError("no ticks to capture")
    sheet = Image.new("RGBA", (sum(f.width for f in frames), frames[0].height))
    x = 0
    for frame in frames:
        sheet.paste(frame, (x, 0))
        x += frame.width
    if scale > 1:
        sheet = sheet.resize((sheet.width * scale, sheet.height * scale), Image.Resampling.NEAREST)
    return sheet


def versus_setup(players: int, cpus: bool = False, rules: SavedRules | None = None) -> MatchSetup:
    """Return a versus setup with the roster's first ``players`` characters: the first two
    on the keyboards, or (with ``cpus``) everyone but player 1 a CPU. ``rules`` are the
    rules to play under (the defaults if not given)."""
    count = min(max(players, 2), len(ROSTER))
    return replace(
        with_saved(MatchSetup(), rules or SavedRules()),
        characters=ROSTER[:count],
        devices=("keyboard:solo", *[""] * (count - 1)) if cpus else KEYBOARDS[:count],
        cpus=(0, *[HUD_CPU_LEVEL] * (count - 1)) if cpus else (),
    )


def open_screen(window: GameWindow, flow: GameFlow, screen: str, players: int = 2) -> None:
    """Show one of :data:`SCREENS`, set up so there is something to look at.

    Raises:
        ValueError: the name is unknown, or the screen is not built yet.
    """
    rules = flow.settings.rules
    if screen == "title":
        flow.show_title()
    elif screen == "main":
        flow.show_main_menu()
    elif screen == "rules":
        flow.show_rules()
    elif screen == "pool":
        flow.show_random_pool()
    elif screen == "settings":
        flow.show_settings()
    elif screen == "controls":
        flow.show_controls()
    elif screen == "controls_pad":
        flow.show_controls(tab=2)
    elif screen == "kit":
        window.show_view(UiKitView(window.pixel_buffer, flow))
    elif screen == "charselect":
        flow.show_character_select(flow.setup)
    elif screen == "stageselect":
        flow.show_stage_select(versus_setup(players, rules=rules))
    elif screen in ("hud", "pause"):
        count = max(players, 4) if screen == "hud" else players
        flow.start_battle(versus_setup(count, cpus=True, rules=rules))
        view = window.current_view
        assert isinstance(view, BattleView)
        view.show_help = False
        for fighter, percent in zip(view.match.fighters, HUD_DAMAGE, strict=False):
            view.match.set_damage(fighter.player_index, percent)
        if screen == "pause":
            view.open_menu()
    elif screen == "training":
        flow.start_battle(training_setup())
        view = window.current_view
        assert isinstance(view, BattleView)
        view.show_help = False
        view.open_menu()
    elif screen == "results":
        flow.start_battle(versus_setup(players, rules=rules))
        view = window.current_view
        assert isinstance(view, BattleView)
        for _ in range(RESULTS_TICK_LIMIT):
            if isinstance(window.current_view, ResultsView):
                break
            # A sandbox, as in the tests: the last player keeps falling until it is out.
            loser = view.match.fighters[-1]
            if view.match.result is None and loser.in_play:
                loser.pos = OUT_OF_BOUNDS
            window.current_view.on_update(TICK_SECONDS)
        else:
            raise ValueError("the match never reached the results screen")
    elif screen == "loading":
        raise ValueError("the loading screen is not built yet (M13 group 3)")
    else:
        raise ValueError(f"unknown screen {screen!r}: expected one of {', '.join(SCREENS)}")


def capture_screen(
    window: GameWindow,
    screen: str,
    script: Sequence[KeyStep] = (),
    ticks: Sequence[int] = (30,),
    crop: tuple[int, int, int, int] | None = None,
    scale: int = 1,
    players: int = 2,
    seed: int = 0,
    settings: Settings | None = None,
) -> Image.Image:
    """Show a screen of the game's flow and return the frames at ``ticks`` side by side.

    Args:
        window: a (hidden) game window.
        screen: one of :data:`SCREENS`.
        script: key events, sent to whatever scene is showing (so a script can walk on).
        ticks: which ticks to capture, counted from when the screen opens.
        crop: ``left, top, width, height`` in native pixels, applied to every frame.
        scale: integer upscale of the sheet.
        players: how many fighters, where the screen has fighters.
        seed: the session seed.
        settings: the user settings to show (the defaults if not given; never saved).
    """
    window.switch_to()
    flow = GameFlow(window, window.pixel_buffer, seed=seed, settings=settings)
    open_screen(window, flow, screen, players)
    return _run(window, script, ticks, crop, scale)
