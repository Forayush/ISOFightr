"""Draws a stage's hazard effects (jets, bolts, wind streaks) over the world.

Plan note "03 - Isometric World and Rendering" ("Hazards"), decision D-063. What to draw comes
from :mod:`isofightr.render.hazard_look`; this only keeps the sprites. It is an overlay of the
world renderer, like the effect renderer: drawn with the world camera active, on top of the
sorted world.
"""

from __future__ import annotations

from collections.abc import Sequence

import arcade

from isofightr.render.hazard_look import HazardSprite


class HazardRenderer:
    """A pool of sprites, one per hazard effect showing this frame."""

    def __init__(self) -> None:
        self.sprites: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._textures: dict[tuple[object, ...], arcade.Texture] = {}
        self.shown = 0
        """How many effects the last :meth:`sync` showed."""

    def sync(self, wanted: Sequence[HazardSprite]) -> None:
        """Show exactly these effects."""
        while len(self.sprites) < len(wanted):
            self.sprites.append(arcade.Sprite())
        for index, sprite in enumerate(self.sprites):
            if index >= len(wanted):
                sprite.visible = False
                continue
            effect = wanted[index]
            texture = self._textures.get(effect.key)
            if texture is None:
                texture = arcade.Texture(effect.build())
                self._textures[effect.key] = texture
            if sprite.texture is not texture:
                sprite.texture = texture
            # Whole pixels: an odd width sits half a pixel off its middle.
            centre_x = round(effect.x) + (texture.width % 2) / 2
            sprite.position = (centre_x, round(effect.bottom) + texture.height / 2)
            sprite.visible = True
        self.shown = len(wanted)

    def draw(self) -> None:
        """Draw the effects (the world camera is active)."""
        if self.shown:
            self.sprites.draw(pixelated=True)
