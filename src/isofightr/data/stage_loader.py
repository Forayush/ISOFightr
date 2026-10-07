"""Loads ``assets/stages/<id>/stage.toml`` into an immutable :class:`~isofightr.sim.stage.Stage`.

Implements the stage file format in the plan note "11 - Stages" with strict validation
(decision D-009): unknown keys are errors, and every error names the file and the key.
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path

from isofightr.config import (
    DEFAULT_BLAST_BOTTOM,
    DEFAULT_BLAST_SIDE,
    DEFAULT_BLAST_TOP,
    DEFAULT_CAMERA_MARGIN,
    PLAYER_SPAWN_COUNT,
)
from isofightr.data.paths import STAGE_FILE_NAME, STAGES_DIR
from isofightr.data.validation import DataError, TableReader
from isofightr.sim.math3d import Vec2
from isofightr.sim.stage import (
    DEFAULT_TILE,
    VOID_SYMBOL,
    BackgroundLayer,
    Cell,
    SoftPlatform,
    Stage,
    StageError,
    build_stage,
)

_TOP_LEVEL_KEYS = (
    "id",
    "display_name",
    "description",
    "tileset",
    "music",
    "grid",
    "legend",
    "soft_platforms",
    "spawns",
    "blast_zone",
    "camera",
    "background",
)
_RESPAWN_KEY = "respawn"
_SPAWN_KEYS = tuple(f"p{index + 1}" for index in range(PLAYER_SPAWN_COUNT))


def list_stage_ids(stages_dir: Path = STAGES_DIR) -> list[str]:
    """Return the ids of every stage that has a ``stage.toml``, sorted."""
    return sorted(path.parent.name for path in stages_dir.glob(f"*/{STAGE_FILE_NAME}"))


def load_stage(stage_id: str, stages_dir: Path = STAGES_DIR) -> Stage:
    """Load a stage by id from ``<stages_dir>/<id>/stage.toml``.

    Raises:
        DataError: if the file is missing, is not valid TOML, or fails validation.
    """
    path = stages_dir / stage_id / STAGE_FILE_NAME
    if not path.is_file():
        known = ", ".join(list_stage_ids(stages_dir)) or "none"
        raise DataError(f"{path}: no such stage {stage_id!r} (available: {known})")
    return load_stage_file(path)


def load_stage_file(path: Path) -> Stage:
    """Load one ``stage.toml``. The stage ``id`` must match its directory name."""
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise DataError(f"{path}: invalid TOML: {error}") from error
    return parse_stage(data, source=str(path), expected_id=path.parent.name)


def parse_stage(
    data: Mapping[str, object], *, source: str, expected_id: str | None = None
) -> Stage:
    """Validate a parsed stage table and build the :class:`Stage`.

    Args:
        data: the parsed TOML document.
        source: file name used in error messages.
        expected_id: if given, the ``id`` key must equal it (the directory name).
    """
    root = TableReader(data, source=source, where="", allowed=_TOP_LEVEL_KEYS)
    stage_id = root.string("id")
    if expected_id is not None and stage_id != expected_id:
        raise root.error(f"is {stage_id!r} but the directory is named {expected_id!r}", "id")

    blast = TableReader(
        data.get("blast_zone", {}),
        source=source,
        where="blast_zone",
        allowed=("side", "top", "bottom"),
    )
    camera = TableReader(
        data.get("camera", {}), source=source, where="camera", allowed=("bounds_margin",)
    )
    spawn_reader = TableReader(
        root.raw("spawns"), source=source, where="spawns", allowed=(*_SPAWN_KEYS, _RESPAWN_KEY)
    )

    try:
        return build_stage(
            id=stage_id,
            display_name=root.string("display_name"),
            description=root.optional_string("description") or "",
            tileset=root.string("tileset"),
            music=root.optional_string("music"),
            grid_rows=_grid_rows(root),
            legend=_legend(data.get("legend", {}), source),
            soft_platforms=[
                _soft_platform(table, source, index)
                for index, table in enumerate(root.tables("soft_platforms"))
            ],
            spawns=[Vec2(*spawn_reader.numbers(key, 2)) for key in _SPAWN_KEYS],
            respawn=Vec2(*spawn_reader.numbers(_RESPAWN_KEY, 2)),
            blast_side=blast.number("side", DEFAULT_BLAST_SIDE),
            blast_top=blast.number("top", DEFAULT_BLAST_TOP),
            blast_bottom=blast.number("bottom", DEFAULT_BLAST_BOTTOM),
            camera_margin=camera.number("bounds_margin", DEFAULT_CAMERA_MARGIN),
            backgrounds=[
                _background(table, source, index)
                for index, table in enumerate(root.tables("background"))
            ],
        )
    except StageError as error:
        raise DataError(f"{source}: {error}") from error


def _grid_rows(root: TableReader) -> list[str]:
    grid = root.string("grid")
    return [line.strip() for line in grid.strip().splitlines()]


def _legend(table: object, source: str) -> dict[str, Cell]:
    reader = TableReader(
        table,
        source=source,
        where="legend",
        allowed=table.keys() if isinstance(table, Mapping) else (),
    )
    legend: dict[str, Cell] = {}
    for symbol in reader.table:
        if len(symbol) != 1 or symbol == VOID_SYMBOL or symbol.isspace():
            raise reader.error(f"symbol must be one character other than {VOID_SYMBOL!r}", symbol)
        entry = TableReader(
            reader.table[symbol],
            source=source,
            where=f"legend.{symbol!r}",
            allowed=("height", "tile", "ledge"),
        )
        height = entry.number("height")
        if height < 0:
            raise entry.error("must be 0 or greater (0 is the main floor level)", "height")
        legend[symbol] = Cell(
            top=height,
            tile=entry.string("tile") if entry.has("tile") else DEFAULT_TILE,
            ledge=entry.boolean("ledge", default=True),
        )
    return legend


def _soft_platform(table: object, source: str, index: int) -> SoftPlatform:
    reader = TableReader(
        table, source=source, where=f"soft_platforms[{index}]", allowed=("rect", "z")
    )
    x0, y0, x1, y1 = reader.integers("rect", 4)
    return SoftPlatform(x0=x0, y0=y0, x1=x1, y1=y1, z=reader.number("z"))


def _background(table: object, source: str, index: int) -> BackgroundLayer:
    reader = TableReader(
        table, source=source, where=f"background[{index}]", allowed=("image", "parallax")
    )
    return BackgroundLayer(image=reader.string("image"), parallax=reader.number("parallax"))
