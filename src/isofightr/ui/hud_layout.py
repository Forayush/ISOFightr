"""Pure layout and color helpers for the battle HUD.

Plan note "13 - Game Modes UI and Flow" ("HUD (battle)") and the damage color ramp in
"09 - Art Direction". Drawing is in :mod:`isofightr.ui.hud`.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from typing import Final

from isofightr.config import NATIVE_W
from isofightr.ui.pixel_font import GLYPH_ADVANCE

type Rgb = tuple[int, int, int]

DAMAGE_RAMP: Final[tuple[tuple[float, Rgb], ...]] = (
    (0.0, (255, 255, 255)),
    (60.0, (255, 232, 96)),
    (100.0, (255, 150, 48)),
    (150.0, (232, 56, 48)),
    (200.0, (150, 24, 40)),
)
"""Damage text color stops: white, yellow, orange, red, dark red (plan note 09)."""
DAMAGE_SCALE: Final[int] = 2
DAMAGE_CAPACITY: Final[int] = len("999%")
PANEL_WIDTH: Final[int] = DAMAGE_CAPACITY * GLYPH_ADVANCE * DAMAGE_SCALE
TAG_CAPACITY: Final[int] = len("P1 KO")
KO_TEXT: Final[str] = "--"


def damage_color(percent: float) -> Rgb:
    """Return the damage text color at ``percent``, blended between the ramp's stops."""
    previous_stop, previous_color = DAMAGE_RAMP[0]
    for stop, color in DAMAGE_RAMP[1:]:
        if percent < stop:
            blend = max(0.0, (percent - previous_stop) / (stop - previous_stop))
            mixed = [round(a + (b - a) * blend) for a, b in zip(previous_color, color, strict=True)]
            return (mixed[0], mixed[1], mixed[2])
        previous_stop, previous_color = stop, color
    return DAMAGE_RAMP[-1][1]


def damage_text(percent: float) -> str:
    """Return the HUD text for a damage value: whole percent, rounded down."""
    return f"{int(percent)}%"


def panel_lefts(player_count: int) -> list[int]:
    """Return the left edge of each player's panel, spread evenly across the screen."""
    return [
        round(NATIVE_W * (index + 1) / (player_count + 1) - PANEL_WIDTH / 2)
        for index in range(player_count)
    ]
