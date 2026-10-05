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

from isofightr.render import projectile_art
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
