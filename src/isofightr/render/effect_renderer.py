"""Draws the overlay VFX layer: hit sparks, attack swings, grab boxes and shield bubbles.

Plan note "03 - Isometric World and Rendering" (render layer 6, "Overlay VFX": drawn on top
of the world for readability, at the projected hit point). Sprites come from a pool and are
drawn as one batched ``SpriteList``.

Reads state only: it never changes what it draws.
"""

from collections.abc import Callable, Sequence
from functools import partial

import arcade
from PIL import Image

from isofightr.render import placeholder_art as art
from isofightr.render.camera import snap
from isofightr.render.effects import BattleEffects
from isofightr.render.iso import project
from isofightr.sim.combat.grab import grab_box
from isofightr.sim.combat.hitbox import active_hitboxes
from isofightr.sim.combat.shield import is_shielding, shield_centre, shield_radius
from isofightr.sim.fighter import Fighter
from isofightr.sim.math3d import Vec3
from isofightr.sim.projectile import Projectile

SHIELD_SIZE_STEP = 0.05
"""Shield bubble textures are built in steps of this radius, so a draining shield reuses them."""


class EffectRenderer:
    """Owns the sprites of the VFX layer. Draw it with the world camera active."""

    def __init__(self) -> None:
        """Create an empty sprite pool."""
        self.sprites: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._pool: list[arcade.Sprite] = []
        self._textures: dict[object, arcade.Texture] = {}

    def sync(
        self,
        effects: BattleEffects,
        fighters: Sequence[Fighter],
        projectiles: Sequence[Projectile] = (),
    ) -> None:
        """Place a sprite for every live spark, raised shield, grab box and hitbox."""
        wanted: list[tuple[arcade.Texture, Vec3]] = []
        for fighter in fighters:
            player = fighter.player_index
            if is_shielding(fighter):
                size = round(shield_radius(fighter) / SHIELD_SIZE_STEP) * SHIELD_SIZE_STEP
                texture = self._texture(
                    ("shield", player, size), partial(art.build_shield, player, size)
                )
                wanted.append((texture, shield_centre(fighter)))
            grab = grab_box(fighter)
            if grab is not None:
                texture = self._texture(
                    ("swing", player, grab.radius), partial(art.build_swing, player, grab.radius)
                )
                wanted.append((texture, grab.start))
            for box in active_hitboxes(fighter):
                radius = box.definition.radius
                texture = self._texture(
                    ("swing", player, radius), partial(art.build_swing, player, radius)
                )
                wanted.append((texture, box.centre))
        for projectile in projectiles:
            ball = (projectile.owner, projectile.hitbox.radius)
            texture = self._texture(("projectile", *ball), partial(art.build_projectile, *ball))
            wanted.append((texture, projectile.pos))
        for spark in effects.sparks:
            key = (spark.tier, spark.effect.value, spark.frame)
            texture = self._texture(("spark", *key), partial(art.build_spark, *key))
            wanted.append((texture, spark.position))

        while len(self._pool) < len(wanted):
            sprite = arcade.Sprite(wanted[0][0])
            self._pool.append(sprite)
            self.sprites.append(sprite)
        for index, sprite in enumerate(self._pool):
            sprite.visible = index < len(wanted)
            if index < len(wanted):
                texture, position = wanted[index]
                if sprite.texture is not texture:
                    sprite.texture = texture
                sx, sy = project(position.x, position.y, position.z)
                # Odd-sized art is centred on a pixel, even-sized art on a pixel corner.
                sprite.position = (
                    snap(sx) + (texture.width % 2) / 2,
                    snap(sy) + (texture.height % 2) / 2,
                )

    def draw(self) -> None:
        """Draw the layer. Call with the world camera active."""
        self.sprites.draw(pixelated=True)

    def _texture(self, key: object, build: Callable[[], Image.Image]) -> arcade.Texture:
        texture = self._textures.get(key)
        if texture is None:
            texture = arcade.Texture(build())
            self._textures[key] = texture
        return texture
