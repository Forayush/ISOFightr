"""Seeded random movement input: the simplest possible "CPU".

Plan note "15 - CPU AI": an AI is just another input source that outputs ``InputFrame``s.
This one ignores the game entirely and mashes plausible movement and attack input. It drives
the golden state-hash tests, the soak tests and ``--headless`` runs, so changing what it
produces for a given seed means re-recording the goldens (``pytest --update-goldens``).

Uses the sim's own PRNG, never Python's ``random``, so it is deterministic everywhere.
"""

from isofightr.sim.input_frame import Button, Dir8, InputFrame
from isofightr.sim.math3d import ZERO2, Vec2
from isofightr.sim.rng import Rng

DIRECTION_CHANGE_ODDS = 25
"""Each tick a player picks a new direction with a 1 in N chance."""
NEUTRAL_CHOICES = 4
"""Extra "let go of the stick" outcomes when picking a direction, next to the 8 directions."""
WALK_TOGGLE_ODDS = 90
JUMP_ODDS = 50
MAX_JUMP_HOLD = 10
VERTICAL_ODDS = 40
MAX_VERTICAL_HOLD = 8
DOWN_BIAS = 3
"""A vertical tap is down unless a 1 in N roll makes it up (down drives more mechanics)."""
ATTACK_ODDS = 30
MAX_ATTACK_HOLD = 4
STRONG_ODDS = 90
MAX_STRONG_HOLD = 40
"""Strong is sometimes held long enough to charge a smash attack."""


def random_inputs(seed: int, frames: int, players: int = 2) -> list[list[InputFrame]]:
    """Return ``frames`` ticks of plausible random input for every player.

    Deterministic for a given seed (it uses the sim's own PRNG, not Python's ``random``).
    Each player holds directions for a while and taps jump and the vertical modifiers now
    and then, which exercises walks, dashes, runs, turns, skids, jumps, fast falls, platform
    drops, KOs and respawns while still spending most of the time on the ground.
    """
    rng = Rng.seeded(seed)
    directions: list[Vec2] = [ZERO2] * players
    walking = [False] * players
    jump_frames = [0] * players
    vertical_frames = [0] * players
    attack_frames = [0] * players
    strong_frames = [0] * players
    verticals = [0] * players
    ticks: list[list[InputFrame]] = []
    for _ in range(frames):
        tick: list[InputFrame] = []
        for player in range(players):
            if rng.below(DIRECTION_CHANGE_ODDS) == 0:
                choice = rng.below(len(Dir8) + NEUTRAL_CHOICES)
                directions[player] = Dir8(choice).world if choice < len(Dir8) else ZERO2
            if rng.below(WALK_TOGGLE_ODDS) == 0:
                walking[player] = not walking[player]
            if jump_frames[player] > 0:
                jump_frames[player] -= 1
            elif rng.below(JUMP_ODDS) == 0:
                jump_frames[player] = rng.between(1, MAX_JUMP_HOLD)
            if vertical_frames[player] > 0:
                vertical_frames[player] -= 1
            elif rng.below(VERTICAL_ODDS) == 0:
                vertical_frames[player] = rng.between(1, MAX_VERTICAL_HOLD)
                verticals[player] = -1 if rng.below(DOWN_BIAS) else 1
            if attack_frames[player] > 0:
                attack_frames[player] -= 1
            elif rng.below(ATTACK_ODDS) == 0:
                attack_frames[player] = rng.between(1, MAX_ATTACK_HOLD)
            if strong_frames[player] > 0:
                strong_frames[player] -= 1
            elif rng.below(STRONG_ODDS) == 0:
                strong_frames[player] = rng.between(1, MAX_STRONG_HOLD)
            held = (
                (Button.JUMP if jump_frames[player] else 0)
                | (Button.WALK if walking[player] else 0)
                | (Button.ATTACK if attack_frames[player] else 0)
                | (Button.STRONG if strong_frames[player] else 0)
            )
            vertical = verticals[player] if vertical_frames[player] else 0
            tick.append(InputFrame(move=directions[player], vertical=vertical, held=held))
        ticks.append(tick)
    return ticks
