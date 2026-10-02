"""Loads ``assets/characters/<id>/fighter.toml`` into an immutable ``CharacterDef``.

Implements "Character data format" and "Validation at load" in the plan note "07 - Fighter
State Machine and Move Data", with strict validation (decision D-009): unknown keys are
errors, and every error names the file and the key.
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from isofightr.data.move_loader import MAX_ELEVATION, load_moves, parse_frame_range
from isofightr.data.paths import CHARACTER_FILE_NAME, CHARACTERS_DIR, MOVES_DIR_NAME
from isofightr.data.validation import DataError, TableReader
from isofightr.sim.character_def import (
    BodyStats,
    CharacterDef,
    GrabDef,
    GrabSet,
    HurtboxDef,
    MovementStats,
    MoveSet,
    PummelDef,
    ThrowDef,
)
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import MoveDef, MoveKind

_SPEED_KEYS = (
    "walk_speed",
    "dash_speed",
    "run_speed",
    "traction",
    "full_hop_vz",
    "short_hop_vz",
    "double_jump_vz",
    "air_accel",
    "air_speed",
    "air_friction",
    "gravity",
    "max_fall",
    "fast_fall",
)
_FRAME_KEYS = ("dash_frames", "jumpsquat", "air_jumps", "land_lag")
_JAB_SLOT = "jab"
_SLOT_KINDS = {
    "ftilt": MoveKind.TILT,
    "utilt": MoveKind.TILT,
    "dtilt": MoveKind.TILT,
    "dash_attack": MoveKind.DASH_ATTACK,
    "fsmash": MoveKind.SMASH,
    "usmash": MoveKind.SMASH,
    "dsmash": MoveKind.SMASH,
    "nair": MoveKind.AERIAL,
    "fair": MoveKind.AERIAL,
    "bair": MoveKind.AERIAL,
    "uair": MoveKind.AERIAL,
    "dair": MoveKind.AERIAL,
    "getup_attack": MoveKind.RECOVERY,
    "ledge_attack": MoveKind.RECOVERY,
    "nspecial": MoveKind.SPECIAL,
    "sspecial": MoveKind.SPECIAL,
    "uspecial": MoveKind.SPECIAL,
    "dspecial": MoveKind.SPECIAL,
    "taunt": MoveKind.TAUNT,
}
_GRAB_KEYS = ("frames", "total", "offset", "radius", "slide")
_THROWS = (("forward", "fthrow"), ("back", "bthrow"), ("up", "uthrow"), ("down", "dthrow"))
_THROW_KEYS = ("damage", "angle", "bkb", "kbg", "release", "total")


def list_character_ids(characters_dir: Path = CHARACTERS_DIR) -> list[str]:
    """Return the ids of every character that has a ``fighter.toml``, sorted."""
    return sorted(path.parent.name for path in characters_dir.glob(f"*/{CHARACTER_FILE_NAME}"))


def load_character(character_id: str, characters_dir: Path = CHARACTERS_DIR) -> CharacterDef:
    """Load a character by id from ``<characters_dir>/<id>/fighter.toml``.

    Raises:
        DataError: if the file is missing, is not valid TOML, or fails validation.
    """
    path = characters_dir / character_id / CHARACTER_FILE_NAME
    if not path.is_file():
        known = ", ".join(list_character_ids(characters_dir)) or "none"
        raise DataError(f"{path}: no such character {character_id!r} (available: {known})")
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise DataError(f"{path}: invalid TOML: {error}") from error
    moves = load_moves(path.parent / MOVES_DIR_NAME)
    return parse_character(data, source=str(path), expected_id=character_id, moves=moves)


def parse_character(
    data: Mapping[str, object],
    *,
    source: str,
    expected_id: str | None = None,
    moves: Mapping[str, MoveDef],
) -> CharacterDef:
    """Validate a parsed ``fighter.toml`` table and build the :class:`CharacterDef`.

    ``moves`` are the character's already loaded move files; every move the moveset names
    must be among them and be of the right kind.
    """
    root = TableReader(
        data,
        source=source,
        where="",
        allowed=("id", "display_name", "weight", "movement", "body", "moveset", "grab", "throws"),
    )
    character_id = root.string("id")
    if expected_id is not None and character_id != expected_id:
        raise root.error(f"is {character_id!r} but the directory is named {expected_id!r}", "id")
    weight = root.number("weight")
    if weight <= 0:
        raise root.error("must be greater than 0", "weight")

    return CharacterDef(
        id=character_id,
        display_name=root.string("display_name"),
        weight=weight,
        movement=_movement(root.subtable("movement", (*_SPEED_KEYS, *_FRAME_KEYS))),
        body=_body(root.subtable("body", ("radius", "height", "hurtbox", "shield_radius_max"))),
        moveset=_moveset(root.subtable("moveset", (_JAB_SLOT, *_SLOT_KINDS)), moves),
        grabs=_grabs(
            root.subtable("grab", ("standing", "dash", "pummel")),
            root.subtable("throws", [name for name, _ in _THROWS]),
        ),
        moves=MappingProxyType(dict(moves)),
    )


def _grabs(grab: TableReader, throws: TableReader) -> GrabSet:
    pummel = grab.subtable("pummel", ("damage", "cooldown"))
    pummel_def = PummelDef(damage=pummel.number("damage"), cooldown=pummel.integer("cooldown"))
    if pummel_def.damage < 0:
        raise pummel.error("must be 0 or greater", "damage")
    if pummel_def.cooldown < 1:
        raise pummel.error("must be 1 or greater", "cooldown")
    parsed = {
        name: _throw(throws.subtable(name, _THROW_KEYS), throw_id) for name, throw_id in _THROWS
    }
    return GrabSet(
        standing=_grab(grab.subtable("standing", _GRAB_KEYS)),
        dash=_grab(grab.subtable("dash", _GRAB_KEYS)),
        pummel=pummel_def,
        forward=parsed["forward"],
        back=parsed["back"],
        up=parsed["up"],
        down=parsed["down"],
    )


def _grab(reader: TableReader) -> GrabDef:
    total = reader.integer("total")
    if total < 1:
        raise reader.error("must be 1 or greater", "total")
    radius = reader.number("radius")
    if radius <= 0:
        raise reader.error("must be greater than 0", "radius")
    slide = reader.number("slide", 0.0) if reader.has("slide") else 0.0
    if slide < 0:
        raise reader.error("must be 0 or greater", "slide")
    return GrabDef(
        frames=parse_frame_range(reader.raw("frames"), total, reader, "frames"),
        total=total,
        offset=Vec3(*reader.numbers("offset", 3)),
        radius=radius,
        slide=slide,
    )


def _throw(reader: TableReader, throw_id: str) -> ThrowDef:
    total, release = reader.integer("total"), reader.integer("release")
    if total < 1:
        raise reader.error("must be 1 or greater", "total")
    if not 1 <= release <= total:
        raise reader.error(f"must be between 1 and total ({total})", "release")
    damage, angle = reader.number("damage"), reader.number("angle")
    if damage < 0:
        raise reader.error("must be 0 or greater", "damage")
    if not -MAX_ELEVATION <= angle <= MAX_ELEVATION:
        raise reader.error(f"must be between -{MAX_ELEVATION:g} and {MAX_ELEVATION:g}", "angle")
    return ThrowDef(
        id=throw_id,
        damage=damage,
        angle=angle,
        bkb=reader.number("bkb"),
        kbg=reader.number("kbg"),
        release=release,
        total=total,
    )


def _moveset(reader: TableReader, moves: Mapping[str, MoveDef]) -> MoveSet:
    jab = reader.raw(_JAB_SLOT)
    if not isinstance(jab, list) or not jab or not all(isinstance(item, str) for item in jab):
        raise reader.error("must be a non-empty list of move ids", _JAB_SLOT)
    for move_id in jab:
        _check_move(reader, _JAB_SLOT, move_id, MoveKind.JAB, moves)
    slots = {}
    for slot, kind in _SLOT_KINDS.items():
        slots[slot] = reader.string(slot)
        _check_move(reader, slot, slots[slot], kind, moves)
    for move in moves.values():
        if move.cancel is not None and move.cancel.into not in moves:
            raise reader.error(f"move {move.id!r} cancels into unknown move {move.cancel.into!r}")
        if move.counter is not None and move.counter.into not in moves:
            raise reader.error(f"move {move.id!r} counters with unknown move {move.counter.into!r}")
    return MoveSet(jab=tuple(jab), **slots)


def _check_move(
    reader: TableReader, slot: str, move_id: str, kind: MoveKind, moves: Mapping[str, MoveDef]
) -> None:
    if move_id not in moves:
        known = ", ".join(sorted(moves)) or "none"
        raise reader.error(f"no move file for {move_id!r} (moves found: {known})", slot)
    if moves[move_id].kind is not kind:
        raise reader.error(
            f"move {move_id!r} is a {moves[move_id].kind.value}, but this slot needs "
            f"a {kind.value}",
            slot,
        )


def _movement(reader: TableReader) -> MovementStats:
    speeds = {key: reader.number(key) for key in _SPEED_KEYS}
    frames = {key: reader.integer(key) for key in _FRAME_KEYS}
    for key, value in speeds.items():
        if value <= 0:
            raise reader.error("must be greater than 0", key)
    for key in ("dash_frames", "jumpsquat"):
        if frames[key] < 1:
            raise reader.error("must be 1 or greater", key)
    for key in ("air_jumps", "land_lag"):
        if frames[key] < 0:
            raise reader.error("must be 0 or greater", key)
    if speeds["short_hop_vz"] >= speeds["full_hop_vz"]:
        raise reader.error("must be less than full_hop_vz", "short_hop_vz")
    if speeds["fast_fall"] < speeds["max_fall"]:
        raise reader.error("must be at least max_fall", "fast_fall")
    return MovementStats(
        walk_speed=speeds["walk_speed"],
        dash_speed=speeds["dash_speed"],
        dash_frames=frames["dash_frames"],
        run_speed=speeds["run_speed"],
        traction=speeds["traction"],
        jumpsquat=frames["jumpsquat"],
        full_hop_vz=speeds["full_hop_vz"],
        short_hop_vz=speeds["short_hop_vz"],
        double_jump_vz=speeds["double_jump_vz"],
        air_jumps=frames["air_jumps"],
        air_accel=speeds["air_accel"],
        air_speed=speeds["air_speed"],
        air_friction=speeds["air_friction"],
        gravity=speeds["gravity"],
        max_fall=speeds["max_fall"],
        fast_fall=speeds["fast_fall"],
        land_lag=frames["land_lag"],
    )


def _body(reader: TableReader) -> BodyStats:
    radius, height = reader.number("radius"), reader.number("height")
    if radius <= 0:
        raise reader.error("must be greater than 0", "radius")
    if height <= 0:
        raise reader.error("must be greater than 0", "height")
    hurt = reader.subtable("hurtbox", ("radius", "z0", "z1"))
    hurtbox = HurtboxDef(radius=hurt.number("radius"), z0=hurt.number("z0"), z1=hurt.number("z1"))
    if hurtbox.radius <= 0:
        raise hurt.error("must be greater than 0", "radius")
    if hurtbox.z1 - hurtbox.z0 < 2 * hurtbox.radius:
        raise hurt.error("must be at least z0 plus twice the radius (a capsule)", "z1")
    shield = reader.number("shield_radius_max")
    if shield <= 0:
        raise reader.error("must be greater than 0", "shield_radius_max")
    return BodyStats(radius=radius, height=height, hurtbox=hurtbox, shield_radius_max=shield)
