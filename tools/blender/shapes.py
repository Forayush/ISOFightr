"""Mesh primitives for scripted models (runs inside Blender).

Built with ``bmesh`` rather than ``bpy.ops`` so they work in background mode without a
context. Every part gets its own mesh data (its material is swapped per render pass).
"""

from __future__ import annotations

import bmesh
import bpy
from mathutils import Matrix, Vector


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
