"""Pure layout, colour and timing helpers for the battle HUD.

Plan note "13 - Game Modes UI and Flow" ("Battle HUD", decision D-061 item 9) and the damage
colour ramp in "09 - Art Direction". The screen is split into three bands: the player cards
along the bottom (:data:`HUD_BAND`), the clock and the KO feed along the top
(:data:`TOP_BAND`), and the play area between them, which nothing fixed may cover (tested).
Things that come and go (popups, the combo counter, banners, off-screen bubbles) are placed
in the play area on purpose. Drawing is in :mod:`isofightr.ui.hud` and
:mod:`isofightr.ui.hud_extras`.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

import math
from collections.abc import Sequence
from typing import Final

from isofightr.art.portraits import ICON_SIZE
from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.ui.focus import Rect
from isofightr.ui.menu import MenuItem

type Rgb = tuple[int, int, int]

DAMAGE_RAMP: Final[tuple[tuple[float, Rgb], ...]] = (
    (0.0, (255, 255, 255)),
    (60.0, (255, 232, 96)),
    (100.0, (255, 150, 48)),
    (150.0, (232, 56, 48)),
    (200.0, (150, 24, 40)),
)
"""Damage text color stops: white, yellow, orange, red, dark red (plan note 09)."""
KO_TEXT: Final[str] = "--"

# --- bands and cards ------------------------------------------------------------------------
HUD_BAND: Final[int] = 48
"""Height of the strip along the bottom that holds the player cards."""
TOP_BAND: Final[int] = 40
"""Height of the strip along the top that holds the clock and the KO feed."""
PLAY_AREA: Final[Rect] = Rect(0, HUD_BAND, NATIVE_W, NATIVE_H - HUD_BAND - TOP_BAND)
"""Where the fight is: the fixed HUD never covers it, and the camera centres on it."""
CAMERA_LIFT: Final[int] = (HUD_BAND - TOP_BAND) // 2
"""Pixels the world is drawn higher on the screen, so the camera's centre is the play
area's."""
CARD_WIDTH: Final[int] = 148
CARD_HEIGHT: Final[int] = 40
CARD_GAP: Final[int] = 8
CARD_BOTTOM: Final[int] = 4
PANEL_WIDTH: Final[int] = CARD_WIDTH
"""The older name of a card's width."""
BUST: Final[Rect] = Rect(4, 4, 32, 32)
"""The bust's well inside a card (card-relative)."""
NAME_LEFT: Final[int] = 40
NAME_BOTTOM: Final[int] = 26
STOCK_LEFT: Final[int] = 40
STOCK_BOTTOM: Final[int] = 6
CARD_STOCK_STEP: Final[int] = 9
"""Stock icons on a card overlap a little, so five fit beside a three-digit percent."""
DAMAGE_RIGHT: Final[int] = 6
"""Gap between the damage number's right edge and the card's."""
DAMAGE_BOTTOM: Final[int] = 4
CROWN_BOTTOM: Final[int] = 30
"""The leader's crown sits on the bust's top edge (card-relative)."""


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
    """Return the left edge of each player's card: side by side, :data:`CARD_GAP` apart,
    centred on the screen."""
    total = player_count * CARD_WIDTH + max(player_count - 1, 0) * CARD_GAP
    first = (NATIVE_W - total) // 2
    return [first + index * (CARD_WIDTH + CARD_GAP) for index in range(player_count)]


def card_rects(player_count: int) -> list[Rect]:
    """Return each player's card on the screen."""
    return [Rect(left, CARD_BOTTOM, CARD_WIDTH, CARD_HEIGHT) for left in panel_lefts(player_count)]


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


# --- the damage number -----------------------------------------------------------------------
ROLL_SHARE: Final[float] = 0.25
"""Each tick the shown percent closes this share of the gap to the real one (at least 1)."""
SHAKE_FROM: Final[float] = 100.0
"""From this percent the number trembles; one more pixel each :data:`SHAKE_STEP` on."""
SHAKE_STEP: Final[float] = 50.0
SHAKE_MAX: Final[int] = 2
HIT_FLASH_TICKS: Final[int] = 4
"""The number shows white this long after a hit (not with "reduce flashing")."""


def roll(shown: float, target: float) -> float:
    """Return the next shown percent: rolling up toward the real one, a quarter of the gap a
    tick but at least one percent, and snapping down at once (a respawn, a reset)."""
    if target <= shown:
        return target
    step = max(math.ceil((target - shown) * ROLL_SHARE), 1)
    return min(shown + step, target)


def shake_amplitude(percent: float, strength: float = 1.0) -> int:
    """Return how many pixels a damage number trembles at ``percent``: none below 100%,
    scaled by the screen-shake setting (0 to 1)."""
    if percent < SHAKE_FROM or strength <= 0:
        return 0
    pixels = 1 + int((percent - SHAKE_FROM) // SHAKE_STEP)
    return min(round(min(pixels, SHAKE_MAX) * strength), SHAKE_MAX)


# --- popups, the clock, the feed, the leader --------------------------------------------------
POPUP_TICKS: Final[int] = 40
POPUP_RISE: Final[int] = 18
POPUP_FADE_TICKS: Final[int] = 12
POPUP_TIERS: Final[tuple[tuple[float, Rgb], ...]] = (
    (0.0, (255, 255, 255)),
    (6.0, (251, 255, 134)),
    (12.0, (247, 150, 23)),
    (18.0, (232, 59, 59)),
)
"""A popup's colour by the hit's damage: white, pale gold, amber, red (Resurrect 64)."""
BIG_POPUP_DAMAGE: Final[float] = 6.0
"""From this much damage a popup uses the bigger font."""
CLOCK_ALARM_FRAMES: Final[int] = 30 * 60
"""In the last 30 seconds the clock turns red and pulses."""
GO_TICKS: Final[int] = 40
"""How long "GO!" stays up after the countdown."""
FEED_LINES: Final[int] = 3
FEED_TICKS: Final[int] = 180
FEED_SLIDE_TICKS: Final[int] = 8
CLOCK: Final[Rect] = Rect(NATIVE_W // 2 - 38, NATIVE_H - 24, 76, 20)
FEED_LEFT: Final[int] = 6
FEED_TOP: Final[int] = NATIVE_H - 1
FEED_ROW: Final[tuple[int, int]] = (160, 12)
FEED_GAP: Final[int] = 1


def feed_rect() -> Rect:
    """Return everything the KO feed's rows can cover, at most :data:`FEED_LINES` of them."""
    bottom = FEED_TOP - FEED_LINES * (FEED_ROW[1] + FEED_GAP)
    return Rect(FEED_LEFT, bottom, FEED_ROW[0], FEED_TOP - bottom)


def popup_text(damage: float) -> str:
    """Return a damage popup's text: ``+12%`` (at least ``+1%``)."""
    return f"+{max(int(damage), 1)}%"


def popup_color(damage: float) -> Rgb:
    """Return a popup's colour for a hit's damage."""
    color = POPUP_TIERS[0][1]
    for floor, tier in POPUP_TIERS:
        if damage >= floor:
            color = tier
    return color


def popup_offset(age: int) -> int:
    """Return how far a popup has risen after ``age`` ticks: fast, then easing."""
    share = min(age / POPUP_TICKS, 1.0)
    return round(POPUP_RISE * (1 - (1 - share) ** 2))


def popup_alpha(age: int) -> int:
    """Return a popup's opacity: solid, then fading over its last ticks."""
    left = POPUP_TICKS - age
    if left >= POPUP_FADE_TICKS:
        return 255
    return max(round(255 * left / POPUP_FADE_TICKS), 0)


def clock_alarm(time_left: int | None) -> bool:
    """Return whether the clock is in its last 30 seconds."""
    return time_left is not None and time_left <= CLOCK_ALARM_FRAMES


def leader(scores: Sequence[int]) -> int | None:
    """Return the player with the highest score, or ``None`` when two or more share it (or
    nobody has scored yet)."""
    if not scores:
        return None
    best = max(scores)
    if scores.count(best) > 1 or all(score == 0 for score in scores):
        return None
    return scores.index(best)


def feed_text(victim: str, killer: str | None) -> str:
    """Return a KO feed line: who KO'd whom, or who fell on their own."""
    return f"{killer} KO {victim}" if killer else f"{victim} FELL"


# --- off-screen bubbles -----------------------------------------------------------------------
BUBBLE_SIZE: Final[int] = 26
"""An off-screen bubble's diameter."""
BUBBLE_INSET: Final[int] = 18
"""Distance of a bubble's centre from the play area's edge."""


def bubble_layout(
    screen_x: float, screen_y: float, area: Rect = PLAY_AREA
) -> tuple[int, int, int] | None:
    """Return where an off-screen fighter's bubble goes and which way its arrow points (one
    of eight, 0 = right, counting anticlockwise in 45 degree steps), or ``None`` while the
    fighter is inside the play area."""
    if area.left <= screen_x <= area.right and area.bottom <= screen_y <= area.top:
        return None
    x = min(max(screen_x, area.left + BUBBLE_INSET), area.right - BUBBLE_INSET)
    y = min(max(screen_y, area.bottom + BUBBLE_INSET), area.top - BUBBLE_INSET)
    angle = math.atan2(screen_y - y, screen_x - x)
    direction = round(angle / (math.pi / 4)) % 8
    return (round(x), round(y), direction)


def play_area_overlaps(rects: Sequence[Rect]) -> list[Rect]:
    """Return the rectangles that reach into the play area (for the layout test)."""
    return [rect for rect in rects if rect.overlaps(PLAY_AREA)]


# --- the pause menu ---------------------------------------------------------------------------
def pause_row_parts(item: MenuItem) -> tuple[str, str]:
    """Return a pause-menu row as its name and its value: a setting's choice, or the part
    after the colon of a row that carries its own value ("Dummy damage: < 40% >"), or no
    value for an action."""
    if item.choices:
        return item.label, item.value
    name, colon, rest = item.label.partition(":")
    if not colon:
        return item.label, ""
    return name, rest.strip().removeprefix("<").removesuffix(">").strip()
