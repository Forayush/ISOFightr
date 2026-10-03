"""Mesh primitives for scripted models (runs inside Blender).

Built with ``bmesh`` rather than ``bpy.ops`` so they work in background mode without a
context. Every part gets its own mesh data (its material is swapped per render pass).
"""

from __future__ import annotations

import math
from itertools import pairwise

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector


def _object(name: str, mesh: bmesh.types.BMesh, material_id: int, parent: bpy.types.Object):
    data = bpy.data.meshes.new(name)
    mesh.to_mesh(data)
    mesh.free()
    for polygon in data.polygons:
        polygon.use_smooth = False
    obj = bpy.data.objects.new(name, data)
    obj["material_id"] = material_id
    obj.parent = parent
    bpy.context.scene.collection.objects.link(obj)
    return obj


def box(
    name: str,
    low: tuple[float, float, float],
    high: tuple[float, float, float],
    material_id: int,
    parent: bpy.types.Object,
) -> bpy.types.Object:
    """An axis-aligned box from ``low`` to ``high`` in the parent's space."""
    mesh = bmesh.new()
    bmesh.ops.create_cube(mesh, size=1.0)
    size = Vector(high) - Vector(low)
    centre = (Vector(high) + Vector(low)) / 2
    bmesh.ops.transform(
        mesh,
        matrix=Matrix.Translation(centre) @ Matrix.Diagonal((*size, 1.0)),
        verts=mesh.verts,
    )
    return _object(name, mesh, material_id, parent)


def cylinder(
    name: str,
    radius: float,
    z0: float,
    z1: float,
    material_id: int,
    parent: bpy.types.Object,
    segments: int = 24,
) -> bpy.types.Object:
    """An upright cylinder of ``radius`` from height ``z0`` to ``z1`` over the origin."""
    mesh = bmesh.new()
    bmesh.ops.create_cone(
        mesh,
        cap_ends=True,
        segments=segments,
        radius1=radius,
        radius2=radius,
        depth=z1 - z0,
    )
    bmesh.ops.translate(mesh, vec=(0.0, 0.0, (z0 + z1) / 2), verts=mesh.verts)
    return _object(name, mesh, material_id, parent)


def rod(
    name: str,
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    r1: float,
    r2: float,
    material_id: int,
    parent: bpy.types.Object,
    segments: int = 16,
) -> bpy.types.Object:
    """A tapered cylinder from ``a`` (radius ``r1``) to ``b`` (radius ``r2``)."""
    start, end = Vector(a), Vector(b)
    axis = end - start
    mesh = bmesh.new()
    bmesh.ops.create_cone(
        mesh, cap_ends=True, segments=segments, radius1=r1, radius2=r2, depth=axis.length
    )
    # The cone runs along z from -depth/2 (radius1) to +depth/2 (radius2).
    turn = Vector((0.0, 0.0, 1.0)).rotation_difference(axis.normalized()).to_matrix().to_4x4()
    bmesh.ops.transform(
        mesh,
        matrix=Matrix.Translation(start) @ turn @ Matrix.Translation((0.0, 0.0, axis.length / 2)),
        verts=mesh.verts,
    )
    return _object(name, mesh, material_id, parent)


def ball(
    name: str,
    centre: tuple[float, float, float],
    radius: float,
    scale: tuple[float, float, float],
    material_id: int,
    parent: bpy.types.Object,
    segments: int = 20,
) -> bpy.types.Object:
    """An ellipsoid: a UV sphere of ``radius`` stretched by ``scale``."""
    mesh = bmesh.new()
    bmesh.ops.create_uvsphere(mesh, u_segments=segments, v_segments=segments // 2, radius=radius)
    bmesh.ops.transform(
        mesh, matrix=Matrix.Translation(centre) @ Matrix.Diagonal((*scale, 1.0)), verts=mesh.verts
    )
    return _object(name, mesh, material_id, parent)


def arc(
    name: str,
    centre: tuple[float, float, float],
    r_in: float,
    r_out: float,
    a0: float,
    a1: float,
    thickness: float,
    turn: tuple[float, float, float],
    material_id: int,
    parent: bpy.types.Object,
) -> bpy.types.Object:
    """A flat ring sector: the smear of a swing.

    It lies in the joint's xy plane before ``turn`` (degrees, XYZ) tilts it. Angles are in
    degrees from +y (forward), increasing toward -x (the character's left), so ``a0 = -90,
    a1 = 90`` sweeps from the right side, across the front, to the left side.
    """
    mesh = bmesh.new()
    steps = max(4, int(abs(a1 - a0) / 10))
    rings: list[list[bmesh.types.BMVert]] = []
    for step in range(steps + 1):
        angle = math.radians(a0 + (a1 - a0) * step / steps)
        direction = Vector((-math.sin(angle), math.cos(angle), 0.0))
        # Taper toward the start of the swing, like a brush stroke.
        inner = r_out - (r_out - r_in) * (0.25 + 0.75 * step / steps)
        rings.append(
            [
                mesh.verts.new(direction * radius + Vector((0.0, 0.0, z)))
                for radius in (inner, r_out)
                for z in (-thickness / 2, thickness / 2)
            ]
        )
    for current, following in pairwise(rings):
        for a, b in ((0, 2), (1, 3), (0, 1), (2, 3)):
            mesh.faces.new((current[a], current[b], following[b], following[a]))
    for end in (rings[0], rings[-1]):
        mesh.faces.new((end[0], end[1], end[3], end[2]))
    rotation = Euler(tuple(math.radians(value) for value in turn), "XYZ").to_matrix().to_4x4()
    bmesh.ops.transform(mesh, matrix=Matrix.Translation(centre) @ rotation, verts=mesh.verts)
    bmesh.ops.recalc_face_normals(mesh, faces=mesh.faces)
    return _object(name, mesh, material_id, parent)


def sphere(
    name: str,
    radius: float,
    centre: tuple[float, float, float],
    material_id: int,
    parent: bpy.types.Object,
    segments: int = 24,
) -> bpy.types.Object:
    """A UV sphere."""
    mesh = bmesh.new()
    bmesh.ops.create_uvsphere(mesh, u_segments=segments, v_segments=segments // 2, radius=radius)
    bmesh.ops.translate(mesh, vec=centre, verts=mesh.verts)
    return _object(name, mesh, material_id, parent)
