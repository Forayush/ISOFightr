"""The Isle: the piece of the game's world every menu is drawn on.

Plan note "13 - Game Modes UI and Flow" ("Planned (M21)", decision D-072). It is the real
thing: a stage (``assets/ui/isle``) drawn by the battle's own world renderer, backdrop and
all, so tiles, props, sprites, shadows and draw order are exactly the battle's. The roster's
fighters stroll on its plaza (a private match that only ever gets scripted input, as the
title screen's island had), and at the ring each player's fighter is shown by a stand-in.
A screen names the station it wants (:mod:`isofightr.scenes.menu_world_model`) and the
camera glides there. One instance is shared by every menu scene (the flow owns it), so the
world carries on from screen to screen.

Nothing here is gameplay: nobody plays on the Isle, and the match on it is never shown to
anyone as a match.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import partial

from isofightr.ai.stroll import Stroller
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.render.fighter_look import FighterLook, fighter_look
from isofightr.render.ground_items import GroundItem
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.sprite_bank import SpriteBank
from isofightr.render.world_renderer import WorldEntity, WorldRenderer
from isofightr.scenes.menu_world_model import (
    ISLE_DIR,
    NUDGE_EASE,
    RING_PAD_BASE,
    RING_SPOTS,
    STATIONS,
    STROLL_BOUNDS,
    Mood,
    Pose,
    StandIn,
    Station,
    camera_at,
    load_isle,
    rest_pose,
    ring_look,
    screen_point,
)
from isofightr.scenes.ticked_view import TickedView
from isofightr.sim.match import Match, MatchRules
from isofightr.ui import select_art, theme

LOG = logging.getLogger(__name__)
START_STATION = "gate"
STROLLERS = 4
"""How many of the roster stroll on the plaza."""
PAD_WIDTH = 44
"""Width of a ring spot's marker in world pixels (it is half as tall: the tiles' slope)."""


class MenuWorld:
    """The Isle's renderer, its fighters and its camera. Tick it once per menu tick and draw
    it first."""

    def __init__(
        self, pixel_buffer: PixelBuffer, seed: int = 0, characters: Sequence[str] | None = None
    ) -> None:
        """Build the island, stand the strollers on its plaza and the camera at the first
        station. ``characters`` are who strolls (the first of the roster if not given)."""
        self.stage = load_isle()
        self.banks: dict[str, SpriteBank] = {}
        """Packed sprites by character id, for every character that has them. Shared with
        whoever asks (:meth:`bank`), so the menus open each character's sheets once."""
        for name in list_character_ids():
            try:
                sprite_set = load_sprite_set(name)
            except SpriteSheetError as error:
                LOG.error("%s: sprites not loaded: %s", name, error)
                continue
            if sprite_set is not None:
                self.banks[name] = SpriteBank(sprite_set)
        self.renderer = WorldRenderer(pixel_buffer, self.stage, self.banks, backdrop_dir=ISLE_DIR)
        names = list(characters if characters is not None else list_character_ids())[:STROLLERS]
        self.match = Match.create(
            self.stage,
            [load_character(name) for name in names],
            seed=seed,
            rules=MatchRules(stocks=None),
        )
        self.strollers = [Stroller(seed * 16 + index, STROLL_BOUNDS) for index in range(len(names))]
        self.ring: list[StandIn | None] = [None] * len(RING_SPOTS)
        """Who stands on each of the ring's four spots."""
        self.pads: list[theme.Ramp | None] = [None] * len(RING_SPOTS)
        """The colours of the marker under each ring spot (``None``: no marker)."""
        self.ticks = 0
        """Ticks the world has lived: it drives the backdrop, the props and the glide."""
        self.station: Station = STATIONS[START_STATION]
        """The station the camera is at, or on its way to."""
        self._from: Pose = rest_pose(self.station)
        self._from_station: Station = self.station
        self._since = 0
        self._nudge = (0.0, 0.0)
        self._nudge_goal = (0, 0)

    # --- the camera --------------------------------------------------------------------------

    @property
    def pose(self) -> Pose:
        """Where the camera is on this tick: on its glide, moved by the nudge."""
        glide = camera_at(self.ticks - self._since, self._from, rest_pose(self.station))
        dx, dy = self._nudge
        if not dx and not dy:
            return glide
        return Pose(glide.x + round(dx), glide.y + round(dy), glide.zoom)

    @property
    def gliding(self) -> bool:
        """Whether the camera is still on its way to its station."""
        return camera_at(self.ticks - self._since, self._from, rest_pose(self.station)) != (
            rest_pose(self.station)
        )

    def go(self, name: str) -> None:
        """Glide to a station from wherever the camera is now (nothing if it is already
        there or on its way there)."""
        station = STATIONS[name]
        if station is self.station:
            return
        self._from = camera_at(self.ticks - self._since, self._from, rest_pose(self.station))
        self._from_station = self.station
        self._since = self.ticks
        self.station = station

    def settle(self, name: str | None = None) -> None:
        """Put the camera at a station at once (the one it is gliding to, if not given):
        tests and captures, and arriving from behind a wipe."""
        if name is not None:
            self.station = STATIONS[name]
        self._from = rest_pose(self.station)
        self._from_station = self.station
        self._since = self.ticks
        self._nudge = (float(self._nudge_goal[0]), float(self._nudge_goal[1]))

    def nudge(self, dx: int, dy: int) -> None:
        """Lean the camera ``(dx, dy)`` world pixels from its station, easing there: the
        main menu looks toward what its cursor is on."""
        self._nudge_goal = (dx, dy)

    def screen_point(self, x: float, y: float, z: float = 0.0) -> tuple[int, int]:
        """Return the native screen pixel (y up) a world point is drawn at right now."""
        return screen_point(self.pose, x, y, z)

    # --- who is on it ------------------------------------------------------------------------

    @property
    def strollers_shown(self) -> bool:
        """Whether the strolling fighters are drawn: not at the ring, which has its own
        fighters at twice the size, nor on the way to or from it (they come and go while
        the island is small)."""
        if not self.station.strollers:
            return False
        return not self.gliding or self._from_station.strollers

    def bank(self, character: str) -> SpriteBank | None:
        """Return a character's packed sprites, if it has any."""
        return self.banks.get(character)

    def stand(
        self, index: int, character: str, costume: int = 0, color_index: int | None = None
    ) -> StandIn:
        """Put a fighter on ring spot ``index`` (or change who is there). A new fighter
        drops in; the same one in another costume just changes."""
        current = self.ring[index]
        colour = index if color_index is None else color_index
        if current is not None and current.character == character:
            current.costume, current.color_index = costume, colour
            return current
        stand_in = StandIn(index, character, costume, colour, Mood.DROP_IN, self.ticks)
        self.ring[index] = stand_in
        return stand_in

    def mood(self, index: int, mood: Mood) -> None:
        """Change what the fighter on a ring spot is doing (nothing if nobody is there, or
        it is doing that already)."""
        stand_in = self.ring[index]
        if stand_in is not None and stand_in.mood is not mood:
            stand_in.mood, stand_in.since = mood, self.ticks

    def leave(self, index: int) -> None:
        """Take the fighter off a ring spot."""
        self.ring[index] = None

    def clear_ring(self) -> None:
        """Empty the ring: nobody on it and no markers."""
        self.ring = [None] * len(RING_SPOTS)
        self.pads = [None] * len(RING_SPOTS)

    # --- per tick, per frame -----------------------------------------------------------------

    def tick(self) -> None:
        """Let a moment pass: the strollers stroll and the camera's lean settles."""
        self.ticks += 1
        self.match.tick(
            [
                stroller.think(fighter.pos.x, fighter.pos.y)
                for stroller, fighter in zip(self.strollers, self.match.fighters, strict=True)
            ]
        )
        dx, dy = self._nudge
        goal_x, goal_y = self._nudge_goal
        self._nudge = (dx + (goal_x - dx) * NUDGE_EASE, dy + (goal_y - dy) * NUDGE_EASE)
        if abs(goal_x - self._nudge[0]) < 0.5 and abs(goal_y - self._nudge[1]) < 0.5:
            self._nudge = (float(goal_x), float(goal_y))

    def _entities(self) -> tuple[list[WorldEntity], dict[int, FighterLook]]:
        entities: list[WorldEntity] = []
        looks: dict[int, FighterLook] = {}
        if self.strollers_shown:
            for fighter in self.match.fighters:
                bank = self.banks.get(fighter.character.id)
                looks[fighter.entity_id] = fighter_look(
                    fighter,
                    self.match.frame,
                    anims=None if bank is None else bank.sprite_set.anims,
                    # Everyone in their own colours: nobody is a player here.
                    costume=0,
                )
                entities.append(fighter)
        for stand_in in self.ring:
            if stand_in is None:
                continue
            stand_in.pos = stand_in.pos_at(self.ticks)
            bank = self.banks.get(stand_in.character)
            looks[stand_in.entity_id] = ring_look(
                stand_in.character,
                {} if bank is None else bank.sprite_set.anims,
                stand_in.pose(self.ticks),
                stand_in.costume,
            )
            entities.append(stand_in)
        return entities, looks

    def _pad_items(self) -> list[GroundItem]:
        """The markers under the ring's spots: flat rings in each slot's colours, lying on
        the mosaic and sorted with the world."""
        items = []
        for index, ramp in enumerate(self.pads):
            if ramp is None:
                continue
            x, y = RING_SPOTS[index]
            items.append(
                GroundItem(
                    RING_PAD_BASE + index,
                    x,
                    y,
                    0.0,
                    ("ring-pad", PAD_WIDTH, ramp),
                    partial(select_art.spawn_marker, PAD_WIDTH, ramp),
                    on_ground=True,
                )
            )
        return items

    def draw(self) -> None:
        """Draw the Isle as the camera sees it. Call inside ``pixel_buffer.drawing()``,
        before the scene's own layer."""
        pose = self.pose
        entities, looks = self._entities()
        self.renderer.sync(entities, self.ticks, looks, ground=self._pad_items())
        self.renderer.draw(pose.centre, zoom=pose.zoom)


class IsleView(TickedView):
    """The Isle with nothing over it: a developer's view of a station, or of a glide."""

    def __init__(
        self, pixel_buffer: PixelBuffer, world: MenuWorld, station: str, goal: str = ""
    ) -> None:
        """Show ``station``; with a ``goal``, glide from it to the goal."""
        super().__init__(pixel_buffer)
        self.world = world
        world.settle(station)
        if goal:
            world.go(goal)

    def tick(self) -> None:
        """Let the world live."""
        self.world.tick()

    def on_draw(self) -> None:
        """Draw the world at native resolution, then upscale it to the window."""
        self.clear()
        with self.pixel_buffer.drawing():
            self.world.draw()
        self.blit_to_window()
