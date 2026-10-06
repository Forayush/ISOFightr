"""A little piece of the game world shown inside a menu: an island with fighters idling.

Plan note "13 - Game Modes UI and Flow" (decision D-061: the title screen's floating island
with the four fighters "idling with their own sprites"). It is the real thing, small: a
stage built from a grid, a private match that only ever gets neutral input (so the fighters
stand and breathe), and the game's own world renderer, so tiles, sprites, shadows and draw
order are exactly the battle's. Nothing here is gameplay: the match is never shown to
anyone else and no one plays it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.character_loader import load_character
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.data.stage_loader import parse_stage
from isofightr.render.fighter_look import costume_for, fighter_look
from isofightr.render.iso import project
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.sprite_bank import SpriteBank
from isofightr.render.world_renderer import WorldRenderer
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3

LOG = logging.getLogger(__name__)

ISLAND_GRID = """
000000
000000
000000
000000
000000
000000
"""
"""The title screen's island: a square of ground, which the projection shows as a diamond."""
ISLAND_SPOTS: tuple[tuple[float, float], ...] = ((0.9, 5.1), (2.4, 3.6), (3.6, 2.4), (5.1, 0.9))
"""Where up to four fighters stand on it (world x, y): in a row across the screen, left to
right (they share ``x + y``, so none stands in front of another)."""
ISLAND_FACINGS: tuple[Dir8, ...] = (Dir8.SE, Dir8.S, Dir8.S, Dir8.SW)
"""They look out of the screen, the outer two turned a little toward the middle."""
PAD_GRID = """
000
000
000
"""
"""A small square of ground for a single fighter."""
PAD_SPOTS: tuple[tuple[float, float], ...] = ((1.5, 1.5), (0.5, 0.5), (2.5, 2.5), (0.5, 2.5))


class Diorama:
    """Fighters standing on a small island, drawn with the battle's renderer."""

    def __init__(
        self,
        pixel_buffer: PixelBuffer,
        characters: Sequence[str],
        grid: str = ISLAND_GRID,
        spots: Sequence[tuple[float, float]] = ISLAND_SPOTS,
        facings: Sequence[Dir8] = ISLAND_FACINGS,
        tileset: str = "grass_stone",
        tile: str = "grass",
    ) -> None:
        """Build the island and stand one fighter per character id on ``spots``.

        A character whose sprites cannot be loaded is drawn as the placeholder capsule, as
        in a battle.
        """
        rows = [row for row in grid.strip().splitlines() if row]
        used = list(spots)[: max(len(characters), 1)]
        spawn = {f"p{index + 1}": list(used[index % len(used)]) for index in range(4)}
        stage = parse_stage(
            {
                "id": "diorama",
                "display_name": "Diorama",
                "tileset": tileset,
                "grid": "\n".join(rows),
                "legend": {"0": {"height": 0, "tile": tile}},
                "spawns": {**spawn, "respawn": list(used[0])},
            },
            source="diorama",
        )
        self.match = Match.create(
            stage, [load_character(name) for name in characters], rules=MatchRules(stocks=None)
        )
        for index, fighter in enumerate(self.match.fighters):
            x, y = used[index % len(used)]
            fighter.pos = Vec3(x, y, fighter.pos.z)
            fighter.facing = facings[index % len(facings)]
        banks: dict[str, SpriteBank] = {}
        for name in dict.fromkeys(characters):
            try:
                sprite_set = load_sprite_set(name)
            except SpriteSheetError as error:
                LOG.error("%s: sprites not loaded: %s", name, error)
                continue
            if sprite_set is not None:
                banks[name] = SpriteBank(sprite_set)
        self.renderer = WorldRenderer(pixel_buffer, stage, banks)
        width, depth = len(rows[0]), len(rows)
        self.centre = project(width / 2, depth / 2, 0.0)
        """The middle of the island's top, in world pixels."""
        self._inputs = [NEUTRAL_INPUT] * len(self.match.fighters)

    def tick(self) -> None:
        """Let a moment pass: the fighters breathe."""
        self.match.tick(self._inputs)

    def draw(self, screen_x: int, screen_y: int) -> None:
        """Draw the island with the middle of its top at a native screen pixel (y up). Call
        inside ``pixel_buffer.drawing()``; whatever was drawn before stays behind it."""
        fighters = self.match.fighters
        looks = {}
        for fighter in fighters:
            bank = self.renderer.banks.get(fighter.character.id)
            looks[fighter.entity_id] = fighter_look(
                fighter,
                self.match.frame,
                anims=None if bank is None else bank.sprite_set.anims,
                costume=0 if bank is None else costume_for(fighter, len(bank.sprite_set.costumes)),
            )
        self.renderer.sync(fighters, self.match.frame, looks)
        camera = (
            round(self.centre[0]) - (screen_x - NATIVE_W // 2),
            round(self.centre[1]) - (screen_y - NATIVE_H // 2),
        )
        self.renderer.draw(camera, background=False)
