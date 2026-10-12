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
from isofightr.data.tileset_art import TilesetArtError, load_tileset_art
from isofightr.data.validation import DataError, TableReader
from isofightr.sim.math3d import ZERO2, ZERO3, Vec2, Vec3
from isofightr.sim.move_def import Effect
from isofightr.sim.stage import (
    DEFAULT_TILE,
    VOID_SYMBOL,
    Ambient,
    BackgroundLayer,
    Cell,
    Hazard,
    PlatformMotion,
    Prop,
    SoftPlatform,
    Stage,
    StageError,
    Underside,
    build_stage,
    hazard_hitbox,
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
    "props",
    "ambient",
    "underside",
    "hazards",
)
_HAZARD_DEFAULTS = {
    # kind: (height, launch angle, base knockback, knockback growth, effect)
    "geyser": (5.0, 88.0, 55.0, 70.0, Effect.FIRE),
    "lightning": (9.0, 361.0, 45.0, 85.0, Effect.ELECTRIC),
}
"""What a hitting hazard does unless its table says otherwise."""
_WIND_HEIGHT = 5.0
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
        stage = build_stage(
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
            props=[_prop(table, source, index) for index, table in enumerate(root.tables("props"))],
            ambient=_ambient(data["ambient"], source) if "ambient" in data else None,
            underside_art=_underside(data["underside"], source) if "underside" in data else None,
            hazards=[
                _hazard(table, source, index) for index, table in enumerate(root.tables("hazards"))
            ],
        )
    except StageError as error:
        raise DataError(f"{source}: {error}") from error
    _check_sprites(stage, source)
    return stage


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
            allowed=("height", "tile", "ledge", "traction", "drive", "bounce"),
        )
        height = entry.number("height")
        if height < 0:
            raise entry.error("must be 0 or greater (0 is the main floor level)", "height")
        legend[symbol] = Cell(
            top=height,
            tile=entry.string("tile") if entry.has("tile") else DEFAULT_TILE,
            ledge=entry.boolean("ledge", default=True),
            traction=entry.number("traction", 1.0),
            drive=Vec2(*entry.numbers("drive", 2)) if entry.has("drive") else ZERO2,
            bounce=entry.number("bounce", 0.0),
        )
    return legend


def _soft_platform(table: object, source: str, index: int) -> SoftPlatform:
    where = f"soft_platforms[{index}]"
    reader = TableReader(table, source=source, where=where, allowed=("rect", "z", "motion"))
    x0, y0, x1, y1 = reader.integers("rect", 4)
    motion = None
    if reader.has("motion"):
        motion = _motion(reader.raw("motion"), source, f"{where}.motion")
    return SoftPlatform(x0=x0, y0=y0, x1=x1, y1=y1, z=reader.number("z"), motion=motion)


def _motion(table: object, source: str, where: str) -> PlatformMotion:
    """Read how a platform moves: ``to`` (one far point), ``points`` (several) or, for a
    ``bob``, an ``amplitude``; all are offsets from where the platform rests."""
    reader = TableReader(
        table,
        source=source,
        where=where,
        allowed=("kind", "to", "points", "amplitude", "period", "phase"),
    )
    kind = reader.string("kind")
    given = [key for key in ("to", "points", "amplitude") if reader.has(key)]
    if len(given) != 1:
        raise reader.error("give exactly one of to, points or amplitude")
    if reader.has("amplitude"):
        if kind != "bob":
            raise reader.error("is only for a bob", "amplitude")
        points: tuple[Vec3, ...] = (Vec3(0.0, 0.0, reader.number("amplitude")),)
    elif reader.has("to"):
        points = (Vec3(*reader.numbers("to", 3)),)
    else:
        raw = reader.raw("points")
        if not isinstance(raw, list) or not raw:
            raise reader.error("must be a list of [x, y, z] offsets", "points")
        try:
            points = tuple(Vec3(*(float(value) for value in point)) for point in raw)
        except (TypeError, ValueError) as error:
            raise reader.error("must be a list of [x, y, z] offsets", "points") from error
    return PlatformMotion(
        kind=kind,
        points=points,
        period=reader.integer("period"),
        phase=reader.integer("phase") if reader.has("phase") else 0,
    )


def _hazard(table: object, source: str, index: int) -> Hazard:
    """Read one ``[[hazards]]`` table. A geyser or lightning takes ``damage`` (and may set
    ``angle``, ``bkb``, ``kbg``); a wind takes a ``push``."""
    reader = TableReader(
        table,
        source=source,
        where=f"hazards[{index}]",
        allowed=(
            "kind", "at", "radius", "height", "z", "rest", "warn", "active", "phase",
            "damage", "angle", "bkb", "kbg", "push",
        ),
    )  # fmt: skip
    kind = reader.string("kind")
    x, y = reader.numbers("at", 2)
    hitbox = None
    push = ZERO3
    height = _WIND_HEIGHT
    if kind in _HAZARD_DEFAULTS:
        height, angle, bkb, kbg, effect = _HAZARD_DEFAULTS[kind]
        if reader.has("push"):
            raise reader.error("is only for a wind", "push")
        hitbox = hazard_hitbox(
            reader.number("damage"),
            reader.number("angle", angle),
            reader.number("bkb", bkb),
            reader.number("kbg", kbg),
            effect,
        )
    elif kind == "wind":
        for key in ("damage", "angle", "bkb", "kbg"):
            if reader.has(key):
                raise reader.error("is not for a wind", key)
        if reader.has("push"):
            push = Vec3(*reader.numbers("push", 3))
    return Hazard(
        kind=kind,
        x=x,
        y=y,
        radius=reader.number("radius"),
        z=reader.number("z", 0.0),
        height=reader.number("height", height),
        rest=reader.integer("rest"),
        warn=reader.integer("warn"),
        active=reader.integer("active"),
        phase=reader.integer("phase") if reader.has("phase") else 0,
        hitbox=hitbox,
        push=push,
    )


def _background(table: object, source: str, index: int) -> BackgroundLayer:
    reader = TableReader(
        table,
        source=source,
        where=f"background[{index}]",
        allowed=("image", "parallax", "scroll", "frames", "frame_ticks"),
    )
    return BackgroundLayer(
        image=reader.string("image"),
        parallax=reader.number("parallax"),
        scroll=reader.number("scroll", 0.0),
        frames=reader.integer("frames") if reader.has("frames") else 1,
        frame_ticks=reader.integer("frame_ticks") if reader.has("frame_ticks") else 0,
    )


def _prop(table: object, source: str, index: int) -> Prop:
    reader = TableReader(
        table,
        source=source,
        where=f"props[{index}]",
        allowed=("sprite", "at", "layer", "period", "phase"),
    )
    x, y = reader.numbers("at", 2)
    return Prop(
        sprite=reader.string("sprite"),
        x=x,
        y=y,
        layer=reader.optional_string("layer") or "world",
        period=reader.integer("period") if reader.has("period") else 0,
        phase=reader.integer("phase") if reader.has("phase") else 0,
    )


def _ambient(table: object, source: str) -> Ambient:
    reader = TableReader(table, source=source, where="ambient", allowed=("kind", "count", "front"))
    return Ambient(
        kind=reader.string("kind"),
        count=reader.integer("count"),
        front=reader.integer("front") if reader.has("front") else 0,
    )


def _underside(table: object, source: str) -> Underside:
    reader = TableReader(table, source=source, where="underside", allowed=("depth", "tile", "hang"))
    hang = reader.raw("hang") if reader.has("hang") else []
    if not isinstance(hang, list) or not all(isinstance(name, str) and name for name in hang):
        raise reader.error("must be a list of prop names", "hang")
    return Underside(
        depth=reader.number("depth"),
        tile=reader.optional_string("tile") or "under",
        hang=tuple(hang),
    )


def _check_sprites(stage: Stage, source: str) -> None:
    """Check that every prop the stage names is in its tileset."""
    names = [prop.sprite for prop in stage.props]
    if stage.underside_art is not None:
        names += stage.underside_art.hang
    if not names:
        return
    try:
        tileset = load_tileset_art(stage.tileset)
    except TilesetArtError as error:
        raise DataError(f"{source}: {error}") from error
    known = () if tileset is None else tileset.prop_names
    for name in names:
        if name not in known:
            listed = ", ".join(known) or "none"
            raise DataError(
                f"{source}: tileset {stage.tileset!r} has no prop {name!r} (it has: {listed})"
            )
