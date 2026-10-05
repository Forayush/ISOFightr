"""Guards hard rule 1: ``isofightr.sim`` is pure, deterministic Python.

It must never import ``arcade`` or ``pyglet``, read a clock, or use ``random`` (plan note
"02 - Technical Architecture", determinism rules).
"""

import ast
import pkgutil
import subprocess
import sys
from pathlib import Path

import isofightr.sim

SIM_DIR = Path(isofightr.sim.__file__).parent
FORBIDDEN_MODULES = frozenset({"arcade", "pyglet", "random", "time", "datetime", "secrets"})
GPU_MODULES = ("arcade", "pyglet")


def _imported_roots(source: str) -> set[str]:
    """Return the top-level package of every absolute import in ``source``."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _sim_module_names() -> list[str]:
    return sorted(
        info.name for info in pkgutil.walk_packages(isofightr.sim.__path__, "isofightr.sim.")
    )


def test_import_scanner_sees_every_import_form() -> None:
    source = "import arcade.gl\nfrom pyglet import math\nfrom . import sibling\nimport os\n"
    assert _imported_roots(source) == {"arcade", "pyglet", "os"}


def test_sim_skeleton_is_present() -> None:
    names = _sim_module_names()
    for expected in ("match", "fighter", "physics", "combat.knockback", "states.ground"):
        assert f"isofightr.sim.{expected}" in names


def test_sim_never_imports_forbidden_modules() -> None:
    offenders = {
        str(path.relative_to(SIM_DIR)): sorted(bad)
        for path in sorted(SIM_DIR.rglob("*.py"))
        if (bad := _imported_roots(path.read_text(encoding="utf-8")) & FORBIDDEN_MODULES)
    }
    assert offenders == {}


def test_importing_all_of_sim_never_loads_arcade_or_pyglet() -> None:
    """Catches indirect imports too, e.g. through a non-sim helper module."""
    script = (
        "import importlib, sys\n"
        f"for name in {_sim_module_names()!r}:\n"
        "    importlib.import_module(name)\n"
        f"loaded = [name for name in {GPU_MODULES!r} if name in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


WINDOWLESS_MODULES = (
    "isofightr.__main__",
    "isofightr.headless",
    "isofightr.audio.cues",
    "isofightr.audio.recipes",
    "isofightr.audio.sound_director",
    "isofightr.audio.synth",
    "isofightr.ai.controller",
    "isofightr.ai.dummy",
    "isofightr.ai.knowledge",
    "isofightr.ai.levels",
    "isofightr.art.anims",
    "isofightr.art.blender",
    "isofightr.art.packer",
    "isofightr.art.palettes",
    "isofightr.art.portraits",
    "isofightr.art.tileset",
    "isofightr.ai.random_inputs",
    "isofightr.ai.terrain",
    "isofightr.ai.view",
    "isofightr.input.gamepad",
    "isofightr.input.keyboard",
    "isofightr.data.sprite_sheet",
    "isofightr.data.tileset_art",
    "isofightr.render.ground_items",
    "isofightr.render.projectile_art",
    "isofightr.render.anim_select",
    "isofightr.render.backdrop",
    "isofightr.render.camera",
    "isofightr.render.depth",
    "isofightr.render.effects",
    "isofightr.render.fighter_look",
    "isofightr.render.hitbox_shapes",
    "isofightr.render.iso",
    "isofightr.render.pixel_scale",
    "isofightr.render.placeholder_art",
    "isofightr.render.shadows",
    "isofightr.render.stage_art",
    "isofightr.render.vfx_art",
    "isofightr.scenes.setup",
    "isofightr.settings",
    "isofightr.ui.hud_layout",
    "isofightr.ui.input_display",
    "isofightr.ui.menu",
    "isofightr.ui.move_list",
    "isofightr.ui.pixel_font",
)
"""Presentation helpers the default test run imports. CI has no display, so none of them may
pull in ``arcade`` or ``pyglet``; the parts that draw live in separate modules."""


def test_windowless_presentation_modules_never_load_arcade_or_pyglet() -> None:
    script = (
        "import importlib, sys\n"
        f"for name in {WINDOWLESS_MODULES!r}:\n"
        "    importlib.import_module(name)\n"
        f"loaded = [name for name in {GPU_MODULES!r} if name in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
