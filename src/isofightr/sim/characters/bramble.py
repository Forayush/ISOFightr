"""Bramble's special-move scripts (plan note "12 - Roster").

- Boulder Toss (neutral): plain data, an arcing projectile that bursts into a ground
  shockwave where it lands.
- Shoulder Charge (side): an armored rush along the stick; catches ledges at its end.
- Vine Lash (up): a tether. If a ledge is in reach, Bramble reels himself to it and hangs;
  otherwise he makes a short leap.
- Quake Slam (down): in the air he plummets with a meteor hitbox; landing (or using it on the
  ground) becomes ``quake_land``, a shockwave around him that pops grounded foes up.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from isofightr.sim.characters import MoveScript, register_script
from isofightr.sim.characters.common import aim_with_stick, dash_motion, fall, fly
from isofightr.sim.events import ShockwaveEvent
from isofightr.sim.fighter import NO_LEDGE
from isofightr.sim.math3d import ZERO2, ZERO3, Vec3

if TYPE_CHECKING:
    from isofightr.sim.fighter import Fighter
    from isofightr.sim.match import Match

CHARGE_FRAMES: Final[tuple[int, int]] = (10, 26)
"""Move frames during which Shoulder Charge travels."""
CHARGE_SPEED: Final[float] = 0.15

VINE_LASH_FRAME: Final[int] = 9
"""The frame the vine is thrown: a ledge in reach is caught then."""
VINE_REACH: Final[float] = 4.2
"""How far (on the ground plane) the vine reaches."""
VINE_BELOW: Final[float] = 1.0
VINE_ABOVE: Final[float] = 5.0
"""A ledge whose top is between this far below and this far above Bramble's feet."""
VINE_REEL_SPEED: Final[float] = 0.32
VINE_REEL_FRAMES: Final[int] = 24
"""Reeling gives up (and Bramble just falls) after this many frames."""
VINE_ARRIVE: Final[float] = 0.35
VINE_LEAP: Final[Vec3] = Vec3(0.05, 0.0, 0.24)
"""The short leap with no ledge in reach: forward and up (forward along the facing)."""
VINE_LEAP_FRAMES: Final[tuple[int, int]] = (9, 20)

QUAKE_HOVER_FRAMES: Final[int] = 10
QUAKE_HOVER_RISE: Final[float] = 0.03
QUAKE_PLUMMET: Final[float] = -0.42
QUAKE_LAND_MOVE: Final[str] = "quake_land"
QUAKE_RADIUS: Final[float] = 2.0
"""Radius of the shockwave ring the landing shows (the hitbox is in quake_land's data)."""


class ShoulderCharge(MoveScript):
    """Side special: an armored rush aimed with the stick."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """Aim with the stick."""
        aim_with_stick(fighter)

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Rush along the facing, holding height in the air."""
        return dash_motion(fighter, CHARGE_FRAMES, CHARGE_SPEED)


class VineLash(MoveScript):
    """Up special: a tether to the nearest ledge in reach, or a short leap."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """Nothing caught yet."""
        fighter.tether_ledge = NO_LEDGE
        fighter.tether_point = ZERO2

    def on_frame(self, match: Match, fighter: Fighter) -> None:
        """Throw the vine; once caught, hang when close enough or give up after a while."""
        from isofightr.sim.states.ledge import grab_ledge_at, hang_position, ledge_within

        frame = fighter.state_frame
        if frame == VINE_LASH_FRAME and not fighter.grounded:
            found = ledge_within(match.stage, fighter, VINE_REACH, VINE_BELOW, VINE_ABOVE)
            if found is not None:
                fighter.tether_ledge, fighter.tether_point = found
        if fighter.tether_ledge == NO_LEDGE:
            return
        ledge = match.stage.ledges[fighter.tether_ledge]
        target = hang_position(ledge, fighter.tether_point)
        arrived = (target - fighter.pos).length() <= VINE_ARRIVE
        if arrived or frame > VINE_LASH_FRAME + VINE_REEL_FRAMES:
            index, point = fighter.tether_ledge, fighter.tether_point
            fighter.tether_ledge = NO_LEDGE
            if arrived:
                fighter.pos = target
                fighter.vel = ZERO3
                grab_ledge_at(match, fighter, index, point)

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Hang still while throwing; reel toward a caught ledge; else leap, then fall."""
        from isofightr.sim.states.ledge import hang_position

        frame = fighter.state_frame
        if frame < VINE_LASH_FRAME:
            fighter.vel = ZERO3
            return True
        if fighter.tether_ledge != NO_LEDGE:
            ledge = match.stage.ledges[fighter.tether_ledge]
            offset = hang_position(ledge, fighter.tether_point) - fighter.pos
            distance = offset.length()
            step = min(VINE_REEL_SPEED, distance)
            fly(fighter, ZERO3 if distance == 0.0 else offset * (step / distance))
            return True
        first, last = VINE_LEAP_FRAMES
        if first <= frame <= last:
            forward = fighter.facing.world * VINE_LEAP.x
            fly(fighter, Vec3(forward.x, forward.y, VINE_LEAP.z))
            return True
        return fall(fighter)

    def on_land(self, match: Match, fighter: Fighter) -> bool:
        """Landing mid-lash just ends it with the normal landing lag."""
        fighter.tether_ledge = NO_LEDGE
        return False


class QuakeSlam(MoveScript):
    """Down special: a plummeting meteor that ends in a ground shockwave."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """On the ground, go straight to the slam."""
        if fighter.grounded:
            from isofightr.sim.states import interrupts

            interrupts.start_move(match, fighter, QUAKE_LAND_MOVE)

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Hover a moment, then drop straight down."""
        if fighter.state_frame <= QUAKE_HOVER_FRAMES:
            fly(fighter, Vec3(0.0, 0.0, QUAKE_HOVER_RISE))
            return True
        fighter.vel = Vec3(0.0, 0.0, QUAKE_PLUMMET)
        fighter.fast_falling = False
        return True

    def on_land(self, match: Match, fighter: Fighter) -> bool:
        """Hitting the ground becomes the slam."""
        from isofightr.sim.states import interrupts

        interrupts.start_move(match, fighter, QUAKE_LAND_MOVE)
        return True


class QuakeLand(MoveScript):
    """The slam itself: a ring on the ground (the hitbox is plain data)."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """Let the presentation show the shockwave."""
        match.events.append(ShockwaveEvent(fighter.player_index, fighter.pos, QUAKE_RADIUS))


register_script("bramble.side_special", ShoulderCharge())
register_script("bramble.up_special", VineLash())
register_script("bramble.down_special", QuakeSlam())
register_script("bramble.quake_land", QuakeLand())
