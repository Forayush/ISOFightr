"""Pictures of the hit splash (decision D-068), drawn with Pillow from a sprite's key.

Plan note "09 - Art Direction" (VFX style). :class:`isofightr.render.hit_splash.HitSplashes`
says what to show as keys: ``("burst", theme, tier, frame)``, ``("core", theme, tier,
frame)``, ``("lines", theme, tier, angle)`` and ``("particle", theme, tier, frame)``; the effect
renderer turns each key into a texture once and caches it.

Until each theme has its own art (M17 group 2), every theme is drawn with the effects that
already exist: the hit spark for the burst and the held core (in the colours of the hit's
effect), the launch streak for the directional lines, and an ember dot for each particle (in
the colour family of the theme). Every colour is a Resurrect 64 entry (they are
:mod:`isofightr.render.vfx_art`'s).

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from typing import Final

from PIL import Image

from isofightr.render import vfx_art

SPARK_EFFECT: Final[dict[str, str]] = {
    "normal": "normal",
    "slash": "slash",
    "fire": "fire",
    "darkness": "darkness",
    "electric": "electric",
    "ice": "ice",
    "earth": "normal",
    "wind": "normal",
}
"""Whose spark colours each theme's placeholder uses (a character theme has none yet)."""
PARTICLE_FAMILY: Final[dict[str, str]] = {
    "normal": "pale",
    "slash": "pale",
    "fire": "fire",
    "darkness": "rune",
    "electric": "wind",
    "ice": "pale",
    "earth": "stone",
    "wind": "wind",
}
"""The colour family (``vfx_art.FAMILIES``) of each theme's particles."""
CORE_SPARK_FRAMES: Final[tuple[int, ...]] = (1, 2, 2)
"""The spark frame the placeholder shows for each frame of the held core: solid once, then
its hollow outline for the rest of the freeze."""
THEMES: Final[tuple[str, ...]] = tuple(SPARK_EFFECT)


def build(key: tuple[str | int, ...]) -> Image.Image:
    """Return the picture for a splash sprite's key (see the module docstring)."""
    kind, theme, tier, step = key
    assert isinstance(theme, str) and isinstance(tier, int) and isinstance(step, int)
    if kind == "burst":
        return vfx_art.build_spark(tier, SPARK_EFFECT[theme], min(step, 1))
    if kind == "core":
        frame = CORE_SPARK_FRAMES[min(step, len(CORE_SPARK_FRAMES) - 1)]
        return vfx_art.build_spark(tier, SPARK_EFFECT[theme], frame)
    if kind == "lines":
        return vfx_art.build_streak(step, 0)
    if kind == "particle":
        return vfx_art.build_fx("ember", PARTICLE_FAMILY[theme], 0, step)
    raise ValueError(f"no splash picture of kind {kind!r}")
