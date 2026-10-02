"""Real devices: keyboard presets, controller polling, and one ``InputFrame`` per player.

Plan note "08 - Controls and Input" ("Default bindings", "Devices and joining"). Until the
character select screen assigns devices (M7), the assignment is fixed:

- Player 1: the one-player keyboard layout, plus the first connected controller.
- Player 2: the arrows-and-numpad keyboard layout, plus the second connected controller.
- Players 3 and 4: the third and fourth controllers.

A player with both a keyboard layout and a controller can use either at any moment.
Controllers may be plugged in or removed while the game runs.
"""

import logging
from collections.abc import Sequence, Set

import arcade
import pyglet
from pyglet.math import Vec2 as PygletVec2

from isofightr.input.gamepad import (
    RIGHT_STICK_MODIFIERS,
    GamepadPreset,
    PadState,
    gamepad_frame,
    merge_frames,
)
from isofightr.input.keyboard import KeyboardBindings, keyboard_frame
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, InputFrame

LOG = logging.getLogger(__name__)
KEY = arcade.key

SOLO_KEYBOARD = KeyboardBindings(
    name="Keyboard (one player)",
    move_up=KEY.W,
    move_down=KEY.S,
    move_left=KEY.A,
    move_right=KEY.D,
    up=KEY.I,
    down=KEY.COMMA,
    buttons=(
        (KEY.J, Button.ATTACK),
        (KEY.K, Button.SPECIAL),
        (KEY.L, Button.GRAB),
        (KEY.U, Button.STRONG),
        (KEY.SPACE, Button.JUMP),
        (KEY.LSHIFT, Button.SHIELD),
        (KEY.LCTRL, Button.WALK),
        (KEY.T, Button.TAUNT),
    ),
)
"""The one-player layout from the plan. Shares no key with :data:`ARROWS_NUMPAD`."""

LEFT_CLUSTER = KeyboardBindings(
    name="Keyboard (left hand)",
    move_up=KEY.W,
    move_down=KEY.S,
    move_left=KEY.A,
    move_right=KEY.D,
    up=KEY.Q,
    down=KEY.E,
    buttons=(
        (KEY.F, Button.ATTACK),
        (KEY.G, Button.SPECIAL),
        (KEY.T, Button.GRAB),
        (KEY.R, Button.STRONG),
        (KEY.SPACE, Button.JUMP),
        (KEY.C, Button.SHIELD),
    ),
)
"""Player 1 squeezed onto the left hand, for two players on one keyboard."""

ARROWS_NUMPAD = KeyboardBindings(
    name="Keyboard (arrows and numpad)",
    move_up=KEY.UP,
    move_down=KEY.DOWN,
    move_left=KEY.LEFT,
    move_right=KEY.RIGHT,
    up=KEY.NUM_8,
    down=KEY.NUM_2,
    buttons=(
        (KEY.NUM_4, Button.ATTACK),
        (KEY.NUM_5, Button.SPECIAL),
        (KEY.NUM_6, Button.GRAB),
        (KEY.NUM_7, Button.STRONG),
        (KEY.NUM_0, Button.JUMP),
        (KEY.NUM_1, Button.SHIELD),
        (KEY.NUM_9, Button.TAUNT),
    ),
)
"""Player 2 on the same keyboard."""

DEFAULT_KEYBOARDS: tuple[KeyboardBindings | None, ...] = (SOLO_KEYBOARD, ARROWS_NUMPAD, None, None)
"""Keyboard layout per player slot (``None`` = controller only)."""


class PadReader:
    """Keeps an up-to-date :class:`PadState` for one pyglet controller.

    Sticks are tracked from pyglet's ``on_stick_motion`` events, whose vectors are up-positive
    on every backend. The raw ``lefty`` attribute is not: it is up-positive under XInput and
    down-positive under DirectInput.
    """

    def __init__(self, controller: "pyglet.input.Controller") -> None:
        """Open the controller and start listening to its sticks."""
        self.controller = controller
        self._left = (0.0, 0.0)
        self._right = (0.0, 0.0)
        controller.open()
        controller.push_handlers(on_stick_motion=self._on_stick_motion)

    def _on_stick_motion(self, controller: object, stick: str, vector: PygletVec2) -> None:
        if stick == "leftstick":
            self._left = (vector.x, vector.y)
        elif stick == "rightstick":
            self._right = (vector.x, vector.y)

    def state(self) -> PadState:
        """Return the controller's current state."""
        pad = self.controller
        return PadState(
            left_x=self._left[0],
            left_y=self._left[1],
            right_x=self._right[0],
            right_y=self._right[1],
            left_trigger=pad.lefttrigger,
            right_trigger=pad.righttrigger,
            a=bool(pad.a),
            b=bool(pad.b),
            x=bool(pad.x),
            y=bool(pad.y),
            left_shoulder=bool(pad.leftshoulder),
            right_shoulder=bool(pad.rightshoulder),
        )

    def close(self) -> None:
        """Stop listening and release the controller."""
        self.controller.remove_handlers(on_stick_motion=self._on_stick_motion)
        self.controller.close()


class InputSource:
    """Builds one ``InputFrame`` per player from the keyboard and connected controllers."""

    def __init__(
        self,
        player_count: int,
        keyboards: Sequence[KeyboardBindings | None] = DEFAULT_KEYBOARDS,
        preset: GamepadPreset = RIGHT_STICK_MODIFIERS,
    ) -> None:
        """Assign keyboard layouts and any connected controllers to the player slots."""
        self.player_count = player_count
        self.keyboards = list(keyboards[:player_count])
        self.preset = preset
        self.pads: list[PadReader | None] = [None] * player_count
        self._manager = pyglet.input.ControllerManager()
        self._manager.push_handlers(on_connect=self._connect, on_disconnect=self._disconnect)
        for controller in self._manager.get_controllers():
            self._connect(controller)

    def poll(self, held_keys: Set[int]) -> list[InputFrame]:
        """Return this tick's input for every player, in player index order."""
        frames = []
        for index in range(self.player_count):
            frame = NEUTRAL_INPUT
            bindings = self.keyboards[index]
            if bindings is not None:
                frame = keyboard_frame(bindings, held_keys)
            pad = self.pads[index]
            if pad is not None:
                frame = merge_frames(frame, gamepad_frame(pad.state(), self.preset))
            frames.append(frame)
        return frames

    def describe(self) -> list[str]:
        """Return a short description of each player's devices, for the debug panel."""
        lines = []
        for index in range(self.player_count):
            devices = []
            bindings = self.keyboards[index]
            if bindings is not None:
                devices.append(bindings.name)
            pad = self.pads[index]
            if pad is not None:
                devices.append(pad.controller.name or "controller")
            lines.append(" + ".join(devices) or "no device")
        return lines

    def close(self) -> None:
        """Release every controller."""
        self._manager.remove_handlers(on_connect=self._connect, on_disconnect=self._disconnect)
        for index, pad in enumerate(self.pads):
            if pad is not None:
                pad.close()
                self.pads[index] = None

    def _connect(self, controller: "pyglet.input.Controller") -> None:
        """Give a newly connected controller to the first player without one."""
        for index, pad in enumerate(self.pads):
            if pad is None:
                self.pads[index] = PadReader(controller)
                LOG.info("controller %r assigned to player %d", controller.name, index + 1)
                return
        LOG.info("controller %r ignored: every player already has one", controller.name)

    def _disconnect(self, controller: "pyglet.input.Controller") -> None:
        for index, pad in enumerate(self.pads):
            if pad is not None and pad.controller is controller:
                pad.close()
                self.pads[index] = None
                LOG.info("controller of player %d disconnected", index + 1)
