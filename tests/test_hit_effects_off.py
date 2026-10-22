"""With hit effects Off the battle shows exactly the hit feedback it showed before the hit
splash (decision D-068, M17).

``tests/fixtures/hit_effects_today.json`` was recorded in M17 group 0, before any hit-splash
code existed: tick by tick, what the effects (sparks, streaks, element extras, dust, trails,
rings, KO blasts, shake, flashes, combo readouts, afterimages), the hit poses and the HUD
showed over a long match of random play and a hit storm. Re-record it (``--update-goldens``)
only together with the sim goldens, after an intended change to the sim itself: the events
then differ, and so do the effects they cause.
"""

import effects_digest as digest
from isofightr.render.effects import BattleEffects
from isofightr.settings import HIT_EFFECTS_FULL, HIT_EFFECTS_OFF

FIXTURE = "hit_effects_today.json"
DESCRIPTION = (
    "Hit feedback before the hit splash (M17 group 0): per window of ticks, a hash of what "
    "the effects, the hit poses and the HUD showed over 2400 ticks of random play by all "
    "four characters on Sky Ruins (90% start, parry and helpless air dodges on, input seed "
    "277) and a 624-tick hit storm (normal, slash, fire and darkness hits, projectiles, shield "
    "hits and parries)."
)


def off() -> BattleEffects:
    return BattleEffects(hit_effects=HIT_EFFECTS_OFF)


def test_the_hit_feedback_is_todays(update_goldens: bool) -> None:
    played = digest.run(off)
    if update_goldens:
        digest.save(FIXTURE, DESCRIPTION, played)
    recorded = digest.load(FIXTURE)
    assert recorded["window"] == digest.WINDOW
    for part in digest.PARTS:
        expected = recorded[part]
        where = digest.first_difference(expected, played[part])
        assert played[part] == expected, f"{part}: {where}"


def test_the_digest_sees_a_change_in_the_effects() -> None:
    """The fixture would catch a different effect: one spark more on one tick changes it."""
    from isofightr.render.effects import BattleEffects, Spark
    from isofightr.sim.math3d import ZERO3
    from isofightr.sim.move_def import Effect

    plain = BattleEffects()
    marked = BattleEffects()
    marked.sparks.append(Spark(ZERO3, 0, Effect.NORMAL))
    assert digest.effects_part(plain, 4) != digest.effects_part(marked, 4)


def test_with_the_hit_splash_the_hit_poses_and_the_hud_are_still_todays() -> None:
    """The splash changes only the effect layer: D-067's poses and the HUD are untouched
    (until the HUD's own reaction, M17 group 4)."""
    played = digest.run(lambda: BattleEffects(hit_effects=HIT_EFFECTS_FULL))
    recorded = digest.load(FIXTURE)
    for part in ("hurt", "hud"):
        where = digest.first_difference(recorded[part], played[part])
        assert played[part] == recorded[part], f"{part}: {where}"
    assert played["effects"] != recorded["effects"], "the splash replaces the spark"
