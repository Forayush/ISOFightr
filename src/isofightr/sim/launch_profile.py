"""How a hit freezes and launches its target, frame by frame, from the real sim.

Plan note "16 - Testing Debug and Tooling" (``launch_profile.py``, decision D-066). The
attacker performs a move on a target standing in front of it, set up as in
:mod:`isofightr.sim.kill_calc` (neither touches the controls). From the tick the launch is
applied (the last hitlag frame, frame 0) the target's movement is recorded: how far it moved
each frame (its speed), how far it is from where it was launched, how high above it, its
hitstun and state, and the speed of its knockback alone. When it is KO'd the record keeps the
place (and the knockback) it was KO'd with.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat import knockback as kb
from isofightr.sim.events import HitEvent
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.kill_calc import DEFAULT_GAP
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import Stage
from isofightr.sim.states.interrupts import start_move

PROFILE_FRAMES: Final[int] = 90
"""How many frames after the launch are recorded."""
TABLE_FRAMES: Final[tuple[int, ...]] = (1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 90)
"""The frames the tool prints (the rows of D-066's baseline table)."""
EARLY_FRAMES: Final[int] = 20
"""The travel in this many frames, as a share of the whole record, measures the snap."""
LOW_KNOCKBACK_SHARE: Final[float] = 0.1
"""The knockback counts as spent once its speed is below this share of its peak."""
HIT_TICK_LIMIT: Final[int] = 240
"""A move that has not hit by this tick never will."""
TELEPORT: Final[float] = 2.0
"""A move of more than this in one frame is a respawn, not travel."""
FRAMES_PER_SECOND: Final[int] = 60


@dataclass(frozen=True, slots=True)
class ProfileRow:
    """The launched target on one frame after the launch."""

    frame: int
    speed: float
    """How far it moved this frame, in units."""
    distance: float
    """How far it is from where it was launched (straight line, in units)."""
    travel: float
    """The same along the ground only (in units)."""
    height: float
    """How far above the launch point it is (in units)."""
    hitstun: int
    """Hitstun frames left."""
    state: StateId
    knockback_speed: float
    """The speed of its knockback velocity alone, in units per frame."""


@dataclass(frozen=True, slots=True)
class LaunchProfile:
    """One hit and the launch it caused."""

    percent: float
    damage: float
    knockback: float
    freeze: int
    """Hitlag frames, for both fighters."""
    hitstun: int
    body_height: float
    rows: tuple[ProfileRow, ...]
    """Frame 0 (the launch tick) to ``PROFILE_FRAMES``."""

    @property
    def state(self) -> StateId:
        """The state the hit put the target in."""
        return self.rows[0].state

    @property
    def peak_speed(self) -> float:
        """The fastest the target moved in one frame, in units."""
        return max(row.speed for row in self.rows)

    def body_heights_per_second(self, speed: float) -> float:
        """Return a speed in units per frame as body heights per second."""
        return speed * FRAMES_PER_SECOND / self.body_height

    def row(self, frame: int) -> ProfileRow:
        """Return the record of a frame (the last one if the record is shorter)."""
        return self.rows[min(frame, len(self.rows) - 1)]

    @property
    def early_share(self) -> float:
        """The share of the whole record's travel along the ground done in the first
        ``EARLY_FRAMES`` frames (1.0 for a target that stopped by then)."""
        whole = self.row(PROFILE_FRAMES).travel
        return 1.0 if whole <= 0.0 else self.row(EARLY_FRAMES).travel / whole

    @property
    def knockback_spent_frame(self) -> int | None:
        """The first frame whose knockback speed is below ``LOW_KNOCKBACK_SHARE`` of its
        peak, or ``None`` if it never is within the record."""
        peak = max(row.knockback_speed for row in self.rows)
        for row in self.rows[1:]:
            if row.knockback_speed < LOW_KNOCKBACK_SHARE * peak:
                return row.frame
        return None

    @property
    def rise(self) -> float:
        """How far above the launch point the target got, in units."""
        return max(row.height for row in self.rows)


def launch_profile(
    stage: Stage,
    attacker: CharacterDef,
    target: CharacterDef,
    move_id: str,
    percent: float,
    facing: Dir8 = Dir8.SE,
    gap: float = DEFAULT_GAP,
    rules: MatchRules | None = None,
) -> LaunchProfile:
    """Return the profile of ``move_id`` hitting a target at ``percent`` standing on the
    stage's respawn point, the attacker ``gap`` units behind it facing it.

    Raises ``ValueError`` if the move never hits.
    """
    match = Match.create(stage, [attacker, target], rules=rules or MatchRules(stocks=None))
    striker, victim = match.fighters
    spot = stage.respawn
    top = stage.surface_top(spot.x, spot.y)
    assert top is not None, "the target must stand on solid ground"
    victim.pos = Vec3(spot.x, spot.y, top)
    victim.damage = percent
    behind = spot - facing.world * gap
    striker.pos = Vec3(behind.x, behind.y, top)
    striker.facing = facing
    start_move(match, striker, move_id)

    hit: HitEvent | None = None
    for _ in range(HIT_TICK_LIMIT):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        for event in match.events:
            if isinstance(event, HitEvent) and event.target == victim.player_index:
                hit = hit or event
        if hit is not None and victim.hitlag == 0:
            break
    if hit is None or victim.launch is not None:
        raise ValueError(f"{move_id} does not hit a target standing {gap} units in front")

    start = last = victim.pos
    knockback_speed = victim.kb_vel.length()
    rows = [ProfileRow(0, 0.0, 0.0, 0.0, 0.0, victim.hitstun, victim.state, knockback_speed)]
    gone = False
    for frame in range(1, PROFILE_FRAMES + 1):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        gone = gone or not victim.in_play
        here = last if gone else victim.pos
        moved = (here - last).length()
        if moved > TELEPORT:
            here, moved, gone = last, 0.0, True
        offset = here - start
        if not gone:
            knockback_speed = victim.kb_vel.length()
        rows.append(
            ProfileRow(
                frame,
                moved,
                offset.length(),
                offset.xy.length(),
                offset.z,
                victim.hitstun,
                victim.state,
                knockback_speed,
            )
        )
        last = here
    return LaunchProfile(
        percent,
        hit.damage,
        hit.knockback,
        hit.hitlag,
        kb.hitstun_frames(hit.knockback),
        target.body.height,
        tuple(rows),
    )


def profile_lines(profile: LaunchProfile, frames: Sequence[int] = TABLE_FRAMES) -> list[str]:
    """Return the profile as text: a summary line, a second line of the D-066 metrics, and
    the table at ``frames`` (the layout of D-066's baseline file)."""
    body = profile.body_height
    peak = profile.row(1).speed
    spent = profile.knockback_spent_frame
    lines = [
        f"--- target at {profile.percent:g}%: hit {profile.damage:.1f}% KB "
        f"{profile.knockback:.0f}, freeze {profile.freeze} frames "
        f"({profile.freeze * 1000 / FRAMES_PER_SECOND:.0f} ms), hitstun {profile.hitstun} "
        f"frames, state {profile.state.name}, peak speed {peak:.3f} u/f = "
        f"{profile.body_heights_per_second(peak):.1f} body-heights/s",
        f"    travel in the first {EARLY_FRAMES} frames {profile.early_share:.0%} of "
        f"{PROFILE_FRAMES}; knockback below {LOW_KNOCKBACK_SHARE:.0%} of its peak on frame "
        f"{'-' if spent is None else spent} (hitstun {profile.hitstun}); rises "
        f"{profile.rise:.2f} u = {profile.rise / body:.2f} body",
        "   frame  speed(u/f)  dist(u)  dist(body)  dz   hitstun_left",
    ]
    for frame in frames:
        row = profile.row(frame)
        lines.append(
            f"   {frame:5d}   {row.speed:9.3f}  {row.distance:7.2f}  "
            f"{row.distance / body:9.2f}  {row.height:+.2f}  {row.hitstun:5d}  {row.state.name}"
        )
    return lines
