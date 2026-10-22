"""With hit effects Off the effect layer draws exactly what it drew before the hit splash
(decision D-068, M17): the sprites the effect renderer places, tick by tick, in a real battle
replaying the same scenarios as ``test_hit_effects_off.py`` (the random play cut short).

``tests/fixtures/hit_effects_today_gl.json`` was recorded in M17 group 0; re-record it
(``pytest -m gl --update-goldens``) only together with the sim goldens.
"""

import hashlib
from typing import Any

import pytest

import effects_digest as digest

pytestmark = pytest.mark.gl

FIXTURE = "hit_effects_today_gl.json"
RANDOM_TICKS = 900
DESCRIPTION = (
    "The effect layer before the hit splash (M17 group 0): per window of ticks, a hash of "
    "every sprite the effect renderer placed (its texture's key and its place) in a battle "
    "replaying the first 900 ticks of test_hit_effects_off's random play and its hit storm."
)


def placed(view: Any) -> tuple[Any, ...]:
    """The effect layer's sprites on this frame: each one's texture key and position."""
    renderer = view.effect_renderer
    keys = {id(texture): key for key, texture in renderer._textures.items()}
    return tuple(
        (keys[id(sprite.texture)], tuple(sprite.position))
        for sprite in renderer._pool[: renderer.live]
    )


def play(window: Any) -> list[str]:
    from isofightr.data.stage_loader import load_stage
    from isofightr.scenes.battle import BattleView
    from isofightr.settings import HIT_EFFECTS_OFF
    from isofightr.sim.replay import Replay

    windows: list[str] = []
    for scenario in digest.scenarios():
        inputs = scenario.inputs if scenario.storm else scenario.inputs[:RANDOM_TICKS]
        replay = Replay(
            scenario.stage,
            scenario.characters,
            scenario.seed,
            scenario.rules,
            tuple(tuple(frames) for frames in inputs),
            "",
        )
        characters = [fighter.character for fighter in scenario.match().fighters]
        view = BattleView(
            window.pixel_buffer,
            load_stage(scenario.stage),
            characters,
            seed=scenario.seed,
            rules=scenario.rules,
            replay=replay,
        )
        view.show_help = False
        view.effects.hit_effects = HIT_EFFECTS_OFF
        window.show_view(view)
        running = hashlib.sha1()
        for tick in range(len(inputs)):
            if scenario.storm:
                digest.storm_round(view.match, tick)
            view.tick()
            view.on_draw()
            running.update(repr(digest.plain(placed(view))).encode())
            if (tick + 1) % digest.WINDOW == 0 or tick + 1 == len(inputs):
                windows.append(running.hexdigest()[:12])
                running = hashlib.sha1()
    return windows


def test_the_effect_layer_draws_todays_sprites(window: Any, update_goldens: bool) -> None:
    played = play(window)
    if update_goldens:
        digest.save(FIXTURE, DESCRIPTION, {"renderer": played})
    recorded = digest.load(FIXTURE)["renderer"]
    lengths = {"random": RANDOM_TICKS}
    assert played == recorded, digest.first_difference(recorded, played, lengths)
