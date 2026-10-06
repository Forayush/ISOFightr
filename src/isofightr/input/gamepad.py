"""Gamepad to ``InputFrame``: analog processing and bindings, as pure functions.

Plan note "08 - Controls and Input" ("Gamepad (Xbox layout)", "Analog processing") and
decision D-061: every action is bound to up to two controls of the pad in a
:class:`PadBindings` table. The left stick always moves; the right stick is either the up
and down modifiers or a smash stick. The two layouts the game shipped with before the table
(:data:`RIGHT_STICK_MODIFIERS`, :data:`MODIFIER_BUMPERS`) are now just tables to start from.
A :class:`PadState` is a plain snapshot of a controller, so this module needs no hardware
and no ``pyglet``; :mod:`isofightr.input.devices` fills snapshots from real controllers.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from typing import Final

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
    left_stick_click: bool = False
    right_stick_click: bool = False
    dpad_up: bool = False
    dpad_down: bool = False
    dpad_left: bool = False
    dpad_right: bool = False
    start: bool = False
    """The pause button. It is never bound to an action."""


CONTROL_FIELDS: Final[dict[str, str]] = {
    "a": "a",
    "b": "b",
    "x": "x",
    "y": "y",
    "leftshoulder": "left_shoulder",
    "rightshoulder": "right_shoulder",
    "lefttrigger": "left_trigger",
    "righttrigger": "right_trigger",
    "leftstick": "left_stick_click",
    "rightstick": "right_stick_click",
    "dpup": "dpad_up",
    "dpdown": "dpad_down",
    "dpleft": "dpad_left",
    "dpright": "dpad_right",
}
"""The controls an action can be bound to, by the name they have in ``settings.toml`` (the
names pyglet gives a controller's buttons), and the :class:`PadState` field each reads."""
PAD_CONTROLS: Final[tuple[str, ...]] = tuple(CONTROL_FIELDS)
PAD_ACTIONS: Final[tuple[str, ...]] = (
    "attack",
    "special",
    "strong",
    "grab",
    "jump",
    "shield",
    "walk",
    "taunt",
    "up",
    "down",
)
"""The actions a gamepad binds (movement is always the left stick)."""
MAX_CONTROLS: Final[int] = 2
"""An action has at most a primary and a secondary control."""
STICK_MODIFIERS: Final[str] = "modifiers"
"""Right stick mode: up and down are the vertical modifiers, sideways is a smash stick."""
STICK_SMASH: Final[str] = "smash"
"""Right stick mode: a smash stick in every direction."""
RIGHT_STICK_MODES: Final[tuple[str, ...]] = (STICK_MODIFIERS, STICK_SMASH)
LAYOUT_RIGHT_STICK: Final[str] = "right_stick_modifiers"
LAYOUT_BUMPERS: Final[str] = "modifier_bumpers"
LAYOUT_CUSTOM: Final[str] = "custom"

_BUTTON_ACTIONS: Final[tuple[tuple[str, int], ...]] = (
    ("attack", Button.ATTACK),
    ("special", Button.SPECIAL),
    ("jump", Button.JUMP),
    ("grab", Button.GRAB),
    ("shield", Button.SHIELD),
    ("strong", Button.STRONG),
    ("walk", Button.WALK),
    ("taunt", Button.TAUNT),
)


@dataclass(frozen=True, slots=True)
class PadBindings:
    """Which control does what on one gamepad. Each tuple names up to two controls from
    :data:`PAD_CONTROLS`; an empty one means the action is not bound."""

    attack: tuple[str, ...] = ("a",)
    special: tuple[str, ...] = ("b",)
    strong: tuple[str, ...] = ("leftshoulder",)
    grab: tuple[str, ...] = ("rightshoulder",)
    jump: tuple[str, ...] = ("x", "y")
    shield: tuple[str, ...] = ("lefttrigger", "righttrigger")
    walk: tuple[str, ...] = ()
    taunt: tuple[str, ...] = ()
    up: tuple[str, ...] = ()
    """Controls that hold the up modifier, besides the right stick."""
    down: tuple[str, ...] = ()
    right_stick: str = STICK_MODIFIERS
    """What the right stick does: one of :data:`RIGHT_STICK_MODES`."""

    @property
    def right_stick_modifiers(self) -> bool:
        """Whether pushing the right stick up or down holds the up or down modifier."""
        return self.right_stick == STICK_MODIFIERS

    def controls(self, action: str) -> tuple[str, ...]:
        """Return the controls bound to an action (none for an unknown action)."""
        return getattr(self, action) if action in PAD_ACTIONS else ()

    def action_of(self, control: str) -> str | None:
        """Return the action a control is bound to, or ``None``."""
        for action in PAD_ACTIONS:
            if control in self.controls(action):
                return action
        return None

    def with_control(self, action: str, control: str, slot: int = 0) -> PadBindings:
        """Return the bindings with a control put on an action, as its primary (slot 0) or
        secondary (slot 1) control. The control is taken away from whatever had it, so one
        button never does two things. An unknown action or control changes nothing."""
        if action not in PAD_ACTIONS or control not in CONTROL_FIELDS:
            return self
        cleared = {
            name: tuple(each for each in self.controls(name) if each != control)
            for name in PAD_ACTIONS
        }
        mine = list(cleared[action])
        if slot <= 0 or not mine:
            mine[:1] = [control]
        else:
            mine[1:] = [control]
        cleared[action] = tuple(mine[:MAX_CONTROLS])
        return replace(self, **cleared)

    def without(self, action: str, slot: int = 0) -> PadBindings:
        """Return the bindings with one control of an action removed (a secondary control
        moves up to be the primary)."""
        if action not in PAD_ACTIONS:
            return self
        mine = list(self.controls(action))
        if slot < len(mine):
            del mine[slot]
        return replace(self, **{action: tuple(mine)})

    @property
    def layout(self) -> str:
        """The id of the stock layout these bindings are, or ``"custom"``."""
        for layout_id, bindings in PAD_LAYOUTS.items():
            if self == bindings:
                return layout_id
        return LAYOUT_CUSTOM

    @property
    def name(self) -> str:
        """The layout's name as menus show it."""
        return LAYOUT_NAMES[self.layout]


RIGHT_STICK_MODIFIERS: Final[PadBindings] = PadBindings()
"""The default layout: right stick up/down are the vertical modifiers."""
MODIFIER_BUMPERS: Final[PadBindings] = PadBindings(
    strong=(),
    shield=("righttrigger",),
    up=("leftshoulder",),
    down=("lefttrigger",),
    right_stick=STICK_SMASH,
)
"""Alternate layout: LB is up and LT is down, for players who dislike the right stick; the
right stick is then a smash stick in every direction."""
PAD_LAYOUTS: Final[dict[str, PadBindings]] = {
    LAYOUT_RIGHT_STICK: RIGHT_STICK_MODIFIERS,
    LAYOUT_BUMPERS: MODIFIER_BUMPERS,
}
"""The stock layouts, by id: shortcuts that fill the whole table."""
LAYOUT_NAMES: Final[dict[str, str]] = {
    LAYOUT_RIGHT_STICK: "Right-stick modifiers",
    LAYOUT_BUMPERS: "Modifier bumpers",
    LAYOUT_CUSTOM: "Custom",
}
BINDING_FIELDS: Final[tuple[str, ...]] = tuple(field.name for field in fields(PadBindings))
assert set(PAD_ACTIONS) | {"right_stick"} == set(BINDING_FIELDS)


def process_stick(x: float, y: float, deadzone: float = STICK_DEADZONE) -> tuple[float, float]:
    """Apply the radial deadzone and outer saturation, rescaling magnitude to 0..1.

    The direction is kept; only the magnitude is remapped, so there is no axis snapping.
    """
    magnitude = math.hypot(x, y)
    if magnitude <= deadzone:
        return (0.0, 0.0)
    scaled = min(1.0, (magnitude - deadzone) / (STICK_SATURATION - deadzone))
    return (x / magnitude * scaled, y / magnitude * scaled)


def control_held(state: PadState, control: str) -> bool:
    """Return whether one named control is held (a trigger past its threshold)."""
    field_name = CONTROL_FIELDS.get(control)
    if field_name is None:
        return False
    value = getattr(state, field_name)
    return value is True or (not isinstance(value, bool) and value >= TRIGGER_THRESHOLD)


def is_held(state: PadState, controls: tuple[str, ...]) -> bool:
    """Return whether any of the named controls is held (triggers past their threshold)."""
    return any(control_held(state, control) for control in controls)


def held_controls(state: PadState) -> frozenset[str]:
    """Return every bindable control that is held right now (the controls screen's live
    test, and what it listens to when rebinding)."""
    return frozenset(control for control in PAD_CONTROLS if control_held(state, control))


def gamepad_frame(
    state: PadState,
    bindings: PadBindings = RIGHT_STICK_MODIFIERS,
    deadzone: float = STICK_DEADZONE,
) -> InputFrame:
    """Return the ``InputFrame`` for a controller snapshot."""
    stick_u, stick_v = process_stick(state.left_x, state.left_y, deadzone)
    move = stick_to_world(stick_u, stick_v)

    up, down = is_held(state, bindings.up), is_held(state, bindings.down)
    if bindings.right_stick_modifiers and abs(state.right_y) > abs(state.right_x):
        # The vertical axis must dominate, so a sideways flick is not read as up or down.
        up = up or state.right_y >= MODIFIER_THRESHOLD
        down = down or state.right_y <= -MODIFIER_THRESHOLD
    vertical = VERTICAL_NONE if up == down else (VERTICAL_UP if up else VERTICAL_DOWN)

    held = 0
    for action, button in _BUTTON_ACTIONS:
        if is_held(state, bindings.controls(action)):
            held |= button
    return InputFrame(move=move, vertical=vertical, held=held, cstick=smash_stick(state, bindings))


def smash_stick(state: PadState, bindings: PadBindings) -> Vec2 | None:
    """Return the world direction the right stick is flicked in, for a "C-stick" smash.

    The sim reacts to the frame this goes from ``None`` to a direction. When the right stick
    is also the up/down modifier, only a mostly sideways push counts.
    """
    x, y = state.right_x, state.right_y
    if math.hypot(x, y) < MODIFIER_THRESHOLD:
        return None
    if bindings.right_stick_modifiers and abs(y) > abs(x):
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
