"""The UI theme: colours, spacing and corner sizes shared by every screen.

Plan note "09 - Art Direction" ("UI theme", decision D-061): dusk over floating isles. Every
colour is a Resurrect 64 entry (a test compares them with ``art_src/palettes``): a deep navy
to teal sky, gold for focus, and the four player colours the fighters already use. Panels
have the angled 2:1 corners of the isometric tiles.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from typing import Final

Rgb = tuple[int, int, int]
Rgba = tuple[int, int, int, int]


def rgb(value: str) -> Rgb:
    """Parse ``"rrggbb"``."""
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def with_alpha(color: Rgb | Rgba, alpha: int) -> Rgba:
    """Return a colour with the given alpha."""
    return (color[0], color[1], color[2], alpha)


# --- the palette entries the UI uses ---------------------------------------------------------
INK: Final[Rgb] = rgb("2e222f")
SLATE: Final[Rgb] = rgb("3e3546")
NIGHT: Final[Rgb] = rgb("323353")
NAVY: Final[Rgb] = rgb("484a77")
STEEL: Final[Rgb] = rgb("4d65b4")
SKY: Final[Rgb] = rgb("4d9be6")
ICE: Final[Rgb] = rgb("8fd3ff")
DEEP_TEAL: Final[Rgb] = rgb("0b5e65")
TEAL: Final[Rgb] = rgb("0b8a8f")
AQUA: Final[Rgb] = rgb("0eaf9b")
MINT: Final[Rgb] = rgb("30e1b9")
GOLD: Final[Rgb] = rgb("f9c22b")
PALE_GOLD: Final[Rgb] = rgb("fbff86")
AMBER: Final[Rgb] = rgb("f79617")
WHITE: Final[Rgb] = rgb("ffffff")
FOG: Final[Rgb] = rgb("c7dcd0")
MIST: Final[Rgb] = rgb("9babb2")
DUST: Final[Rgb] = rgb("7f708a")
RED: Final[Rgb] = rgb("e83b3b")
CRIMSON: Final[Rgb] = rgb("ae2334")
MAROON: Final[Rgb] = rgb("6e2727")
GREEN: Final[Rgb] = rgb("1ebc73")
PLUM: Final[Rgb] = rgb("6b3e75")
VIOLET: Final[Rgb] = rgb("905ea9")

PALETTE: Final[tuple[Rgb, ...]] = (
    INK, SLATE, NIGHT, NAVY, STEEL, SKY, ICE, DEEP_TEAL, TEAL, AQUA, MINT, GOLD, PALE_GOLD,
    AMBER, WHITE, FOG, MIST, DUST, RED, CRIMSON, MAROON, GREEN, PLUM, VIOLET,
)  # fmt: skip
"""Every colour above, for the palette test."""

# --- roles -----------------------------------------------------------------------------------
TEXT: Final[Rgb] = WHITE
TEXT_MUTED: Final[Rgb] = MIST
TEXT_DIM: Final[Rgb] = DUST
TEXT_ON_FOCUS: Final[Rgb] = INK
TEXT_SHADOW: Final[Rgba] = with_alpha(INK, 255)
FOCUS: Final[Rgb] = GOLD
"""The colour of whatever the cursor is on."""
FOCUS_GLOW: Final[Rgb] = PALE_GOLD
HEADING: Final[Rgb] = GOLD
DANGER: Final[Rgb] = RED
"""Unbound controls, warnings, the last seconds of the clock."""
ON: Final[Rgb] = MINT
OFF: Final[Rgb] = DUST

PANEL_ALPHA: Final[int] = 240
"""Panels let a little of the backdrop through."""
PANEL_FILL: Final[Rgba] = with_alpha(NIGHT, PANEL_ALPHA)
PANEL_DEEP: Final[Rgba] = with_alpha(INK, PANEL_ALPHA)
"""Insets and bars inside a panel."""
PANEL_BORDER: Final[Rgba] = with_alpha(STEEL, 255)
PANEL_LIGHT: Final[Rgba] = with_alpha(NAVY, 255)
"""The lit top edge inside a panel's border."""
BUTTON_FILL: Final[Rgba] = with_alpha(NAVY, 255)
BUTTON_BORDER: Final[Rgba] = with_alpha(STEEL, 255)
BUTTON_FOCUS_FILL: Final[Rgba] = with_alpha(GOLD, 255)
BUTTON_FOCUS_BORDER: Final[Rgba] = with_alpha(PALE_GOLD, 255)
DANGER_FILL: Final[Rgba] = with_alpha(CRIMSON, 255)
DANGER_BORDER: Final[Rgba] = with_alpha(RED, 255)
GAUGE_FILL: Final[Rgba] = with_alpha(GOLD, 255)
GAUGE_TRACK: Final[Rgba] = with_alpha(INK, 255)
DIM_OVERLAY: Final[Rgba] = with_alpha(NIGHT, 205)
"""Laid over the backdrop behind a screen that is mostly text."""
BACKGROUND: Final[Rgba] = with_alpha(NIGHT, 255)
"""What a menu clears to before the backdrop is drawn."""

PLAYER_COLORS: Final[tuple[Rgb, ...]] = (RED, SKY, GOLD, GREEN)
"""P1 red, P2 blue, P3 yellow, P4 green: the same entries the fighters' rings use."""


def player_color(index: int) -> Rgb:
    """Return a player's colour (indices wrap)."""
    return PLAYER_COLORS[index % len(PLAYER_COLORS)]


# --- sizes -----------------------------------------------------------------------------------
CORNER: Final[int] = 4
"""Height of a panel's angled corner in pixels; it is twice as wide (the tiles' 2:1 slope)."""
SMALL_CORNER: Final[int] = 2
"""Corner of buttons, key caps and other small widgets."""
GAP: Final[int] = 4
PAD: Final[int] = 8
MARGIN: Final[int] = 12
FOOTER_HEIGHT: Final[int] = 18
"""Height of the dark strip the hint line at the bottom of a screen sits on."""
"""Distance from the screen edge to the outermost panels."""
ROW_HEIGHT: Final[int] = 18
"""Height of one row of a list (rules, settings)."""
BUTTON_HEIGHT: Final[int] = 22
ICON_SIZE: Final[int] = 12
