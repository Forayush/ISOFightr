"""Draws a stage and everything on it into the native buffer, correctly depth-sorted.

Implements "Render layers", "Depth sorting rules" and "Shadows and readability" in the plan
note "03 - Isometric World and Rendering". All world sprites (tiles, platform decks, shadows,
fighters) live in one ``SpriteList`` whose order comes from :class:`DepthSorter` every frame,
so the whole world is a single batched draw call (decision D-019).

Reads state only: it never changes what it draws.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

import arcade
from arcade.types import LBWH, LRBT
from PIL import Image

from isofightr.config import ISLAND_THICKNESS, NATIVE_H, NATIVE_W, Z_PX
from isofightr.render import placeholder_art as art
from isofightr.render.camera import snap
from isofightr.render.depth import (
    DepthSorter,
    DrawEntry,
    DynamicItem,
    ScreenRect,
    StaticItem,
    StaticKind,
)
from isofightr.render.iso import project
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.shadows import FULL_MASK, apply_mask, shadow_mask
from isofightr.sim.input_frame import Dir8
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import Stage

SHADOW_RANK = 0
BODY_RANK = 1
HIDDEN_DRAW_RANK = -1
BODY_RECT_HALF_WIDTH = art.BODY_HALF_WIDTH + 3
"""Half-width of everything the fighter sprite draws: the body plus the arrow tips."""
BODY_HEIGHT_UNITS = art.BODY_HEIGHT / Z_PX


class WorldEntity(Protocol):
    """What the renderer needs to know about a fighter-like thing. Read-only."""

    @property
    def entity_id(self) -> int:
        """Unique and stable for the whole match."""

    @property
    def player_index(self) -> int:
        """0-based player slot, which picks the color."""

    @property
    def pos(self) -> Vec3:
        """Feet position in world units."""

    @property
    def facing(self) -> Dir8:
        """Which of the eight directions the entity faces."""


class Overlay(Protocol):
    """Anything that draws itself in world pixel space on top of the world."""

    def draw(self) -> None:
        """Draw with the world camera already active."""


class _RankedSprite(arcade.Sprite):
    """A sprite that remembers its place in the current draw order."""

    draw_rank: int = HIDDEN_DRAW_RANK


class WorldRenderer:
    """Owns the sprites for one stage and its entities, and keeps them sorted."""

    def __init__(self, pixel_buffer: PixelBuffer, stage: Stage) -> None:
        """Build the static stage sprites and the world camera."""
        self.stage = stage
        self.sorter = DepthSorter(stage)
        self.sprites: arcade.SpriteList[_RankedSprite] = arcade.SpriteList()
        self.camera = arcade.Camera2D(
            viewport=LBWH(0, 0, NATIVE_W, NATIVE_H),
            position=(0, 0),
            projection=LRBT(-NATIVE_W / 2, NATIVE_W / 2, -NATIVE_H / 2, NATIVE_H / 2),
            render_target=pixel_buffer.framebuffer,
        )
        self._textures: dict[object, arcade.Texture] = {}
        self._static_sprites = [self._make_static_sprite(item) for item in self.sorter.statics]
        self._bodies: dict[int, _RankedSprite] = {}
        self._shadows: dict[int, _RankedSprite] = {}
        self._order: list[DrawEntry] | None = None

        self._background: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._background.append(
            arcade.Sprite(
                self._texture(("sky",), art.build_sky),
                center_x=NATIVE_W / 2,
                center_y=NATIVE_H / 2,
            )
        )

    # --- per-frame -------------------------------------------------------------------------

    def sync(self, entities: Sequence[WorldEntity]) -> None:
        """Update sprite positions, textures and draw order from the current world state."""
        self._drop_missing({entity.entity_id for entity in entities})
        items: list[DynamicItem] = []
        for entity in entities:
            items.append(self._sync_body(entity))
            shadow_item = self._sync_shadow(entity)
            if shadow_item is not None:
                items.append(shadow_item)

        order = self.sorter.draw_order(items)
        if order != self._order:
            self._order = order
            self._apply_order(order)

    def draw(self, camera_centre: tuple[int, int], overlay: "Overlay | None" = None) -> None:
        """Draw the background, then the sorted world as seen from ``camera_centre``.

        Call inside ``pixel_buffer.drawing()``. ``camera_centre`` is in whole world pixels.
        ``overlay`` is drawn last, in the same world pixel space (debug overlays).
        """
        self._background.draw(pixelated=True)
        self.camera.position = camera_centre
        with self.camera.activate():
            self.sprites.draw(pixelated=True)
            if overlay is not None:
                overlay.draw()

    # --- statics ---------------------------------------------------------------------------

    def _make_static_sprite(self, item: StaticItem) -> _RankedSprite:
        light = (item.cx + item.cy) % 2 == 0
        if item.kind is StaticKind.COLUMN:
            cell = self.stage.cell(item.cx, item.cy)
            assert cell is not None
            bottom = self.stage.bounds.z_min - ISLAND_THICKNESS
            side_px = snap((cell.top - bottom) * Z_PX)
            tile = cell.tile
            texture = self._texture(
                ("tile", tile, light, side_px), lambda: art.build_tile(tile, light, side_px)
            )
        elif item.kind is StaticKind.DECAL:
            texture = self._texture(("platform_shadow",), art.build_platform_shadow)
        else:
            texture = self._texture(("deck", light), lambda: art.build_deck(light))

        centre_x, back_y = project(item.cx, item.cy, item.top)
        sprite = _RankedSprite(
            texture, center_x=snap(centre_x), center_y=snap(back_y) - texture.height / 2
        )
        self.sprites.append(sprite)
        return sprite

    # --- dynamics --------------------------------------------------------------------------

    def _sync_body(self, entity: WorldEntity) -> DynamicItem:
        sprite = self._bodies.get(entity.entity_id)
        texture = self._texture(
            ("fighter", entity.player_index, entity.facing),
            lambda: art.build_fighter(entity.player_index, entity.facing),
        )
        if sprite is None:
            sprite = _RankedSprite(texture)
            self._bodies[entity.entity_id] = sprite
            self.sprites.append(sprite)
            self._order = None
        elif sprite.texture is not texture:
            sprite.texture = texture

        pos = entity.pos
        feet_x, feet_y = (snap(value) for value in project(pos.x, pos.y, pos.z))
        sprite.position = (
            feet_x + art.FIGHTER_CANVAS / 2 - art.FIGHTER_PIVOT_X,
            feet_y + art.FIGHTER_CANVAS / 2 - art.FIGHTER_PIVOT_FROM_BOTTOM,
        )
        return DynamicItem(
            item_id=_body_item_id(entity.entity_id),
            rank=BODY_RANK,
            x=pos.x,
            y=pos.y,
            z=pos.z,
            height=BODY_HEIGHT_UNITS,
            rect=ScreenRect(
                feet_x - BODY_RECT_HALF_WIDTH,
                feet_y,
                feet_x + BODY_RECT_HALF_WIDTH,
                feet_y + art.BODY_HEIGHT,
            ),
        )

    def _sync_shadow(self, entity: WorldEntity) -> DynamicItem | None:
        sprite = self._shadows.get(entity.entity_id)
        if sprite is None:
            sprite = _RankedSprite(self._shadow_texture(entity.player_index, 0, FULL_MASK))
            self._shadows[entity.entity_id] = sprite
            self.sprites.append(sprite)
            self._order = None

        pos = entity.pos
        surface = self.stage.support_below(pos.x, pos.y, pos.z)
        sprite.visible = surface is not None
        if surface is None:
            return None

        centre_x, centre_y = (snap(value) for value in project(pos.x, pos.y, surface))
        variant = art.shadow_variant_index(pos.z - surface)
        mask = shadow_mask(self.stage, centre_x, centre_y, surface)
        texture = self._shadow_texture(entity.player_index, variant, mask)
        if sprite.texture is not texture:
            sprite.texture = texture
        sprite.position = (centre_x, centre_y)
        half_w, half_h = art.SHADOW_WIDTH / 2, art.SHADOW_HEIGHT / 2
        return DynamicItem(
            item_id=_shadow_item_id(entity.entity_id),
            rank=SHADOW_RANK,
            x=pos.x,
            y=pos.y,
            z=surface,
            height=0.0,
            rect=ScreenRect(
                centre_x - half_w, centre_y - half_h, centre_x + half_w, centre_y + half_h
            ),
        )

    def _drop_missing(self, alive: set[int]) -> None:
        for sprites in (self._bodies, self._shadows):
            for entity_id in [key for key in sprites if key not in alive]:
                sprites.pop(entity_id).remove_from_sprite_lists()
                self._order = None

    def _apply_order(self, order: Sequence[DrawEntry]) -> None:
        for sprite in self._shadows.values():
            sprite.draw_rank = HIDDEN_DRAW_RANK
        for rank, entry in enumerate(order):
            if entry.is_static:
                self._static_sprites[entry.index].draw_rank = rank
            else:
                entity_id, is_body = divmod(entry.index, 2)
                (self._bodies if is_body else self._shadows)[entity_id].draw_rank = rank
        self.sprites.sort(key=lambda sprite: sprite.draw_rank)

    # --- textures --------------------------------------------------------------------------

    def _texture(self, key: object, build: Callable[[], Image.Image]) -> arcade.Texture:
        """Return the cached texture for ``key``, building its image on first use."""
        texture = self._textures.get(key)
        if texture is None:
            texture = arcade.Texture(build())
            self._textures[key] = texture
        return texture

    def _shadow_texture(self, player_index: int, variant: int, mask: bytes) -> arcade.Texture:
        # One small texture per distinct clip mask. Masks only vary near surface edges, and
        # repeat as a fighter moves along one, so the cache stays in the low hundreds.
        return self._texture(
            ("shadow", player_index, variant, mask),
            lambda: apply_mask(art.build_shadow(player_index, variant), mask),
        )


def _shadow_item_id(entity_id: int) -> int:
    return entity_id * 2


def _body_item_id(entity_id: int) -> int:
    return entity_id * 2 + 1
