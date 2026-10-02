"""F1 debug overlay: hurtboxes and active hitboxes, drawn from the sim's own collision shapes.

Plan note "13 - Game Modes UI and Flow" (training mode: "Show hitboxes/hurtboxes", F1). The
shapes come from the same functions hit resolution uses, so the overlay cannot disagree with
what actually hits. The screen geometry is in :mod:`isofightr.render.hitbox_shapes`.
"""

from collections.abc import Sequence
from typing import Final

import arcade

from isofightr.render.hitbox_shapes import capsule_ellipses, sphere_ellipse
from isofightr.sim.combat.hitbox import active_hitboxes, hurtbox
from isofightr.sim.fighter import Fighter
from isofightr.sim.math3d import Capsule

type Color = tuple[int, int, int, int]

HURTBOX_FILL: Final[Color] = (255, 224, 64, 70)
HURTBOX_LINE: Final[Color] = (255, 224, 64, 255)
INVINCIBLE_FILL: Final[Color] = (80, 160, 255, 70)
INVINCIBLE_LINE: Final[Color] = (80, 160, 255, 255)
HITBOX_FILL: Final[Color] = (255, 48, 48, 110)
HITBOX_LINE: Final[Color] = (255, 48, 48, 255)
SWEEP_LINE: Final[Color] = (255, 150, 150, 255)
LINE_WIDTH: Final[int] = 1


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
