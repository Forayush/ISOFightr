"""Pictures of the hit splash (decision D-068), drawn with Pillow from a sprite's key.

Plan note "09 - Art Direction" (VFX style). :class:`isofightr.render.hit_splash.HitSplashes`
says what to show as keys, and the effect renderer turns each key into a texture once:

- ``("burst", theme, tier, frame)``: the contact flash, the contact tick and the next (the one
  picture that may be solid: it lasts two ticks);
- ``("split", theme, tier, frame, channel)``: the burst's silhouette in one of two colours,
  drawn two pixels to either side under a heavy or critical burst (a chromatic split made of
  palette colours, never a blend);
- ``("core", theme, tier, angle, frame)``: the held splash, pointing ``angle`` sixteenths of a
  turn counter-clockwise from screen right (``-1``: no direction), open line art;
- ``("lines", theme, tier, angle)``: the directional lines along the launch and the short
  counter-streak behind;
- ``("particle", theme, size, angle, frame)``: one dispersal particle flying ``angle``
  (``size`` 0 for light and medium hits, 1 for heavy and critical ones);
- ``("ring", theme, tier, frame)``: the shockwave ring of a heavy or critical launch;
- ``("flare", theme, frame)``: the critical flare.

Every picture is drawn per angle with pixel-exact polygons and lines (no rotated images, no
anti-aliasing) in Resurrect 64 colours. A theme without its own art yet uses the effects that
already exist (the hit spark, the launch streak, an ember dot). :func:`theme_keys` lists every
key of a theme, in the order a battle builds them ahead of time.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

import math
from collections.abc import Callable
from typing import Final

from PIL import Image, ImageDraw, ImageFilter

from isofightr.render import vfx_art

Rgba = tuple[int, int, int, int]
Key = tuple[str | int, ...]
Point = tuple[float, float]


def _rgba(value: str) -> Rgba:
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


TIERS: Final[int] = 4
ANGLES: Final[int] = 16
HEAVY: Final[int] = 2
BURST_FRAMES: Final[int] = 2
CORE_FRAMES: Final[int] = 3
PARTICLE_FRAMES: Final[int] = 3
RING_FRAMES: Final[int] = 4
FLARE_FRAMES: Final[int] = 3
SPLIT_CHANNELS: Final[int] = 2
SIZES: Final[tuple[int, ...]] = (17, 25, 35, 47)
"""The side of a tier's burst, core and lines pictures, in pixels (odd: centred on a pixel)."""
PARTICLE_SIZE: Final[int] = 9
FLARE_SIZE: Final[int] = 61

SPARK_EFFECT: Final[dict[str, str]] = {
    "normal": "normal",
    "slash": "slash",
    "fire": "fire",
    "darkness": "darkness",
    "electric": "electric",
    "ice": "ice",
    "earth": "normal",
    "wind": "normal",
}
"""Whose spark colours each theme's placeholder uses (a character theme has none yet)."""
PARTICLE_FAMILY: Final[dict[str, str]] = {
    "normal": "pale",
    "slash": "pale",
    "fire": "fire",
    "darkness": "rune",
    "electric": "wind",
    "ice": "pale",
    "earth": "stone",
    "wind": "wind",
}
"""The colour family (``vfx_art.FAMILIES``) of each theme's placeholder particles."""
CORE_SPARK_FRAMES: Final[tuple[int, ...]] = (1, 2, 2)
"""The spark frame a placeholder shows for each frame of the held core."""
THEMES: Final[tuple[str, ...]] = tuple(SPARK_EFFECT)

# --- slash (Rook's steel, and every slashing hit) ---------------------------------------------
WHITE: Final[Rgba] = _rgba("ffffff")
SLASH_PALE: Final[Rgba] = _rgba("c7dcd0")
SLASH_ICE: Final[Rgba] = _rgba("8fd3ff")
SLASH_BLUE: Final[Rgba] = _rgba("4d9be6")
SLASH_DEEP: Final[Rgba] = _rgba("4d65b4")
SPLIT_COLOURS: Final[dict[str, tuple[Rgba, Rgba]]] = {
    "slash": (_rgba("e83b3b"), _rgba("30e1b9")),
    "fire": (_rgba("c32454"), _rgba("8ff8e2")),
    "darkness": (_rgba("ed8099"), _rgba("0eaf9b")),
    "earth": (_rgba("cd683d"), _rgba("4d9be6")),
    "wind": (_rgba("f04f78"), _rgba("4d65b4")),
    "electric": (_rgba("c32454"), _rgba("30e1b9")),
    "ice": (_rgba("cf657f"), _rgba("0b8a8f")),
}
"""The two colours of each theme's chromatic split: drawn left and right of the burst."""
SLASH_BURST_REACH: Final[tuple[float, ...]] = (4.0, 6.0, 9.0, 12.0)
"""How far the burst's long rays reach from the contact point, by tier."""
SLASH_CRESCENT: Final[tuple[float, ...]] = (5.0, 7.5, 10.5, 14.0)
"""The radius of the held crescent, by tier."""
SLASH_THICKNESS: Final[tuple[float, ...]] = (1.5, 2.0, 3.0, 3.5)
"""The crescent's thickness at its middle, by tier."""
SLASH_SPAN_DEGREES: Final[float] = 68.0
"""Half the crescent's arc."""
SLASH_SPIKE: Final[tuple[float, ...]] = (3.0, 5.0, 7.0, 9.0)
"""How far the needles reach past the crescent along the launch, by tier."""
SLASH_SPIKE_SPREAD_DEGREES: Final[float] = 24.0
SLASH_LINES: Final[tuple[tuple[float, float, float], ...]] = (
    (0.0, 1.0, 1.0),
    (-3.0, 0.75, 0.8),
    (3.0, 0.6, 0.7),
)
"""Each directional line: ``(sideways offset, length share, start share)``."""
RING_RADII: Final[tuple[float, ...]] = (7.0, 11.0, 14.0, 16.0)
"""The shockwave ring's half-width on each frame (critical rings are 1.3 times as wide)."""
RING_SQUASH: Final[float] = 0.7
"""The ring's height over its width: a little flattened, so it reads as a wave not a halo."""


def _direction(angle: int) -> tuple[Point, Point]:
    """Return the unit direction of a sixteenth on screen in image space (y runs down), and
    the unit direction a quarter turn counter-clockwise from it."""
    turn = 2.0 * math.pi * (angle % ANGLES) / ANGLES
    along = (math.cos(turn), -math.sin(turn))
    return along, (along[1], -along[0])


def _at(centre: float, along: Point, across: Point, forward: float, side: float) -> Point:
    """A point ``forward`` along and ``side`` across from the centre, on whole pixels."""
    return (
        round(centre + along[0] * forward + across[0] * side),
        round(centre + along[1] * forward + across[1] * side),
    )


def _canvas(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw, float]:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image), (size - 1) / 2


def _needle(
    draw: ImageDraw.ImageDraw,
    centre: float,
    along: Point,
    across: Point,
    start: float,
    length: float,
    width: float,
    fill: Rgba,
) -> None:
    """A thin pointed spike from ``start`` to ``start + length`` along the direction."""
    if width < 0.75:
        draw.line(
            (_at(centre, along, across, start, 0.0), _at(centre, along, across, start + length, 0)),
            fill=fill,
        )
        return
    draw.polygon(
        [
            _at(centre, along, across, start, width),
            _at(centre, along, across, start + length, 0.0),
            _at(centre, along, across, start, -width),
        ],
        fill=fill,
    )


def _crescent(
    centre: float,
    along: Point,
    across: Point,
    radius: float,
    thickness: float,
    back: float,
    span_degrees: float = SLASH_SPAN_DEGREES,
) -> list[Point]:
    """A crescent convex along the direction: the arc of a circle centred ``back`` behind the
    centre, thickest in the middle and tapering to points at its tips, ``span_degrees`` to
    either side."""
    span = math.radians(span_degrees)
    steps = max(6, round(radius * 1.5))
    outer, inner = [], []
    for index in range(steps + 1):
        phi = -span + 2.0 * span * index / steps
        taper = math.cos(phi / span * math.pi / 2.0)
        for reach, ring in ((radius, outer), (radius - thickness * taper, inner)):
            forward = -back + reach * math.cos(phi)
            side = reach * math.sin(phi)
            ring.append(_at(centre, along, across, forward, side))
    return outer + inner[::-1]


def _slash_burst(tier: int, frame: int, glints: bool = True) -> Image.Image:
    """A four-point flash, its long rays across the screen, with a ring of glints next
    (``glints`` off: the star alone, the chromatic split's shape)."""
    image, draw, centre = _canvas(SIZES[tier])
    reach = SLASH_BURST_REACH[tier] * (1.0 if frame == 0 else 1.35)
    waist = max(1.0, reach * 0.22)
    for along in ((1.0, 0.0), (0.0, 1.0)):
        across = (along[1], -along[0])
        draw.polygon(
            [
                _at(centre, along, across, reach, 0.0),
                _at(centre, along, across, 0.0, waist),
                _at(centre, along, across, -reach, 0.0),
                _at(centre, along, across, 0.0, -waist),
            ],
            fill=SLASH_ICE if frame else WHITE,
        )
    if frame == 0:
        core = max(1.0, reach * 0.35)
        draw.ellipse((centre - core, centre - core, centre + core, centre + core), fill=WHITE)
    else:
        inner = reach * 0.45
        draw.polygon(
            [(centre + inner, centre), (centre, centre + inner * 0.5),
             (centre - inner, centre), (centre, centre - inner * 0.5)],
            fill=WHITE,
        )  # fmt: skip
        for index in range(8 if glints else 0):
            turn = math.pi / 4.0 * index + math.pi / 8.0
            x = round(centre + math.cos(turn) * (reach * 0.8))
            y = round(centre + math.sin(turn) * (reach * 0.8))
            draw.point((x, y), fill=SLASH_PALE)
    return image


def _slash_core(tier: int, angle: int, frame: int) -> Image.Image:
    """The held cut: a white-blue crescent across the launch, convex along it, with needles
    pointing the way the target will fly; it thins out over its three frames."""
    if angle < 0:
        return _slash_cross(tier, frame)
    image, draw, centre = _canvas(SIZES[tier])
    along, across = _direction(angle)
    radius = SLASH_CRESCENT[tier]
    thickness = SLASH_THICKNESS[tier] * (1.0, 0.8, 0.55)[frame]
    back = radius * 0.6
    draw.polygon(_crescent(centre, along, across, radius, thickness, back), fill=SLASH_BLUE)
    if thickness >= 1.5:
        inner = _crescent(centre, along, across, radius - 0.5, thickness * 0.5, back)
        draw.polygon(inner, fill=WHITE if frame < 2 else SLASH_ICE)
    front = radius - back
    spike = SLASH_SPIKE[tier] + frame
    width = (0.5, 1.0, 1.25, 1.5)[tier] * (1.0, 0.8, 0.5)[frame]
    for turn, share, colour in (
        (0.0, 1.0, WHITE),
        (SLASH_SPIKE_SPREAD_DEGREES, 0.6, SLASH_ICE),
        (-SLASH_SPIKE_SPREAD_DEGREES, 0.6, SLASH_ICE),
    ):
        tilted, tilted_across = _turned(along, turn)
        _needle(draw, centre, tilted, tilted_across, front, spike * share, width * share, colour)
    return image


def _turned(along: Point, degrees: float) -> tuple[Point, Point]:
    """A direction turned ``degrees`` counter-clockwise on screen, and its quarter turn."""
    turn = math.radians(degrees)
    cos, sin = math.cos(turn), math.sin(turn)
    # Counter-clockwise on screen is clockwise in image space (y runs down).
    turned = (along[0] * cos + along[1] * sin, -along[0] * sin + along[1] * cos)
    return turned, (turned[1], -turned[0])


def _slash_cross(tier: int, frame: int) -> Image.Image:
    """The held cut when the launch has no direction on screen: four needles in an X."""
    image, draw, centre = _canvas(SIZES[tier])
    spike = SLASH_SPIKE[tier] + SLASH_CRESCENT[tier] * 0.5 + frame
    width = (0.5, 1.0, 1.25, 1.5)[tier] * (1.0, 0.8, 0.5)[frame]
    for index in range(4):
        along, across = _turned((1.0, 0.0), 45.0 + 90.0 * index)
        _needle(draw, centre, along, across, 1.0, spike, width, WHITE if index % 2 else SLASH_ICE)
    return image


def _lines(
    tier: int, angle: int, start: float, colours: tuple[Rgba, Rgba, Rgba, Rgba]
) -> Image.Image:
    """Speed lines ahead along the launch from ``start``, the middle one longest, and a short
    dim counter-streak behind: 1 px wide, so they never hide what is behind them. ``colours``
    are the main line's, its edge's, the side lines' and the counter-streak's."""
    main, edge_colour, side_colour, counter = colours
    image, draw, centre = _canvas(SIZES[tier])
    along, across = _direction(angle)
    reach = centre - 1.0
    for side, length, first in SLASH_LINES:
        begin = start + (reach - start) * (1.0 - first) * 0.5
        end = min(reach, begin + (reach - start) * length)
        offset = side * (0.6 + 0.2 * tier)
        if side == 0.0:  # the main line has an edge, so it reads on a light stage too
            edge = offset - 1.0
            draw.line(
                (_at(centre, along, across, begin, edge), _at(centre, along, across, end, edge)),
                fill=edge_colour,
            )
        draw.line(
            (_at(centre, along, across, begin, offset), _at(centre, along, across, end, offset)),
            fill=main if side == 0.0 else side_colour,
        )
    back = -start * 0.8
    draw.line(
        (_at(centre, along, across, back, 0.0), _at(centre, along, across, back - reach * 0.35, 0)),
        fill=counter,
    )
    return image


def _slash_lines(tier: int, angle: int) -> Image.Image:
    """The slash's speed lines: white with a blue edge, ice beside, deep blue behind."""
    colours = (WHITE, SLASH_BLUE, SLASH_ICE, SLASH_DEEP)
    return _lines(tier, angle, SLASH_CRESCENT[tier] * 0.55, colours)


def _slash_particle(size: int, angle: int, frame: int) -> Image.Image:
    """A steel spark: a short stroke along its flight, shrinking and cooling as it goes."""
    image, draw, centre = _canvas(PARTICLE_SIZE)
    along, across = _direction(angle)
    length = (3.0, 5.0)[size] - frame
    head_colour = (WHITE, SLASH_ICE, SLASH_BLUE)[frame]
    tail_colour = (SLASH_ICE, SLASH_BLUE, SLASH_DEEP)[frame]
    tail = _at(centre, along, across, -length / 2.0, 0.0)
    head = _at(centre, along, across, length / 2.0, 0.0)
    middle = _at(centre, along, across, 0.0, 0.0)
    draw.line((tail, middle), fill=tail_colour)
    draw.line((middle, head), fill=head_colour)
    return image


def _ring(tier: int, frame: int, colours: tuple[Rgba, Rgba, Rgba]) -> Image.Image:
    """A shockwave ring spreading from the contact point, flattened a little; solid, then
    thinner, then broken into dashes as it fades."""
    width = RING_RADII[frame] * (1.3 if tier > HEAVY else 1.0)
    size = 2 * math.ceil(width) + 3
    image, draw, centre = _canvas(size)
    height = width * RING_SQUASH
    box = (centre - width, centre - height, centre + width, centre + height)
    first, second, third = colours
    if frame < 2:
        draw.ellipse(box, outline=first if frame == 0 else second)
        return image
    dashes = 12
    for index in range(dashes):
        if index % 2:
            continue
        start = 360.0 * index / dashes
        draw.arc(box, start, start + 360.0 / dashes, fill=third if frame == 3 else second)
    return image


def _flare(frame: int, colours: tuple[Rgba, Rgba, Rgba]) -> Image.Image:
    """The critical flare: long thin rays across and up the screen, shorter diagonals, a ring
    of glints; it lengthens and fades over its frames."""
    image, draw, centre = _canvas(FLARE_SIZE)
    first, second, third = colours
    reach = (centre - 8.0, centre - 2.0, centre)[frame]
    for along in ((1.0, 0.0), (0.0, 1.0)):
        for sign in (1.0, -1.0):
            inner = 4.0 + frame * 4.0
            tip = (centre + along[0] * reach * sign, centre + along[1] * reach * sign)
            base = (centre + along[0] * inner * sign, centre + along[1] * inner * sign)
            draw.line((round(base[0]), round(base[1]), round(tip[0]), round(tip[1])),
                      fill=first if frame < 2 else second)  # fmt: skip
    diagonal = reach * 0.45
    for index in range(4):
        turn = math.pi / 4.0 + math.pi / 2.0 * index
        x0 = round(centre + math.cos(turn) * 3.0)
        y0 = round(centre + math.sin(turn) * 3.0)
        x1 = round(centre + math.cos(turn) * diagonal)
        y1 = round(centre + math.sin(turn) * diagonal)
        draw.line((x0, y0, x1, y1), fill=second if frame < 2 else third)
    glints = 8
    for index in range(glints):
        turn = 2.0 * math.pi * index / glints + math.pi / glints
        radius = reach * (0.55 + 0.1 * frame)
        draw.point(
            (round(centre + math.cos(turn) * radius), round(centre + math.sin(turn) * radius)),
            fill=third,
        )
    return image


def _outlined(image: Image.Image, colour: Rgba) -> Image.Image:
    """``image`` with a 1 px outline of ``colour`` round everything drawn (the fighters' own
    outline style), so white and pale art still reads on a light stage."""
    grown = image.getchannel("A").filter(ImageFilter.MaxFilter(3))
    outline = Image.new("RGBA", image.size, colour)
    under = Image.new("RGBA", image.size, (0, 0, 0, 0))
    under.paste(outline, (0, 0), grown.point(lambda alpha: 255 if alpha else 0))
    under.alpha_composite(image)
    return under


def _silhouette(image: Image.Image, colour: Rgba) -> Image.Image:
    """Every drawn pixel of ``image`` in one colour (the chromatic split's copies)."""
    filled = Image.new("RGBA", image.size, colour)
    blank = Image.new("RGBA", image.size, (0, 0, 0, 0))
    mask = image.getchannel("A").point(lambda alpha: 255 if alpha else 0)
    return Image.composite(filled, blank, mask)


# --- fire (Mote's flames, and every fire hit) ---------------------------------------------
FIRE_PALE: Final[Rgba] = _rgba("fbff86")
FIRE_YELLOW: Final[Rgba] = _rgba("f9c22b")
FIRE_ORANGE: Final[Rgba] = _rgba("f79617")
FIRE_DEEP: Final[Rgba] = _rgba("fb6b1d")
FIRE_RED: Final[Rgba] = _rgba("ea4f36")
FIRE_EDGE: Final[Rgba] = _rgba("b33831")
"""The outline of fire's art: brick red, so it reads on light stages."""
SMOKE: Final[Rgba] = _rgba("7f708a")
SMOKE_DARK: Final[Rgba] = _rgba("625565")
FIRE_BURST_REACH: Final[tuple[float, ...]] = (4.0, 6.0, 9.0, 12.0)
"""How far the burst's longest flame points reach, by tier."""
FIRE_BURST_POINTS: Final[tuple[float, ...]] = (1.0, 0.45, 0.72, 0.45)
"""The burst's points in turn, as shares of its reach: long, short, middling, short."""
FIRE_TONGUE: Final[tuple[float, ...]] = (6.0, 9.0, 12.5, 16.0)
"""The length of the held plume's middle flame, by tier."""
FIRE_TONGUE_WIDTH: Final[tuple[float, ...]] = (1.5, 2.0, 2.75, 3.5)
FIRE_SPREAD_DEGREES: Final[float] = 34.0
"""How far the side flames lean from the launch."""
FIRE_FLICKER_DEGREES: Final[tuple[float, ...]] = (0.0, 6.0, -5.0)
"""How the plume sways from frame to frame."""
SMOKE_PUFFS: Final[int] = 10


def _fire_burst(tier: int, frame: int, sparks: bool = True) -> Image.Image:
    """A jagged flash of flame: sixteen points of three lengths, a hot core; next a bigger
    orange one throwing a few sparks (``sparks`` off: the flame alone, the split's shape)."""
    image, draw, centre = _canvas(SIZES[tier])
    reach = FIRE_BURST_REACH[tier] * (1.0 if frame == 0 else 1.3)
    for share, colour in ((1.0, FIRE_YELLOW if frame == 0 else FIRE_ORANGE),
                          (0.55, FIRE_PALE if frame == 0 else FIRE_YELLOW)):  # fmt: skip
        points = []
        for index in range(16):
            turn = 2.0 * math.pi * index / 16 + math.pi / 4.0
            radius = max(1.0, reach * share * FIRE_BURST_POINTS[index % 4])
            points.append((round(centre + math.cos(turn) * radius),
                           round(centre - math.sin(turn) * radius)))  # fmt: skip
        draw.polygon(points, fill=colour)
    if frame == 1 and sparks:
        for index in range(6):
            turn = 2.0 * math.pi * index / 6 + 0.4
            x = round(centre + math.cos(turn) * reach * 1.05)
            y = round(centre - math.sin(turn) * reach * 1.05)
            draw.point((x, y), fill=FIRE_RED if index % 2 else FIRE_YELLOW)
    return image


def _flame(
    draw: ImageDraw.ImageDraw,
    centre: float,
    along: Point,
    across: Point,
    start: float,
    length: float,
    width: float,
    sway: float,
    fill: Rgba,
) -> None:
    """A tongue of flame from ``start`` to ``start + length`` along the direction: broad at
    its root, licking out at one side and in at the other, pointed at its tip."""
    draw.polygon(
        [
            _at(centre, along, across, start, width),
            _at(centre, along, across, start + length * 0.35, width * (0.95 + sway)),
            _at(centre, along, across, start + length * 0.55, width * 0.4),
            _at(centre, along, across, start + length * 0.72, width * (0.55 - sway)),
            _at(centre, along, across, start + length, 0.0),
            _at(centre, along, across, start + length * 0.6, -width * 0.45),
            _at(centre, along, across, start + length * 0.4, -width * (0.85 - sway)),
            _at(centre, along, across, start, -width),
        ],
        fill=fill,
    )


def _fire_core(tier: int, angle: int, frame: int) -> Image.Image:
    """The held plume: three separate flames streaming the way the target will fly, the
    middle one longest and hottest, the side ones leaning out from a little further along;
    they sway, shrink, and lick a flame off ahead over the freeze."""
    if angle < 0:
        return _fire_crown(tier, frame)
    image, draw, centre = _canvas(SIZES[tier])
    along, _ = _direction(angle)
    length = FIRE_TONGUE[tier] * (1.0, 0.9, 0.8)[frame]
    width = FIRE_TONGUE_WIDTH[tier] * (0.85, 0.75, 0.6)[frame]
    sway = (0.0, 0.2, -0.15)[frame]
    flicker = FIRE_FLICKER_DEGREES[frame]
    for lean, share, root, outer, inner in (
        (FIRE_SPREAD_DEGREES, 0.62, width * 1.1, FIRE_RED, FIRE_DEEP),
        (-FIRE_SPREAD_DEGREES, 0.62, width * 1.1, FIRE_RED, FIRE_DEEP),
        (0.0, 1.0, -length * 0.15, FIRE_ORANGE, FIRE_YELLOW),
    ):
        tongue, tongue_across = _turned(along, lean + flicker)
        reach, broad = length * share, width * share
        _flame(draw, centre, tongue, tongue_across, root, reach, broad, sway, outer)
        _flame(draw, centre, tongue, tongue_across, root + reach * 0.12, reach * 0.6,
               broad * 0.45, -sway, inner)  # fmt: skip
    if frame:  # a lick of flame breaking off ahead of the middle one
        tip = length * 0.85 + 1.5 + frame
        lick = max(1.0, width * 0.45)
        draw.polygon(
            [_at(centre, along, (along[1], -along[0]), tip + step, side)
             for step, side in ((0.0, 0.0), (lick, lick * 0.6), (lick * 2.0, 0.0),
                                (lick, -lick * 0.6))],
            fill=FIRE_YELLOW if frame == 1 else FIRE_ORANGE,
        )  # fmt: skip
    return image


def _fire_crown(tier: int, frame: int) -> Image.Image:
    """The held plume when the launch has no direction on screen: six short flames round
    the contact point."""
    image, draw, centre = _canvas(SIZES[tier])
    length = FIRE_TONGUE[tier] * 0.55 * (1.0, 0.9, 0.78)[frame]
    width = FIRE_TONGUE_WIDTH[tier] * 0.7
    for index in range(6):
        along, across = _turned((1.0, 0.0), 60.0 * index + 30.0 + FIRE_FLICKER_DEGREES[frame])
        fill = FIRE_ORANGE if index % 2 else FIRE_YELLOW
        _flame(draw, centre, along, across, 1.0, length, width, 0.1, fill)
    return image


def _fire_lines(tier: int, angle: int) -> Image.Image:
    """Heat streaks: yellow with a red edge, orange beside, smoke behind."""
    colours = (FIRE_YELLOW, FIRE_RED, FIRE_ORANGE, SMOKE)
    return _lines(tier, angle, FIRE_TONGUE[tier] * 0.45, colours)


def _fire_particle(size: int, angle: int, frame: int) -> Image.Image:
    """An ember: a hot dot with a glowing tail behind it, cooling from yellow to red."""
    image, draw, centre = _canvas(PARTICLE_SIZE)
    along, across = _direction(angle)
    middle = round(centre)
    heads = ((FIRE_PALE, FIRE_ORANGE), (FIRE_YELLOW, FIRE_DEEP), (FIRE_RED, FIRE_RED))[frame]
    tail = (2.0, 3.0)[size] - frame
    if tail >= 1.0:
        end = _at(centre, along, across, -tail, 0.0)
        draw.line(((middle, middle), end), fill=heads[1])
    if size and frame == 0:
        draw.rectangle((middle, middle - 1, middle + 1, middle), fill=heads[0])
    else:
        draw.point((middle, middle), fill=heads[0])
    return image


def _puff_ring(tier: int, frame: int, colours: tuple[tuple[Rgba, Rgba], ...]) -> Image.Image:
    """An expanding ring of puffs round a flattened ellipse, thinning out; ``colours`` are
    the two colours the puffs alternate in, on each frame."""
    width = RING_RADII[frame] * (1.3 if tier > HEAVY else 1.0)
    size = 2 * math.ceil(width) + 5
    image, draw, centre = _canvas(size)
    height = width * RING_SQUASH
    puff = (1.5, 1.5, 1.0, 0.5)[frame]
    for index in range(SMOKE_PUFFS):
        if frame == 3 and index % 2:
            continue
        turn = 2.0 * math.pi * index / SMOKE_PUFFS + frame * 0.2
        x = centre + math.cos(turn) * width
        y = centre + math.sin(turn) * height
        colour = colours[frame][index % 2]
        draw.ellipse((round(x - puff), round(y - puff), round(x + puff), round(y + puff)),
                     fill=colour)  # fmt: skip
    return image


def _smoke_ring(tier: int, frame: int) -> Image.Image:
    """An expanding smoke ring: glowing at first, then grey and thinning out."""
    colours = ((FIRE_ORANGE, SMOKE), (SMOKE, SMOKE_DARK), (SMOKE_DARK, SMOKE), (SMOKE_DARK,) * 2)
    return _puff_ring(tier, frame, colours)


# --- darkness (Mote's shadow magic) -------------------------------------------------------
DARK_PALE: Final[Rgba] = _rgba("eaaded")
DARK_LILAC: Final[Rgba] = _rgba("a884f3")
DARK_VIOLET: Final[Rgba] = _rgba("905ea9")
DARK_DEEP: Final[Rgba] = _rgba("6b3e75")
DARK_VOID: Final[Rgba] = _rgba("2e222f")
DARK_EDGE: Final[Rgba] = _rgba("45293f")
"""The outline of darkness's art: deep plum, so it reads on light stages."""
DARK_VOID_RADIUS: Final[tuple[float, ...]] = (2.0, 3.0, 4.0, 5.5)
"""The radius of the void at the burst's heart, by tier."""
DARK_WISP: Final[tuple[float, ...]] = (6.5, 9.5, 13.0, 17.0)
"""How far the held wisps reach along the launch, by tier."""
DARK_WISP_WAVE: Final[tuple[float, ...]] = (1.2, 1.8, 2.6, 3.2)
"""How far the wisps wave to the side, by tier."""
IMPLOSION_RADII: Final[tuple[float, ...]] = (16.0, 12.0, 8.0, 4.0)
"""The implosion ring's half-width on each frame: it closes in, where a shockwave spreads."""


def _dark_burst(tier: int, frame: int, rim: bool = True) -> Image.Image:
    """A hole torn in the light: a dark void with a pale violet halo and four spikes pointing
    in at it; next it closes, its spikes longer (``rim`` off: the halo's shape alone, the
    split's)."""
    image, draw, centre = _canvas(SIZES[tier])
    void = DARK_VOID_RADIUS[tier] * (1.0 if frame == 0 else 0.6)
    reach = void * 2.2 + frame * 1.5
    halo = void + 1.5
    draw.ellipse((centre - halo, centre - halo, centre + halo, centre + halo),
                 fill=DARK_LILAC if frame == 0 else DARK_VIOLET)  # fmt: skip
    for index in range(4):
        along, across = _turned((1.0, 0.0), 45.0 + 90.0 * index)
        tip = _at(centre, along, across, halo - 0.5, 0.0)
        draw.polygon(
            [tip, _at(centre, along, across, reach, 1.2), _at(centre, along, across, reach, -1.2)],
            fill=DARK_PALE if frame == 0 else DARK_LILAC,
        )
    if rim:
        draw.ellipse((centre - void, centre - void, centre + void, centre + void), fill=DARK_VOID)
        if frame == 0:
            draw.point((round(centre - void * 0.4), round(centre - void * 0.4)), fill=DARK_PALE)
    return image


def _wisp(
    draw: ImageDraw.ImageDraw,
    centre: float,
    along: Point,
    across: Point,
    side: float,
    length: float,
    wave: float,
    phase: float,
    colours: tuple[Rgba, Rgba],
    root_width: int = 2,
) -> None:
    """A curling tendril of shadow from near the centre out along the direction, waving more
    the further it goes, ``root_width`` px thick at its root and 1 px after."""
    steps = max(4, round(length))
    points = []
    for index in range(steps + 1):
        share = index / steps
        sway = math.sin(phase + share * math.pi * 1.6) * wave * share
        points.append(_at(centre, along, across, 1.0 + share * length, side + sway))
    root, tip = points[: steps // 2 + 1], points[steps // 2 :]
    draw.line(root, fill=colours[0], width=root_width)
    draw.line(tip, fill=colours[1], width=1)


def _dark_core(tier: int, angle: int, frame: int) -> Image.Image:
    """The held shadow: a small void at the contact point and three violet wisps trailing
    the way the target will fly, waving and stretching over the freeze."""
    if angle < 0:
        return _dark_swirl(tier, frame)
    image, draw, centre = _canvas(SIZES[tier])
    along, across = _direction(angle)
    length = DARK_WISP[tier] * (0.85, 0.95, 1.0)[frame]
    wave = DARK_WISP_WAVE[tier]
    spread = 1.5 + tier * 0.9
    for side, share, phase, colours, thick in (
        (spread, 0.75, 0.4, (DARK_VIOLET, DARK_DEEP), 1),
        (-spread, 0.75, 2.6, (DARK_VIOLET, DARK_DEEP), 1),
        (0.0, 1.0, 1.3, (DARK_LILAC, DARK_VIOLET), 2),
    ):
        _wisp(draw, centre, along, across, side, length * share, wave,
              phase + frame * 1.1, colours, thick)  # fmt: skip
    void = max(1.0, DARK_VOID_RADIUS[tier] * 0.6)
    draw.ellipse((centre - void, centre - void, centre + void, centre + void),
                 fill=DARK_VOID, outline=DARK_LILAC)  # fmt: skip
    return image


def _dark_swirl(tier: int, frame: int) -> Image.Image:
    """The held shadow when the launch has no direction on screen: wisps curling round the
    void, as if it were drawing them in."""
    image, draw, centre = _canvas(SIZES[tier])
    length = DARK_WISP[tier] * 0.6
    for index in range(4):
        along, across = _turned((1.0, 0.0), 90.0 * index + frame * 20.0)
        colours = (DARK_LILAC, DARK_VIOLET) if index % 2 else (DARK_VIOLET, DARK_DEEP)
        _wisp(draw, centre, along, across, 0.0, length, DARK_WISP_WAVE[tier], 0.0, colours)
    void = max(1.0, DARK_VOID_RADIUS[tier] * 0.6)
    draw.ellipse((centre - void, centre - void, centre + void, centre + void),
                 fill=DARK_VOID, outline=DARK_LILAC)  # fmt: skip
    return image


def _dark_lines(tier: int, angle: int) -> Image.Image:
    """Shadow streaks: lilac with a deep violet edge, violet beside, plum behind."""
    colours = (DARK_LILAC, DARK_DEEP, DARK_VIOLET, DARK_EDGE)
    return _lines(tier, angle, DARK_WISP[tier] * 0.5, colours)


def _dark_particle(size: int, angle: int, frame: int) -> Image.Image:
    """A mote of shadow: a dark speck ringed in lilac, a wisp of tail behind, fading to plum."""
    image, draw, centre = _canvas(PARTICLE_SIZE)
    along, across = _direction(angle)
    middle = round(centre)
    tail = (2.0, 3.0)[size] - frame
    if tail >= 1.0:
        draw.line(((middle, middle), _at(centre, along, across, -tail, 0.0)),
                  fill=(DARK_VIOLET, DARK_DEEP, DARK_EDGE)[frame])  # fmt: skip
    if size and frame == 0:
        draw.rectangle((middle - 1, middle - 1, middle + 1, middle + 1), fill=DARK_LILAC)
        draw.point((middle, middle), fill=DARK_VOID)
    else:
        draw.point((middle, middle), fill=(DARK_PALE, DARK_LILAC, DARK_VIOLET)[frame])
    return image


def _implosion_ring(tier: int, frame: int) -> Image.Image:
    """The implosion: a ring that starts wide and closes in on the contact point, dashed
    while wide, then solid, ending in a dark point."""
    widest = IMPLOSION_RADII[0] * (1.3 if tier > HEAVY else 1.0)
    width = IMPLOSION_RADII[frame] * (1.3 if tier > HEAVY else 1.0)
    size = 2 * math.ceil(widest) + 3
    image, draw, centre = _canvas(size)
    height = width * RING_SQUASH
    box = (centre - width, centre - height, centre + width, centre + height)
    if frame == 0:
        dashes = 14
        for index in range(0, dashes, 2):
            start = 360.0 * index / dashes
            draw.arc(box, start, start + 360.0 / dashes, fill=DARK_PALE)
    else:
        draw.ellipse(box, outline=(DARK_LILAC, DARK_VIOLET, DARK_DEEP)[frame - 1])
    if frame == 3:
        draw.point((round(centre), round(centre)), fill=DARK_VOID)
    return image


# --- earth (Bramble's stone and moss) -----------------------------------------------------
STONE_PALE: Final[Rgba] = _rgba("c7dcd0")
STONE: Final[Rgba] = _rgba("9babb2")
STONE_DARK: Final[Rgba] = _rgba("7f708a")
STONE_DEEP: Final[Rgba] = _rgba("625565")
CRYSTAL_PALE: Final[Rgba] = _rgba("8ff8e2")
CRYSTAL: Final[Rgba] = _rgba("30e1b9")
CRYSTAL_DEEP: Final[Rgba] = _rgba("0eaf9b")
LEAF: Final[Rgba] = _rgba("91db69")
LEAF_DARK: Final[Rgba] = _rgba("1ebc73")
EARTH_EDGE: Final[Rgba] = _rgba("3e3546")
"""The outline of earth's art: deep slate, so it reads on light stages."""
EARTH_BURST_REACH: Final[tuple[float, ...]] = (4.0, 6.0, 9.0, 12.0)
EARTH_BURST_POINTS: Final[tuple[float, ...]] = (1.0, 0.55, 0.85, 0.5, 0.95, 0.6)
"""The burst's six spikes, as shares of its reach: an uneven, broken-rock star."""
EARTH_SHARD: Final[tuple[float, ...]] = (6.0, 8.5, 12.0, 15.5)
"""The length of the held fan's middle crystal shard, by tier."""
EARTH_SHARD_WIDTH: Final[tuple[float, ...]] = (1.25, 1.75, 2.5, 3.0)
EARTH_FAN_DEGREES: Final[float] = 36.0
"""How far the side shards lean from the launch."""


def _earth_burst(tier: int, frame: int, chips: bool = True) -> Image.Image:
    """A rock cracking under the blow: an uneven six-spiked star of pale stone round a white
    point; next it breaks into its spikes with chips flying (``chips`` off: the star alone,
    the split's shape)."""
    image, draw, centre = _canvas(SIZES[tier])
    reach = EARTH_BURST_REACH[tier] * (1.0 if frame == 0 else 1.3)
    points = []
    for index, share in enumerate(EARTH_BURST_POINTS):
        turn = 2.0 * math.pi * index / 6 + 0.3
        tip = reach * share
        notch = reach * 0.3
        middle = turn + math.pi / 6
        points.append((round(centre + math.cos(turn) * tip), round(centre - math.sin(turn) * tip)))
        points.append((round(centre + math.cos(middle) * notch),
                       round(centre - math.sin(middle) * notch)))  # fmt: skip
    draw.polygon(points, fill=STONE_PALE if frame == 0 else STONE)
    core = max(1.0, reach * 0.22)
    draw.rectangle((round(centre - core), round(centre - core), round(centre + core),
                    round(centre + core)), fill=WHITE if frame == 0 else STONE_PALE)  # fmt: skip
    if frame == 1 and chips:
        for index in range(5):
            turn = 2.0 * math.pi * index / 5 + 0.9
            x = round(centre + math.cos(turn) * reach * 1.1)
            y = round(centre - math.sin(turn) * reach * 1.1)
            draw.rectangle((x, y, x + 1, y + 1), fill=STONE_DARK if index % 2 else CRYSTAL)
    return image


def _shard(
    draw: ImageDraw.ImageDraw,
    centre: float,
    along: Point,
    across: Point,
    start: float,
    length: float,
    width: float,
    colours: tuple[Rgba, Rgba],
) -> None:
    """A crystal shard from ``start`` out along the direction: a long pointed prism, its lit
    facet (one side) paler than the other."""
    base, shoulder, tip = start, start + length * 0.3, start + length
    draw.polygon(
        [
            _at(centre, along, across, base, width * 0.6),
            _at(centre, along, across, shoulder, width),
            _at(centre, along, across, tip, 0.0),
            _at(centre, along, across, shoulder, -width),
            _at(centre, along, across, base, -width * 0.6),
        ],
        fill=colours[1],
    )
    draw.polygon(
        [
            _at(centre, along, across, base, width * 0.6),
            _at(centre, along, across, shoulder, width),
            _at(centre, along, across, tip, 0.0),
            _at(centre, along, across, shoulder, 0.0),
        ],
        fill=colours[0],
    )


def _chunk(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, shade: int) -> None:
    """A small angular rock at ``(x, y)``: a pale top over a darker side."""
    top = [(round(x - size), round(y)), (round(x), round(y - size * 0.7)),
           (round(x + size), round(y - size * 0.2)), (round(x + size * 0.4), round(y + size * 0.6)),
           (round(x - size * 0.6), round(y + size * 0.5))]  # fmt: skip
    draw.polygon(top, fill=(STONE, STONE_DARK)[shade])
    draw.line([top[0], top[1], top[2]], fill=(STONE_PALE, STONE)[shade])


def _earth_core(tier: int, angle: int, frame: int) -> Image.Image:
    """The held break: a fan of three crystal shards jutting the way the target will fly,
    rock chunks knocked loose beside them; the shards crack over the freeze."""
    if angle < 0:
        return _earth_geode(tier, frame)
    image, draw, centre = _canvas(SIZES[tier])
    along, _ = _direction(angle)
    length = EARTH_SHARD[tier] * (0.9, 1.0, 1.0)[frame]
    width = EARTH_SHARD_WIDTH[tier]
    for lean, share, root, colours in (
        (EARTH_FAN_DEGREES, 0.6, width * 1.3, (CRYSTAL, CRYSTAL_DEEP)),
        (-EARTH_FAN_DEGREES, 0.6, width * 1.3, (CRYSTAL, CRYSTAL_DEEP)),
        (0.0, 1.0, -length * 0.15, (CRYSTAL_PALE, CRYSTAL)),
    ):
        shard, shard_across = _turned(along, lean)
        _shard(draw, centre, shard, shard_across, root, length * share, width * share,
               colours)  # fmt: skip
        if frame == 2:  # cracked: a gap across the shard
            crack = root + length * share * 0.55
            ends = (
                _at(centre, shard, shard_across, crack, width),
                _at(centre, shard, shard_across, crack, -width),
            )
            draw.line(ends, fill=(0, 0, 0, 0))  # the outline then draws the crack dark
    rocks = ((-length * 0.25, length * 0.45), (-length * 0.3, -length * 0.5))
    for index, (forward, side) in enumerate(rocks):
        x, y = _at(centre, along, (along[1], -along[0]), forward + frame * 0.6, side)
        _chunk(draw, x, y, 1.0 + tier * 0.5, index % 2)
    return image


def _earth_geode(tier: int, frame: int) -> Image.Image:
    """The held break when the launch has no direction on screen: five crystal shards
    jutting all round, like a split geode."""
    image, draw, centre = _canvas(SIZES[tier])
    length = EARTH_SHARD[tier] * 0.65 * (0.9, 1.0, 1.0)[frame]
    width = EARTH_SHARD_WIDTH[tier] * 0.8
    for index in range(5):
        along, across = _turned((1.0, 0.0), 72.0 * index + 90.0)
        colours = (CRYSTAL_PALE, CRYSTAL) if index % 2 == 0 else (CRYSTAL, CRYSTAL_DEEP)
        _shard(draw, centre, along, across, 1.0, length, width, colours)
    return image


def _earth_lines(tier: int, angle: int) -> Image.Image:
    """Dust streaks: pale stone with a slate edge, stone beside, dark dust behind."""
    colours = (STONE_PALE, STONE_DARK, STONE, STONE_DEEP)
    return _lines(tier, angle, EARTH_SHARD[tier] * 0.5, colours)


def _earth_particle(size: int, angle: int, frame: int) -> Image.Image:
    """A rock chip, or on odd angles a torn leaf: they fall and darken as they go."""
    image, draw, centre = _canvas(PARTICLE_SIZE)
    middle = round(centre)
    if angle % 2:
        along, across = _direction(angle)
        colour = (LEAF, LEAF_DARK, LEAF_DARK)[frame]
        reach = (1.5, 2.5)[size] - (frame > 1)
        draw.line((_at(centre, along, across, -reach, 0.5), _at(centre, along, across, reach, 0)),
                  fill=colour)  # fmt: skip
        if size and frame < 2:
            draw.point(_at(centre, along, across, 0.0, -1.0), fill=LEAF_DARK)
        return image
    top, side = ((STONE_PALE, STONE), (STONE, STONE_DARK), (STONE_DARK, STONE_DEEP))[frame]
    if size:
        draw.rectangle((middle - 1, middle - 1, middle + 1, middle), fill=top)
        draw.line((middle - 1, middle + 1, middle + 1, middle + 1), fill=side)
    else:
        draw.point((middle, middle), fill=top)
        draw.point((middle, middle + 1), fill=side)
    return image


def _dust_ring(tier: int, frame: int) -> Image.Image:
    """A ring of dust thrown out round the contact point: stone grey, then darker (pale
    stone would vanish on a light stage, whose tiles are that colour)."""
    colours = ((STONE, STONE_DARK), (STONE_DARK, STONE_DEEP), (STONE_DEEP, STONE_DARK),
               (STONE_DEEP,) * 2)  # fmt: skip
    return _puff_ring(tier, frame, colours)


# --- wind (Zephyr's gusts) ----------------------------------------------------------------
WIND_PALE: Final[Rgba] = _rgba("c7dcd0")
WIND_MINT: Final[Rgba] = _rgba("8ff8e2")
WIND_TEAL: Final[Rgba] = _rgba("30e1b9")
WIND_DEEP: Final[Rgba] = _rgba("0b8a8f")
WIND_EDGE: Final[Rgba] = _rgba("0b5e65")
"""The outline of wind's art: deep teal, so the white reads on light stages."""
WIND_BURST_REACH: Final[tuple[float, ...]] = (4.0, 6.0, 8.5, 11.0)
WIND_ARCS: Final[tuple[tuple[float, float, float], ...]] = (
    (0.45, 1.6, 74.0),
    (0.7, 1.3, 62.0),
    (0.95, 1.0, 50.0),
)
"""The held gust's nested crescents: ``(distance as a share of its reach, thickness, half
span in degrees)``: the nearer ones wider, the farther ones thinner."""
WIND_REACH: Final[tuple[float, ...]] = (6.5, 9.5, 13.5, 17.5)
WIND_DOUBLE_RING: Final[float] = 9.0
"""A shock ring at least this wide (half-width, px) is drawn double; a narrower one would be
a solid blob."""
"""How far the held gust's farthest crescent sits along the launch, by tier."""


def _wind_burst(tier: int, frame: int, swirl: bool = True) -> Image.Image:
    """A puff of air: a white core with three arcs spiralling round it; next a wider, mint
    spiral (``swirl`` off: the core alone, the split's shape)."""
    image, draw, centre = _canvas(SIZES[tier])
    reach = WIND_BURST_REACH[tier] * (1.0 if frame == 0 else 1.35)
    core = max(1.5, reach * (0.45 if frame == 0 else 0.3))
    draw.ellipse((centre - core, centre - core, centre + core, centre + core),
                 fill=WHITE if frame == 0 else WIND_MINT)  # fmt: skip
    if not swirl:
        return image
    box = (centre - reach, centre - reach, centre + reach, centre + reach)
    for index in range(3):
        start = 120.0 * index + frame * 40.0
        draw.arc(box, start, start + 75.0, fill=WHITE if frame == 0 else WIND_MINT,
                 width=2 if frame == 0 else 1)  # fmt: skip
        inner = reach * 0.7
        draw.arc((centre - inner, centre - inner, centre + inner, centre + inner),
                 start + 60.0, start + 110.0, fill=WIND_TEAL)  # fmt: skip
    return image


def _wind_core(tier: int, angle: int, frame: int) -> Image.Image:
    """The held gust: three thin nested crescents of air sweeping the way the target will
    fly, rippling outward over the freeze, the farthest fading."""
    if angle < 0:
        return _wind_ring_of_air(tier, frame)
    image, draw, centre = _canvas(SIZES[tier])
    along, across = _direction(angle)
    reach = WIND_REACH[tier]
    colours = ((WHITE, WIND_MINT, WIND_TEAL), (WIND_MINT, WHITE, WIND_MINT),
               (WIND_TEAL, WIND_MINT, WHITE))[frame]  # fmt: skip
    for (share, thickness, span), colour in zip(WIND_ARCS, colours, strict=True):
        distance = reach * share + frame * 0.8
        radius = max(3.0, reach * 0.55)
        back = radius - distance
        scale = 0.6 + 0.2 * tier
        crescent = _crescent(centre, along, across, radius, thickness * scale, back, span)
        draw.polygon(crescent, fill=colour)
    return image


def _wind_ring_of_air(tier: int, frame: int) -> Image.Image:
    """The held gust when the launch has no direction on screen: a broken ring of air round
    the contact point, turning."""
    image, draw, centre = _canvas(SIZES[tier])
    radius = WIND_REACH[tier] * 0.55 + frame * 0.6
    box = (centre - radius, centre - radius, centre + radius, centre + radius)
    for index in range(4):
        start = 90.0 * index + frame * 25.0
        draw.arc(box, start, start + 55.0, fill=WHITE if index % 2 else WIND_MINT, width=2)
    return image


def _wind_lines(tier: int, angle: int) -> Image.Image:
    """Air streaks: white with a teal edge, mint beside, deep teal behind."""
    colours = (WHITE, WIND_DEEP, WIND_MINT, WIND_DEEP)
    return _lines(tier, angle, WIND_REACH[tier] * 0.5, colours)


def _wind_particle(size: int, angle: int, frame: int) -> Image.Image:
    """A wisp of air: a short stroke along its flight with a curl at its head, fading from
    white to teal."""
    image, draw, centre = _canvas(PARTICLE_SIZE)
    along, across = _direction(angle)
    length = (2.0, 3.0)[size] - frame * 0.5
    colour = (WHITE, WIND_MINT, WIND_TEAL)[frame]
    head = _at(centre, along, across, length / 2.0, 0.0)
    draw.line((_at(centre, along, across, -length / 2.0, 0.0), head), fill=colour)
    if frame < 2:
        draw.point(_at(centre, along, across, length / 2.0 - 1.0, 1.0), fill=WIND_MINT)
    return image


def _shock_ring(tier: int, frame: int) -> Image.Image:
    """A sharp double shock ring of air spreading from the contact point: two thin rings at
    first, then one, dashed as it fades."""
    width = RING_RADII[frame] * (1.3 if tier > HEAVY else 1.0)
    size = 2 * math.ceil(width) + 3
    image, draw, centre = _canvas(size)
    height = width * RING_SQUASH
    box = (centre - width, centre - height, centre + width, centre + height)
    if frame < 2:
        draw.ellipse(box, outline=WHITE if frame == 0 else WIND_MINT)
        if width >= WIND_DOUBLE_RING:  # room inside for the second ring
            inner = (box[0] + 3, box[1] + 2, box[2] - 3, box[3] - 2)
            draw.ellipse(inner, outline=WIND_MINT if frame == 0 else WIND_TEAL)
        return image
    dashes = 16
    for index in range(0, dashes, 2):
        start = 360.0 * index / dashes + frame * 10.0
        draw.arc(box, start, start + 360.0 / dashes, fill=WIND_MINT if frame == 2 else WIND_TEAL)
    return image


# --- electric (lightning: Storm Galleon's bolts, and every electric hit) -------------------
VOLT_PALE: Final[Rgba] = _rgba("fbff86")
VOLT_YELLOW: Final[Rgba] = _rgba("f9c22b")
VOLT_BLUE: Final[Rgba] = _rgba("8fd3ff")
VOLT_EDGE: Final[Rgba] = _rgba("484a77")
"""The outline of electric's art: the storm's navy (the lightning hazard's own colours)."""
VOLT_BOLT: Final[tuple[float, ...]] = (7.0, 10.0, 14.0, 18.0)
"""How far the held bolt reaches along the launch, by tier."""
VOLT_JAGS: Final[tuple[tuple[tuple[float, float], ...], ...]] = (
    ((0.0, 0.0), (0.3, 1.0), (0.42, -0.8), (0.72, 0.7), (1.0, -0.2)),
    ((0.0, 0.0), (0.25, -0.9), (0.5, 0.9), (0.62, -0.5), (1.0, 0.2)),
    ((0.0, 0.0), (0.35, 0.8), (0.5, -1.0), (0.78, 0.8), (1.0, 0.0)),
)
"""The bolt's joints on each frame of the hold: ``(how far along, how far to the side as a
share of the tier's jag)``, unevenly spaced like real lightning, a new shape each frame."""
VOLT_JAG: Final[tuple[float, ...]] = (1.0, 1.5, 2.2, 3.0)


def _zigzag(
    centre: float,
    along: Point,
    across: Point,
    start: float,
    length: float,
    jag: float,
    joints: tuple[tuple[float, float], ...],
) -> list[Point]:
    """The joints of a lightning bolt from ``start`` out along the direction."""
    return [
        _at(centre, along, across, start + length * share, jag * side) for share, side in joints
    ]


def _bolt(draw: ImageDraw.ImageDraw, joints: list[Point], across: Point, glow: bool) -> None:
    """A bolt along ``joints``: one white pixel wide, with a pale yellow glow a pixel to one
    side when ``glow``."""
    if glow:
        shifted = [(round(x + across[0]), round(y + across[1])) for x, y in joints]
        draw.line(shifted, fill=VOLT_PALE)
    draw.line(joints, fill=WHITE)


CRACKLE: Final[tuple[tuple[float, float], ...]] = ((0.0, 0.0), (0.4, 1.0), (0.7, -1.0), (1.0, 0.0))
"""The joints of the short zigzags of the burst, the crackle and a spark."""


def _volt_burst(tier: int, frame: int, crackle: bool = True) -> Image.Image:
    """A crackle of power: a white core with six short zigzags jumping out of it; next the
    zigzags longer with blue tips (``crackle`` off: the core alone, the split's shape)."""
    image, draw, centre = _canvas(SIZES[tier])
    core = max(1.5, (1.5, 2.0, 3.0, 4.0)[tier] * (1.0 if frame == 0 else 0.7))
    draw.ellipse((centre - core, centre - core, centre + core, centre + core),
                 fill=WHITE if frame == 0 else VOLT_PALE)  # fmt: skip
    if not crackle:
        return image
    reach = VOLT_BOLT[tier] * (0.5 if frame == 0 else 0.7)
    for index in range(6):
        along, across = _turned((1.0, 0.0), 60.0 * index + 15.0 + frame * 30.0)
        joints = _zigzag(centre, along, across, core, reach - core, 1.0, CRACKLE)
        _bolt(draw, joints, across, tier >= HEAVY and frame == 0)
        if frame == 1:
            draw.point(joints[-1], fill=VOLT_BLUE)
    return image


def _volt_core(tier: int, angle: int, frame: int) -> Image.Image:
    """The held bolt: forked lightning from the contact point along the launch, flickering
    to a new zigzag on each frame, with two forks branching off it."""
    if angle < 0:
        return _volt_crackle(tier, frame)
    image, draw, centre = _canvas(SIZES[tier])
    along, across = _direction(angle)
    length = VOLT_BOLT[tier]
    jag = VOLT_JAG[tier]
    joints = _zigzag(centre, along, across, -length * 0.1, length, jag, VOLT_JAGS[frame])
    _bolt(draw, joints, across, tier >= 1)
    for joint, lean in ((2, 35.0),) if tier else ():
        fork, fork_across = _turned(along, lean if frame != 1 else -lean)
        x, y = joints[joint]
        branch = [(x, y)]
        for step, side in ((0.2, 0.8), (0.4, -0.4)):
            dx = fork[0] * length * step + fork_across[0] * jag * side
            dy = fork[1] * length * step + fork_across[1] * jag * side
            branch.append((round(x + dx), round(y + dy)))
        draw.line(branch, fill=VOLT_BLUE if frame == 2 else VOLT_PALE)
    return image


def _volt_crackle(tier: int, frame: int) -> Image.Image:
    """The held bolt when the launch has no direction on screen: four short zigzags
    crackling round the contact point, jumping to new places each frame."""
    image, draw, centre = _canvas(SIZES[tier])
    reach = VOLT_BOLT[tier] * 0.55
    for index in range(4):
        along, across = _turned((1.0, 0.0), 90.0 * index + 45.0 + frame * 22.5)
        joints = _zigzag(centre, along, across, 1.5, reach, VOLT_JAG[tier] * 0.5, CRACKLE)
        _bolt(draw, joints, across, tier >= HEAVY)
    return image


def _volt_lines(tier: int, angle: int) -> Image.Image:
    """Charged streaks: pale yellow with a navy edge, blue beside, navy behind."""
    colours = (VOLT_PALE, VOLT_EDGE, VOLT_BLUE, VOLT_EDGE)
    return _lines(tier, angle, VOLT_BOLT[tier] * 0.5, colours)


def _volt_particle(size: int, angle: int, frame: int) -> Image.Image:
    """A spark: a tiny zigzag along its flight, white, then pale yellow, then blue."""
    image, draw, centre = _canvas(PARTICLE_SIZE)
    along, across = _direction(angle)
    length = (2.0, 3.0)[size]
    colour = (WHITE, VOLT_PALE, VOLT_BLUE)[frame]
    if frame == 2:
        draw.point((round(centre), round(centre)), fill=colour)
        return image
    joints = _zigzag(centre, along, across, -length / 2.0, length, 1.0, CRACKLE)
    draw.line(joints, fill=colour)
    return image


def _volt_ring(tier: int, frame: int) -> Image.Image:
    """A ring of crackling charge spreading from the contact point: an ellipse whose edge
    jumps in and out, white, then pale yellow, then broken and blue."""
    width = RING_RADII[frame] * (1.3 if tier > HEAVY else 1.0)
    size = 2 * math.ceil(width + 1.0) + 3
    image, draw, centre = _canvas(size)
    points = []
    teeth = 18
    for index in range(teeth):
        turn = 2.0 * math.pi * index / teeth
        reach = width + (1.0 if index % 2 else -1.0)
        points.append((round(centre + math.cos(turn) * reach),
                       round(centre + math.sin(turn) * reach * RING_SQUASH)))  # fmt: skip
    colour = (WHITE, VOLT_PALE, VOLT_BLUE, VOLT_BLUE)[frame]
    if frame < 2:
        draw.line([*points, points[0]], fill=colour)
    else:
        for index in range(0, teeth, 3 if frame == 2 else 4):
            draw.line([points[index], points[(index + 1) % teeth]], fill=colour)
    return image


# --- ice (frost and icicles; no move or hazard is icy today) -------------------------------
FROST: Final[Rgba] = _rgba("c7dcd0")
ICE_BLUE: Final[Rgba] = _rgba("8fd3ff")
ICE_DEEP: Final[Rgba] = _rgba("4d9be6")
ICE_EDGE: Final[Rgba] = _rgba("484a77")
"""The outline of ice's art: navy, so the white and frost read on light stages."""
ICE_FLAKE: Final[tuple[float, ...]] = (4.0, 6.0, 8.5, 11.0)
"""How far a snowflake's arms reach, by tier."""
ICICLE: Final[tuple[float, ...]] = (6.5, 9.5, 13.5, 17.0)
"""The length of the held fan's longest icicle, by tier."""
ICICLE_WIDTH: Final[tuple[float, ...]] = (1.0, 1.5, 2.0, 2.5)
ICICLES: Final[tuple[tuple[float, float, float], ...]] = (
    (0.0, 1.0, 0.0),
    (22.0, 0.7, 1.6),
    (-22.0, 0.7, 1.6),
)
"""The held fan's icicles: ``(lean in degrees, length as a share, how far out its root is as
a share of the icicle's width)``: the side ones start further along, so the three stay
apart."""


def _snowflake(
    draw: ImageDraw.ImageDraw,
    centre: float,
    reach: float,
    turn: float,
    arm: Rgba,
    branch: Rgba,
) -> None:
    """A six-armed snowflake: arms ``reach`` long, each with a pair of side branches."""
    for index in range(6):
        along, across = _turned((1.0, 0.0), turn + 60.0 * index)
        draw.line((_at(centre, along, across, 0.0, 0.0), _at(centre, along, across, reach, 0.0)),
                  fill=arm)  # fmt: skip
        if reach >= 4.0:
            fork = reach * 0.55
            for side in (1.0, -1.0):
                draw.line((_at(centre, along, across, fork, 0.0),
                           _at(centre, along, across, fork + reach * 0.25, side * reach * 0.22)),
                          fill=branch)  # fmt: skip


def _ice_burst(tier: int, frame: int, branches: bool = True) -> Image.Image:
    """A flash of frost: a white snowflake round a pale core; next bigger, its arms ice blue
    (``branches`` off: the core and arms only, the split's shape)."""
    image, draw, centre = _canvas(SIZES[tier])
    reach = ICE_FLAKE[tier] * (1.0 if frame == 0 else 1.3)
    core = max(1.0, reach * 0.25)
    draw.ellipse((centre - core, centre - core, centre + core, centre + core),
                 fill=WHITE if frame == 0 else FROST)  # fmt: skip
    arm = WHITE if frame == 0 else ICE_BLUE
    _snowflake(draw, centre, reach, 30.0 * frame, arm, FROST if branches else (0, 0, 0, 0))
    return image


def _icicle(
    draw: ImageDraw.ImageDraw,
    centre: float,
    along: Point,
    across: Point,
    start: float,
    length: float,
    width: float,
) -> None:
    """An icicle from ``start`` out along the direction: a long thin spike, white on its lit
    side and ice blue on the other."""
    base_left = _at(centre, along, across, start, width)
    base_right = _at(centre, along, across, start, -width)
    middle = _at(centre, along, across, start, 0.0)
    tip = _at(centre, along, across, start + length, 0.0)
    draw.polygon([base_left, tip, base_right], fill=ICE_BLUE)
    draw.polygon([base_left, tip, middle], fill=WHITE)


def _ice_core(tier: int, angle: int, frame: int) -> Image.Image:
    """The held frost: a narrow spray of icicles shooting the way the target will fly from a
    small snowflake at the contact point; they lengthen, then frost over."""
    if angle < 0:
        return _ice_flake_core(tier, frame)
    image, draw, centre = _canvas(SIZES[tier])
    along, _ = _direction(angle)
    length = ICICLE[tier] * (0.85, 1.0, 1.0)[frame]
    width = ICICLE_WIDTH[tier]
    for lean, share, root in ICICLES:
        spike, spike_across = _turned(along, lean)
        broad = width * (0.6 + share * 0.4)
        _icicle(draw, centre, spike, spike_across, 1.0 + width * root, length * share, broad)
    _snowflake(draw, centre, max(2.0, ICE_FLAKE[tier] * 0.45), 15.0, FROST, FROST)
    if frame == 2:  # frosting over: pale flecks along the longest icicle
        for share in (0.35, 0.65):
            draw.point(_at(centre, along, (along[1], -along[0]), length * share, 0.0), fill=FROST)
    return image


def _ice_flake_core(tier: int, frame: int) -> Image.Image:
    """The held frost when the launch has no direction on screen: a big snowflake, turning a
    little each frame."""
    image, draw, centre = _canvas(SIZES[tier])
    _snowflake(draw, centre, ICICLE[tier] * 0.6, 10.0 * frame, WHITE, ICE_BLUE)
    return image


def _ice_lines(tier: int, angle: int) -> Image.Image:
    """Frost streaks: white with an ice blue edge, frost beside, navy behind."""
    colours = (WHITE, ICE_DEEP, FROST, ICE_EDGE)
    return _lines(tier, angle, ICICLE[tier] * 0.5, colours)


def _ice_particle(size: int, angle: int, frame: int) -> Image.Image:
    """A fleck of ice that glints: a small cross, then a speck, fading to blue (it looks the
    same whichever way it flies)."""
    image, draw, centre = _canvas(PARTICLE_SIZE)
    middle = round(centre)
    colour = (WHITE, FROST, ICE_BLUE)[frame]
    arm = (1, 2)[size] if frame == 0 else (1 if frame == 1 and size else 0)
    draw.line((middle - arm, middle, middle + arm, middle), fill=colour)
    draw.line((middle, middle - arm, middle, middle + arm), fill=colour)
    return image


def _frost_ring(tier: int, frame: int) -> Image.Image:
    """A ring of frost spreading from the contact point: small ice crystals round a flattened
    ellipse, white, then frost, then sparse and blue."""
    width = RING_RADII[frame] * (1.3 if tier > HEAVY else 1.0)
    size = 2 * math.ceil(width) + 5
    image, draw, centre = _canvas(size)
    height = width * RING_SQUASH
    crystals = 12
    colour = (WHITE, FROST, ICE_BLUE, ICE_BLUE)[frame]
    for index in range(0, crystals, 1 if frame < 2 else 2):
        turn = 2.0 * math.pi * index / crystals + frame * 0.15
        x = round(centre + math.cos(turn) * width)
        y = round(centre + math.sin(turn) * height)
        if frame < 2:
            draw.polygon([(x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)], fill=colour)
        else:
            draw.point((x, y), fill=colour)
    return image


SLASH_RING: Final[tuple[Rgba, Rgba, Rgba]] = (WHITE, SLASH_ICE, SLASH_BLUE)
ICE_FLARE: Final[tuple[Rgba, Rgba, Rgba]] = (WHITE, FROST, ICE_BLUE)
VOLT_FLARE: Final[tuple[Rgba, Rgba, Rgba]] = (WHITE, VOLT_PALE, VOLT_BLUE)
WIND_FLARE: Final[tuple[Rgba, Rgba, Rgba]] = (WHITE, WIND_MINT, WIND_TEAL)
EARTH_FLARE: Final[tuple[Rgba, Rgba, Rgba]] = (STONE_PALE, CRYSTAL, STONE_DARK)
DARK_FLARE: Final[tuple[Rgba, Rgba, Rgba]] = (DARK_PALE, DARK_LILAC, DARK_VIOLET)
FIRE_FLARE: Final[tuple[Rgba, Rgba, Rgba]] = (FIRE_PALE, FIRE_YELLOW, FIRE_RED)
DRAWN: Final[dict[str, dict[str, Callable[..., Image.Image]]]] = {
    "slash": {
        "burst": lambda tier, frame: _outlined(_slash_burst(tier, frame), SLASH_DEEP),
        "split": lambda tier, frame: _slash_burst(tier, frame, glints=False),
        "core": lambda tier, angle, frame: _outlined(_slash_core(tier, angle, frame), SLASH_DEEP),
        "lines": _slash_lines,
        "particle": _slash_particle,
        "ring": lambda tier, frame: _outlined(_ring(tier, frame, SLASH_RING), SLASH_DEEP),
        "flare": lambda frame: _outlined(_flare(frame, SLASH_RING), SLASH_DEEP),
    },
    "darkness": {
        "burst": lambda tier, frame: _outlined(_dark_burst(tier, frame), DARK_EDGE),
        "split": lambda tier, frame: _dark_burst(tier, frame, rim=False),
        "core": lambda tier, angle, frame: _outlined(_dark_core(tier, angle, frame), DARK_EDGE),
        "lines": _dark_lines,
        "particle": _dark_particle,
        "ring": lambda tier, frame: _outlined(_implosion_ring(tier, frame), DARK_EDGE),
        "flare": lambda frame: _outlined(_flare(frame, DARK_FLARE), DARK_EDGE),
    },
    "earth": {
        "burst": lambda tier, frame: _outlined(_earth_burst(tier, frame), EARTH_EDGE),
        "split": lambda tier, frame: _earth_burst(tier, frame, chips=False),
        "core": lambda tier, angle, frame: _outlined(_earth_core(tier, angle, frame), EARTH_EDGE),
        "lines": _earth_lines,
        "particle": _earth_particle,
        "ring": _dust_ring,  # dust reads on a light stage without an outline, like smoke
        "flare": lambda frame: _outlined(_flare(frame, EARTH_FLARE), EARTH_EDGE),
    },
    "wind": {
        "burst": lambda tier, frame: _outlined(_wind_burst(tier, frame), WIND_EDGE),
        "split": lambda tier, frame: _wind_burst(tier, frame, swirl=False),
        "core": lambda tier, angle, frame: _outlined(_wind_core(tier, angle, frame), WIND_EDGE),
        "lines": _wind_lines,
        "particle": _wind_particle,
        "ring": lambda tier, frame: _outlined(_shock_ring(tier, frame), WIND_EDGE),
        "flare": lambda frame: _outlined(_flare(frame, WIND_FLARE), WIND_EDGE),
    },
    "electric": {
        "burst": lambda tier, frame: _outlined(_volt_burst(tier, frame), VOLT_EDGE),
        "split": lambda tier, frame: _volt_burst(tier, frame, crackle=False),
        "core": lambda tier, angle, frame: _outlined(_volt_core(tier, angle, frame), VOLT_EDGE),
        "lines": _volt_lines,
        "particle": _volt_particle,
        "ring": lambda tier, frame: _outlined(_volt_ring(tier, frame), VOLT_EDGE),
        "flare": lambda frame: _outlined(_flare(frame, VOLT_FLARE), VOLT_EDGE),
    },
    "ice": {
        "burst": lambda tier, frame: _outlined(_ice_burst(tier, frame), ICE_EDGE),
        "split": lambda tier, frame: _ice_burst(tier, frame, branches=False),
        "core": lambda tier, angle, frame: _outlined(_ice_core(tier, angle, frame), ICE_EDGE),
        "lines": _ice_lines,
        "particle": _ice_particle,
        "ring": lambda tier, frame: _outlined(_frost_ring(tier, frame), ICE_EDGE),
        "flare": lambda frame: _outlined(_flare(frame, ICE_FLARE), ICE_EDGE),
    },
    "fire": {
        "burst": lambda tier, frame: _outlined(_fire_burst(tier, frame), FIRE_EDGE),
        "split": lambda tier, frame: _fire_burst(tier, frame, sparks=False),
        "core": lambda tier, angle, frame: _outlined(_fire_core(tier, angle, frame), FIRE_EDGE),
        "lines": _fire_lines,
        "particle": _fire_particle,
        "ring": _smoke_ring,  # grey smoke reads on a light stage without an outline
        "flare": lambda frame: _outlined(_flare(frame, FIRE_FLARE), FIRE_EDGE),
    },
}
"""The themes with their own art, and how each draws each kind of picture."""


def _placeholder(kind: str, theme: str, steps: tuple[int, ...]) -> Image.Image:
    """A theme without art yet: the hit spark, the launch streak, an ember dot."""
    effect = SPARK_EFFECT[theme]
    if kind == "burst":
        tier, frame = steps
        return vfx_art.build_spark(tier, effect, min(frame, 1))
    if kind == "core":
        tier, _, frame = steps
        return vfx_art.build_spark(tier, effect, CORE_SPARK_FRAMES[frame])
    if kind == "lines":
        _, angle = steps
        return vfx_art.build_streak(angle, 0)
    if kind == "particle":
        _, _, frame = steps
        return vfx_art.build_fx("ember", PARTICLE_FAMILY[theme], 0, frame)
    if kind == "ring":
        tier, frame = steps
        core, mid, edge = vfx_art.FAMILIES[PARTICLE_FAMILY[theme]]
        return _outlined(_ring(tier, frame, (core, mid, edge)), edge)
    if kind == "flare":
        (frame,) = steps
        return vfx_art.build_spark(3, effect, min(frame, 2))
    raise ValueError(f"no splash picture of kind {kind!r}")


def build(key: Key) -> Image.Image:
    """Return the picture for a splash sprite's key (see the module docstring)."""
    kind, theme, *rest = key
    assert isinstance(kind, str) and isinstance(theme, str)
    steps = tuple(int(step) for step in rest)
    drawers = DRAWN.get(theme)
    if kind == "split":
        tier, frame, channel = steps
        shape = drawers.get("split") if drawers else None
        burst = shape(tier, frame) if shape else build(("burst", theme, tier, frame))
        return _silhouette(burst, split_colours(theme)[channel])
    if drawers is None or kind not in drawers:
        if kind not in ("burst", "core", "lines", "particle", "ring", "flare"):
            raise ValueError(f"no splash picture of kind {kind!r}")
        return _placeholder(kind, theme, steps)
    return drawers[kind](*steps)


def has_art(theme: str) -> bool:
    """Whether a theme has its own art (the others still use the old effects)."""
    return theme in DRAWN


def split_colours(theme: str) -> tuple[Rgba, Rgba]:
    """The two colours of a theme's chromatic split (red and cyan unless it has its own)."""
    return SPLIT_COLOURS.get(theme, SPLIT_COLOURS["slash"])


def heavy(key: Key) -> bool:
    """Whether a picture is only shown by heavy and critical hits (built after the others)."""
    kind = key[0]
    if kind in ("split", "ring", "flare"):
        return True
    level = key[2]
    assert isinstance(level, int)
    return level >= (1 if kind == "particle" else HEAVY)


def theme_keys(theme: str) -> list[Key]:
    """Every picture a theme can show, the commonest first (light and medium hits, then heavy
    and critical ones), in the order a battle builds them ahead of time."""
    keys: list[Key] = []
    for tiers in ((0, 1), (2, 3)):
        for tier in tiers:
            keys += [("burst", theme, tier, frame) for frame in range(BURST_FRAMES)]
            for angle in range(-1, ANGLES):
                keys += [("core", theme, tier, angle, frame) for frame in range(CORE_FRAMES)]
            keys += [("lines", theme, tier, angle) for angle in range(ANGLES)]
        size = 0 if tiers[0] < HEAVY else 1
        keys += [
            ("particle", theme, size, angle, frame)
            for angle in range(ANGLES)
            for frame in range(PARTICLE_FRAMES)
        ]
    for tier in (2, 3):
        keys += [
            ("split", theme, tier, frame, channel)
            for frame in range(BURST_FRAMES)
            for channel in range(SPLIT_CHANNELS)
        ]
        keys += [("ring", theme, tier, frame) for frame in range(RING_FRAMES)]
    keys += [("flare", theme, frame) for frame in range(FLARE_FRAMES)]
    return keys
