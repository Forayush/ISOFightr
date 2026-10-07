"""Pictures of a whole stage for the menus, drawn by the battle's own renderer.

Plan note "13 - Game Modes UI and Flow" ("Stage select", decision D-061): the stage select
preview is "built from the stage's backdrop and its real tiles (not flat diamonds)". So it
is the real thing: the stage's :class:`WorldRenderer` draws the stage and its parallax
layers into an offscreen native-size buffer, once, and the middle of that frame is kept as
a picture, with a marker on each spawn. Thumbnails are the same picture made smaller and
put back on the Resurrect 64 palette.

Rendering needs the window's GL context, so call these from a scene, not from the sim or
a test without a display. The pictures are cached by stage id for the whole session.
"""

from __future__ import annotations

import arcade
from PIL import Image

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.render.iso import project, stage_screen_centre
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.world_renderer import WorldRenderer
from isofightr.sim.stage import Stage
from isofightr.ui import select_art, theme

PREVIEW_SIZE = (400, 206)
"""The picture stage select shows; the loading screen and the thumbnails are made from it."""
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


def stage_picture(window: arcade.Window, stage: Stage, size: tuple[int, int]) -> Image.Image:
    """Return a picture of a whole stage: its backdrop, its tiles and its spawns, centred,
    ``size`` pixels (at most the native screen). Drawn once per stage id and size."""
    key = f"{stage.id}:{size[0]}x{size[1]}"
    cached = _previews.get(key)
    if cached is not None:
        return cached
    buffer = PixelBuffer(window)
    renderer = WorldRenderer(buffer, stage)
    renderer.sync([])
    centre = stage_screen_centre(stage)
    with buffer.drawing(theme.BACKGROUND):
        renderer.draw((round(centre[0]), round(centre[1])), overlays=[_Markers(stage)])
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
