"""F1 debug overlay: hurtboxes and active hitboxes, drawn from the sim's own collision shapes.

Plan note "13 - Game Modes UI and Flow" (training mode: "Show hitboxes/hurtboxes", F1). The
shapes come from the same functions hit resolution uses, so the overlay cannot disagree with
what actually hits. A sphere in the world is an ellipse on screen in this projection.

The geometry helpers are pure; only :class:`HitboxOverlay` draws.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import arcade

from isofightr.render.camera import snap
from isofightr.render.iso import project
from isofightr.render.placeholder_art import SPHERE_HEIGHT_PER_UNIT, SPHERE_WIDTH_PER_UNIT
from isofightr.sim.combat.hitbox import active_hitboxes, hurtbox
from isofightr.sim.fighter import Fighter
from isofightr.sim.math3d import Capsule, Vec3

type Color = tuple[int, int, int, int]

HURTBOX_FILL: Final[Color] = (255, 224, 64, 70)
HURTBOX_LINE: Final[Color] = (255, 224, 64, 255)
INVINCIBLE_FILL: Final[Color] = (80, 160, 255, 70)
INVINCIBLE_LINE: Final[Color] = (80, 160, 255, 255)
HITBOX_FILL: Final[Color] = (255, 48, 48, 110)
HITBOX_LINE: Final[Color] = (255, 48, 48, 255)
SWEEP_LINE: Final[Color] = (255, 150, 150, 255)
LINE_WIDTH: Final[int] = 1


@dataclass(frozen=True, slots=True)
class ScreenEllipse:
    """A world sphere as it appears on screen, in world pixels."""

    x: float
    y: float
    width: float
    height: float


def sphere_ellipse(centre: Vec3, radius: float) -> ScreenEllipse:
    """Return the on-screen outline of a world-space sphere."""
    sx, sy = project(centre.x, centre.y, centre.z)
    return ScreenEllipse(
        snap(sx), snap(sy), radius * SPHERE_WIDTH_PER_UNIT * 2, radius * SPHERE_HEIGHT_PER_UNIT * 2
    )


def capsule_ellipses(capsule: Capsule) -> tuple[ScreenEllipse, ScreenEllipse]:
    """Return the on-screen outlines of a capsule's two end spheres."""
    return (
        sphere_ellipse(capsule.start, capsule.radius),
        sphere_ellipse(capsule.end, capsule.radius),
    )


class HitboxOverlay:
    """Draws every in-play fighter's hurtbox and hitboxes in world pixel space."""

    def __init__(self) -> None:
        """Start with nothing to draw."""
        self.fighters: Sequence[Fighter] = ()

    def draw(self) -> None:
        """Draw the overlay. Call with the world camera active."""
        for fighter in self.fighters:
            invincible = fighter.invincible
            fill = INVINCIBLE_FILL if invincible else HURTBOX_FILL
            line = INVINCIBLE_LINE if invincible else HURTBOX_LINE
            _draw_capsule(hurtbox(fighter), fill, line)
        for fighter in self.fighters:
            for box in active_hitboxes(fighter):
                if box.previous != box.centre:
                    start = sphere_ellipse(box.previous, box.definition.radius)
                    arcade.draw_ellipse_outline(
                        start.x, start.y, start.width, start.height, SWEEP_LINE, LINE_WIDTH
                    )
                shape = sphere_ellipse(box.centre, box.definition.radius)
                arcade.draw_ellipse_filled(shape.x, shape.y, shape.width, shape.height, HITBOX_FILL)
                arcade.draw_ellipse_outline(
                    shape.x, shape.y, shape.width, shape.height, HITBOX_LINE, LINE_WIDTH
                )


def _draw_capsule(capsule: Capsule, fill: Color, line: Color) -> None:
    low, high = capsule_ellipses(capsule)
    half = low.width / 2
    if high.y > low.y:
        arcade.draw_lrbt_rectangle_filled(low.x - half, low.x + half, low.y, high.y, fill)
        for side in (-half, half):
            arcade.draw_line(low.x + side, low.y, high.x + side, high.y, line, LINE_WIDTH)
    for end in (low, high):
        arcade.draw_ellipse_filled(end.x, end.y, end.width, end.height, fill)
        arcade.draw_ellipse_outline(end.x, end.y, end.width, end.height, line, LINE_WIDTH)
