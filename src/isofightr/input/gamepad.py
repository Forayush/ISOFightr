"""Gamepad to ``InputFrame``: analog processing and bindings, as pure functions.

Plan note "08 - Controls and Input" ("Gamepad (Xbox layout)", "Analog processing"). The left
stick moves; in the default preset the right stick's up and down are the vertical modifiers.
A :class:`PadState` is a plain snapshot of a controller, so this module needs no hardware
and no ``pyglet``; :mod:`isofightr.input.devices` fills snapshots from real controllers.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

import math
from dataclasses import dataclass

from isofightr.config import (
    MODIFIER_THRESHOLD,
    STICK_DEADZONE,
    STICK_SATURATION,
    TRIGGER_THRESHOLD,
)
from isofightr.sim.input_frame import (
    VERTICAL_DOWN,
    VERTICAL_NONE,
    VERTICAL_UP,
    Button,
    InputFrame,
    stick_to_world,
)
from isofightr.sim.math3d import Vec2


@dataclass(frozen=True, slots=True)
class PadState:
    """A snapshot of one controller. Stick axes are -1 to 1 with **up positive**."""

    left_x: float = 0.0
    left_y: float = 0.0
    right_x: float = 0.0
    right_y: float = 0.0
    left_trigger: float = 0.0
    right_trigger: float = 0.0
    a: bool = False
    b: bool = False
    x: bool = False
    y: bool = False
    left_shoulder: bool = False
    right_shoulder: bool = False


@dataclass(frozen=True, slots=True)
class GamepadPreset:
    """Which control does what. Each tuple names :class:`PadState` fields."""

    name: str
    attack: tuple[str, ...]
    special: tuple[str, ...]
    jump: tuple[str, ...]
    grab: tuple[str, ...]
    shield: tuple[str, ...]
    strong: tuple[str, ...]
    up: tuple[str, ...]
    """Controls that hold the up modifier, besides the right stick."""
    down: tuple[str, ...]
    right_stick_modifiers: bool
    """Whether pushing the right stick up or down holds the up or down modifier."""


RIGHT_STICK_MODIFIERS = GamepadPreset(
    name="Right-stick modifiers",
    attack=("a",),
    special=("b",),
    jump=("x", "y"),
    grab=("right_shoulder",),
    shield=("left_trigger", "right_trigger"),
    strong=("left_shoulder",),
    up=(),
    down=(),
    right_stick_modifiers=True,
)
"""The default preset: right stick up/down are the vertical modifiers."""

MODIFIER_BUMPERS = GamepadPreset(
    name="Modifier bumpers",
    attack=("a",),
    special=("b",),
    jump=("x", "y"),
    grab=("right_shoulder",),
    shield=("right_trigger",),
    strong=(),
    up=("left_shoulder",),
    down=("left_trigger",),
    right_stick_modifiers=False,
)
"""Alternate preset: LB is up and LT is down, for players who dislike the right stick."""

_BUTTON_FIELDS = (
    ("attack", Button.ATTACK),
    ("special", Button.SPECIAL),
    ("jump", Button.JUMP),
    ("grab", Button.GRAB),
    ("shield", Button.SHIELD),
    ("strong", Button.STRONG),
)


def process_stick(x: float, y: float, deadzone: float = STICK_DEADZONE) -> tuple[float, float]:
    """Apply the radial deadzone and outer saturation, rescaling magnitude to 0..1.

    The direction is kept; only the magnitude is remapped, so there is no axis snapping.
    """
    magnitude = math.hypot(x, y)
    if magnitude <= deadzone:
        return (0.0, 0.0)
    scaled = min(1.0, (magnitude - deadzone) / (STICK_SATURATION - deadzone))
    return (x / magnitude * scaled, y / magnitude * scaled)


def is_held(state: PadState, controls: tuple[str, ...]) -> bool:
    """Return whether any of the named controls is held (triggers past their threshold)."""
    for name in controls:
        value = getattr(state, name)
        if value is True or (not isinstance(value, bool) and value >= TRIGGER_THRESHOLD):
            return True
    return False


def gamepad_frame(
    state: PadState,
    preset: GamepadPreset = RIGHT_STICK_MODIFIERS,
    deadzone: float = STICK_DEADZONE,
) -> InputFrame:
    """Return the ``InputFrame`` for a controller snapshot."""
    stick_u, stick_v = process_stick(state.left_x, state.left_y, deadzone)
    move = stick_to_world(stick_u, stick_v)

    up, down = is_held(state, preset.up), is_held(state, preset.down)
    if preset.right_stick_modifiers and abs(state.right_y) > abs(state.right_x):
        # The vertical axis must dominate, so a sideways flick is not read as up or down.
        up = up or state.right_y >= MODIFIER_THRESHOLD
        down = down or state.right_y <= -MODIFIER_THRESHOLD
    vertical = VERTICAL_NONE if up == down else (VERTICAL_UP if up else VERTICAL_DOWN)

    held = 0
    for field_name, button in _BUTTON_FIELDS:
        if is_held(state, getattr(preset, field_name)):
            held |= button
    return InputFrame(move=move, vertical=vertical, held=held, cstick=smash_stick(state, preset))


def smash_stick(state: PadState, preset: GamepadPreset) -> Vec2 | None:
    """Return the world direction the right stick is flicked in, for a "C-stick" smash.

    The sim reacts to the frame this goes from ``None`` to a direction. When the right stick
    is also the up/down modifier, only a mostly sideways push counts.
    """
    x, y = state.right_x, state.right_y
    if math.hypot(x, y) < MODIFIER_THRESHOLD:
        return None
    if preset.right_stick_modifiers and abs(y) > abs(x):
        return None
    return stick_to_world(x, y).normalized()


def merge_frames(first: InputFrame, second: InputFrame) -> InputFrame:
    """Combine two devices driving the same player (keyboard plus a gamepad).

    The stick pushed further wins, buttons are combined, and opposite vertical intents cancel.
    """
    move = first.move if first.move.length() >= second.move.length() else second.move
    verticals = {first.vertical, second.vertical} - {VERTICAL_NONE}
    vertical = verticals.pop() if len(verticals) == 1 else VERTICAL_NONE
    cstick = first.cstick if first.cstick is not None else second.cstick
    return InputFrame(move=move, vertical=vertical, held=first.held | second.held, cstick=cstick)
