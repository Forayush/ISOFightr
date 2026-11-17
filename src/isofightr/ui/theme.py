"""The UI theme: colours, spacing and corner sizes shared by every screen.

Plan note "09 - Art Direction" ("UI theme", decision D-061): dusk over floating isles. Every
colour is a Resurrect 64 entry (a test compares them with ``art_src/palettes``): a deep navy
to teal sky, gold for focus, and the four player colours the fighters already use. Panels
have the angled 2:1 corners of the isometric tiles.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from dataclasses import dataclass
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
ASH: Final[Rgb] = rgb("625565")
SALMON: Final[Rgb] = rgb("f68181")
BRICK: Final[Rgb] = rgb("9e4539")
LEAF: Final[Rgb] = rgb("91db69")
FOREST: Final[Rgb] = rgb("239063")
PINE: Final[Rgb] = rgb("165a4c")

PALETTE: Final[tuple[Rgb, ...]] = (
    INK, SLATE, NIGHT, NAVY, STEEL, SKY, ICE, DEEP_TEAL, TEAL, AQUA, MINT, GOLD, PALE_GOLD,
    AMBER, WHITE, FOG, MIST, DUST, RED, CRIMSON, MAROON, GREEN, PLUM, VIOLET, ASH, SALMON,
    BRICK, LEAF, FOREST, PINE,
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
CAUTION_FILL: Final[Rgba] = with_alpha(INK, 255)
CAUTION_BORDER: Final[Rgba] = with_alpha(CRIMSON, 255)
CAUTION_TEXT: Final[Rgb] = SALMON
"""A button that overwrites things, while the cursor is elsewhere (decision D-070)."""
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


Ramp = tuple[Rgb, Rgb, Rgb, Rgb]
"""Four shades of one colour: light, base, dark and deep."""
PLAYER_RAMPS: Final[tuple[Ramp, ...]] = (
    (SALMON, RED, CRIMSON, MAROON),
    (ICE, SKY, STEEL, NAVY),
    (PALE_GOLD, GOLD, AMBER, BRICK),
    (LEAF, GREEN, FOREST, PINE),
)
"""Each player colour with its lighter and darker neighbours, for art painted in it."""
EMPTY_RAMP: Final[Ramp] = (MIST, DUST, ASH, SLATE)
"""The greys a slot nobody has joined is painted in."""
OPEN_SPOT_RAMP: Final[Ramp] = (WHITE, MIST, DUST, FOG)
"""The marker of a ring spot nobody stands on: pale, so it reads as a place, not a hole."""


def player_ramp(index: int) -> Ramp:
    """Return a player's colour ramp (indices wrap)."""
    return PLAYER_RAMPS[index % len(PLAYER_RAMPS)]


# --- surfaces (decision D-072) ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Surface:
    """What a block is made of: the colours of a slab, of the things set into it and of the
    text written on it. Every widget is a block seen like a tile (a top face, a front lip,
    an outline), in one of two surfaces: :data:`STONE` for menus, :data:`INKED` for anything
    drawn over a match."""

    name: str
    face: Rgba
    """A slab's top face."""
    light: Rgb
    """The lit line along the top of a face."""
    lip: Rgb
    """A slab's front face, under its top."""
    outline: Rgb
    well: Rgba
    """Things sunk into a slab: a stepper's value, a bar's track, a row's strip."""
    well_edge: Rgb
    button: Rgb
    """A resting button's top face (it must read on the slab it sits on)."""
    button_light: Rgb
    button_lip: Rgb
    text: Rgb
    text_muted: Rgb
    """Second-rank text; still 4.5:1 on the face (tested)."""
    text_dim: Rgb
    """Text that is switched off or not available: the one role allowed to be faint."""
    accent: Rgb
    """Section titles and other text that should stand out without being the cursor."""
    warning: Rgb
    """The caption of a button that overwrites things, at rest (decision D-070)."""
    shadow: bool
    """Whether text on this surface gets the ink drop shadow (light text does)."""


STONE: Final[Surface] = Surface(
    name="stone",
    face=with_alpha(FOG, 255),
    light=WHITE,
    lip=MIST,
    outline=INK,
    well=with_alpha(WHITE, 255),
    well_edge=MIST,
    button=WHITE,
    button_light=WHITE,
    button_lip=MIST,
    text=INK,
    text_muted=ASH,
    text_dim=DUST,
    accent=DEEP_TEAL,
    warning=CRIMSON,
    shadow=False,
)
"""Carved marble, the Isle's own stuff: the menus' surface."""
INKED: Final[Surface] = Surface(
    name="ink",
    face=with_alpha(NIGHT, PANEL_ALPHA),
    light=NAVY,
    lip=INK,
    outline=INK,
    well=with_alpha(INK, 255),
    well_edge=NAVY,
    button=NAVY,
    button_light=STEEL,
    button_lip=NIGHT,
    text=WHITE,
    text_muted=MIST,
    text_dim=DUST,
    accent=GOLD,
    warning=SALMON,
    shadow=True,
)
"""Dark blocks with light text: what is drawn over a match (the HUD, the pause menu), where
a pale slab would glare."""
SURFACES: Final[tuple[Surface, ...]] = (STONE, INKED)

GRASS_LIGHT: Final[Rgb] = LEAF
GRASS: Final[Rgb] = GREEN
GRASS_DARK: Final[Rgb] = FOREST
"""The turf along the top of a header plate: the Isle's rim."""

# --- sizes -----------------------------------------------------------------------------------
LIP: Final[int] = 3
"""Height of a block's front lip."""
RAISE: Final[int] = 2
"""How far the block under the cursor stands above its resting place."""
ROW_TALL: Final[int] = 24
"""Height of one row of an options tab (decision D-072: few rows, big enough to read)."""
PROMPT_HEIGHT: Final[int] = 14
"""Height of a key cap in a prompt bar."""
PROMPT_LIP: Final[int] = 2
"""Its lip: a row less than a button's, so the fixed-width capitals (8 px) have a clear row
above and below them on the cap's face."""
CORNER: Final[int] = 4
"""Height of a panel's angled corner in pixels; it is twice as wide (the tiles' 2:1 slope)."""
SMALL_CORNER: Final[int] = 2
"""Corner of buttons, key caps and other small widgets."""
GAP: Final[int] = 4
PAD: Final[int] = 8
MARGIN: Final[int] = 12
HEADER_HEIGHT: Final[int] = 28
"""Height of the title bar across the top of a screen."""
FOOTER_HEIGHT: Final[int] = 18
"""Height of the dark strip the hint line at the bottom of a screen sits on."""
"""Distance from the screen edge to the outermost panels."""
ROW_HEIGHT: Final[int] = 18
"""Height of one row of a list (rules, settings)."""
BUTTON_HEIGHT: Final[int] = 22
ICON_SIZE: Final[int] = 12
