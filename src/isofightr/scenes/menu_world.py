"""The Isle: the piece of the game's world every menu is drawn on.

Plan note "13 - Game Modes UI and Flow" ("Planned (M21)", decision D-072). It is the real
thing: a stage (``assets/ui/isle``) drawn by the battle's own world renderer, backdrop and
all, so tiles, props, sprites, shadows and draw order are exactly the battle's. A screen
names the station it wants (:mod:`isofightr.scenes.menu_world_model`) and the camera glides
there. One instance is shared by every menu scene (the flow owns it), so the world carries
on from screen to screen.

Nothing here is gameplay: nobody plays on the Isle.
"""

from __future__ import annotations

from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.world_renderer import WorldRenderer
from isofightr.scenes.menu_world_model import (
    ISLE_DIR,
    STATIONS,
    Pose,
    Station,
    camera_at,
    load_isle,
    rest_pose,
    screen_point,
)
from isofightr.scenes.ticked_view import TickedView

START_STATION = "gate"


class MenuWorld:
    """The Isle's renderer and its camera. Tick it once per menu tick, draw it first."""

    def __init__(self, pixel_buffer: PixelBuffer) -> None:
        """Build the island's sprites and stand the camera at the first station."""
        self.stage = load_isle()
        self.renderer = WorldRenderer(pixel_buffer, self.stage, backdrop_dir=ISLE_DIR)
        self.ticks = 0
        """Ticks the world has lived: it drives the backdrop, the props and the glide."""
        self.station: Station = STATIONS[START_STATION]
        """The station the camera is at, or on its way to."""
        self._from: Pose = rest_pose(self.station)
        self._since = 0

    @property
    def pose(self) -> Pose:
        """Where the camera is on this tick."""
        return camera_at(self.ticks - self._since, self._from, rest_pose(self.station))

    @property
    def gliding(self) -> bool:
        """Whether the camera is still on its way."""
        return self.pose != rest_pose(self.station)

    def go(self, name: str) -> None:
        """Glide to a station from wherever the camera is now (nothing if it is already
        there or on its way there)."""
        station = STATIONS[name]
        if station is self.station:
            return
        self._from = self.pose
        self._since = self.ticks
        self.station = station

    def settle(self, name: str | None = None) -> None:
        """Put the camera at a station at once (the one it is gliding to, if not given):
        tests and captures, and arriving from behind a wipe."""
        if name is not None:
            self.station = STATIONS[name]
        self._from = rest_pose(self.station)
        self._since = self.ticks

    def tick(self) -> None:
        """Let a moment pass."""
        self.ticks += 1

    def screen_point(self, x: float, y: float, z: float = 0.0) -> tuple[int, int]:
        """Return the native screen pixel (y up) a world point is drawn at right now."""
        return screen_point(self.pose, x, y, z)

    def draw(self) -> None:
        """Draw the Isle as the camera sees it. Call inside ``pixel_buffer.drawing()``,
        before the scene's own layer."""
        pose = self.pose
        self.renderer.sync([], self.ticks, {})
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
