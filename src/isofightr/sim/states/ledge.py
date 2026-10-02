"""Ledges: catching one, hanging, trumping, and the ledge options.

Plan note "06 - Shield Dodge Grab and Ledge" ("Ledges"). Ledge lines come from the stage
(:func:`isofightr.sim.stage.generate_ledges`). A falling fighter close to a line, on its
outer side and a little below its top, snaps to it. While hanging or climbing the fighter is
placed by its state, not by physics.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.combat import constants as c
from isofightr.sim.events import JumpEvent, JumpKind, LedgeGrabEvent
from isofightr.sim.fighter import NO_LEDGE, Fighter, GroundKind, StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, Press
from isofightr.sim.math3d import ZERO3, Vec2, Vec3
from isofightr.sim.stage import NO_PLATFORM, LedgeLine, Stage
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import STATES, AirState, State, change_state, register

if TYPE_CHECKING:
    from isofightr.sim.match import Match

OPTION_DOT = 0.38
"""How far toward (or away from) the stage the stick must point to pick getup (or drop)."""
ROLL_PROBE_STEP = 0.2
"""Spacing of the checks for solid ground along a ledge roll's path, in units."""
CLIMB_FRACTION = 0.4
"""Share of a ledge roll spent getting up onto the stage before rolling inward."""


# --- geometry ------------------------------------------------------------------------------


def closest_point(ledge: LedgeLine, position: Vec2) -> Vec2:
    """Return the point of a ledge line nearest to a ground position."""
    along = ledge.end - ledge.start
    length_squared = along.dot(along)
    if length_squared == 0.0:
        return ledge.start
    t = max(0.0, min(1.0, (position - ledge.start).dot(along) / length_squared))
    return ledge.start + along * t


def find_ledge(stage: Stage, fighter: Fighter) -> tuple[int, Vec2] | None:
    """Return the ledge line a fighter is in reach of, and the point on it, or ``None``.

    In reach: on the line's outer side, within ``LEDGE_REACH`` of it on the ground plane, with
    the feet between ``LEDGE_Z_BELOW`` below its top. The nearest line wins (the first in
    stage order on a tie), which at a corner is the one the fighter is more squarely beside.
    """
    position = fighter.pos.xy
    nearest, farthest = c.LEDGE_Z_BELOW
    best: tuple[float, int, Vec2] | None = None
    for index, ledge in enumerate(stage.ledges):
        if not ledge.z - farthest <= fighter.pos.z <= ledge.z - nearest:
            continue
        point = closest_point(ledge, position)
        offset = position - point
        distance = offset.length()
        if distance > c.LEDGE_REACH or offset.dot(ledge.normal) < 0.0:
            continue
        if best is None or distance < best[0]:
            best = (distance, index, point)
    return None if best is None else (best[1], best[2])


def hang_position(ledge: LedgeLine, point: Vec2) -> Vec3:
    """Return where a fighter hanging from ``point`` has its feet."""
    out = point + ledge.normal * c.LEDGE_HANG_OUT
    return Vec3(out.x, out.y, ledge.z - c.LEDGE_HANG_BELOW)


def top_position(ledge: LedgeLine, point: Vec2, inset: float) -> Vec3:
    """Return the spot on top of the stage ``inset`` units inside the ledge line."""
    inside = point - ledge.normal * inset
    return Vec3(inside.x, inside.y, ledge.z)


def ledge_intangible_frames(fighter: Fighter) -> int:
    """Return the intangibility a ledge grab gives: less after a long time in the air or at
    high damage, none for a regrab without touching the ground."""
    if fighter.ledge_grabs > 0:
        return 0
    frames = (
        c.LEDGE_INTANGIBLE_BASE
        - fighter.air_frames * c.LEDGE_INTANGIBLE_PER_AIR_FRAME
        - fighter.damage * c.LEDGE_INTANGIBLE_PER_DAMAGE
    )
    return max(c.LEDGE_INTANGIBLE_MIN, math.floor(frames))


def occupant_of(match: Match, newcomer: Fighter, index: int, point: Vec2) -> Fighter | None:
    """Return the fighter already hanging at this spot of the ledge, if any."""
    for other in match.fighters:
        if other is newcomer or other.state is not StateId.LEDGE_HANG or other.ledge != index:
            continue
        if (other.ledge_point - point).length() < c.LEDGE_OCCUPIED_DISTANCE:
            return other
    return None


def try_grab_ledge(match: Match, fighter: Fighter) -> bool:
    """Catch a ledge if the fighter is falling next to one (tick step 5, after moving)."""
    if not STATES[fighter.state].can_grab_ledge(fighter) or fighter.grounded:
        return False
    if fighter.hitlag > 0:
        return False
    if fighter.ledge_cooldown > 0 or fighter.buffer.vertical == VERTICAL_DOWN:
        return False
    velocity = fighter.vel + fighter.kb_vel
    if velocity.z > 0.0:
        return False
    found = find_ledge(match.stage, fighter)
    if found is None:
        return False
    index, point = found
    ledge = match.stage.ledges[index]
    if velocity.xy.dot(ledge.normal) > c.LEDGE_AWAY_SPEED:
        return False

    trumped = occupant_of(match, fighter, index, point)
    if trumped is not None:
        change_state(match, trumped, StateId.LEDGE_TRUMPED)
    fighter.ledge = index
    fighter.ledge_point = point
    change_state(match, fighter, StateId.LEDGE_HANG)
    match.events.append(
        LedgeGrabEvent(
            fighter.player_index, fighter.pos, None if trumped is None else trumped.player_index
        )
    )
    return True


def _ledge(match: Match, fighter: Fighter) -> LedgeLine:
    return match.stage.ledges[fighter.ledge]


def _leave(fighter: Fighter) -> None:
    """Common to every way of leaving a ledge: it cannot be regrabbed at once."""
    fighter.ledge_cooldown = c.LEDGE_REGRAB_COOLDOWN


def _stand_on_top(match: Match, fighter: Fighter, inset: float) -> None:
    """Put the fighter on the stage, standing, ``inset`` inside its ledge."""
    fighter.pos = top_position(_ledge(match, fighter), fighter.ledge_point, inset)
    fighter.ground = GroundKind.CELL
    fighter.platform = NO_PLATFORM
    fighter.vel = ZERO3
    fighter.air_frames = 0
    fighter.ledge_grabs = 0


def _climb(match: Match, fighter: Fighter, progress: float, inset: float) -> None:
    """Place a climbing fighter ``progress`` (0 to 1) of the way from hanging to standing."""
    ledge = _ledge(match, fighter)
    start = hang_position(ledge, fighter.ledge_point)
    end = top_position(ledge, fighter.ledge_point, inset)
    fighter.pos = start + (end - start) * max(0.0, min(1.0, progress))


def roll_inset(stage: Stage, ledge: LedgeLine, point: Vec2) -> float:
    """Return how far inward a ledge roll can go: up to ``LEDGE_ROLL_DISTANCE``, stopping
    where the ground at the ledge's height ends."""
    inset = c.LEDGE_GETUP_INSET
    while inset + ROLL_PROBE_STEP <= c.LEDGE_ROLL_DISTANCE:
        probe = point - ledge.normal * (inset + ROLL_PROBE_STEP)
        if stage.surface_top(probe.x, probe.y) != ledge.z:
            break
        inset += ROLL_PROBE_STEP
    return inset


# --- states --------------------------------------------------------------------------------


class _OnLedge(State):
    """Shared by the states that hang from or climb a ledge: no physics, regrab cooldown."""

    uses_physics = False

    def exit(self, match: Match, fighter: Fighter) -> None:
        """Start the regrab cooldown."""
        _leave(fighter)


@register
class LedgeHang(_OnLedge):
    """Hanging from a ledge, facing the stage."""

    id = StateId.LEDGE_HANG

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Snap to the ledge, stop, and get fresh air options."""
        ledge = _ledge(match, fighter)
        fighter.pos = hang_position(ledge, fighter.ledge_point)
        fighter.vel = ZERO3
        fighter.kb_vel = ZERO3
        fighter.ground = GroundKind.NONE
        fighter.platform = NO_PLATFORM
        fighter.hitstun = 0
        fighter.fast_falling = False
        fighter.air_jumps_left = fighter.character.movement.air_jumps
        fighter.air_dodge_used = False
        fighter.air_moves_used = []
        interrupts.snap_facing(fighter, ledge.normal * -1.0)
        fighter.intangible_frames = ledge_intangible_frames(fighter)
        fighter.ledge_grabs += 1
        # Whatever was held or tapped on the way in must not pick a ledge option.
        for press in (Press.FLICK, Press.UP, Press.DOWN, Press.JUMP, Press.SHIELD, Press.ATTACK):
            fighter.buffer.consume(press)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Pick a ledge option on a fresh input, or let go after hanging too long."""
        if fighter.state_frame > c.LEDGE_MAX_HANG:
            self._drop(match, fighter)
            return
        if fighter.state_frame <= c.LEDGE_ACTION_DELAY:
            return
        buffer = fighter.buffer
        inward = _ledge(match, fighter).normal * -1.0
        if buffer.consume(Press.JUMP):
            self._jump(match, fighter, inward)
        elif buffer.consume(Press.ATTACK) or buffer.consume(Press.SPECIAL):
            change_state(match, fighter, StateId.LEDGE_ATTACK)
        elif buffer.consume(Press.SHIELD):
            change_state(match, fighter, StateId.LEDGE_ROLL)
        elif buffer.consume(Press.UP):
            change_state(match, fighter, StateId.LEDGE_GETUP)
        elif buffer.consume(Press.DOWN):
            self._drop(match, fighter)
        elif buffer.stick_active and buffer.consume(Press.FLICK):
            toward = interrupts.stick_direction(fighter).dot(inward)
            if toward > OPTION_DOT:
                change_state(match, fighter, StateId.LEDGE_GETUP)
            elif toward < -OPTION_DOT:
                self._drop(match, fighter)

    @staticmethod
    def _drop(match: Match, fighter: Fighter) -> None:
        fighter.intangible_frames = 0
        change_state(match, fighter, StateId.FALL)

    @staticmethod
    def _jump(match: Match, fighter: Fighter, inward: Vec2) -> None:
        stats = fighter.character.movement
        drift = inward * c.LEDGE_JUMP_IN_SPEED
        fighter.vel = Vec3(drift.x, drift.y, stats.full_hop_vz * c.LEDGE_JUMP_VZ_MULT)
        fighter.intangible_frames = c.LEDGE_JUMP_INTANGIBLE
        match.events.append(JumpEvent(fighter.player_index, JumpKind.FULL_HOP, fighter.pos))
        change_state(match, fighter, StateId.JUMP)


@register
class LedgeGetup(_OnLedge):
    """Climbing onto the stage."""

    id = StateId.LEDGE_GETUP

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Intangible for most of the climb."""
        fighter.intangible_frames = c.LEDGE_GETUP_INTANGIBLE

    def step(self, match: Match, fighter: Fighter) -> None:
        """Stand on the stage when the climb is done."""
        if fighter.state_frame > c.LEDGE_GETUP_FRAMES:
            _stand_on_top(match, fighter, c.LEDGE_GETUP_INSET)
            interrupts.become_ground_neutral(match, fighter)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Move from the hang to the standing spot."""
        _climb(match, fighter, fighter.state_frame / c.LEDGE_GETUP_FRAMES, c.LEDGE_GETUP_INSET)


@register
class LedgeAttack(_OnLedge):
    """A quick climb that ends in the character's ledge attack."""

    id = StateId.LEDGE_ATTACK

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Intangible during the climb."""
        fighter.intangible_frames = c.LEDGE_ATTACK_CLIMB_FRAMES

    def step(self, match: Match, fighter: Fighter) -> None:
        """Stand on the stage and attack."""
        if fighter.state_frame > c.LEDGE_ATTACK_CLIMB_FRAMES:
            _stand_on_top(match, fighter, c.LEDGE_GETUP_INSET)
            interrupts.start_move(match, fighter, fighter.character.moveset.ledge_attack)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Move from the hang to the standing spot."""
        progress = fighter.state_frame / c.LEDGE_ATTACK_CLIMB_FRAMES
        _climb(match, fighter, progress, c.LEDGE_GETUP_INSET)


@register
class LedgeRoll(_OnLedge):
    """Climbing up and rolling further onto the stage."""

    id = StateId.LEDGE_ROLL

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Intangible for most of the roll."""
        fighter.intangible_frames = c.LEDGE_ROLL_INTANGIBLE

    def step(self, match: Match, fighter: Fighter) -> None:
        """Stand at the end of the roll."""
        if fighter.state_frame > c.LEDGE_ROLL_FRAMES:
            inset = roll_inset(match.stage, _ledge(match, fighter), fighter.ledge_point)
            _stand_on_top(match, fighter, inset)
            interrupts.become_ground_neutral(match, fighter)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Get up onto the stage first, then travel inward along it."""
        ledge = _ledge(match, fighter)
        progress = fighter.state_frame / c.LEDGE_ROLL_FRAMES
        if progress < CLIMB_FRACTION:
            _climb(match, fighter, progress / CLIMB_FRACTION, c.LEDGE_GETUP_INSET)
            return
        full = roll_inset(match.stage, ledge, fighter.ledge_point)
        along = min(1.0, (progress - CLIMB_FRACTION) / (1.0 - CLIMB_FRACTION))
        inset = c.LEDGE_GETUP_INSET + (full - c.LEDGE_GETUP_INSET) * along
        fighter.pos = top_position(ledge, fighter.ledge_point, inset)


@register
class LedgeTrumped(AirState):
    """Knocked off a ledge by someone grabbing the same spot: a short helpless pop."""

    id = StateId.LEDGE_TRUMPED

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Pop away from the stage with no intangibility."""
        away = _ledge(match, fighter).normal * c.LEDGE_TRUMP_SPEED
        fighter.vel = Vec3(away.x, away.y, 0.0)
        fighter.intangible_frames = 0
        fighter.stun_frames = c.LEDGE_TRUMP_FRAMES
        _leave(fighter)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Fall freely once the lag is over."""
        fighter.stun_frames -= 1
        if fighter.stun_frames <= 0:
            fighter.stun_frames = 0
            change_state(match, fighter, StateId.FALL)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Fall with no control."""
        physics.apply_gravity(fighter)


__all__ = ["NO_LEDGE", "find_ledge", "try_grab_ledge"]
