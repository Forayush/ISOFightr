"""Draws the overlay VFX layer: hit sparks, attack swings, grab boxes and shield bubbles.

Plan note "03 - Isometric World and Rendering" (render layer 6, "Overlay VFX": drawn on top
of the world for readability, at the projected hit point). Sprites come from a pool and are
drawn as one batched ``SpriteList``.

Reads state only: it never changes what it draws.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from functools import partial

import arcade
from PIL import Image

from isofightr.render import placeholder_art as art
from isofightr.render import projectile_art, vfx_art
from isofightr.render.camera import snap
from isofightr.render.effects import BattleEffects
from isofightr.render.ground_items import ProjectileLooks
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
        self.projectile_looks = ProjectileLooks()
        self.plain_projectiles = False
        """Draw every projectile as the placeholder ball (``placeholder_art=True``)."""

    def sync(
        self,
        effects: BattleEffects,
        fighters: Sequence[Fighter],
        projectiles: Sequence[Projectile] = (),
        animated: Collection[int] = (),
        colors: Mapping[int, int] | None = None,
        camera_centre: tuple[int, int] | None = None,
    ) -> None:
        """Place a sprite for every live spark, raised shield, grab box and hitbox.

        Fighters whose ``entity_id`` is in ``animated`` show their attack in their own sprite,
        so their hitboxes get no swing blob. ``colors`` gives every player's color index (for
        KO blasts of fighters no longer in play); ``camera_centre`` is where the camera looks,
        in world pixels, so a KO blast can start at the edge of the view.
        """
        wanted: list[tuple[arcade.Texture, Vec3]] = []
        for fighter in fighters:
            player = fighter.color_index
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
            if fighter.entity_id in animated:
                continue
            for box in active_hitboxes(fighter):
                radius = box.definition.radius
                texture = self._texture(
                    ("swing", player, radius), partial(art.build_swing, player, radius)
                )
                wanted.append((texture, box.centre))
        colors = {fighter.player_index: fighter.color_index for fighter in fighters}
        self.projectile_looks.learn([fighter.character for fighter in fighters])
        for projectile in projectiles:
            if projectile.bursting:
                continue  # the shockwave ring shows it
            color = colors.get(projectile.owner, projectile.owner)
            style = None if self.plain_projectiles else self.projectile_looks.style(projectile)
            if style is None:
                ball = (color, projectile.hitbox.radius)
                texture = self._texture(("projectile", *ball), partial(art.build_projectile, *ball))
                wanted.append((texture, projectile.pos))
                continue
            if style.decal:
                continue  # a ground decal: the world renderer draws it in depth order
            heading = projectile_art.heading_of(projectile.vel) if style.headed else 0
            frame = projectile_art.frame_of(style, projectile.age)
            base = projectile.definition.hitbox.damage
            step = projectile_art.charge_step(projectile.damage, base) if style.charged else 0
            key = (style.name, heading, frame, step, color)
            texture = self._texture(
                ("styled", *key),
                partial(projectile_art.build, style, heading, frame, step, color),
            )
            wanted.append((texture, projectile.pos))
        for spark in effects.sparks:
            key = (spark.tier, spark.effect.value, spark.frame)
            texture = self._texture(("spark", *key), partial(vfx_art.build_spark, *key))
            wanted.append((texture, spark.position))
        for ring in effects.rings:
            texture = self._texture(("ring", ring.frame), partial(vfx_art.build_ring, ring.frame))
            wanted.append((texture, ring.position))
        for puff in effects.puffs:
            key = (puff.size, puff.frame)
            texture = self._texture(("puff", *key), partial(vfx_art.build_puff, *key))
            wanted.append((texture, puff.position))
        for effect in effects.fx:
            key = (effect.kind, effect.family, effect.variant, effect.frame)
            texture = self._texture(("fx", *key), partial(vfx_art.build_fx, *key))
            wanted.append((texture, effect.at))
        for streak in effects.streaks:
            key = (streak.angle, streak.frame)
            texture = self._texture(("streak", *key), partial(vfx_art.build_streak, *key))
            wanted.append((texture, streak.position))
        for trail in effects.trails:
            key = (trail.fiery, trail.frame)
            texture = self._texture(("trail", *key), partial(vfx_art.build_trail, *key))
            wanted.append((texture, trail.position))
        placed: list[tuple[arcade.Texture, tuple[float, float]]] = []
        if camera_centre is not None:
            for blast in effects.blasts:
                color = (colors or {}).get(blast.player, blast.player)
                angle_index, base = vfx_art.ko_beam_placement(
                    blast.position, blast.normal, camera_centre
                )
                key = (color, angle_index, blast.frame)
                texture = self._texture(
                    ("ko", *key),
                    partial(
                        vfx_art.build_ko_beam, art.player_color(color), angle_index, blast.frame
                    ),
                )
                placed.append((texture, base))

        screen: list[tuple[arcade.Texture, tuple[float, float]]] = [
            (texture, project(position.x, position.y, position.z)) for texture, position in wanted
        ]
        screen += placed
        while len(self._pool) < len(screen):
            sprite = arcade.Sprite(screen[0][0])
            self._pool.append(sprite)
            self.sprites.append(sprite)
        for index, sprite in enumerate(self._pool):
            sprite.visible = index < len(screen)
            if index < len(screen):
                texture, (sx, sy) = screen[index]
                if sprite.texture is not texture:
                    sprite.texture = texture
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
