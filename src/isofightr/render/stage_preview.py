"""Pictures of a whole stage for the menus, drawn by the battle's own renderer, and the
stage itself, live.

Plan note "13 - Game Modes UI and Flow" ("Stage select", decisions D-061 and D-072): the
stage select preview is "built from the stage's backdrop and its real tiles (not flat
diamonds)". So it is the real thing: the stage's :class:`WorldRenderer` draws the stage and
its parallax layers into an offscreen native-size buffer, once, and that frame is kept as a
picture, with a marker on each spawn. Since D-072 the picture is the whole screen, the stage
framed a little high so the strip of tiles under it leaves it in view. Thumbnails are the
same picture made smaller and put back on the Resurrect 64 palette.

:class:`LivePreview` draws a stage as it is, every frame: its clouds drift, its props sway,
its platforms move. Stage select shows it once the cursor has rested on a stage.

Rendering needs the window's GL context, so call these from a scene, not from the sim or
a test without a display. The pictures are cached by stage id for the whole session.
"""

from __future__ import annotations

from collections import OrderedDict

import arcade
from PIL import Image

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.render.iso import project, stage_screen_centre
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.world_renderer import WorldRenderer
from isofightr.sim.stage import Stage
from isofightr.ui import select_art, theme

PREVIEW_SIZE = (NATIVE_W, NATIVE_H)
"""The picture stage select shows: the whole screen (decision D-072). The loading screen and
the thumbnails are made from it."""
PREVIEW_LIFT = 46
"""The stage is drawn this many pixels above the screen's middle, so the strip of tiles and
the slab along the bottom of stage select leave it in view."""
LIVE_KEEP = 3
"""Live previews kept ready: the stage under the cursor and the last two it was on."""
MARKER_WIDTH = 16
"""A spawn marker: a diamond ring this wide (half as tall), in the player's colour."""

_previews: dict[str, Image.Image] = {}
_stage_ids: list[str] | None = None


class _Markers:
    """The spawn markers, drawn over the finished stage in world pixels."""

    def __init__(self, stage: Stage) -> None:
        self.sprites: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        for index in range(min(len(stage.spawns), len(theme.PLAYER_RAMPS))):
            point = stage.spawn_point(index)
            x, y = project(point.x, point.y, point.z)
            image = select_art.spawn_marker(MARKER_WIDTH, theme.player_ramp(index))
            texture = arcade.Texture(image, hash=f"spawn-marker:{index}")
            self.sprites.append(arcade.Sprite(texture, center_x=round(x), center_y=round(y)))

    def draw(self) -> None:
        self.sprites.draw(pixelated=True)


def preview_camera(stage: Stage) -> tuple[int, int]:
    """Return where the camera looks at a stage in its preview: its middle, lowered by
    :data:`PREVIEW_LIFT` so the stage is drawn that much higher."""
    centre_x, centre_y = stage_screen_centre(stage)
    return (round(centre_x), round(centre_y) - PREVIEW_LIFT)


def stage_picture(window: arcade.Window, stage: Stage, size: tuple[int, int]) -> Image.Image:
    """Return a picture of a whole stage: its backdrop, its tiles and its spawns, as
    :func:`preview_camera` frames it, ``size`` pixels from the middle of the screen (at most
    the native screen). Drawn once per stage id and size."""
    key = f"{stage.id}:{size[0]}x{size[1]}"
    cached = _previews.get(key)
    if cached is not None:
        return cached
    buffer = PixelBuffer(window)
    renderer = WorldRenderer(buffer, stage)
    renderer.sync([])
    with buffer.drawing(theme.BACKGROUND):
        renderer.draw(preview_camera(stage), overlays=[_Markers(stage)])
    data = buffer.framebuffer.read(components=4)
    frame = Image.frombytes("RGBA", (NATIVE_W, NATIVE_H), bytes(data))
    frame = frame.transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert("RGB")
    width, height = min(size[0], NATIVE_W), min(size[1], NATIVE_H)
    left, top = (NATIVE_W - width) // 2, (NATIVE_H - height) // 2
    picture = frame.crop((left, top, left + width, top + height)).convert("RGBA")
    _previews[key] = picture
    return picture


def thumbnail(picture: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Return a stage picture made ``size`` big: as much of it as has that shape, from the
    middle, shrunk (each new pixel the average of the ones it covers) and put back on the
    picture's own colours without dithering, so it stays flat pixel art in the same palette."""
    width, height = size
    scale = min(picture.width / width, picture.height / height)
    crop_w, crop_h = round(width * scale), round(height * scale)
    left, top = (picture.width - crop_w) // 2, (picture.height - crop_h) // 2
    rgb = picture.convert("RGB")
    middle = rgb.crop((left, top, left + crop_w, top + crop_h))
    small = middle.resize(size, Image.Resampling.BOX)
    colours = sorted(rgb.getcolors(maxcolors=1 << 16) or [], reverse=True)[:256]
    palette = Image.new("P", (1, 1))
    flat = [channel for _, colour in colours for channel in colour]
    palette.putpalette(flat + flat[:3] * (256 - len(colours)))
    return small.quantize(palette=palette, dither=Image.Dither.NONE).convert("RGBA")


def warm_next(window: arcade.Window, size: tuple[int, int] = PREVIEW_SIZE) -> bool:
    """Draw the picture of one stage that has none yet (about 15 to 50 ms), so stage select
    opens at once. A screen before it calls this once a tick. Returns whether one was
    drawn (``False`` once every stage has its picture)."""
    global _stage_ids
    if _stage_ids is None:
        _stage_ids = list_stage_ids()
    for stage_id in _stage_ids:
        if f"{stage_id}:{size[0]}x{size[1]}" not in _previews:
            stage_picture(window, load_stage(stage_id), size)
            return True
    return False


class LivePreview:
    """Stages drawn as they are, frame by frame, with their spawns marked: what stage select
    shows once its cursor has rested. Building one costs a few tens of milliseconds, so the
    last :data:`LIVE_KEEP` are kept."""

    def __init__(self, pixel_buffer: PixelBuffer) -> None:
        """Keep nothing yet; draw into ``pixel_buffer``."""
        self.pixel_buffer = pixel_buffer
        self._kept: OrderedDict[str, tuple[WorldRenderer, _Markers]] = OrderedDict()

    def ready(self, stage_id: str) -> bool:
        """Whether a stage's live preview is built."""
        return stage_id in self._kept

    def build(self, stage: Stage) -> None:
        """Build a stage's live preview (forgetting the oldest beyond :data:`LIVE_KEEP`)."""
        if stage.id in self._kept:
            self._kept.move_to_end(stage.id)
            return
        self._kept[stage.id] = (WorldRenderer(self.pixel_buffer, stage), _Markers(stage))
        while len(self._kept) > LIVE_KEEP:
            self._kept.popitem(last=False)

    def draw(self, stage: Stage, frame: int, mechanics: bool = True) -> bool:
        """Draw a stage as it is on ``frame`` (its platforms where they are if it has
        mechanics and they are on), framed as its picture is. Call inside
        ``pixel_buffer.drawing()``. Returns ``False`` (and draws nothing) if it is not
        built."""
        kept = self._kept.get(stage.id)
        if kept is None:
            return False
        renderer, markers = kept
        live = stage.at(frame) if mechanics and stage.moves else stage
        renderer.sync([], frame, {}, live=live)
        renderer.draw(preview_camera(stage), overlays=[markers])
        return True
