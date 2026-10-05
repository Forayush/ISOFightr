"""Capture a scripted battle offscreen as a contact sheet, to review how effects look.

Plan note "16 - Testing Debug and Tooling" (``capture_scene.py``, decision D-060). A hidden
:class:`~isofightr.app.GameWindow` runs a :class:`~isofightr.scenes.battle.BattleView` with
scripted key presses for player 1 and saves chosen ticks side by side. The match is a
sandbox: fighters may be placed anywhere and given damage, as in the tests.

Imports ``arcade`` (through the app), so it needs a display.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import arcade
from PIL import Image

from isofightr.app import GameWindow
from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.scenes.battle import BattleView
from isofightr.sim.input_frame import facing_from_move
from isofightr.sim.math3d import Vec3

PRESS, RELEASE = "@", "!"


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

    frames: list[Image.Image] = []
    wanted = sorted(set(ticks))
    for tick in range(1, (wanted[-1] if wanted else 0) + 1):
        for step in script:
            if step.tick == tick:
                (view.on_key_press if step.down else view.on_key_release)(step.key, 0)
        view.on_update(TICK_SECONDS)
        if tick in wanted:
            view.on_draw()
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
