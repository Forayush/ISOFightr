"""Draws the overlay VFX layer: hit sparks, attack swings, grab boxes and shield bubbles.

Plan note "03 - Isometric World and Rendering" (render layer 6, "Overlay VFX": drawn on top
of the world for readability, at the projected hit point). Sprites come from a pool and are
drawn as one batched ``SpriteList``.

Reads state only: it never changes what it draws.
"""

import hashlib
import time
from collections import deque
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from functools import partial
from typing import Final

import arcade
from PIL import Image

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.render import placeholder_art as art
from isofightr.render import projectile_art, splash_art, vfx_art
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
SHIELD_SHIMMER_TICKS = 8
"""Ticks each shimmer frame of the shield bubble is shown."""
"""Shield bubble textures are built in steps of this radius, so a draining shield reuses them."""
SCREEN_FLASH_ALPHAS: Final[tuple[int, ...]] = (0, 40, 80)
"""The critical hit's screen flash, by strength (``HitSplashes.screen_flash``): white this
opaque on the contact tick, half that on the next (decision D-068)."""
WARM_BUDGET_SECONDS: Final[float] = 0.001
"""How long building splash textures ahead of time may take in one drawn frame."""
WARM_PICTURES: Final[int] = 1
"""The most new splash pictures built ahead of time in one drawn frame: each costs about
0.6 ms in all (drawing it, making the texture, adding it to the atlas), most of it outside
what the frame's own clock sees, and twice that on a busy machine (decision D-068)."""
WARM_PICTURES_COUNTDOWN: Final[int] = 8
"""The same during the countdown (180 ticks before a versus match), when nothing moves yet
and a frame has time to spare: most of a match's pictures are built then."""


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
        self.live = 0
        """How many sprites the layer placed on the last :meth:`sync` (its live sprites)."""
        self._flash_layer: arcade.SpriteList[arcade.SpriteSolidColor] = arcade.SpriteList()
        self._flash = arcade.SpriteSolidColor(NATIVE_W * 2, NATIVE_H * 2)
        self._flash.visible = False
        self._flash_layer.append(self._flash)
        self._warm: deque[tuple[str | int, ...]] = deque()
        """Splash pictures still to build ahead of time, the next first."""
        self._by_content: dict[str, arcade.Texture] = {}
        """Splash textures by a digest of their pixels: pictures that come out the same (small
        particles at neighbouring angles) share one texture and one place in the atlas."""

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
                if self.plain_projectiles:
                    texture = self._texture(
                        ("shield", player, size), partial(art.build_shield, player, size)
                    )
                else:
                    shimmer = (
                        effects.ticks // SHIELD_SHIMMER_TICKS
                    ) % vfx_art.SHIELD_SHIMMER_FRAMES
                    width, height = art.sphere_screen_size(size)
                    texture = self._texture(
                        ("bubble", player, size, shimmer),
                        partial(
                            vfx_art.build_shield, art.player_color(player), width, height, shimmer
                        ),
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
        self._flash.visible = False
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
            flash = effects.splashes.screen_flash()
            self._flash.visible = flash > 0
            if flash:
                self._flash.position = camera_centre
                self._flash.alpha = SCREEN_FLASH_ALPHAS[min(flash, len(SCREEN_FLASH_ALPHAS) - 1)]
        for picture in effects.splashes.sprites():
            texture = self._splash_texture(("splash", *picture.key))
            placed.append((texture, (picture.x, picture.y)))

        screen: list[tuple[arcade.Texture, tuple[float, float]]] = [
            (texture, project(position.x, position.y, position.z)) for texture, position in wanted
        ]
        screen += placed
        self.live = len(screen)
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
        if self._flash.visible:
            self._flash_layer.draw()

    def warm_splashes(self, themes: Iterable[str]) -> None:
        """Queue every splash picture of ``themes`` to be built ahead of time (decision D-068):
        :meth:`warm` builds them a few at a time, so a hit rarely builds its own. Light and
        medium hits' pictures of every theme come first, then heavy and critical ones. Themes
        without art of their own are left out (they reuse a few old effects' pictures)."""
        drawn = [theme for theme in themes if splash_art.has_art(theme)]
        keys = [("splash", *key) for theme in drawn for key in splash_art.theme_keys(theme)]
        self._warm.extend(sorted(keys, key=lambda key: splash_art.heavy(key[1:])))

    def warm(self, budget: float = WARM_BUDGET_SECONDS, limit: int = WARM_PICTURES) -> int:
        """Build queued splash pictures into textures, and into the atlas: at most ``limit``
        of them, and none once ``budget`` seconds have gone. Returns how many it built."""
        started = time.perf_counter()
        built = 0
        atlas = self.sprites.atlas or arcade.get_window().ctx.default_atlas
        while self._warm and built < limit and time.perf_counter() - started < budget:
            key = self._warm.popleft()
            if key in self._textures:
                continue
            known = len(self._by_content)
            texture = self._splash_texture(key)
            if len(self._by_content) > known:  # a new picture, not one already built
                atlas.add(texture)
                built += 1
        return built

    def _splash_texture(self, key: tuple[str | int, ...]) -> arcade.Texture:
        """A splash picture's texture; pictures with the same pixels share one, named after
        a digest of them (so arcade need not hash the image itself)."""
        texture = self._textures.get(key)
        if texture is None:
            image = splash_art.build(key[1:])
            digest = hashlib.blake2b(image.tobytes(), digest_size=12).hexdigest()
            name = f"splash-{image.width}x{image.height}-{digest}"
            texture = self._by_content.get(name)
            if texture is None:
                texture = arcade.Texture(image, hash=name)
                self._by_content[name] = texture
            self._textures[key] = texture
        return texture

    @property
    def warming(self) -> int:
        """How many splash pictures are still queued to be built ahead of time."""
        return len(self._warm)

    def _texture(self, key: object, build: Callable[[], Image.Image]) -> arcade.Texture:
        texture = self._textures.get(key)
        if texture is None:
            texture = arcade.Texture(build())
            self._textures[key] = texture
        return texture
