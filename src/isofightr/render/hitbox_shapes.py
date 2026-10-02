"""Where the sim's collision shapes land on screen, for the F1 hitbox overlay.

A sphere in the world is an ellipse on screen in this projection. Drawing is in
:mod:`isofightr.render.hitbox_overlay`.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from dataclasses import dataclass

from isofightr.render.camera import snap
from isofightr.render.iso import project
from isofightr.render.placeholder_art import SPHERE_HEIGHT_PER_UNIT, SPHERE_WIDTH_PER_UNIT
from isofightr.sim.math3d import Capsule, Vec3


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
