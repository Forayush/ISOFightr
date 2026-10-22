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
    centre: float, along: Point, across: Point, radius: float, thickness: float, back: float
) -> list[Point]:
    """A crescent convex along the direction: the arc of a circle centred ``back`` behind the
    centre, thickest in the middle and tapering to points at its tips."""
    span = math.radians(SLASH_SPAN_DEGREES)
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


def _smoke_ring(tier: int, frame: int) -> Image.Image:
    """An expanding smoke ring: puffs round a flattened ellipse, glowing at first, then grey
    and thinning out."""
    width = RING_RADII[frame] * (1.3 if tier > HEAVY else 1.0)
    size = 2 * math.ceil(width) + 5
    image, draw, centre = _canvas(size)
    height = width * RING_SQUASH
    puff = (1.5, 1.5, 1.0, 0.5)[frame]
    colours = ((FIRE_ORANGE, SMOKE), (SMOKE, SMOKE_DARK), (SMOKE_DARK, SMOKE), (SMOKE_DARK,) * 2)
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


SLASH_RING: Final[tuple[Rgba, Rgba, Rgba]] = (WHITE, SLASH_ICE, SLASH_BLUE)
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
