"""Scene, camera and render setup shared by every Blender script (runs inside Blender).

Plan note "03 - Isometric World and Rendering" ("Rendering 3D source art", D-044): an
orthographic camera at 30 degrees elevation, 16 * sqrt(2) px per world unit, and the scene
squashed by sqrt(2/3) along z, reproduces the game's projection
``sx = (x - y) * 16``, ``sy = -(x + y) * 8 + z * 16`` pixel for pixel.

Every frame is rendered twice with Cycles, one sample per pixel at the pixel centre (no
anti-aliasing) and the "Raw" view transform, so pixel values are exact:

- the **id pass**: each part emits ``material_id * ID_STEP`` in red, ``part_index * PART_STEP``
  in green and its distance from the camera in blue (``DEPTH_NEAR`` to ``DEPTH_FAR`` mapped to
  0..255), so the packer can draw outlines where one part passes in front of another;
- the **light pass**: every part is white diffuse lit by one sun, so the red channel is
  ``255 * cos(angle to the light)`` (0 in shadow).

**Axes:** the game's world is mirror-handed relative to a real camera: it draws world +x to
the screen's right while looking along ``(-1, -1)``, where a right-handed view would show +x on
the left. So Blender's ``(x, y, z)`` is the game's ``(y, x, z)`` (:func:`game_to_blender`).
Models are built in Blender's own right-handed space and look correct (a right hand stays a
right hand); only positions and directions coming from the game are swapped.

``tools/pack_sprites.py`` turns the two into palette indices. Blender's Python cannot import
``isofightr``, so this module only uses ``bpy``, ``mathutils`` and the standard library.
"""

from __future__ import annotations

import math
from pathlib import Path

import bpy
from mathutils import Vector

PX_PER_UNIT = 16.0 * math.sqrt(2.0)
"""Screen pixels per world unit along the ground axes' diagonal."""
ELEVATION_DEGREES = 30.0
Z_SQUASH = math.sqrt(2.0 / 3.0)
"""The camera would draw a unit of height as PX_PER_UNIT * cos(30) = 19.6 px; the game uses 16."""
ID_STEP = 8
"""Material ids are written as ``id * ID_STEP`` so that rounding can never merge two ids."""
PART_STEP = 4
"""Part indices are written as ``index * PART_STEP`` (at most 63 parts)."""
CAMERA_DISTANCE = 40.0
DEPTH_NEAR = CAMERA_DISTANCE - 6.0
DEPTH_FAR = CAMERA_DISTANCE + 6.0
SUN_STRENGTH = math.pi
"""A white diffuse surface facing this sun renders exactly 1.0 (255)."""
LIGHT_FROM_SCREEN = (-0.55, 0.75, 0.37)
"""Direction toward the key light in screen terms: (right, up, toward the viewer)."""
ROOT_NAME = "iso_root"


def game_to_blender(x: float, y: float, z: float = 0.0) -> Vector:
    """Convert a game world point or direction to Blender space (x and y swapped)."""
    return Vector((y, x, z))


def screen_axes() -> tuple[Vector, Vector, Vector]:
    """Return Blender vectors for screen right, screen up and toward the viewer (unit length).

    The camera looks along ``(-1, -1)`` tilted down by 30 degrees, so screen right is Blender
    ``(-1, 1)/sqrt(2)`` (game ``(1, -1)/sqrt(2)``).
    """
    elevation = math.radians(ELEVATION_DEGREES)
    right = Vector((-1.0, 1.0, 0.0)).normalized()
    horizontal_back = Vector((1.0, 1.0, 0.0)).normalized()
    world_up = Vector((0.0, 0.0, 1.0))
    toward_viewer = horizontal_back * math.cos(elevation) + world_up * math.sin(elevation)
    up = world_up * math.cos(elevation) - horizontal_back * math.sin(elevation)
    return right, up, toward_viewer


def reset_scene() -> bpy.types.Scene:
    """Empty the file and return the scene, set up for exact, alias-free renders."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.cycles.seed = 0
    scene.cycles.pixel_filter_type = "BOX"
    scene.cycles.filter_width = 0.01
    scene.cycles.max_bounces = 0
    scene.cycles.diffuse_bounces = 0
    scene.render.film_transparent = True
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 4
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.dither_intensity = 0.0
    scene.view_settings.view_transform = "Raw"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.display_settings.display_device = "sRGB"
    world = bpy.data.worlds.new("black")
    world.color = (0.0, 0.0, 0.0)
    scene.world = world
    root = bpy.data.objects.new(ROOT_NAME, None)
    root.scale = (1.0, 1.0, Z_SQUASH)
    scene.collection.objects.link(root)
    return scene


def root() -> bpy.types.Object:
    """The empty every model hangs from; it carries the z squash."""
    return bpy.data.objects[ROOT_NAME]


def setup_camera(scene: bpy.types.Scene, width: int, height: int, pivot: tuple[int, int]) -> None:
    """Add the orthographic camera.

    Args:
        width, height: the canvas in pixels.
        pivot: the pixel corner, from the top-left, where world ``(0, 0, 0)`` lands.
    """
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0
    data = bpy.data.cameras.new("iso_camera")
    data.type = "ORTHO"
    data.ortho_scale = max(width, height) / PX_PER_UNIT
    data.clip_start = 0.1
    data.clip_end = CAMERA_DISTANCE * 2
    camera = bpy.data.objects.new("iso_camera", data)
    scene.collection.objects.link(camera)
    scene.camera = camera

    right, up, toward_viewer = screen_axes()
    # The image centre shows the world point that is this many pixels right/up of the origin.
    centre_right = (width / 2 - pivot[0]) / PX_PER_UNIT
    centre_up = (pivot[1] - height / 2) / PX_PER_UNIT
    target = right * centre_right + up * centre_up
    camera.location = target + toward_viewer * CAMERA_DISTANCE
    camera.rotation_euler = (math.radians(90.0 - ELEVATION_DEGREES), 0.0, math.radians(135.0))


def setup_sun(scene: bpy.types.Scene) -> None:
    """Add the key light: one sun from the screen's top-left, a little toward the viewer."""
    right, up, toward_viewer = screen_axes()
    light_from = (
        right * LIGHT_FROM_SCREEN[0]
        + up * LIGHT_FROM_SCREEN[1]
        + toward_viewer * LIGHT_FROM_SCREEN[2]
    ).normalized()
    data = bpy.data.lights.new("sun", "SUN")
    data.energy = SUN_STRENGTH
    data.angle = 0.0
    sun = bpy.data.objects.new("sun", data)
    sun.rotation_euler = light_from.to_track_quat("Z", "Y").to_euler()
    scene.collection.objects.link(sun)


def _id_pass_material(name: str, red: float, green: float) -> bpy.types.Material:
    """Emit ``(red, green, depth)``, where depth is the camera distance mapped to 0..1."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    camera = tree.nodes.new("ShaderNodeCameraData")
    depth = tree.nodes.new("ShaderNodeMapRange")
    depth.clamp = True
    depth.inputs["From Min"].default_value = DEPTH_NEAR
    depth.inputs["From Max"].default_value = DEPTH_FAR
    depth.inputs["To Min"].default_value = 0.0
    depth.inputs["To Max"].default_value = 1.0
    combine = tree.nodes.new("ShaderNodeCombineColor")
    combine.inputs["Red"].default_value = red
    combine.inputs["Green"].default_value = green
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    tree.links.new(camera.outputs["View Z Depth"], depth.inputs["Value"])
    tree.links.new(depth.outputs["Result"], combine.inputs["Blue"])
    tree.links.new(combine.outputs["Color"], emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def _white_diffuse() -> bpy.types.Material:
    material = bpy.data.materials.get("light_white")
    if material is not None:
        return material
    material = bpy.data.materials.new("light_white")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    output = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(diffuse.outputs["BSDF"], output.inputs["Surface"])
    return material


def id_material(material_id: int, part_index: int) -> bpy.types.Material:
    """Return the id-pass material for a material id and part index (cached)."""
    name = f"id_{material_id}_{part_index}"
    material = bpy.data.materials.get(name)
    if material is None:
        material = _id_pass_material(
            name, material_id * ID_STEP / 255.0, part_index * PART_STEP / 255.0
        )
    return material


def model_objects() -> list[bpy.types.Object]:
    """Every mesh that carries a ``material_id``."""
    return [obj for obj in bpy.data.objects if obj.type == "MESH" and "material_id" in obj]


def render_passes(scene: bpy.types.Scene, id_path: Path, light_path: Path) -> None:
    """Render the id pass and the light pass of the current frame."""
    meshes = model_objects()
    for obj in meshes:
        obj.data.materials.clear()
        part_index = int(obj.get("part_index", 0))
        obj.data.materials.append(id_material(int(obj["material_id"]), part_index))
    _render(scene, id_path)
    white = _white_diffuse()
    for obj in meshes:
        obj.data.materials.clear()
        obj.data.materials.append(white)
    _render(scene, light_path)


def _render(scene: bpy.types.Scene, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
