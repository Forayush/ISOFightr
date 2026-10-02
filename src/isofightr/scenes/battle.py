"""The battle scene. M1: an isometric stage with free-moving placeholder fighters.

Implements the M1 sandbox from the roadmap: the stage renders depth-sorted with shadows, a
debug "free-cam" moves a placeholder with no physics, the camera follows and clamps, and F3
shows the grid, ledges and blast zone. From M2 on, :meth:`BattleView.tick` polls input, steps
the sim ``Match`` and feeds its events to the presentation layer instead.

Sandbox keys: W/A/S/D move (screen-relative), I and comma raise and lower, Tab switches
placeholder, F3 debug overlay, F8 reset positions, C toggles the camera clamp.
"""

import arcade

from isofightr.config import NATIVE_H, Z_PX
from isofightr.render.camera import FollowCamera, bounds_on_screen
from isofightr.render.debug_overlay import StageOverlay
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.placeholder_art import BODY_HEIGHT
from isofightr.render.world_renderer import WorldRenderer
from isofightr.scenes.sandbox import Sandbox
from isofightr.scenes.ticked_view import TickedView
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import Stage
from isofightr.ui.pixel_font import GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel

KEY_MOVE_UP = arcade.key.W
KEY_MOVE_DOWN = arcade.key.S
KEY_MOVE_LEFT = arcade.key.A
KEY_MOVE_RIGHT = arcade.key.D
KEY_RISE = arcade.key.I
KEY_SINK = arcade.key.COMMA
KEY_SWITCH = arcade.key.TAB
KEY_OVERLAY = arcade.key.F3
KEY_RESET = arcade.key.F8
KEY_CAMERA_CLAMP = arcade.key.C

HUD_MARGIN = 4
HUD_CAPACITY = 100
HELP_TEXT = "WASD move  I/, up/down  TAB switch  F3 debug  F8 reset  C camera clamp"
BODY_CENTRE_HEIGHT = BODY_HEIGHT / 2 / Z_PX
"""The camera tracks a fighter's middle rather than its feet, in units above the feet."""


class BattleView(TickedView):
    """Runs the fixed 60 Hz loop over the sandbox and draws the stage."""

    def __init__(
        self, pixel_buffer: PixelBuffer, stage: Stage, max_ticks: int | None = None
    ) -> None:
        """Create the view for ``stage``. See :class:`TickedView` for the other arguments."""
        super().__init__(pixel_buffer, max_ticks)
        self.stage = stage
        self.sandbox = Sandbox.create(stage)
        self.renderer = WorldRenderer(pixel_buffer, stage)
        self.camera = FollowCamera(limits=bounds_on_screen(stage.camera_bounds))
        self.camera.snap_to(self._camera_targets())
        self.show_overlay = False
        self._held_keys: set[int] = set()

        glyphs = GlyphAtlas()
        self.overlay = StageOverlay(stage, glyphs)
        self._hud: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._help = PixelLabel(glyphs, self._hud, HUD_MARGIN, HUD_MARGIN, len(HELP_TEXT))
        self._help.text = HELP_TEXT
        status_y = NATIVE_H - HUD_MARGIN - GLYPH_HEIGHT
        self._status = PixelLabel(glyphs, self._hud, HUD_MARGIN, status_y, HUD_CAPACITY)

    # --- input -----------------------------------------------------------------------------

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """Track held keys and handle the sandbox's one-shot debug keys."""
        self._held_keys.add(symbol)
        if symbol == KEY_OVERLAY:
            self.show_overlay = not self.show_overlay
        elif symbol == KEY_RESET:
            self.sandbox.reset()
        elif symbol == KEY_SWITCH:
            self.sandbox.cycle_control()
        elif symbol == KEY_CAMERA_CLAMP:
            self.camera.clamped = not self.camera.clamped

    def on_key_release(self, symbol: int, modifiers: int) -> None:
        """Stop tracking a released key."""
        self._held_keys.discard(symbol)

    def _axis(self, positive: int, negative: int) -> float:
        return float(positive in self._held_keys) - float(negative in self._held_keys)

    # --- loop ------------------------------------------------------------------------------

    def tick(self) -> None:
        """Advance one fixed step: move the controlled placeholder, pan the camera."""
        self.sandbox.step(
            stick_u=self._axis(KEY_MOVE_RIGHT, KEY_MOVE_LEFT),
            stick_v=self._axis(KEY_MOVE_UP, KEY_MOVE_DOWN),
            rise=self._axis(KEY_RISE, KEY_SINK),
        )
        self.camera.update(self._camera_targets())

    def _camera_targets(self) -> list[Vec3]:
        lift = Vec3(0.0, 0.0, BODY_CENTRE_HEIGHT)
        return [entity.pos + lift for entity in self.sandbox.entities]

    def on_draw(self) -> None:
        """Draw the world at native resolution, then upscale it to the window."""
        self.clear()
        self.renderer.sync(self.sandbox.entities)
        self._status.text = self._status_text() if self.show_overlay else ""
        with self.pixel_buffer.drawing():
            self.renderer.draw(
                self.camera.pixel_centre, overlay=self.overlay if self.show_overlay else None
            )
            self._hud.draw(pixelated=True)
        self.blit_to_window()

    def _status_text(self) -> str:
        entity = self.sandbox.controlled_entity
        pos = entity.pos
        ground = self.stage.support_below(pos.x, pos.y, pos.z)
        ground_text = "none" if ground is None else f"{ground:.2f}"
        clamp = "on" if self.camera.clamped else "off"
        return (
            f"P{entity.player_index + 1} x={pos.x:.2f} y={pos.y:.2f} z={pos.z:.2f} "
            f"facing={entity.facing.name} ground={ground_text} clamp={clamp}"
        )
