"""Pure layout and color helpers for the battle HUD.

Plan note "13 - Game Modes UI and Flow" ("HUD (battle)") and the damage color ramp in
"09 - Art Direction". Drawing is in :mod:`isofightr.ui.hud`.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from typing import Final

from isofightr.art.portraits import ICON_SIZE
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


COMBO_MIN_HITS: Final[int] = 2
"""A single hit is not a combo: the counter shows from the second hit of a string."""
COMBO_CAPACITY: Final[int] = len("99 HITS 999%")
COMBO_COLOR: Final[Rgb] = (255, 232, 96)


def combo_text(hits: int, damage: float) -> str:
    """Return the combo counter's text: the hits in the string and its damage, or "" for
    a single hit."""
    if hits < COMBO_MIN_HITS:
        return ""
    return f"{min(hits, 99)} HITS {int(damage)}%"


def damage_text(percent: float) -> str:
    """Return the HUD text for a damage value: whole percent, rounded down."""
    return f"{int(percent)}%"


def panel_lefts(player_count: int) -> list[int]:
    """Return the left edge of each player's panel, spread evenly across the screen."""
    return [
        round(NATIVE_W * (index + 1) / (player_count + 1) - PANEL_WIDTH / 2)
        for index in range(player_count)
    ]


STOCK_SLOT_SIZE: Final[int] = ICON_SIZE
"""A stock icon's square slot: a character's head icon, or the placeholder disc centred in it."""
MAX_STOCK_ICONS: Final[int] = 5
"""More stocks than this are shown as one icon and a number."""
STOCK_ICON_STEP: Final[int] = STOCK_SLOT_SIZE + 1
"""Horizontal distance between stock icons, in pixels."""
BUBBLE_MARGIN: Final[int] = 12
"""Distance of an off-screen marker's centre from the screen edge, in pixels."""


def stock_icons_shown(stocks: int | None) -> int:
    """Return how many stock icons to draw: one per stock, or a single one beside a count."""
    if stocks is None or stocks <= 0:
        return 0
    return stocks if stocks <= MAX_STOCK_ICONS else 1


def stock_count_text(stocks: int | None) -> str:
    """Return the number shown next to the single icon when there are too many stocks."""
    return f"x{stocks}" if stocks is not None and stocks > MAX_STOCK_ICONS else ""


def bubble_position(
    screen_x: float, screen_y: float, width: int, height: int
) -> tuple[int, int] | None:
    """Return where to draw the marker for a fighter at a screen position, or ``None`` if the
    fighter is in view. The marker sits on the nearest point of the screen's edge."""
    if 0 <= screen_x <= width and 0 <= screen_y <= height:
        return None
    x = min(max(screen_x, BUBBLE_MARGIN), width - BUBBLE_MARGIN)
    y = min(max(screen_y, BUBBLE_MARGIN), height - BUBBLE_MARGIN)
    return (round(x), round(y))


# --- score and player tags (the Rules screen's display options, decision D-061) -------------
SCORE_CAPACITY: Final[int] = len("+99")
SCORE_COLOR: Final[Rgb] = (249, 194, 43)
TAG_GAP: Final[int] = 5
"""Pixels between the top of a fighter's head and the tip of its name tag's arrow."""
TAG_MARGIN: Final[int] = 10
"""A tag is dropped once its fighter is this far outside the screen."""
CPU_TAG: Final[str] = "CPU"


def score_text(score: int) -> str:
    """Return a player's score as the HUD shows it: signed, so 0 reads as a score."""
    return f"{max(min(score, 99), -99):+d}" if score else "0"


def tag_text(player_index: int, cpu_level: int = 0) -> str:
    """Return the name tag over a fighter: ``P1`` to ``P4``, or ``CPU``."""
    return CPU_TAG if cpu_level > 0 else f"P{player_index + 1}"


def tag_anchor(head_x: float, head_y: float, width: int, height: int) -> tuple[int, int] | None:
    """Return where a name tag's arrow tip goes, in native pixels (centre x, bottom y), for
    a fighter whose head top is at a screen position; ``None`` when that is off screen (the
    off-screen marker takes over). The tag sits above the head, so it can never cover the
    fighter's shadow or ring."""
    if not -TAG_MARGIN <= head_x <= width + TAG_MARGIN:
        return None
    if not -TAG_MARGIN <= head_y <= height + TAG_MARGIN:
        return None
    return (round(head_x), round(head_y) + TAG_GAP)
