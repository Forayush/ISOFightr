"""F10 input display: what the game received from each player this tick.

Plan note "13 - Game Modes UI and Flow" (debug keys, decision D-053). One line per player: the
stick (screen direction and magnitude), the up/down modifier, the right stick, the held
buttons, the presses still buffered (with their age in frames), then the fighter's state,
state frame and move. It reads the fighter's own input buffer, so it shows exactly the
``InputFrame`` the sim used, whichever device (or replay, or dummy) produced it.

Pure Python (no ``arcade``); :mod:`isofightr.scenes.battle` draws the lines.
"""

from typing import Final

from isofightr.sim.constants import STICK_NEUTRAL
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_UP, Button, Press, facing_from_move
from isofightr.sim.math3d import Vec2

NOTHING: Final[str] = "-"
BUTTON_LABELS: Final[tuple[tuple[Button, str], ...]] = (
    (Button.JUMP, "JUMP"),
    (Button.ATTACK, "ATK"),
    (Button.SPECIAL, "SPEC"),
    (Button.STRONG, "SMASH"),
    (Button.SHIELD, "SHLD"),
    (Button.GRAB, "GRAB"),
    (Button.WALK, "WALK"),
    (Button.TAUNT, "TAUNT"),
)
PRESS_LABELS: Final[dict[Press, str]] = {
    Press.ATTACK: "ATK",
    Press.SPECIAL: "SPEC",
    Press.STRONG: "SMASH",
    Press.JUMP: "JUMP",
    Press.SHIELD: "SHLD",
    Press.GRAB: "GRAB",
    Press.TAUNT: "TAUNT",
    Press.UP: "UP",
    Press.DOWN: "DOWN",
    Press.FLICK: "FLICK",
    Press.CSTICK: "CSTICK",
}


def stick_text(move: Vec2 | None) -> str:
    """Return a stick as its screen direction and magnitude (``SE 1.00``), or ``-`` at rest."""
    if move is None or move.length() <= STICK_NEUTRAL:
        return NOTHING
    direction = facing_from_move(move)
    assert direction is not None
    return f"{direction.name} {move.length():.2f}"


def input_line(fighter: Fighter) -> str:
    """Return the F10 line for one fighter."""
    buffer = fighter.buffer
    frame = buffer.frame
    vertical = {VERTICAL_UP: "UP", VERTICAL_DOWN: "DOWN"}.get(frame.vertical, NOTHING)
    held = " ".join(label for button, label in BUTTON_LABELS if frame.held & button) or NOTHING
    buffered = (
        " ".join(
            f"{PRESS_LABELS[press]}{buffer.ages[press]}" for press in Press if buffer.has(press)
        )
        or NOTHING
    )
    move = fighter.move_id if fighter.state is StateId.ATTACK and fighter.move_id else NOTHING
    return (
        f"P{fighter.player_index + 1} stick {stick_text(frame.move)} mod {vertical} "
        f"c {stick_text(frame.cstick)} held {held} buf {buffered} "
        f"> {fighter.state.value} f{fighter.state_frame} move {move}"
    )


def input_lines(fighters: list[Fighter], width: int) -> list[str]:
    """Return every fighter's F10 line, in player order, clipped to ``width`` characters."""
    return [input_line(fighter)[:width] for fighter in fighters]
