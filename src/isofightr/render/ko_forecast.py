"""Will this hit KO? A forecast of a fighter's pending launch, for the hit splash.

Decision D-068 (M17): the hit splash's critical tier is for hits that KO. A KO comes long
after the hit, but the launch is known the moment the hit lands (``fighter.launch``: its
knockback, heading and elevation before DI), so this flies it the way the sim will in
hitstun: gravity times ``HITSTUN_GRAVITY_MULT`` while stunned, the knockback losing
``KB_DECAY`` a frame, no DI and no drift, until it leaves the blast zone (a KO: through the
bottom only while still stunned, as :mod:`isofightr.sim.kill_calc` counts them) or comes down
onto solid ground (not a KO). ``tests/test_ko_forecast.py`` holds it to the real sim's KO
percents.

Presentation only: it reads the fighter and the stage and changes neither. Pure Python (no
``arcade``).
"""

from typing import Final

from isofightr.sim.combat.constants import HITSTUN_GRAVITY_MULT, KB_DECAY
from isofightr.sim.combat.knockback import hitstun_frames, launch_speed, launch_vector
from isofightr.sim.fighter import Fighter
from isofightr.sim.math3d import ZERO3, Vec3
from isofightr.sim.stage import Stage

FORECAST_MIN_KNOCKBACK: Final[float] = 80.0
"""A launch weaker than tumble strength is never forecast to KO (and is not flown)."""
FORECAST_FRAMES: Final[int] = 240
"""The longest flight forecast: a launch still airborne by then does not count as a KO."""
SETTLED_SPEED: Final[float] = 0.05
"""Out of hitstun with its knockback slower than this (units a frame), a fighter has stopped
being carried: the launch did not KO."""
GROUND_GRACE_FRAMES: Final[int] = 1
"""A launch from the ground starts on it: it only counts as coming down after this frame."""


def will_ko(stage: Stage, fighter: Fighter) -> bool:
    """Return whether ``fighter``'s pending launch, undisturbed and without DI, carries it out
    through the stage's blast zone. ``stage`` is the stage as it is now (``match.stage``)."""
    launch = fighter.launch
    if launch is None or launch.knockback < FORECAST_MIN_KNOCKBACK:
        return False
    elevation = launch.elevation
    if fighter.grounded and elevation < 0.0:
        elevation = 0.0  # as the launch itself does: never into the floor
    knockback = launch_vector(launch.heading, elevation) * launch_speed(launch.knockback)
    knockback = knockback + launch.carry
    movement = fighter.character.movement
    stunned_for = hitstun_frames(launch.knockback)
    zone = stage.blast_zone
    position = fighter.pos
    fall = 0.0
    for frame in range(FORECAST_FRAMES):
        stunned = frame < stunned_for
        scale = HITSTUN_GRAVITY_MULT if stunned else 1.0
        fall = max(fall - movement.gravity * scale, -movement.max_fall * scale)
        speed = knockback.length()
        knockback = ZERO3 if speed <= KB_DECAY else knockback * ((speed - KB_DECAY) / speed)
        position = position + knockback + Vec3(0.0, 0.0, fall)
        if not zone.contains(position):
            return stunned or position.z >= zone.z_min
        top = stage.surface_top(position.x, position.y)
        coming_down = knockback.z + fall < 0.0
        if frame > GROUND_GRACE_FRAMES and top is not None and position.z <= top and coming_down:
            return False
        if not stunned and knockback.length() < SETTLED_SPEED:
            return False
    return False
