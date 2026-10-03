"""Materials, light bands and costumes of a character: ``art_src/characters/<id>/palettes.toml``.

Plan note "09 - Art Direction" ("Palette") and decision D-045. Every colour must come from the
master palette. A sheet pixel is a palette index; the index layout is fixed by the material
order:

- index 0 is transparent;
- material ``m`` (1-based, the order in the file) owns indices ``1 + (m - 1) * 5 + k``:
  ``k`` = 0 highlight, 1 light, 2 mid, 3 shadow, 4 outline.

A costume is just a different colour for every index, so swapping one is swapping the PNG's
palette.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from isofightr.data.paths import REPO_ROOT

ART_SRC: Final[Path] = REPO_ROOT / "art_src"
RAMP_LENGTH: Final[int] = 5
"""Highlight, light, mid, shadow, outline."""
BANDS: Final[int] = 4
OUTLINE_SLOT: Final[int] = 4
TRANSPARENT_INDEX: Final[int] = 0

Rgb = tuple[int, int, int]


class PaletteError(ValueError):
    """``palettes.toml`` or the master palette is malformed."""


@dataclass(frozen=True, slots=True)
class Material:
    """One material of a character's model."""

    name: str
    lit: bool = True
    """Whether light bands apply; unlit materials always use the highlight colour."""
    outline: bool = True
    """Whether the packer draws outlines around this material."""


@dataclass(frozen=True, slots=True)
class Costume:
    """A full set of colours: one ramp per material."""

    name: str
    ramps: tuple[tuple[Rgb, ...], ...]
    """``RAMP_LENGTH`` colours per material, in material order."""

    def colors(self) -> list[Rgb]:
        """Return the colour of every palette index, index 0 (transparent) first."""
        return [(0, 0, 0), *(color for ramp in self.ramps for color in ramp)]


@dataclass(frozen=True, slots=True)
class CharacterPalettes:
    """Everything the packer needs to turn render passes into palette indices."""

    materials: tuple[Material, ...]
    bands: tuple[float, ...]
    """Light thresholds, brightest first: at or above ``bands[0]`` is highlight, etc."""
    costumes: tuple[Costume, ...]

    @property
    def index_count(self) -> int:
        """How many palette indices a sheet uses, transparent included."""
        return 1 + len(self.materials) * RAMP_LENGTH

    def band_of(self, light: float) -> int:
        """Return the band (0 = highlight .. 3 = shadow) for a light value in 0..1."""
        for band, threshold in enumerate(self.bands):
            if light >= threshold:
                return band
        return BANDS - 1


def ramp_index(material_id: int, slot: int) -> int:
    """Return the palette index of a material's ramp slot (``material_id`` is 1-based)."""
    return 1 + (material_id - 1) * RAMP_LENGTH + slot


def load_master(name: str, root: Path = ART_SRC) -> frozenset[Rgb]:
    """Return the colours of a master palette in ``art_src/palettes``."""
    data = tomllib.loads((root / "palettes" / f"{name}.toml").read_text(encoding="utf-8"))
    return frozenset(parse_hex(value) for value in data["colors"])


def parse_hex(value: str) -> Rgb:
    """Parse ``"rrggbb"``."""
    if len(value) != 6:
        raise PaletteError(f"not a colour: {value!r}")
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        raise PaletteError(f"not a colour: {value!r}") from None


def load_palettes(character_id: str, root: Path = ART_SRC) -> CharacterPalettes:
    """Load and validate a character's ``palettes.toml``."""
    return load_palettes_in(root / "characters" / character_id, root)


def load_palettes_in(folder: Path, root: Path = ART_SRC) -> CharacterPalettes:
    """Load and validate the ``palettes.toml`` in an art source folder (character or tileset)."""
    path = folder / "palettes.toml"
    return parse_palettes(tomllib.loads(path.read_text(encoding="utf-8")), root)


def parse_palettes(data: dict[str, Any], root: Path = ART_SRC) -> CharacterPalettes:
    """Validate parsed ``palettes.toml`` data. Unknown keys and off-palette colours are errors."""
    _check_keys(data, {"master", "bands", "materials", "costumes"}, "palettes.toml")
    master = load_master(data["master"], root)
    materials = []
    for entry in data["materials"]:
        _check_keys(entry, {"name", "lit", "outline"}, "material")
        materials.append(
            Material(entry["name"], bool(entry.get("lit", True)), bool(entry.get("outline", True)))
        )
    names = [material.name for material in materials]
    if len(set(names)) != len(names):
        raise PaletteError("material names repeat")
    bands = tuple(float(value) for value in data["bands"])
    if len(bands) != BANDS - 1 or list(bands) != sorted(bands, reverse=True):
        raise PaletteError(f"bands must be {BANDS - 1} thresholds, brightest first")

    costumes: list[Costume] = []
    for entry in data["costumes"]:
        _check_keys(entry, {"name", *names}, "costume")
        ramps = []
        for name in names:
            values = entry.get(name)
            if values is None:
                if not costumes:
                    raise PaletteError(f"costume {entry['name']}: the first costume needs {name}")
                ramps.append(costumes[0].ramps[names.index(name)])
                continue
            if len(values) != RAMP_LENGTH:
                raise PaletteError(f"costume {entry['name']}: {name} needs {RAMP_LENGTH} colours")
            ramp = tuple(parse_hex(value) for value in values)
            for color in ramp:
                if color not in master:
                    raise PaletteError(
                        f"costume {entry['name']}: {name} uses {color}, not in {data['master']}"
                    )
            ramps.append(ramp)
        costumes.append(Costume(entry["name"], tuple(ramps)))
    if not costumes:
        raise PaletteError("no costumes")
    return CharacterPalettes(tuple(materials), bands, tuple(costumes))


def _check_keys(data: dict[str, Any], allowed: set[str], what: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise PaletteError(f"{what}: unknown keys {sorted(unknown)}")
