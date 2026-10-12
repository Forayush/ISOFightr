"""Flat things lying on the ground that are not fighters: projectile shadows and decals.

Plan notes "03 - Isometric World and Rendering" (D-019: every world sprite is placed by the
depth sorter; D-021: shadows are clipped to their surface) and decision D-060. A ground item
is a flat image on a surface; the world renderer clips it to that surface and gives it to
the sorter with its exact pixel rect, so a fighter standing on a decal is drawn over it and a
shadow never paints over the void or a tile's side.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Final

from PIL import Image

from isofightr.render import projectile_art, vfx_art
from isofightr.render.projectile_art import Style
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.move_def import ProjectileDef
from isofightr.sim.projectile import Projectile
from isofightr.sim.stage import Stage

DECAL_RANK: Final[int] = -1
"""Decals are drawn before shadows at the same place (a shadow lies on the decal)."""
SHADOW_RANK: Final[int] = 0
"""The same rank as a fighter's shadow."""
ITEMS_PER_PROJECTILE: Final[int] = 2
EFFECT_DECAL_BASE: Final[int] = 1 << 16
"""Ids of effect decals start here, above any projectile's items in a match."""


@dataclass(frozen=True, slots=True)
class GroundItem:
    """A flat image lying on a surface, centred on a ground position."""

    item_id: int
    """Unique among ground items and stable for as long as the item exists."""
    x: float
    y: float
    surface: float
    """Height of the surface it lies on."""
    key: tuple[object, ...]
    """What the image looks like: equal keys share a texture."""
    build: Callable[[], Image.Image]
    rank: int = DECAL_RANK
    on_ground: bool = False
    """Whether it lies on solid ground, which never moves: it is then clipped against the
    stage as loaded, and the renderer may keep the clipping for the next time something
    lies in the same place (a stage's flat props, the shadows of its moving platforms)."""


class ProjectileLooks:
    """Which art style each projectile definition has, for the characters in a match.

    The style follows the definition, not the current owner, so a reflected projectile keeps
    its shape (and takes the reflector's colours).
    """

    def __init__(self) -> None:
        self._styles: dict[ProjectileDef, Style | None] = {}
        self._known: set[int] = set()

    def learn(self, characters: Sequence[CharacterDef]) -> None:
        """Add the projectile definitions of ``characters`` (cheap to call every frame)."""
        for character in characters:
            if id(character) in self._known:
                continue
            self._known.add(id(character))
            for move_id, move in character.moves.items():
                for definition in move.projectiles:
                    self._styles[definition] = projectile_art.style_of(character.id, move_id)

    def style(self, projectile: Projectile) -> Style | None:
        """Return a projectile's style, or ``None`` for the plain ball."""
        return self._styles.get(projectile.definition)


def projectile_items(
    stage: Stage,
    projectiles: Sequence[Projectile],
    looks: ProjectileLooks,
    colors: Mapping[int, int],
) -> list[GroundItem]:
    """Return the ground items of the projectiles in flight: a shadow under each one that is
    over a surface, or the decal itself for a ground style (the Snare Glyph)."""
    items = []
    for projectile in projectiles:
        if projectile.bursting or not projectile.alive:
            continue
        pos = projectile.pos
        surface = stage.support_below(pos.x, pos.y, pos.z)
        if surface is None:
            continue
        style = looks.style(projectile)
        color = colors.get(projectile.owner, projectile.owner)
        base = projectile.id * ITEMS_PER_PROJECTILE
        if style is not None and style.decal:
            frame = projectile_art.frame_of(style, projectile.age)
            items.append(
                GroundItem(
                    base,
                    pos.x,
                    pos.y,
                    surface,
                    ("decal", style.name, frame, color),
                    partial(projectile_art.build, style, 0, frame, 0, color),
                    DECAL_RANK,
                )
            )
            continue
        step = projectile_art.shadow_step(pos.z - projectile.hitbox.radius - surface)
        items.append(
            GroundItem(
                base + 1,
                pos.x,
                pos.y,
                surface,
                ("projectile_shadow", step),
                partial(projectile_art.build_shadow, step),
                SHADOW_RANK,
            )
        )
    return items


def decal_items(
    stage: Stage, decals: Sequence[tuple[int, float, float, float, int]]
) -> list[GroundItem]:
    """Return the ground items of effect decals (ground cracks), given as
    ``(id, x, y, z, fade)``. Each lies on the surface under its position."""
    items = []
    for decal_id, x, y, z, fade in decals:
        surface = stage.support_below(x, y, z)
        if surface is None:
            continue
        items.append(
            GroundItem(
                EFFECT_DECAL_BASE + decal_id,
                x,
                y,
                surface,
                ("crack", fade),
                partial(vfx_art.build_crack, fade),
                DECAL_RANK,
            )
        )
    return items


# --- the shadows of moving platforms (decision D-063) -------------------------------------

PLATFORM_SHADOW_BASE: Final[int] = (1 << 19) + (1 << 18)
"""Ids of platform shadows start here: above the stage's flat props, and still under
``1 << 20``, where the world renderer's ids for ground items end."""
SURFACES_PER_PLATFORM: Final[int] = 4
"""Heights of ground one platform's shadow may fall on at once."""
SHADOW_SAMPLE: Final[float] = 0.45
"""How far from a cell's middle its shadow looks for ground: nearly to its corners."""


def platform_shadows(rest: Stage, live: Stage) -> list[GroundItem]:
    """Return the shadow every moving platform casts on the solid ground under it.

    A platform in this projection could as well be lying on the ground further back as
    floating: its shadow is what says how high it is. ``rest`` is the stage as loaded (it
    says which platforms move), ``live`` the same stage on this frame. One picture of the
    whole platform per height of ground under it (the renderer clips each to its own
    surface, so a platform half over an edge shades only the ground that is there); nothing
    over the void, and nothing on ground that is higher than the platform.
    """
    from isofightr.render.placeholder_art import build_moving_shadow

    shadows = []
    for index, (still, now) in enumerate(
        zip(rest.soft_platforms, live.soft_platforms, strict=True)
    ):
        if still.motion is None:
            continue
        columns = round(still.x1 - still.x0)
        rows = round(still.y1 - still.y0)
        tops = set()
        for row in range(rows):
            for column in range(columns):
                x, y = now.x0 + column + 0.5, now.y0 + row + 0.5
                for dx, dy in ((0.0, 0.0), (-1.0, -1.0), (-1.0, 1.0), (1.0, -1.0), (1.0, 1.0)):
                    top = rest.surface_top(x + dx * SHADOW_SAMPLE, y + dy * SHADOW_SAMPLE)
                    if top is not None and top < now.z:
                        tops.add(top)
        for order, top in enumerate(sorted(tops)[:SURFACES_PER_PLATFORM]):
            shadows.append(
                GroundItem(
                    PLATFORM_SHADOW_BASE + index * SURFACES_PER_PLATFORM + order,
                    now.x0 + columns / 2,
                    now.y0 + rows / 2,
                    top,
                    ("platform-shadow", columns, rows),
                    partial(build_moving_shadow, columns, rows),
                    DECAL_RANK,
                    on_ground=True,
                )
            )
    return shadows
