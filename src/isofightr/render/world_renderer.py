"""Draws a stage and everything on it into the native buffer, correctly depth-sorted.

Implements "Render layers", "Depth sorting rules" and "Shadows and readability" in the plan
note "03 - Isometric World and Rendering". All world sprites (tiles, platform decks, shadows,
fighters) live in one ``SpriteList`` whose order comes from :class:`DepthSorter` every frame,
so the whole world is a single batched draw call (decision D-019).

Reads state only: it never changes what it draws.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from enum import IntEnum
from typing import Protocol

import arcade
from arcade.types import LBWH, LRBT
from PIL import Image

from isofightr.config import (
    INVINCIBLE_BLINK_FRAMES,
    NATIVE_H,
    NATIVE_W,
    OCCLUDED_FIGHTER_ALPHA,
    TILE_H,
    Z_PX,
)
from isofightr.data.paths import STAGES_DIR
from isofightr.data.tileset_art import TilesetArtError, load_tileset_art
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
from isofightr.render.fighter_look import DEFAULT_LOOK, FighterLook, Pose
from isofightr.render.iso import project
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.shadows import FULL_MASK, apply_mask, shadow_mask
from isofightr.render.sprite_bank import SpriteBank, Tint
from isofightr.render.stage_art import StageArt
from isofightr.sim.input_frame import Dir8
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import Stage

LOG = logging.getLogger(__name__)
HIDDEN_DRAW_RANK = -1
BACKDROP_COPIES = 3
BODY_RECT_HALF_WIDTH = art.BODY_HALF_WIDTH + 3
"""Half-width of everything the fighter sprite draws: the body plus the arrow tips."""
BODY_HEIGHT_UNITS = art.BODY_HEIGHT / Z_PX


class Part(IntEnum):
    """The sprites one entity can own. The value is also the tie-break rank among items at
    the same place: flat things on the ground are drawn before the body standing on them."""

    SHADOW = 0
    REVIVAL_PLATFORM = 1
    BODY = 2


class WorldEntity(Protocol):
    """What the renderer needs to know about a fighter-like thing. Read-only."""

    @property
    def entity_id(self) -> int:
        """Unique and stable for the whole match."""

    @property
    def player_index(self) -> int:
        """0-based player slot, which picks the color."""

    @property
    def color_index(self) -> int:
        """Which player color to draw in (the team's in a team match)."""

    @property
    def pos(self) -> Vec3:
        """Feet position in world units."""

    @property
    def facing(self) -> Dir8:
        """Which of the eight directions the entity faces."""

    @property
    def invincible(self) -> bool:
        """Whether the entity is invincible right now (its sprite blinks)."""

    @property
    def on_revival_platform(self) -> bool:
        """Whether the entity stands on a revival platform (which is then drawn under it)."""


class Overlay(Protocol):
    """Anything that draws itself in world pixel space on top of the world."""

    def draw(self) -> None:
        """Draw with the world camera already active."""


class _RankedSprite(arcade.Sprite):
    """A sprite that remembers its place in the current draw order."""

    draw_rank: int = HIDDEN_DRAW_RANK


class WorldRenderer:
    """Owns the sprites for one stage and its entities, and keeps them sorted."""

    def __init__(
        self,
        pixel_buffer: PixelBuffer,
        stage: Stage,
        banks: Mapping[str, SpriteBank] | None = None,
    ) -> None:
        """Build the static stage sprites and the world camera.

        ``banks`` holds the packed sprites of characters that have them, by character id;
        everyone else is drawn as the placeholder capsule.
        """
        self.stage = stage
        self.banks: Mapping[str, SpriteBank] = banks or {}
        try:
            tileset = load_tileset_art(stage.tileset)
        except TilesetArtError as error:
            LOG.error("tileset %s not loaded: %s", stage.tileset, error)
            tileset = None
        self.stage_art = None if tileset is None else StageArt(tileset)
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
        self._parts: dict[tuple[int, Part], _RankedSprite] = {}
        self._order: list[DrawEntry] | None = None

        # "X-ray" copies of fighters that the stage partly hides, drawn faintly over the
        # finished world. Where the fighter is in plain view the copy changes nothing you can
        # see (the same pixels blended over themselves, at most one 8-bit level off); behind
        # a platform or the island it shows.
        self._ghosts: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._ghost_of: dict[int, arcade.Sprite] = {}

        self._background: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._layers = self._load_backdrop()
        if not self._layers:
            self._background.append(
                arcade.Sprite(
                    self._texture(("sky",), art.build_sky),
                    center_x=NATIVE_W / 2,
                    center_y=NATIVE_H / 2,
                )
            )
        rows, columns = len(stage.cells), len(stage.cells[0]) if stage.cells else 0
        self._backdrop_reference = project(columns / 2, rows / 2, 0.0)
        """The camera centre at which every backdrop layer sits centred on the screen."""

    # --- per-frame -------------------------------------------------------------------------

    def sync(
        self,
        entities: Sequence[WorldEntity],
        frame: int = 0,
        looks: Mapping[int, FighterLook] | None = None,
    ) -> None:
        """Update sprite positions, textures and draw order from the current world state.

        ``frame`` is the match frame; it only drives the invincibility blink. ``looks`` gives
        the pose, flash and shake of entities by ``entity_id``; the rest stand normally.
        """
        self._drop_missing({entity.entity_id for entity in entities})
        blink_off = (frame // INVINCIBLE_BLINK_FRAMES) % 2 == 1
        items: list[DynamicItem] = []
        for entity in entities:
            look = DEFAULT_LOOK if looks is None else looks.get(entity.entity_id, DEFAULT_LOOK)
            hidden = look.hidden or (entity.invincible and blink_off)
            items.append(self._sync_body(entity, look, hidden=hidden))
            for item in (self._sync_shadow(entity), self._sync_revival_platform(entity)):
                if item is not None:
                    items.append(item)

        order = self.sorter.draw_order(items)
        if order != self._order:
            self._order = order
            self._apply_order(order)

    def _load_backdrop(self) -> list[tuple[float, list[arcade.Sprite]]]:
        """Load the stage's parallax layers: each repeats three times across."""
        layers = []
        for layer in self.stage.backgrounds:
            path = STAGES_DIR / self.stage.id / layer.image
            try:
                image = Image.open(path).convert("RGBA")
            except OSError as error:
                LOG.error("background %s not loaded: %s", path, error)
                continue
            texture = arcade.Texture(image, hash=f"backdrop:{self.stage.id}:{layer.image}")
            copies = [arcade.Sprite(texture) for _ in range(BACKDROP_COPIES)]
            for sprite in copies:
                self._background.append(sprite)
            layers.append((layer.parallax, copies))
        return layers

    def _place_backdrop(self, camera_centre: tuple[int, int]) -> None:
        """Scroll each layer by its share of how far the camera is from the stage centre."""
        reference_x, reference_y = self._backdrop_reference
        for parallax, copies in self._layers:
            width = copies[0].texture.width
            shift_x = -round((camera_centre[0] - reference_x) * parallax)
            shift_y = -round((camera_centre[1] - reference_y) * parallax)
            # Wrap so one copy always covers the screen, with its neighbours either side.
            centre_x = NATIVE_W / 2 + (shift_x % width) - width / 2
            for index, sprite in enumerate(copies):
                sprite.position = (centre_x + (index - 1) * width, NATIVE_H / 2 + shift_y)

    def draw(
        self, camera_centre: tuple[int, int], overlays: Sequence[Overlay] = (), zoom: int = 1
    ) -> None:
        """Draw the background, then the sorted world as seen from ``camera_centre``.

        Call inside ``pixel_buffer.drawing()``. ``camera_centre`` is in whole world pixels.
        ``overlays`` are drawn last and in order, in the same world pixel space (the VFX
        layer, debug overlays).
        """
        self._place_backdrop(camera_centre)
        self._background.draw(pixelated=True)
        self.camera.position = camera_centre
        self.camera.zoom = zoom
        with self.camera.activate():
            self.sprites.draw(pixelated=True)
            if OCCLUDED_FIGHTER_ALPHA > 0:
                self._ghosts.draw(pixelated=True)
            for overlay in overlays:
                overlay.draw()

    # --- statics ---------------------------------------------------------------------------

    def _make_static_sprite(self, item: StaticItem) -> _RankedSprite:
        light = (item.cx + item.cy) % 2 == 0
        if item.kind is StaticKind.COLUMN:
            cell = self.stage.cell(item.cx, item.cy)
            assert cell is not None
            side_px = snap((cell.top - self.stage.underside) * Z_PX)
            tile = cell.tile
            texture = self._texture(
                ("tile", tile, light, side_px), lambda: self._tile_image(tile, light, side_px)
            )
        elif item.kind is StaticKind.DECAL:
            texture = self._texture(("platform_shadow",), art.build_platform_shadow)
        else:
            texture = self._texture(("deck", light), lambda: self._deck_image(light))

        centre_x, back_y = project(item.cx, item.cy, item.top)
        sprite = _RankedSprite(
            texture, center_x=snap(centre_x), center_y=snap(back_y) - texture.height / 2
        )
        self.sprites.append(sprite)
        return sprite

    def _tile_image(self, tile: str, light: bool, side_px: int) -> Image.Image:
        rendered = None if self.stage_art is None else self.stage_art.tile(tile, light, side_px)
        return rendered or art.build_tile(tile, light, side_px)

    def _deck_image(self, light: bool) -> Image.Image:
        rendered = None if self.stage_art is None else self.stage_art.deck(light)
        return rendered or art.build_deck(light)

    # --- dynamics --------------------------------------------------------------------------

    def _part(self, entity: WorldEntity, part: Part, texture: arcade.Texture) -> _RankedSprite:
        """Return the entity's sprite for ``part``, creating it on first use."""
        key = (entity.entity_id, part)
        sprite = self._parts.get(key)
        if sprite is None:
            sprite = _RankedSprite(texture)
            self._parts[key] = sprite
            self.sprites.append(sprite)
            self._order = None
        elif sprite.texture is not texture:
            sprite.texture = texture
        return sprite

    def _sync_body(self, entity: WorldEntity, look: FighterLook, hidden: bool) -> DynamicItem:
        pos = entity.pos
        feet_x, feet_y = (snap(value) for value in project(pos.x, pos.y, pos.z))
        bank = self.banks.get(look.character) if look.sprite is not None else None
        if bank is not None and look.sprite is not None:
            # A packed frame: placed by its feet pivot; its rect bounds exactly what it draws.
            tint = Tint.FLASH if look.flash else Tint.DIM if look.dim else Tint.NORMAL
            choice = look.sprite
            texture = bank.texture(choice.anim, choice.pose, entity.facing, look.costume, tint)
            frame = bank.frame(choice.anim, choice.pose, entity.facing)
            left = feet_x + look.offset_x - frame.pivot_x
            top = feet_y + frame.pivot_y
            rect = ScreenRect(left, top - frame.height, left + frame.width, top)
            position = (left + frame.width / 2, top - frame.height / 2)
        else:
            lying = look.pose is Pose.DOWN
            turns = look.quarter_turns if look.pose is Pose.TUMBLE else 0
            texture = self._texture(
                ("fighter", entity.color_index, entity.facing, lying, turns, look.flash, look.dim),
                lambda: art.build_fighter(
                    entity.color_index, entity.facing, lying, turns, look.flash, look.dim
                ),
            )
            position = (
                feet_x + look.offset_x + art.FIGHTER_CANVAS / 2 - art.FIGHTER_PIVOT_X,
                feet_y + art.FIGHTER_CANVAS / 2 - art.FIGHTER_PIVOT_FROM_BOTTOM,
            )
            rect = ScreenRect(
                feet_x - BODY_RECT_HALF_WIDTH,
                feet_y,
                feet_x + BODY_RECT_HALF_WIDTH,
                feet_y + art.BODY_HEIGHT,
            )
        sprite = self._part(entity, Part.BODY, texture)
        sprite.position = position
        sprite.visible = not hidden

        item = DynamicItem(
            item_id=_item_id(entity.entity_id, Part.BODY),
            rank=Part.BODY,
            x=pos.x,
            y=pos.y,
            z=pos.z,
            height=BODY_HEIGHT_UNITS,
            rect=rect,
        )

        ghost = self._ghost_of.get(entity.entity_id)
        if ghost is None:
            ghost = arcade.Sprite(texture)
            ghost.alpha = OCCLUDED_FIGHTER_ALPHA
            self._ghost_of[entity.entity_id] = ghost
            self._ghosts.append(ghost)
        elif ghost.texture is not texture:
            ghost.texture = texture
        ghost.position = sprite.position
        # Only while the stage hides part of the fighter, so fighters overlapping each other
        # in the open are not tinted by one another.
        ghost.visible = not hidden and self.sorter.is_hidden_by_stage(item)
        return item

    def _sync_shadow(self, entity: WorldEntity) -> DynamicItem | None:
        sprite = self._part(
            entity, Part.SHADOW, self._shadow_texture(entity.color_index, 0, FULL_MASK)
        )
        pos = entity.pos
        surface = self.stage.support_below(pos.x, pos.y, pos.z)
        sprite.visible = surface is not None
        if surface is None:
            return None

        centre_x, centre_y = (snap(value) for value in project(pos.x, pos.y, surface))
        variant = art.shadow_variant_index(pos.z - surface)
        mask = shadow_mask(self.stage, centre_x, centre_y, surface)
        texture = self._shadow_texture(entity.color_index, variant, mask)
        if sprite.texture is not texture:
            sprite.texture = texture
        sprite.position = (centre_x, centre_y)
        half_w, half_h = art.SHADOW_WIDTH / 2, art.SHADOW_HEIGHT / 2
        return DynamicItem(
            item_id=_item_id(entity.entity_id, Part.SHADOW),
            rank=Part.SHADOW,
            x=pos.x,
            y=pos.y,
            z=surface,
            height=0.0,
            rect=ScreenRect(
                centre_x - half_w, centre_y - half_h, centre_x + half_w, centre_y + half_h
            ),
        )

    def _sync_revival_platform(self, entity: WorldEntity) -> DynamicItem | None:
        texture = self._texture(("revival_platform",), art.build_revival_platform)
        sprite = self._part(entity, Part.REVIVAL_PLATFORM, texture)
        sprite.visible = entity.on_revival_platform
        if not entity.on_revival_platform:
            return None

        pos = entity.pos
        feet_x, feet_y = (snap(value) for value in project(pos.x, pos.y, pos.z))
        # The feet stand at the middle of the platform's top diamond.
        top = feet_y + TILE_H // 2
        sprite.position = (feet_x, top - texture.height / 2)
        return DynamicItem(
            item_id=_item_id(entity.entity_id, Part.REVIVAL_PLATFORM),
            rank=Part.REVIVAL_PLATFORM,
            x=pos.x,
            y=pos.y,
            z=pos.z,
            height=0.0,
            rect=ScreenRect(
                feet_x - texture.width / 2, top - texture.height, feet_x + texture.width / 2, top
            ),
        )

    def _drop_missing(self, alive: set[int]) -> None:
        for key in [key for key in self._parts if key[0] not in alive]:
            self._parts.pop(key).remove_from_sprite_lists()
            self._order = None
        for entity_id in [key for key in self._ghost_of if key not in alive]:
            self._ghost_of.pop(entity_id).remove_from_sprite_lists()

    def _apply_order(self, order: Sequence[DrawEntry]) -> None:
        for sprite in self._parts.values():
            sprite.draw_rank = HIDDEN_DRAW_RANK
        for rank, entry in enumerate(order):
            if entry.is_static:
                self._static_sprites[entry.index].draw_rank = rank
            else:
                entity_id, part = divmod(entry.index, len(Part))
                self._parts[(entity_id, Part(part))].draw_rank = rank
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


def _item_id(entity_id: int, part: Part) -> int:
    """Return the depth sorter id of one of an entity's sprites."""
    return entity_id * len(Part) + part
