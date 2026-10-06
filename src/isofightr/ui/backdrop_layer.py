"""Draws the menu backdrop: the scrolling dusk layers and the drifting tiles.

Plan note "09 - Art Direction" ("UI theme", decision D-061). Where things are comes from
:mod:`isofightr.ui.backdrop`; this module only holds the sprites. One instance is shared by
every menu scene (the flow owns it), so the sky does not jump when the scene changes.
"""

import logging

import arcade
from PIL import Image

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.ui.backdrop import (
    BACKDROP_DIR,
    LAYERS,
    TILE_HALF_WIDTHS,
    build_drift_tile,
    drift_positions,
    layer_shift,
)

LOG = logging.getLogger(__name__)


class MenuBackdrop:
    """The backdrop's sprites. Draw it first, inside ``pixel_buffer.drawing()``."""

    def __init__(self) -> None:
        """Load the layers (a missing one is skipped with a warning) and make the tiles."""
        self.sprites: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._layers: list[tuple[float, int, list[arcade.Sprite]]] = []
        for layer in LAYERS:
            path = BACKDROP_DIR / layer.image
            try:
                with Image.open(path) as opened:
                    image = opened.convert("RGBA")
            except OSError as error:
                LOG.warning("menu backdrop layer %s not loaded: %s", path, error)
                continue
            texture = arcade.Texture(image, hash=f"menu-backdrop:{layer.image}")
            # Two copies side by side, so the seam can scroll through the screen.
            copies = [arcade.Sprite(texture, center_y=NATIVE_H / 2) for _ in range(2)]
            for sprite in copies:
                self.sprites.append(sprite)
            self._layers.append((layer.speed, image.width, copies))
        tile_textures = [
            arcade.Texture(build_drift_tile(half), hash=f"menu-backdrop:tile:{half}")
            for half in TILE_HALF_WIDTHS
        ]
        self._tiles = []
        for _, _, size in drift_positions(0):
            sprite = arcade.Sprite(tile_textures[size])
            self.sprites.append(sprite)
            self._tiles.append(sprite)
        self._placed_at: int | None = None

    def place(self, tick: int) -> None:
        """Move everything to where it is at ``tick``."""
        if tick == self._placed_at:
            return
        self._placed_at = tick
        for speed, width, copies in self._layers:
            shift = layer_shift(tick, speed, width) if width > NATIVE_W else 0
            for index, sprite in enumerate(copies):
                sprite.center_x = width / 2 - shift + index * width
        for sprite, (x, y, _) in zip(self._tiles, drift_positions(tick), strict=True):
            # Even-sized tiles sit on whole pixels when centred on a whole pixel.
            sprite.position = (x, y - sprite.height / 2)

    def draw(self, tick: int) -> None:
        """Draw the backdrop as it is at ``tick``."""
        self.place(tick)
        self.sprites.draw(pixelated=True)
