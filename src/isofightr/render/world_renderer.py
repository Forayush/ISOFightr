"""Draws a stage and everything on it into the native buffer, correctly depth-sorted.

Implements "Render layers", "Depth sorting rules" and "Shadows and readability" in the plan
note "03 - Isometric World and Rendering". All world sprites (tiles, platform decks, shadows,
fighters) live in one ``SpriteList`` whose order comes from :class:`DepthSorter` every frame,
so the whole world is a single batched draw call (decision D-019).

Reads state only: it never changes what it draws.
"""

import logging
import math
from collections.abc import Callable, Mapping, Sequence
from enum import IntEnum
from typing import Protocol

import arcade
from arcade.types import LBWH, LRBT
from PIL import Image

from isofightr.config import (
    BACKDROP_FRAME_TICKS,
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
from isofightr.render.ambient import build_mote, covers, motes
from isofightr.render.camera import snap
from isofightr.render.depth import (
    PLATFORM_ITEM_BASE,
    DepthSorter,
    DrawEntry,
    DynamicItem,
    ScreenRect,
    StaticItem,
    StaticKind,
    dynamic_goes_first,
    moving_blocks,
)
from isofightr.render.depth_cues import Cue, Place, cue
from isofightr.render.fighter_look import DEFAULT_LOOK, FighterLook, Pose
from isofightr.render.ground_items import GroundItem, platform_shadows
from isofightr.render.iso import project
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.props import (
    PROP_ITEM_BASE,
    PlacedProp,
    ground_items,
    ground_props,
    placed_props,
)
from isofightr.render.shadows import FULL_MASK, apply_mask, shadow_mask
from isofightr.render.sprite_bank import SpriteBank, Tint
from isofightr.render.stage_art import DECK_TILE, Edges, StageArt, cell_edges, tile_variant
from isofightr.settings import DEPTH_OFF, DEPTH_STANDARD, DEPTH_STRONG
from isofightr.sim.input_frame import Dir8
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import BackgroundLayer, Stage

LOG = logging.getLogger(__name__)
HIDDEN_DRAW_RANK = -1
GROUND_ITEM_BASE = 1 << 20
"""Depth sorter ids of ground items start here, far above any fighter part's id."""
BACKDROP_COPIES = 3
BODY_RECT_HALF_WIDTH = art.BODY_HALF_WIDTH + 3
"""Half-width of everything the fighter sprite draws: the body plus the arrow tips."""
BODY_HEIGHT_UNITS = art.BODY_HEIGHT / Z_PX


class Part(IntEnum):
    """The sprites one entity can own. The value is also the tie-break rank among items at
    the same place: flat things on the ground are drawn before the body standing on them."""

    GRID = 0
    """The "Strong" depth aid's grid on the plane under a fighter that is off the stage."""
    SHADOW = 1
    """The marker: shadow and ring on a surface, or the dashed ring where there is none."""
    REVIVAL_PLATFORM = 2
    LINE = 3
    """The dotted line from the marker to the feet."""
    BODY = 4


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
        self.calm = False
        """The "reduce flashing" setting: ambient sprites then neither blink nor turn."""
        self.depth_aids = DEPTH_STANDARD
        """The "depth aids" setting (decision D-065): off draws the world as it was before
        (no marker over the void, a faint copy of a hidden fighter)."""
        self._tick = 0
        """The frame of the last :meth:`sync`: it drives everything that moves by itself."""
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
        self._ground: dict[int, _RankedSprite] = {}
        """Sprites of ground items (projectile shadows, decals), by item id."""
        self._ground_images: dict[object, Image.Image] = {}
        self._ground_masks: dict[tuple[float, float, float, int, int], bytes] = {}
        """The clipping of things lying on solid ground, by place and size: the ground does
        not move, so it is worked out once per place."""
        self._order: list[DrawEntry] | None = None

        # Props (decision D-063): decorations from the tileset, sorted like everything else.
        self.props: list[PlacedProp] = placed_props(stage, tileset)
        self._prop_items = [prop.item for prop in self.props]
        self._ground_props = ground_props(stage, tileset)
        self._prop_frames: list[list[arcade.Texture]] = []
        self._prop_sprites: list[_RankedSprite] = []
        for prop in self.props:
            frames = self._prop_textures(prop)
            rect = prop.rect
            sprite = _RankedSprite(
                frames[0],
                center_x=(rect.left + rect.right) / 2,
                center_y=(rect.bottom + rect.top) / 2,
            )
            self._prop_frames.append(frames)
            self._prop_sprites.append(sprite)
            self.sprites.append(sprite)

        # The cells of platforms that move (decision D-063): dynamic blocks, placed every
        # frame from where the match says the platform is.
        self.live: Stage = stage
        self._block_items: list[DynamicItem] = []
        """The stage on the frame being drawn: ``stage``, with its platforms where they are."""
        self._blocks: dict[int, _RankedSprite] = {}
        for block in moving_blocks(stage, stage):
            cell = block.item_id % 2
            texture = self._texture(
                ("deck", cell == 0, cell), lambda cell=cell: self._deck_image(cell == 0, cell)
            )
            sprite = _RankedSprite(texture)
            self._blocks[block.item_id] = sprite
            self.sprites.append(sprite)

        # Ambient sprites: some behind the world (screen space), some in front of it.
        self._motes_back: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._motes_front: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._mote_sprites: list[arcade.Sprite] = []
        self._body_rects: list[ScreenRect] = []
        ambient = stage.ambient
        if ambient is not None:
            for index in range(ambient.count):
                sprite = arcade.Sprite(self._mote_texture(0))
                front = index >= ambient.count - ambient.front
                (self._motes_front if front else self._motes_back).append(sprite)
                self._mote_sprites.append(sprite)

        # "X-ray" copies of fighters that the stage partly hides, drawn faintly over the
        # finished world. Where the fighter is in plain view the copy changes nothing you can
        # see (the same pixels blended over themselves, at most one 8-bit level off); behind
        # a platform or the island it shows.
        self._ghosts: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._ghost_of: dict[int, arcade.Sprite] = {}
        self._outlines: dict[tuple[arcade.Texture, int], arcade.Texture] = {}
        self._alphas: dict[arcade.Texture, tuple[int, int, bytes]] = {}
        """Which pixels of a texture are solid (width, height, one byte each), for
        :meth:`_covers`."""

        # A marker or a height line that the stage is in front of is drawn once more over
        # the finished world, thinned: it is never hidden (decision D-065).
        self._covered: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._covered_of: dict[tuple[int, Part], arcade.Sprite] = {}

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
        ground: Sequence[GroundItem] = (),
        live: Stage | None = None,
    ) -> None:
        """Update sprite positions, textures and draw order from the current world state.

        ``frame`` is the match frame; it only drives the invincibility blink. ``looks`` gives
        the pose, flash and shake of entities by ``entity_id``; the rest stand normally.
        ``ground`` are the flat items lying on the stage this frame (projectile shadows,
        decals): they are clipped to their surface and sorted with everything else.
        ``live`` is the stage on this frame (``match.stage``) when its platforms move;
        without it they are drawn where they rest.
        """
        self._drop_missing({entity.entity_id for entity in entities})
        self._tick = frame
        self.live = live if live is not None else self.stage
        blink_off = (frame // INVINCIBLE_BLINK_FRAMES) % 2 == 1
        self._block_items = list(moving_blocks(self.stage, self.live))
        items: list[DynamicItem] = []
        self._body_rects = []
        for entity in entities:
            look = DEFAULT_LOOK if looks is None else looks.get(entity.entity_id, DEFAULT_LOOK)
            hidden = look.hidden or (entity.invincible and blink_off)
            body = self._sync_body(entity, look, hidden=hidden)
            items.append(body)
            if not hidden:
                self._body_rects.append(body.rect)
                if self._behind_a_prop(body, self._parts[(entity.entity_id, Part.BODY)]):
                    self._ghost_of[entity.entity_id].visible = True
            items.extend(self._sync_marker(entity, hidden))
            platform = self._sync_revival_platform(entity)
            if platform is not None:
                items.append(platform)

        for prop, sprite, frames in zip(
            self.props, self._prop_sprites, self._prop_frames, strict=True
        ):
            texture = frames[prop.frame(frame)]
            if sprite.texture is not texture:
                sprite.texture = texture
        items.extend(self._prop_items)
        for block in self._block_items:
            rect = block.rect
            self._blocks[block.item_id].position = (
                (rect.left + rect.right) / 2,
                (rect.bottom + rect.top) / 2,
            )
            items.append(block)

        if self._ground_props and self.stage_art is not None:
            # The stage's own decals (glowing runes, markings) lie under everything else.
            flat = ground_items(self._ground_props, frame, self.stage_art.prop, self.calm)
            ground = [*flat, *ground]
        if self.stage.has_mechanics:
            ground = [*platform_shadows(self.stage, self.live), *ground]
        self._drop_ground({item.item_id for item in ground})
        items.extend(self._sync_ground(item) for item in ground)

        order = self.sorter.draw_order(items)
        if order != self._order:
            self._order = order
            self._apply_order(order)

    def _load_backdrop(
        self,
    ) -> list[tuple[BackgroundLayer, list[arcade.Texture], list[arcade.Sprite]]]:
        """Load the stage's parallax layers: each repeats three times across. A layer with
        ``frames`` holds that many pictures stacked top to bottom."""
        layers = []
        for layer in self.stage.backgrounds:
            path = STAGES_DIR / self.stage.id / layer.image
            try:
                image = Image.open(path).convert("RGBA")
            except OSError as error:
                LOG.error("background %s not loaded: %s", path, error)
                continue
            tall = image.height // layer.frames
            textures = [
                arcade.Texture(
                    image.crop((0, index * tall, image.width, (index + 1) * tall)),
                    hash=f"backdrop:{self.stage.id}:{layer.image}:{index}",
                )
                for index in range(layer.frames)
            ]
            copies = [arcade.Sprite(textures[0]) for _ in range(BACKDROP_COPIES)]
            for sprite in copies:
                self._background.append(sprite)
            layers.append((layer, textures, copies))
        return layers

    def _place_backdrop(self, camera_centre: tuple[int, int]) -> None:
        """Scroll each layer by its share of how far the camera is from the stage centre,
        plus its own drift, and show its frame for this tick."""
        reference_x, reference_y = self._backdrop_reference
        for layer, textures, copies in self._layers:
            parallax = layer.parallax
            texture = textures[
                (self._tick // (layer.frame_ticks or BACKDROP_FRAME_TICKS)) % len(textures)
            ]
            for sprite in copies:
                if sprite.texture is not texture:
                    sprite.texture = texture
            width = copies[0].texture.width
            shift_x = -round((camera_centre[0] - reference_x) * parallax)
            shift_x -= round(layer.scroll * self._tick)
            shift_y = -round((camera_centre[1] - reference_y) * parallax)
            # Wrap so one copy always covers the screen, with its neighbours either side.
            centre_x = NATIVE_W / 2 + (shift_x % width) - width / 2
            for index, sprite in enumerate(copies):
                sprite.position = (centre_x + (index - 1) * width, NATIVE_H / 2 + shift_y)

    def draw(
        self,
        camera_centre: tuple[int, int],
        overlays: Sequence[Overlay] = (),
        zoom: int = 1,
        background: bool = True,
    ) -> None:
        """Draw the background, then the sorted world as seen from ``camera_centre``.

        Call inside ``pixel_buffer.drawing()``. ``camera_centre`` is in whole world pixels.
        ``overlays`` are drawn last and in order, in the same world pixel space (the VFX
        layer, debug overlays). ``background=False`` leaves out the stage's backdrop, for a
        world drawn over something else (a menu's island).
        """
        if background:
            self._place_backdrop(camera_centre)
            self._background.draw(pixelated=True)
        if self._mote_sprites:
            self._place_motes(camera_centre, zoom)
            self._motes_back.draw(pixelated=True)
        self.camera.position = camera_centre
        self.camera.zoom = zoom
        with self.camera.activate():
            self.sprites.draw(pixelated=True)
            self._covered.draw(pixelated=True)
            if OCCLUDED_FIGHTER_ALPHA > 0:
                self._ghosts.draw(pixelated=True)
            if self._mote_sprites:
                self._motes_front.draw(pixelated=True)
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
            variant = self._variant(tile, item.cx, item.cy)
            edges = cell_edges(self.stage, item.cx, item.cy)
            texture = self._texture(
                ("tile", tile, light, side_px, variant, edges),
                lambda: self._tile_image(tile, light, side_px, variant, edges),
            )
        elif item.kind is StaticKind.DECAL:
            texture = self._texture(("platform_shadow",), art.build_platform_shadow)
        elif item.kind is StaticKind.UNDER:
            side_px = snap((item.top - item.bottom) * Z_PX)
            under = self.stage.underside_art
            tile = "under" if under is None else under.tile
            variant = self._variant(tile, item.cx + 1, item.cy + 2)
            texture = self._texture(
                ("under", tile, side_px, variant), lambda: self._under_image(tile, side_px, variant)
            )
        else:
            variant = self._variant(DECK_TILE, item.cx, item.cy)
            texture = self._texture(
                ("deck", light, variant), lambda: self._deck_image(light, variant)
            )

        centre_x, back_y = project(item.cx, item.cy, item.top)
        sprite = _RankedSprite(
            texture, center_x=snap(centre_x), center_y=snap(back_y) - texture.height / 2
        )
        self.sprites.append(sprite)
        return sprite

    def _variant(self, tile: str, cx: int, cy: int) -> int:
        """Return which of a tile's images a cell shows (0 without a rendered tileset)."""
        if self.stage_art is None:
            return 0
        return tile_variant(self.stage_art.tileset, tile, cx, cy)

    def _tile_image(
        self, tile: str, light: bool, side_px: int, variant: int, edges: Edges
    ) -> Image.Image:
        rendered = None
        if self.stage_art is not None:
            rendered = self.stage_art.tile(tile, light, side_px, variant, edges)
        return rendered or art.build_tile(tile, light, side_px)

    def _under_image(self, tile: str, side_px: int, variant: int) -> Image.Image:
        rendered = None if self.stage_art is None else self.stage_art.under(tile, side_px, variant)
        return rendered or art.build_tile(tile, False, side_px)

    def _deck_image(self, light: bool, variant: int = 0) -> Image.Image:
        rendered = None if self.stage_art is None else self.stage_art.deck(light, variant)
        return rendered or art.build_deck(light)

    # --- props and ambience ----------------------------------------------------------------

    def _prop_textures(self, prop: PlacedProp) -> list[arcade.Texture]:
        """Return a prop's frames as textures (shared by every prop of that name)."""
        stage_art = self.stage_art
        assert stage_art is not None
        name = prop.art.name
        return [
            self._texture(("prop", name, index), lambda index=index: stage_art.prop(name, index))
            for index in range(prop.art.frames)
        ]

    def _behind_a_prop(self, body: DynamicItem, sprite: arcade.Sprite) -> bool:
        """Return whether a prop is drawn over part of a fighter (who is then shown like one
        behind the stage, decisions D-025 and D-065). With the depth aids on, the prop's
        solid pixels must really cover the fighter's."""
        exact = self.depth_aids != DEPTH_OFF
        return any(
            item.rect.overlaps(body.rect)
            and dynamic_goes_first(body, item)
            and (not exact or self._covers(prop, sprite))
            for item, prop in zip(self._prop_items, self._prop_sprites, strict=True)
        )

    def _mote_texture(self, frame: int) -> arcade.Texture:
        ambient = self.stage.ambient
        assert ambient is not None
        kind = ambient.kind
        return self._texture(("mote", kind, frame), lambda: build_mote(kind, frame))

    def _place_motes(self, camera_centre: tuple[int, int], zoom: int) -> None:
        """Put every ambient sprite where it is this tick; the ones in front are placed in
        world pixels (they are drawn with the world) and hidden where they would cover a
        fighter."""
        centre_x, centre_y = camera_centre
        on_screen = [
            (
                (rect.left - centre_x) * zoom + NATIVE_W / 2,
                (rect.bottom - centre_y) * zoom + NATIVE_H / 2,
                (rect.right - centre_x) * zoom + NATIVE_W / 2,
                (rect.top - centre_y) * zoom + NATIVE_H / 2,
            )
            for rect in self._body_rects
        ]
        found = motes(self.stage.ambient, self._tick, camera_centre, self.calm)
        for mote, sprite in zip(found, self._mote_sprites, strict=True):
            texture = self._mote_texture(mote.frame)
            if sprite.texture is not texture:
                sprite.texture = texture
            if mote.front:
                sprite.position = (
                    centre_x + (mote.x - NATIVE_W / 2) / zoom,
                    centre_y + (mote.y - NATIVE_H / 2) / zoom,
                )
                sprite.visible = mote.visible and not covers(mote, on_screen)
            else:
                sprite.position = (mote.x, mote.y)
                sprite.visible = mote.visible

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

        # What shows of a fighter the stage hides: its outline in the player's colour, or
        # with the depth aids off the faint copy there always was (decision D-025).
        outlined = self.depth_aids != DEPTH_OFF
        shown = self._outline(texture, entity.color_index) if outlined else texture
        ghost = self._ghost_of.get(entity.entity_id)
        if ghost is None:
            ghost = arcade.Sprite(shown)
            self._ghost_of[entity.entity_id] = ghost
            self._ghosts.append(ghost)
        elif ghost.texture is not shown:
            ghost.texture = shown
        ghost.alpha = 255 if outlined else OCCLUDED_FIGHTER_ALPHA
        ghost.position = sprite.position
        # Only while the stage hides part of the fighter, so fighters overlapping each other
        # in the open are not tinted by one another. The faint copy changes nothing where the
        # fighter is in plain view, so overlapping rectangles were test enough for it; an
        # outline would show there, so it asks whether solid pixels really cover the fighter.
        if hidden:
            ghost.visible = False
        elif outlined:
            ghost.visible = any(
                self._covers(self._static_sprites[index], sprite)
                for index in self.sorter.statics_in_front(item)
            )
        else:
            ghost.visible = self.sorter.is_hidden_by_stage(item)
        return item

    def _alpha(self, texture: arcade.Texture) -> tuple[int, int, bytes]:
        found = self._alphas.get(texture)
        if found is None:
            image = texture.image
            found = (image.width, image.height, image.getchannel("A").tobytes())
            self._alphas[texture] = found
        return found

    def _covers(self, front: arcade.Sprite, behind: arcade.Sprite, least: int = 128) -> bool:
        """Return whether a solid pixel of ``front`` lies over a pixel of ``behind`` whose
        alpha is ``least`` or more (every pixel is looked at: a ring is one pixel thin)."""
        front_w, front_h, front_alpha = self._alpha(front.texture)
        back_w, back_h, back_alpha = self._alpha(behind.texture)
        front_left = round(front.center_x - front_w / 2)
        front_top = round(front.center_y + front_h / 2)
        back_left = round(behind.center_x - back_w / 2)
        back_top = round(behind.center_y + back_h / 2)
        left, right = max(front_left, back_left), min(front_left + front_w, back_left + back_w)
        top, bottom = min(front_top, back_top), max(front_top - front_h, back_top - back_h)
        for y in range(top - 1, bottom - 1, -1):
            front_row = (front_top - 1 - y) * front_w - front_left
            back_row = (back_top - 1 - y) * back_w - back_left
            for x in range(left, right):
                if back_alpha[back_row + x] >= least and front_alpha[front_row + x] >= 128:
                    return True
        return False

    def _sync_marker(self, entity: WorldEntity, hidden: bool) -> list[DynamicItem]:
        """Place what says where an entity is (decision D-065): the shadow and ring on the
        surface below it; where there is no surface, a dashed ring on the stage's reference
        plane (or on the ground above, under the island); a dotted line up to the feet when
        they are far from the marker; and, with the "strong" setting, a grid on the plane
        around a fighter that is off the stage. With the setting off, or on a revival
        platform, only the shadow on a surface is drawn, as it always was."""
        color = entity.color_index
        sprite = self._part(entity, Part.SHADOW, self._shadow_texture(color, 0, FULL_MASK))
        pos = entity.pos
        aided = self.depth_aids != DEPTH_OFF and not entity.on_revival_platform
        if aided:
            found = cue(self.live, pos.x, pos.y, pos.z)
        else:
            surface = self.live.support_below(pos.x, pos.y, pos.z)
            self._hide_cues(entity)
            sprite.visible = surface is not None
            if surface is None:
                return []
            found = Cue(Place.SURFACE, surface, pos.z - surface, False, 0.0)

        centre_x, centre_y = (snap(value) for value in project(pos.x, pos.y, found.marker_z))
        if found.dashed:
            # On the plane over the void the ring is whole; on the ground above a fighter
            # that is under the island it is clipped to that ground like any shadow.
            mask = FULL_MASK
            if found.place is Place.UNDER:
                mask = shadow_mask(self.live, centre_x, centre_y, found.marker_z)
            texture = self._texture(
                ("void_ring", color, mask), lambda: apply_mask(art.build_void_ring(color), mask)
            )
        else:
            variant = art.shadow_variant_index(found.height)
            mask = shadow_mask(self.live, centre_x, centre_y, found.marker_z)
            texture = self._shadow_texture(color, variant, mask)
        if sprite.texture is not texture:
            sprite.texture = texture
        sprite.position = (centre_x, centre_y)
        sprite.visible = True
        half_w, half_h = art.SHADOW_WIDTH / 2, art.SHADOW_HEIGHT / 2
        marker = DynamicItem(
            item_id=_item_id(entity.entity_id, Part.SHADOW),
            rank=Part.SHADOW,
            x=pos.x,
            y=pos.y,
            z=found.marker_z,
            height=0.0,
            rect=ScreenRect(
                centre_x - half_w, centre_y - half_h, centre_x + half_w, centre_y + half_h
            ),
        )
        items = [marker]
        if not aided:
            return items

        shows = not hidden
        covered = shows and self._cue_covered(marker, sprite)
        over = self._covered_part(entity, Part.SHADOW)
        over.visible = covered
        if covered:
            over.texture = self._texture(
                ("ring_over", color, found.dashed),
                lambda: art.dithered(art.build_ring(color, found.dashed)),
            )
            over.position = (centre_x, centre_y)
        line = self._sync_line(entity, found, centre_x, shows)
        if line is not None:
            items.append(line)
        grid = self._sync_grid(entity, found, shows)
        if grid is not None:
            items.append(grid)
        return items

    def _sync_line(
        self, entity: WorldEntity, found: Cue, centre_x: float, shows: bool
    ) -> DynamicItem | None:
        """Place an entity's height line: among the world's sprites when nothing solid is in
        its way, and (thinner) over the world where the stage is in front of it."""
        color = entity.color_index
        pos = entity.pos
        sprite = self._part(entity, Part.LINE, self._line_texture(color, 1, False))
        over = self._covered_part(entity, Part.LINE)
        pixels = round(found.line * Z_PX)
        if pixels <= 0 or not shows:
            sprite.visible = over.visible = False
            return None
        low_z = min(found.marker_z, pos.z)
        bottom = snap(project(pos.x, pos.y, low_z)[1])
        position = (centre_x + 0.5, bottom + pixels / 2)
        item = DynamicItem(
            item_id=_item_id(entity.entity_id, Part.LINE),
            rank=Part.LINE,
            x=pos.x,
            y=pos.y,
            z=low_z,
            height=found.line,
            rect=ScreenRect(centre_x, bottom, centre_x + 1, bottom + pixels),
        )
        sprite.visible = not found.through_solid
        if sprite.visible:
            sprite.texture = self._line_texture(color, pixels, False)
            sprite.position = position
        over.visible = found.through_solid or self._cue_covered(item, sprite)
        if over.visible:
            over.texture = self._line_texture(color, pixels, True)
            over.position = position
        return None if found.through_solid else item

    def _sync_grid(self, entity: WorldEntity, found: Cue, shows: bool) -> DynamicItem | None:
        """Place the "strong" setting's grid on the reference plane around an entity that is
        over the void: the outlines of the empty cells near it."""
        sprite = self._parts.get((entity.entity_id, Part.GRID))
        wanted = shows and self.depth_aids == DEPTH_STRONG and found.place is Place.VOID
        if not wanted:
            if sprite is not None:
                sprite.visible = False
            return None
        pos = entity.pos
        reach = art.PLANE_GRID_RADIUS
        cell_x, cell_y = math.floor(pos.x), math.floor(pos.y)
        void = tuple(
            tuple(
                self.stage.cell(cell_x + column, cell_y + row) is None
                for column in range(-reach, reach + 1)
            )
            for row in range(-reach, reach + 1)
        )
        texture = self._texture(("plane_grid", void), lambda: art.build_plane_grid(void))
        sprite = self._part(entity, Part.GRID, texture)
        # The picture's top corner is the far corner of the cell ``reach`` back on both axes.
        top_x, top_y = project(cell_x - reach, cell_y - reach, found.marker_z)
        sprite.position = (snap(top_x), snap(top_y) - texture.height / 2)
        sprite.visible = True
        return DynamicItem(
            item_id=_item_id(entity.entity_id, Part.GRID),
            rank=Part.GRID,
            x=cell_x + 0.5,
            y=cell_y + 0.5,
            z=found.marker_z,
            height=0.0,
            rect=ScreenRect(
                snap(top_x) - texture.width / 2,
                snap(top_y) - texture.height,
                snap(top_x) + texture.width / 2,
                snap(top_y),
            ),
        )

    def _cue_covered(self, item: DynamicItem, sprite: arcade.Sprite) -> bool:
        """Return whether solid pixels of the stage, a prop or a moving platform's cell are
        drawn over any pixel of a cue (a marker or a height line)."""
        if any(
            self._covers(self._static_sprites[index], sprite, 1)
            for index in self.sorter.statics_in_front(item)
        ):
            return True
        others = [
            *zip(self._prop_items, self._prop_sprites, strict=True),
            *((block, self._blocks[block.item_id]) for block in self._block_items),
        ]
        return any(
            other.rect.overlaps(item.rect)
            and dynamic_goes_first(item, other)
            and self._covers(front, sprite, 1)
            for other, front in others
        )

    def _hide_cues(self, entity: WorldEntity) -> None:
        """Hide an entity's line, grid and covered copies (the depth aids are off for it)."""
        for part in (Part.LINE, Part.GRID):
            sprite = self._parts.get((entity.entity_id, part))
            if sprite is not None:
                sprite.visible = False
        for part in (Part.SHADOW, Part.LINE):
            over = self._covered_of.get((entity.entity_id, part))
            if over is not None:
                over.visible = False

    def _covered_part(self, entity: WorldEntity, part: Part) -> arcade.Sprite:
        """Return the sprite that redraws one of an entity's cues over the world."""
        key = (entity.entity_id, part)
        sprite = self._covered_of.get(key)
        if sprite is None:
            sprite = arcade.Sprite(self._line_texture(entity.color_index, 1, True))
            sprite.visible = False
            self._covered_of[key] = sprite
            self._covered.append(sprite)
        return sprite

    def _line_texture(self, player_index: int, pixels: int, covered: bool) -> arcade.Texture:
        step = art.COVERED_LINE_STEP if covered else art.HEIGHT_LINE_STEP
        return self._texture(
            ("height_line", player_index, pixels, covered),
            lambda: art.build_height_line(player_index, pixels, step),
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

    def _sync_ground(self, item: GroundItem) -> DynamicItem:
        """Place a ground item's sprite, clipped to its surface, and describe it to the sorter
        with the exact rect of what it draws."""
        image = self._ground_images.get(item.key)
        if image is None:
            image = self._ground_images[item.key] = item.build()
        width, height = image.size
        screen_x, screen_y = project(item.x, item.y, item.surface)
        centre_x = snap(screen_x) + (width % 2) / 2
        centre_y = snap(screen_y) + (height % 2) / 2
        if item.on_ground:
            place = (centre_x, centre_y, item.surface, width, height)
            found = self._ground_masks.get(place)
            if found is None:
                found = shadow_mask(self.stage, centre_x, centre_y, item.surface, width, height)
                self._ground_masks[place] = found
            mask = found
        else:
            mask = shadow_mask(self.live, centre_x, centre_y, item.surface, width, height)
        texture = self._texture(("ground", item.key, mask), lambda: apply_mask(image, mask))
        sprite = self._ground.get(item.item_id)
        if sprite is None:
            sprite = _RankedSprite(texture)
            self._ground[item.item_id] = sprite
            self.sprites.append(sprite)
            self._order = None
        elif sprite.texture is not texture:
            sprite.texture = texture
        sprite.position = (centre_x, centre_y)
        return DynamicItem(
            item_id=GROUND_ITEM_BASE + item.item_id,
            rank=item.rank,
            x=item.x,
            y=item.y,
            z=item.surface,
            height=0.0,
            rect=ScreenRect(
                centre_x - width / 2,
                centre_y - height / 2,
                centre_x + width / 2,
                centre_y + height / 2,
            ),
        )

    def _drop_ground(self, alive: set[int]) -> None:
        for item_id in [item_id for item_id in self._ground if item_id not in alive]:
            self._ground.pop(item_id).remove_from_sprite_lists()
            self._order = None

    def _drop_missing(self, alive: set[int]) -> None:
        for key in [key for key in self._parts if key[0] not in alive]:
            self._parts.pop(key).remove_from_sprite_lists()
            self._order = None
        for entity_id in [key for key in self._ghost_of if key not in alive]:
            self._ghost_of.pop(entity_id).remove_from_sprite_lists()
        for key in [key for key in self._covered_of if key[0] not in alive]:
            self._covered_of.pop(key).remove_from_sprite_lists()

    def _apply_order(self, order: Sequence[DrawEntry]) -> None:
        for sprite in (*self._parts.values(), *self._ground.values()):
            sprite.draw_rank = HIDDEN_DRAW_RANK
        for rank, entry in enumerate(order):
            if entry.is_static:
                self._static_sprites[entry.index].draw_rank = rank
            elif entry.index >= PLATFORM_ITEM_BASE:
                self._blocks[entry.index].draw_rank = rank
            elif entry.index >= PROP_ITEM_BASE:
                self._prop_sprites[entry.index - PROP_ITEM_BASE].draw_rank = rank
            elif entry.index >= GROUND_ITEM_BASE:
                self._ground[entry.index - GROUND_ITEM_BASE].draw_rank = rank
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

    def _outline(self, texture: arcade.Texture, player_index: int) -> arcade.Texture:
        """Return the outline picture of a fighter's frame (built once per frame and colour)."""
        key = (texture, player_index)
        found = self._outlines.get(key)
        if found is None:
            found = arcade.Texture(art.build_outline(texture.image, player_index))
            self._outlines[key] = found
        return found

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
