"""Builds a character from ``rig.toml`` and poses it (runs inside Blender).

Plan note "10 - Animation and Asset Pipeline" ("Blender conventions"). A joint is an empty; a
part is a mesh parented to its joint, built in the joint's own space. A pose sets joint
rotations (degrees, XYZ), the hips offset and which hidden parts show.
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


class Rig:
    """A built character: its joints, parts and rest positions."""

    def __init__(self, rig_path: Path, materials: list[str], root: bpy.types.Object) -> None:
        data = tomllib.loads(rig_path.read_text(encoding="utf-8"))
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
        for index, part in enumerate(data["parts"], start=1):
            obj = _build_part(part, materials.index(part["material"]) + 1, self.joints)
            obj["part_index"] = index
            if part.get("hidden", False):
                self.hideable[part["name"]] = obj

    def face(self, direction: tuple[float, float]) -> None:
        """Turn the character so its forward (+y) points along a Blender ground vector."""
        x, y = direction
        self.facing.rotation_euler = (0.0, 0.0, math.atan2(-x, y))

    def pose(self, pose: dict[str, Any]) -> None:
        """Apply a pose: unlisted joints go back to rest."""
        for name, joint in self.joints.items():
            angles = pose.get(name, (0.0, 0.0, 0.0))
            joint.rotation_euler = tuple(math.radians(value) for value in angles)
            joint.location = self.rest[name]
        offset = Vector(pose.get("offset", (0.0, 0.0, 0.0)))
        self.joints[ROOT_JOINT].location = self.rest[ROOT_JOINT] + offset
        shown = set(pose.get("show", ()))
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
    raise ValueError(f"part {name}: unknown shape {shape!r}")


def merged_poses(anim: dict[str, Any]) -> list[dict[str, Any]]:
    """Return an animation's poses with its ``base`` merged into each (pose values win)."""
    base = anim.get("base", {})
    return [{**base, **pose} for pose in anim["poses"]]
