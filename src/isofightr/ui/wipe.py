"""The cloud wipe: a bank of cloud rises through the screen between two worlds.

Plan note "09 - Art Direction" ("Planned (M21)", decision D-072). The menus live on an island
above a sea of cloud; going from it to a stage, or back, is a climb through that cloud. One
tall band of cloud with a ragged top and bottom slides up: while its top edge crosses the
screen it covers the scene that is ending (a picture of its last frame), then, as its bottom
edge follows, it uncovers the new one. It replaces the fade from black of D-061.

Everything is a function of the tick, and the art is Pillow-drawn from palette colours.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import random
from typing import Final

from PIL import Image, ImageDraw

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.ui import theme
from isofightr.ui.anim import ease_in, ease_out, lerp

CLOSE_TICKS: Final[int] = 10
"""Ticks the cloud takes to cover the old scene."""
OPEN_TICKS: Final[int] = 14
"""Ticks it then takes to clear the new one."""
WIPE_TICKS: Final[int] = CLOSE_TICKS + OPEN_TICKS
EDGE: Final[int] = 44
"""Height of the band's ragged top and of its ragged bottom."""
BAND_HEIGHT: Final[int] = NATIVE_H + 2 * EDGE
"""The band is a screen tall between its two ragged edges, so it can cover everything."""
SEED: Final[int] = 7
PUFF_RADII: Final[tuple[int, int]] = (14, 30)
BODY: Final[theme.Rgb] = theme.WHITE
SHADE: Final[theme.Rgb] = theme.ICE
"""The underside of the cloud's bumps."""
RIM: Final[theme.Rgb] = theme.FOG


def band_bottom(tick: int) -> int | None:
    """Return the screen y (y up) of the band's bottom edge on a tick of the wipe, or
    ``None`` once it has passed. On tick 0 its top is at the bottom of the screen; on tick
    :data:`CLOSE_TICKS` it covers the whole screen; after :data:`WIPE_TICKS` it is gone."""
    if tick < 0 or tick >= WIPE_TICKS:
        return None
    covering = -EDGE
    if tick <= CLOSE_TICKS:
        return round(lerp(-BAND_HEIGHT, covering, ease_out(tick / CLOSE_TICKS)))
    return round(lerp(covering, NATIVE_H, ease_in((tick - CLOSE_TICKS) / OPEN_TICKS)))


def covers(tick: int) -> bool:
    """Whether the band hides the whole screen on a tick: the moment the scene behind it
    may change without being seen."""
    bottom = band_bottom(tick)
    return bottom is not None and bottom <= -EDGE and bottom + BAND_HEIGHT - EDGE >= NATIVE_H


def shows_old(tick: int) -> bool:
    """Whether the scene that is ending is still the one behind the cloud."""
    return 0 <= tick < CLOSE_TICKS


def running(tick: int) -> bool:
    """Whether the wipe is still on screen."""
    return band_bottom(tick) is not None


def build_band(width: int = NATIVE_W, seed: int = SEED) -> Image.Image:
    """Return the band of cloud: solid in the middle, puffs along its top and its bottom.
    Every colour is a palette entry."""
    rng = random.Random(seed)
    image = Image.new("RGBA", (width, BAND_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    low, high = PUFF_RADII

    def puffs(count: int) -> list[tuple[int, int]]:
        step = width / count
        return [
            (round(step * (index + rng.random())), rng.randint(low, high)) for index in range(count)
        ]

    # The bottom edge first (it is behind the body): shaded puffs hanging under the cloud.
    for x, radius in puffs(16):
        centre = BAND_HEIGHT - EDGE + radius // 3
        draw.ellipse((x - radius, centre - radius, x + radius, centre + radius), fill=SHADE)
        draw.ellipse((x - radius, centre - radius - 3, x + radius, centre + radius - 3), fill=BODY)
    draw.rectangle((0, EDGE, width - 1, BAND_HEIGHT - EDGE), fill=BODY)
    # The top edge: round puffs with a thin rim of shadow under each, so they read as heaps.
    for x, radius in puffs(16):
        centre = EDGE - radius // 4
        draw.ellipse((x - radius, centre - radius, x + radius, centre + radius), fill=BODY)
    for x, radius in puffs(9):
        centre = EDGE + radius + rng.randint(6, 40)
        draw.arc(
            (x - radius, centre - radius, x + radius, centre + radius), 20, 160, fill=RIM, width=1
        )
    # Hard edges only: a pixel is the cloud or it is not.
    alpha = image.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    image.putalpha(alpha)
    return image
