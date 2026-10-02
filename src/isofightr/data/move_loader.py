"""Loads ``assets/characters/<id>/moves/<move>.toml`` into immutable ``MoveDef``s.

Implements "Move data format" and "Validation at load" in the plan note "07 - Fighter State
Machine and Move Data": frame ranges parse and fall inside the move, hitbox ids are unique
within a window, radii are positive, angles are in range, and unknown keys are errors.
"""

import itertools
import tomllib
from collections.abc import Mapping
from pathlib import Path

from isofightr.data.validation import DataError, TableReader
from isofightr.sim.combat.constants import SAKURAI_ANGLE
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import (
    CancelDef,
    ChargeDef,
    DirectionMode,
    Effect,
    FrameRange,
    HitboxDef,
    HitWindow,
    MotionWindow,
    MoveDef,
    MoveKind,
)

MOVE_SUFFIX = ".toml"
_MOVE_KEYS = (
    "id",
    "kind",
    "total",
    "faf",
    "anim",
    "charge",
    "windows",
    "motion",
    "cancel",
    "landing_lag",
    "autocancel",
)
_HITBOX_KEYS = (
    "id",
    "group",
    "offset",
    "radius",
    "damage",
    "angle",
    "yaw",
    "direction_mode",
    "bkb",
    "kbg",
    "fkb",
    "hitlag_mult",
    "sdi_mult",
    "effect",
    "hits",
    "rehit",
    "clank",
)
_HIT_TARGETS = ("ground", "air")
MAX_ELEVATION = 90.0


def load_moves(moves_dir: Path) -> dict[str, MoveDef]:
    """Load every move file in a character's ``moves`` directory, keyed by move id."""
    moves: dict[str, MoveDef] = {}
    for path in sorted(moves_dir.glob(f"*{MOVE_SUFFIX}")):
        try:
            with path.open("rb") as file:
                data = tomllib.load(file)
        except tomllib.TOMLDecodeError as error:
            raise DataError(f"{path}: invalid TOML: {error}") from error
        move = parse_move(data, source=str(path), expected_id=path.stem)
        moves[move.id] = move
    return moves


def parse_frame_range(text: object, total: int, reader: TableReader, key: str) -> FrameRange:
    """Parse ``"14-16"``, ``"7"`` or the open-ended ``"38-"`` into an inclusive range.

    Frames are 1-indexed and must lie inside ``1..total``.
    """
    if isinstance(text, int) and not isinstance(text, bool):
        text = str(text)
    if not isinstance(text, str):
        raise reader.error(f'must be a frame range like "14-16", got {text!r}', key)
    first_text, dash, last_text = text.partition("-")
    try:
        first = int(first_text)
        last = first if not dash else (total if last_text == "" else int(last_text))
    except ValueError:
        raise reader.error(f'must be a frame range like "14-16", got {text!r}', key) from None
    if not 1 <= first <= last <= total:
        raise reader.error(f"frames {text!r} must lie within 1..{total} in order", key)
    return FrameRange(first, last)


def parse_move(
    data: Mapping[str, object], *, source: str, expected_id: str | None = None
) -> MoveDef:
    """Validate a parsed move table and build the :class:`MoveDef`."""
    root = TableReader(data, source=source, where="", allowed=_MOVE_KEYS)
    move_id = root.string("id")
    if expected_id is not None and move_id != expected_id:
        raise root.error(f"is {move_id!r} but the file is named {expected_id!r}", "id")
    kind = _enum(root, "kind", MoveKind, None)
    total = root.integer("total")
    if total < 1:
        raise root.error("must be 1 or greater", "total")
    faf = root.integer("faf")
    if not 1 <= faf <= total + 1:
        raise root.error(f"must be between 1 and total + 1 ({total + 1})", "faf")

    is_aerial = kind is MoveKind.AERIAL
    for key in ("landing_lag", "autocancel"):
        if root.has(key) and not is_aerial:
            raise root.error("is only allowed on aerials", key)
    if is_aerial and not root.has("landing_lag"):
        raise root.error("missing required key (aerials need a landing lag)", "landing_lag")
    if root.has("charge") and kind is not MoveKind.SMASH:
        raise root.error("is only allowed on smash attacks", "charge")

    windows = tuple(
        _window(table, source, index, total, clank_default=not is_aerial)
        for index, table in enumerate(root.tables("windows"))
    )
    for earlier, later in itertools.pairwise(windows):
        if later.frames.first <= earlier.frames.last:
            raise root.error("hit windows must be in order and must not overlap", "windows")

    autocancel: tuple[FrameRange, ...] = ()
    if root.has("autocancel"):
        ranges = root.raw("autocancel")
        if not isinstance(ranges, list):
            raise root.error("must be an array of frame ranges", "autocancel")
        autocancel = tuple(parse_frame_range(r, total, root, "autocancel") for r in ranges)

    return MoveDef(
        id=move_id,
        kind=kind,
        total=total,
        faf=faf,
        anim=root.string("anim") if root.has("anim") else move_id,
        windows=windows,
        motion=tuple(
            _motion(table, source, index, total)
            for index, table in enumerate(root.tables("motion"))
        ),
        charge=_charge(root, total) if root.has("charge") else None,
        cancel=_cancel(root, total) if root.has("cancel") else None,
        landing_lag=root.integer("landing_lag") if is_aerial else 0,
        autocancel=autocancel,
    )


def _enum[E](reader: TableReader, key: str, enum: type[E], default: E | None) -> E:
    if default is not None and not reader.has(key):
        return default
    text = reader.string(key)
    try:
        return enum(text)  # type: ignore[call-arg]
    except ValueError:
        choices = ", ".join(member.value for member in enum)  # type: ignore[attr-defined]
        raise reader.error(f"must be one of {choices}; got {text!r}", key) from None


def _window(table: object, source: str, index: int, total: int, clank_default: bool) -> HitWindow:
    where = f"windows[{index}]"
    reader = TableReader(table, source=source, where=where, allowed=("frames", "hitboxes"))
    frames = parse_frame_range(reader.raw("frames"), total, reader, "frames")
    hitboxes = tuple(
        _hitbox(entry, source, f"{where}.hitboxes[{number}]", clank_default)
        for number, entry in enumerate(reader.tables("hitboxes"))
    )
    if not hitboxes:
        raise reader.error("needs at least one hitbox", "hitboxes")
    ids = [hitbox.id for hitbox in hitboxes]
    if len(set(ids)) != len(ids):
        raise reader.error(f"hitbox ids must be unique within a window, got {ids}", "hitboxes")
    return HitWindow(frames=frames, hitboxes=tuple(sorted(hitboxes, key=lambda box: box.id)))


def _hitbox(table: object, source: str, where: str, clank_default: bool) -> HitboxDef:
    reader = TableReader(table, source=source, where=where, allowed=_HITBOX_KEYS)
    radius = reader.number("radius")
    if radius <= 0:
        raise reader.error("must be greater than 0", "radius")
    damage = reader.number("damage")
    if damage < 0:
        raise reader.error("must be 0 or greater", "damage")
    angle = reader.number("angle")
    if angle != SAKURAI_ANGLE and not -MAX_ELEVATION <= angle <= MAX_ELEVATION:
        raise reader.error(f"must be between -90 and 90, or {SAKURAI_ANGLE:g} (Sakurai)", "angle")
    rehit = reader.integer("rehit") if reader.has("rehit") else 0
    if rehit < 0:
        raise reader.error("must be 0 or greater", "rehit")

    hits = _HIT_TARGETS
    if reader.has("hits"):
        raw = reader.raw("hits")
        if not isinstance(raw, list) or not raw or any(item not in _HIT_TARGETS for item in raw):
            raise reader.error(f'must be a list of "ground" and/or "air", got {raw!r}', "hits")
        hits = tuple(raw)

    return HitboxDef(
        id=reader.integer("id"),
        group=reader.integer("group") if reader.has("group") else 0,
        offset=Vec3(*reader.numbers("offset", 3)),
        radius=radius,
        damage=damage,
        angle=angle,
        yaw=reader.number("yaw", 0.0),
        direction_mode=_enum(reader, "direction_mode", DirectionMode, DirectionMode.FACING),
        bkb=reader.number("bkb", 0.0),
        kbg=reader.number("kbg", 100.0),
        fkb=reader.number("fkb", 0.0),
        hitlag_mult=reader.number("hitlag_mult", 1.0),
        sdi_mult=reader.number("sdi_mult", 1.0),
        effect=_enum(reader, "effect", Effect, Effect.NORMAL),
        hits_ground="ground" in hits,
        hits_air="air" in hits,
        rehit=rehit,
        clank=reader.boolean("clank", default=clank_default),
    )


def _motion(table: object, source: str, index: int, total: int) -> MotionWindow:
    reader = TableReader(
        table, source=source, where=f"motion[{index}]", allowed=("frames", "velocity")
    )
    return MotionWindow(
        frames=parse_frame_range(reader.raw("frames"), total, reader, "frames"),
        velocity=Vec3(*reader.numbers("velocity", 3)),
    )


def _charge(root: TableReader, total: int) -> ChargeDef:
    reader = root.subtable("charge", ("frame", "max_frames", "damage_mult"))
    frame, max_frames = reader.integer("frame"), reader.integer("max_frames")
    if not 1 <= frame <= total:
        raise reader.error(f"must be within 1..{total}", "frame")
    if max_frames < 1:
        raise reader.error("must be 1 or greater", "max_frames")
    damage_mult = reader.number("damage_mult")
    if damage_mult < 1:
        raise reader.error("must be 1 or greater", "damage_mult")
    return ChargeDef(frame=frame, max_frames=max_frames, damage_mult=damage_mult)


def _cancel(root: TableReader, total: int) -> CancelDef:
    reader = root.subtable("cancel", ("frames", "into"))
    return CancelDef(
        frames=parse_frame_range(reader.raw("frames"), total, reader, "frames"),
        into=reader.string("into"),
    )
