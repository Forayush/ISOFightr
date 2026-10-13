"""Measures whether a stage's backdrop reads as *behind* the stage (decision D-065).

Plan notes "09 - Art Direction" (readability rule 4: backgrounds are lower in contrast than
the playfield) and "11 - Stages". The playfield is what a fighter stands on: the top faces of
the tiles a stage uses. Every backdrop layer but the sky must then pass three rules:

``colours``
    At most :data:`MAX_SHARED` of its opaque pixels are an exact colour of the playfield (the
    shared ink colours aside). A hill painted in the stage's own grass looks like ground.
``contrast``
    Its spread of lightness is at most :data:`MAX_CONTRAST` times the playfield's.
``haze``
    Its mean colour is nearer the sky behind the island than the playfield's is: at most
    :data:`MAX_HAZE_NEAR` times as far, and :data:`MAX_HAZE_FAR` times for a far layer (one
    whose parallax is :data:`FAR_PARALLAX` or less). Distance swallows colour: the further
    a thing is, the more it looks like the sky.

Lights are allowed: the lightest colours of a layer, up to :data:`LIGHT_SHARE` of its pixels,
are left out of ``contrast`` and ``haze`` (windows, lava, stars, the rim of a cloud). A sparse
layer (under :data:`SPARSE_COVER` of its picture: birds, stars, an aurora's curtain) cannot
be taken for ground and only has to pass ``colours``.

The rule D-065 first proposed, mean saturation at most 0.7 times the tileset's, was dropped
before any of this was built: haze toward a blue sky *raises* saturation, and four stages
have playfields so grey that nothing but six of the palette's colours would have passed.

Pure Python plus Pillow (no ``arcade``), so the report runs in a test without a window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Final

from PIL import Image

from isofightr.data.paths import STAGES_DIR
from isofightr.data.tileset_art import TILESETS_DIR, VARIANT_SUFFIXES
from isofightr.sim.stage import Stage

Rgb = tuple[int, int, int]
Lab = tuple[float, float, float]
MAX_SHARED: Final[float] = 0.10
MAX_CONTRAST: Final[float] = 0.70
MAX_HAZE_NEAR: Final[float] = 1.00
MAX_HAZE_FAR: Final[float] = 0.70
FAR_PARALLAX: Final[float] = 0.10
LIGHT_SHARE: Final[float] = 0.15
SPARSE_COVER: Final[float] = 0.05
INK: Final[frozenset[Rgb]] = frozenset({(0x2E, 0x22, 0x2F), (255, 255, 255), (0, 0, 0)})
"""Colours everything shares (the palette's ink, white, black): they do not count as the
playfield's."""
DECK_TILE: Final[str] = "deck"
TILE_TOP: Final[tuple[int, int]] = (32, 16)
"""A tile picture's top face: a diamond this big in its top rows."""
SKY_WINDOW: Final[tuple[int, int, int, int]] = (160, 80, 480, 280)
"""The part of the sky picture the island stands in front of (left, top, right, bottom)."""
RULES: Final[tuple[str, ...]] = ("colours", "contrast", "haze")
EXCUSED: Final[dict[str, tuple[str, ...]]] = {"frostpeak": ("colours",)}
"""Rules a stage is excused from, with the reason in the Decision Log (D-065). Frostpeak:
every pale blue and grey of the palette is its own snow and ice, so mountains and cloud
behind it cannot avoid them and still look like mountains and cloud. It still has to pass
contrast and haze."""
Table = dict[Rgb, int]


@cache
def oklab(colour: Rgb) -> Lab:
    """Return a colour in OKLab: lightness 0..1, then two axes of hue and strength. Equal
    distances there look about equally different, which RGB and HSV do not give."""
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for c in (colour[0] / 255, colour[1] / 255, colour[2] / 255)
    ]
    long = 0.4122214708 * linear[0] + 0.5363325363 * linear[1] + 0.0514459929 * linear[2]
    middle = 0.2119034982 * linear[0] + 0.6806995451 * linear[1] + 0.1073969566 * linear[2]
    short = 0.0883024619 * linear[0] + 0.2817188376 * linear[1] + 0.6299787005 * linear[2]
    long, middle, short = (value ** (1 / 3) for value in (long, middle, short))
    return (
        0.2104542553 * long + 0.7936177850 * middle - 0.0040720468 * short,
        1.9779984951 * long - 2.4285922050 * middle + 0.4505937099 * short,
        0.0259040371 * long + 0.7827717662 * middle - 0.8086757660 * short,
    )


def colour_table(image: Image.Image) -> Table:
    """Return how many opaque pixels a picture has of each colour."""
    table: Table = {}
    for count, (red, green, blue, alpha) in image.convert("RGBA").getcolors(1 << 24) or []:
        if alpha >= 128:
            table[(red, green, blue)] = table.get((red, green, blue), 0) + count
    return table


def mean_colour(table: Table) -> Lab:
    """Return a colour table's mean, in OKLab."""
    total = max(sum(table.values()), 1)
    sums = [0.0, 0.0, 0.0]
    for colour, count in table.items():
        for axis, value in enumerate(oklab(colour)):
            sums[axis] += value * count
    return (sums[0] / total, sums[1] / total, sums[2] / total)


def contrast(table: Table) -> float:
    """Return a colour table's spread of lightness (the standard deviation of OKLab L)."""
    total = max(sum(table.values()), 1)
    mean = sum(oklab(colour)[0] * count for colour, count in table.items()) / total
    spread = sum((oklab(colour)[0] - mean) ** 2 * count for colour, count in table.items())
    return math.sqrt(spread / total)


def without_lights(table: Table, share: float = LIGHT_SHARE) -> Table:
    """Return a colour table without its lightest colours, as long as they are no more than
    ``share`` of its pixels together (whole colours only, lightest first)."""
    total = sum(table.values())
    left = dict(table)
    dropped = 0
    for colour in sorted(table, key=lambda each: oklab(each)[0], reverse=True):
        if len(left) == 1 or dropped + table[colour] > share * total:
            break
        dropped += table[colour]
        del left[colour]
    return left


def _base_name(stem: str) -> str:
    """Return the tile a picture is of: ``grass`` for ``grass_b``."""
    head, _, tail = stem.rpartition("_")
    return head if head and len(tail) == 1 and tail in VARIANT_SUFFIXES else stem


def playfield_table(stage: Stage, tilesets_dir: Path = TILESETS_DIR) -> Table:
    """Return the colours of what a fighter stands on: the top faces of every tile the
    stage's cells and platforms use, variants included (empty if the tileset has no art)."""
    names = {cell.tile for row in stage.cells for cell in row if cell is not None}
    if stage.soft_platforms:
        names.add(DECK_TILE)
    width, height = TILE_TOP
    table: Table = {}
    for path in sorted((tilesets_dir / stage.tileset).glob("*.png")):
        if _base_name(path.stem) not in names:
            continue
        with Image.open(path) as picture:
            top = picture.convert("RGBA").crop((0, 0, width, height))
        pixels = top.load()
        assert pixels is not None
        for y in range(height):
            for x in range(width):
                inside = abs(x - (width - 1) / 2) / (width / 2) + abs(y - (height - 1) / 2) / (
                    height / 2
                )
                red, green, blue, alpha = pixels[x, y]
                if inside <= 1.0 and alpha >= 128:
                    table[(red, green, blue)] = table.get((red, green, blue), 0) + 1
    return table


def haze_colour(sky: Image.Image) -> Lab:
    """Return the colour distance fades toward on a stage: the mean of the sky where the
    island stands in front of it."""
    return mean_colour(colour_table(sky.convert("RGBA").crop(SKY_WINDOW)))


@dataclass(frozen=True, slots=True)
class LayerReport:
    """One backdrop layer against the rules."""

    image: str
    sky: bool
    """Whether it is the stage's sky (its first layer): exempt, and where the haze comes
    from."""
    cover: float
    """Share of the layer's picture that is opaque."""
    shared: float
    """Share of its opaque pixels in an exact colour of the playfield."""
    contrast: float
    """Its spread of lightness over the playfield's (lights left out)."""
    haze: float
    """How far its mean colour is from the sky, over how far the playfield's is."""
    haze_limit: float
    failed: tuple[str, ...]
    """The rules it breaks (names from :data:`RULES`)."""
    excused: tuple[str, ...] = ()
    """Rules it breaks that its stage is excused from (:data:`EXCUSED`)."""

    @property
    def passed(self) -> bool:
        """Whether the layer breaks no rule."""
        return not self.failed

    @property
    def sparse(self) -> bool:
        """Whether the layer is too sparse to be taken for ground."""
        return self.cover < SPARSE_COVER


def check_layer(
    picture: Image.Image,
    name: str,
    parallax: float,
    playfield: Table,
    haze: Lab,
    sky: bool = False,
) -> LayerReport:
    """Measure one layer's picture (a single frame of it) against the rules."""
    table = colour_table(picture)
    total = max(sum(table.values()), 1)
    cover = sum(table.values()) / max(picture.width * picture.height, 1)
    touchable = set(playfield) - INK
    shared = sum(count for colour, count in table.items() if colour in touchable) / total
    body = without_lights(table) if table else table
    field_contrast = max(contrast(playfield), 1e-6)
    field_haze = max(math.dist(mean_colour(playfield), haze), 1e-6)
    layer_contrast = contrast(body) / field_contrast if body else 0.0
    layer_haze = math.dist(mean_colour(body), haze) / field_haze if body else 0.0
    limit = MAX_HAZE_FAR if parallax <= FAR_PARALLAX else MAX_HAZE_NEAR
    failed: list[str] = []
    if not sky and table:
        if shared > MAX_SHARED:
            failed.append("colours")
        if cover >= SPARSE_COVER:
            if layer_contrast > MAX_CONTRAST:
                failed.append("contrast")
            if layer_haze > limit:
                failed.append("haze")
    return LayerReport(name, sky, cover, shared, layer_contrast, layer_haze, limit, tuple(failed))


def check_stage(
    stage: Stage, stages_dir: Path = STAGES_DIR, tilesets_dir: Path = TILESETS_DIR
) -> list[LayerReport]:
    """Measure every backdrop layer of a stage. The first layer is its sky."""
    playfield = playfield_table(stage, tilesets_dir)
    if not playfield or not stage.backgrounds:
        return []
    folder = stages_dir / stage.id
    pictures = []
    for layer in stage.backgrounds:
        with Image.open(folder / layer.image) as picture:
            whole = picture.convert("RGBA")
        pictures.append(whole.crop((0, 0, whole.width, whole.height // layer.frames)))
    haze = haze_colour(pictures[0])
    excused = EXCUSED.get(stage.id, ())
    reports = [
        check_layer(picture, layer.image, layer.parallax, playfield, haze, sky=index == 0)
        for index, (layer, picture) in enumerate(zip(stage.backgrounds, pictures, strict=True))
    ]
    return [
        replace(
            each,
            failed=tuple(rule for rule in each.failed if rule not in excused),
            excused=tuple(rule for rule in each.failed if rule in excused),
        )
        for each in reports
    ]


def failures(reports: list[LayerReport]) -> list[str]:
    """Return one line per layer that breaks a rule ("bg_4_pads.png: colours")."""
    return [f"{each.image}: {', '.join(each.failed)}" for each in reports if not each.passed]


def report_lines(reports: list[LayerReport]) -> list[str]:
    """Return the report's table for a stage, one line per layer."""
    lines = []
    for each in reports:
        if each.sky:
            verdict = "sky"
        elif each.passed:
            verdict = "pass" + (f" (excused: {', '.join(each.excused)})" if each.excused else "")
        else:
            verdict = "FAIL " + ", ".join(each.failed)
        measures = f"shared {each.shared:4.0%}  "
        if each.sparse and not each.sky:
            measures += "sparse" + " " * 27
        else:
            measures += (
                f"contrast {each.contrast:4.2f}x  haze {each.haze:4.2f}x (<= {each.haze_limit:.1f})"
            )
        lines.append(f"  {each.image:26s} cover {each.cover:4.0%}  {measures}  {verdict}")
    return lines
