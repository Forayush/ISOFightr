"""Builds a character from ``rig.toml`` and poses it (runs inside Blender).

Plan note "10 - Animation and Asset Pipeline" ("Blender conventions"). A joint is an empty; a
part is a mesh parented to its joint, built in the joint's own space. A pose sets joint
rotations (degrees, XYZ), the hips offset and which smears show.

Pose data is merged in this order, later winning joint by joint: the animation's ``base``, the
named library pose the pose ``use``s (``poses.toml``), then the pose's own values.
"""

from __future__ import annotations

import math
import tomllib
from pathlib import Path
from typing import Any

import bpy
import shapes
from mathutils import Vector

FACING_NAME = "facing"
ROOT_JOINT = "hips"
POSE_KEYS = frozenset({"offset", "show", "start", "use"})
SMEAR_MATERIAL = "smear"
MAX_PART_INDEX = 63
"""Part indices are written into 8 bits as ``index * 4`` (``isoscene.PART_STEP``)."""


class PoseError(ValueError):
    """A pose names a joint, smear or library pose that does not exist."""


class Rig:
    """A built character: its joints, parts and rest positions."""

    def __init__(self, rig_path: Path, materials: list[str], root: bpy.types.Object) -> None:
        data = tomllib.loads(rig_path.read_text(encoding="utf-8"))
        self.materials = materials
        self.facing = bpy.data.objects.new(FACING_NAME, None)
        self.facing.parent = root
        bpy.context.scene.collection.objects.link(self.facing)
        self.joints: dict[str, bpy.types.Object] = {}
        self.rest: dict[str, Vector] = {}
        for joint in data["joints"]:
            empty = bpy.data.objects.new(joint["name"], None)
            empty.parent = self.joints[joint["parent"]] if joint["parent"] else self.facing
            empty.location = joint["at"]
            empty.rotation_mode = "XYZ"
            bpy.context.scene.collection.objects.link(empty)
            self.joints[joint["name"]] = empty
            self.rest[joint["name"]] = Vector(joint["at"])
        self.hideable: dict[str, bpy.types.Object] = {}
        self.part_count = 0
        for index, part in enumerate(data.get("parts", []), start=1):
            obj = self._build(part)
            obj["part_index"] = index
            if part.get("hidden", False):
                self.hideable[part["name"]] = obj
            self.part_count = index

    def _build(self, part: dict[str, Any]) -> bpy.types.Object:
        material = part.get("material", SMEAR_MATERIAL)
        if material not in self.materials:
            raise PoseError(f"part {part['name']}: unknown material {material!r}")
        if part["joint"] not in self.joints:
            raise PoseError(f"part {part['name']}: unknown joint {part['joint']!r}")
        return _build_part(part, self.materials.index(material) + 1, self.joints)

    def add_smears(self, smears: list[dict[str, Any]]) -> list[bpy.types.Object]:
        """Build an animation's own smear parts (hidden until a pose shows them)."""
        built = []
        for smear in smears:
            obj = self._build(smear)
            obj["part_index"] = 0
            obj.hide_render = True
            self.hideable[smear["name"]] = obj
            built.append(obj)
        return built

    def add_parts(self, parts: list[dict[str, Any]]) -> list[bpy.types.Object]:
        """Build an animation's own always-visible parts (a tile's stones, planks, tufts)."""
        built = []
        for offset, part in enumerate(parts):
            obj = self._build(part)
            # Part numbers only decide interior lines between neighbouring parts, so beyond the
            # 63 the id pass can hold they wrap around.
            obj["part_index"] = (self.part_count + offset) % MAX_PART_INDEX + 1
            built.append(obj)
        return built

    def remove(self, objects: list[bpy.types.Object]) -> None:
        """Delete parts added with :meth:`add_smears`."""
        for obj in objects:
            self.hideable.pop(obj.name, None)
            mesh = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)

    def face(self, direction: tuple[float, float]) -> None:
        """Turn the character so its forward (+y) points along a Blender ground vector."""
        x, y = direction
        self.facing.rotation_euler = (0.0, 0.0, math.atan2(-x, y))

    def pose(self, pose: dict[str, Any]) -> None:
        """Apply a merged pose: unlisted joints go back to rest."""
        unknown = set(pose) - POSE_KEYS - set(self.joints)
        if unknown:
            raise PoseError(f"unknown joints {sorted(unknown)}")
        shown = set(pose.get("show", ()))
        if shown - set(self.hideable):
            raise PoseError(f"unknown smears {sorted(shown - set(self.hideable))}")
        for name, joint in self.joints.items():
            angles = pose.get(name, (0.0, 0.0, 0.0))
            joint.rotation_euler = tuple(math.radians(value) for value in angles)
            joint.location = self.rest[name]
        offset = Vector(pose.get("offset", (0.0, 0.0, 0.0)))
        if ROOT_JOINT in self.joints:
            self.joints[ROOT_JOINT].location = self.rest[ROOT_JOINT] + offset
        for name, obj in self.hideable.items():
            obj.hide_render = name not in shown


def _build_part(
    part: dict[str, Any], material_id: int, joints: dict[str, bpy.types.Object]
) -> bpy.types.Object:
    parent = joints[part["joint"]]
    name, shape = part["name"], part["shape"]
    if shape == "box":
        return shapes.box(name, tuple(part["low"]), tuple(part["high"]), material_id, parent)
    if shape == "rod":
        return shapes.rod(
            name,
            tuple(part["a"]),
            tuple(part["b"]),
            part["r1"],
            part["r2"],
            material_id,
            parent,
        )
    if shape == "ball":
        return shapes.ball(
            name,
            tuple(part["centre"]),
            part["radius"],
            tuple(part.get("scale", (1.0, 1.0, 1.0))),
            material_id,
            parent,
        )
    if shape == "arc":
        return shapes.arc(
            name,
            tuple(part.get("centre", (0.0, 0.0, 0.0))),
            part["r_in"],
            part["r_out"],
            part["a0"],
            part["a1"],
            part.get("thickness", 0.04),
            tuple(part.get("turn", (0.0, 0.0, 0.0))),
            material_id,
            parent,
        )
    raise PoseError(f"part {name}: unknown shape {shape!r}")


def load_library(path: Path) -> dict[str, dict[str, Any]]:
    """Load a character's named poses (``poses.toml``), if it has any."""
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def merged_poses(
    anim: dict[str, Any], library: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Return an animation's poses, each merged as base < library pose < its own values."""
    library = library or {}
    base = anim.get("base", {})
    merged = []
    for pose in anim["poses"]:
        used = pose.get("use", base.get("use"))
        if used is not None and used not in library:
            raise PoseError(f"no library pose {used!r}")
        merged.append({**base, **(library.get(used, {}) if used else {}), **pose})
    return merged
