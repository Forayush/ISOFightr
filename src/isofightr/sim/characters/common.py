"""Helpers shared by special-move scripts.

Plan note "12 - Roster": specials aim on the ground plane with the stick, and some pick a 3D
direction with the up and down modifiers too.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from isofightr.sim import physics
from isofightr.sim.fighter import GroundKind
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_UP, facing_from_move
from isofightr.sim.math3d import ZERO3, Vec3
from isofightr.sim.stage import NO_PLATFORM

if TYPE_CHECKING:
    from isofightr.sim.fighter import Fighter


def stick(fighter: Fighter) -> Vec3:
    """The stick on the ground plane (zero when it is near the centre)."""
    move = fighter.buffer.move if fighter.buffer.stick_active else None
    return ZERO3 if move is None else Vec3(move.x, move.y, 0.0)


def aim_with_stick(fighter: Fighter) -> None:
    """Turn the fighter to face the stick (eight ways); with no direction held, keep facing."""
    if fighter.buffer.stick_active:
        facing = facing_from_move(fighter.buffer.move)
        if facing is not None:
            fighter.facing = facing


UP: Final[Vec3] = Vec3(0.0, 0.0, 1.0)


def direction_3d(fighter: Fighter, default: Vec3 = UP) -> Vec3:
    """A unit 3D direction from the stick (ground plane) and the up/down modifiers. With
    nothing held, ``default``."""
    ground = stick(fighter)
    vertical = fighter.buffer.vertical
    z = 1.0 if vertical == VERTICAL_UP else -1.0 if vertical == VERTICAL_DOWN else 0.0
    wanted = Vec3(ground.x, ground.y, z)
    length = wanted.length()
    return default if length == 0.0 else wanted * (1.0 / length)


def leave_ground(fighter: Fighter) -> None:
    """Take the fighter off the ground so its motion can carry it up."""
    if fighter.grounded:
        fighter.ground = GroundKind.NONE
        fighter.platform = NO_PLATFORM


def dash_motion(fighter: Fighter, frames: tuple[int, int], speed: float) -> bool:
    """Wind up in place, dash along the facing during ``frames`` (holding height in the air),
    then come out of it. Always handles the motion (returns ``True``) except on the ground
    after the dash, where the move's own motion and traction take over."""
    first, last = frames
    frame = fighter.state_frame
    if first <= frame <= last:
        dash = fighter.facing.world * speed
        fighter.vel = Vec3(dash.x, dash.y, 0.0)
        fighter.fast_falling = False
        return True
    if frame < first:
        fighter.vel = ZERO3
        return True
    if fighter.grounded:
        return False
    if frame == last + 1:
        slow = fighter.facing.world * fighter.character.movement.air_speed
        fighter.vel = Vec3(slow.x, slow.y, 0.0)
    physics.apply_gravity(fighter)
    return True


def fly(fighter: Fighter, velocity: Vec3) -> None:
    """Move at ``velocity`` this frame, off the ground if it rises."""
    if velocity.z > 0.0:
        leave_ground(fighter)
    fighter.vel = velocity
    fighter.fast_falling = False


def fall(fighter: Fighter) -> bool:
    """Ordinary falling with drift in the air; on the ground leave it to the move."""
    if fighter.grounded:
        return False
    physics.apply_gravity(fighter)
    physics.apply_air_drift(fighter)
    return True
