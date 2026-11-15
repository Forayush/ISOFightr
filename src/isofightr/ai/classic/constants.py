"""The M10 CPU's tunables, frozen (decision D-071).

A copy of the ``CPU_*`` block of :mod:`isofightr.config` as it was when the M10 CPU was frozen
as the benchmark (2026-11-15). The classic CPU reads these, never ``config``, so tuning the
game's CPU cannot change the opponent it is measured against. Do not edit.
"""

from typing import Final

CPU_MIN_LEVEL: Final[int] = 1
CPU_MAX_LEVEL: Final[int] = 9
CPU_DEFAULT_LEVEL: Final[int] = 5
CPU_LEVEL_ANCHORS: Final[tuple[int, ...]] = (1, 3, 5, 7, 9)
CPU_REACTION_FRAMES: Final[tuple[float, ...]] = (40, 28, 18, 12, 7)
"""How old the CPU's view of its opponents is, in frames."""
CPU_DECISION_FRAMES: Final[tuple[float, ...]] = (30, 20, 12, 8, 4)
"""How often a CPU in neutral picks a new plan, in frames."""
CPU_DEFEND_CHANCE: Final[tuple[float, ...]] = (0.05, 0.20, 0.40, 0.60, 0.80)
"""Chance to shield or dodge an attack it sees coming."""
CPU_DI_QUALITY: Final[tuple[float, ...]] = (0.0, 0.2, 0.5, 0.8, 1.0)
"""Chance to DI a launch toward survival (otherwise it holds nothing)."""
CPU_TECH_CHANCE: Final[tuple[float, ...]] = (0.0, 0.15, 0.40, 0.70, 0.90)
CPU_AIM_JITTER_DEGREES: Final[tuple[float, ...]] = (40.0, 22.0, 10.0, 4.0, 0.0)
"""Random error added to every direction the CPU aims."""
CPU_AGGRESSION: Final[tuple[float, ...]] = (0.25, 0.45, 0.65, 0.85, 0.95)
"""Chance to attack when one of its moves reaches the target."""
CPU_PREDICTION: Final[tuple[float, ...]] = (0.0, 0.3, 0.6, 0.85, 1.0)
"""Share of its reaction delay the CPU makes up for by extrapolating the target's motion."""
CPU_EDGEGUARD_CHANCE: Final[tuple[float, ...]] = (0.0, 0.0, 0.4, 0.8, 1.0)
"""Chance to go and guard the ledge while the target recovers."""
CPU_RECOVERY_MIXUP: Final[tuple[float, ...]] = (0.0, 0.0, 0.4, 0.6, 0.8)
"""Chance to vary recovery timing (jump late, up special early) instead of the plain route."""
CPU_LEDGE_WAIT_MAX: Final[tuple[float, ...]] = (10, 20, 35, 45, 50)
"""Longest the CPU waits on a ledge before picking an option, in frames."""
CPU_MASH_EVERY: Final[tuple[float, ...]] = (8, 6, 4, 3, 2)
"""Frames between presses while mashing out of a grab."""
CPU_PUNISH_MARGIN: Final[tuple[float, ...]] = (0, 1, 2, 3, 4)
"""Frames of an opponent's end lag the CPU leaves spare when it picks a punish."""

CPU_HIT_SLACK: Final[float] = -0.1
"""Units added to hitbox reach when the CPU judges whether a move will connect: negative, so
it only counts on hits with some overlap to spare (a borderline swing would whiff forever)."""
CPU_THREAT_SLACK: Final[float] = 0.15
"""Units added to an opponent's hitbox reach when the CPU judges whether it is in danger."""
CPU_THREAT_FRAMES: Final[int] = 8
"""How far ahead the CPU looks for hitboxes and projectiles that will reach it."""
CPU_CLOSE_RANGE: Final[float] = 1.4
"""Distance a brawler tries to keep from its target."""
CPU_ZONER_RANGE: Final[float] = 4.5
"""Distance a character with a long-range projectile tries to keep."""
CPU_ZONER_REACH: Final[float] = 8.0
"""A projectile that hits this far away makes its character a zoner."""
CPU_ZONER_HEIGHT: Final[float] = 1.0
"""A zoner only keeps its distance from a target at about its own height."""
CPU_WALK_RANGE: Final[float] = 2.5
"""Closer than this the CPU walks instead of dashing."""
CPU_WALK_TILT: Final[float] = 0.55
CPU_TURN_TILT: Final[float] = 0.3
"""A light push behind the CPU: enough to turn around without walking off."""
CPU_EDGE_LOOKAHEAD: Final[float] = 0.9
"""How far ahead of its feet a grounded CPU checks for ground before moving on, at least."""
CPU_EDGE_MARGIN: Final[float] = 0.15
"""Added to a character's skid distance (run speed squared over twice its traction): a CPU
looks at least that far ahead, so a fast runner can still stop before an edge."""
CPU_STEP_HEIGHT: Final[float] = 0.4
"""A height difference the CPU treats as level ground (anything more needs a jump)."""
CPU_REGION_SNAP: Final[float] = 0.75
"""A fighter belongs to a region if one of its cell centres is this close (per axis)."""
CPU_JUMP_REACH_SHARE: Final[float] = 0.6
"""Share of its full-hop-plus-air-jump distance a CPU counts on when planning a jump."""
CPU_JUMP_RISE_SHARE: Final[float] = 0.7
"""Share of its full-hop-plus-air-jump height a CPU counts on when planning a jump."""
CPU_ROUTE_HEIGHT_COST: Final[float] = 0.5
"""Route cost of a unit of height, against a unit of distance."""
CPU_TAKEOFF_RADIUS: Final[float] = 0.4
"""How close to a route's takeoff point the CPU gets before it jumps."""
CPU_SAFE_INSET: Final[float] = 0.8
"""How far inside a ledge the CPU stands when its target is off the stage."""
CPU_LEDGE_APPROACH_OUT: Final[float] = 0.3
"""While below a ledge, the CPU aims this far outside it so it does not slide under."""
CPU_LEDGE_APPROACH_IN: Final[float] = 0.8
"""Once level with a ledge, the CPU aims this far inside it to land on the stage."""
CPU_DESTINATION_BIAS: Final[float] = 0.6
"""Weight of "toward where I am going" against "nearest" when picking a ledge to recover to."""
CPU_UPSPECIAL_SAFETY: Final[float] = 0.7
"""Share of its up special's measured rise the CPU counts on when deciding to use it."""
CPU_TECH_PRESS_FRAMES: Final[int] = 5
"""A tumbling CPU presses shield this many frames (or fewer) before it lands."""
CPU_AIR_DODGE_FRAMES: Final[int] = 5
"""An airborne CPU air dodges a hit it sees landing within this many frames."""
CPU_DOWNED_OPENING_FRAMES: Final[int] = 11
"""The least a CPU counts on a downed opponent (knocked down, dizzy, helpless) staying open."""
CPU_SHIELD_HOLD_EXTRA: Final[int] = 4
"""Frames the CPU keeps its shield up after the threat it saw has passed."""
CPU_GETUP_MIN_LOCK: Final[int] = 2
CPU_KILL_HEADROOM: Final[float] = 1.0
"""A launch that would carry the target this many units short of the blast zone still counts
as a KO (it keeps flying a little after its knockback runs out)."""
CPU_SOFTLOCK_FRAMES: Final[int] = 20 * 60
"""The soak test's soft-lock limit: no fighter may stay in one state longer than this."""
