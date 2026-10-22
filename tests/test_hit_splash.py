"""Tests for the hit splash model (decision D-068, M17 group 1): its tier, theme and screen
direction, its three phases tied to the hit's freeze (burst, hold, dispersal), its particles
(deterministic, in a cone around the launch after DI), its caps, and how the battle's effects
use it (instead of the spark and the launch streak, unless hit effects are off).
"""

import math
from typing import Any

import pytest

from helpers import hold, place
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.render import hit_splash as hs
from isofightr.render import splash_art
from isofightr.render.effects import PARRY_SHAKE_PIXELS, BattleEffects, streak_angle
from isofightr.render.hit_splash import (
    CRITICAL,
    HEAVY,
    LIGHT,
    MEDIUM,
    GuardSplash,
    HitSplashes,
    Phase,
    angle_step,
    screen_turn,
    theme_of,
    tier_of,
)
from isofightr.render.iso import project
from isofightr.render.placeholder_art import sphere_screen_size
from isofightr.settings import HIT_EFFECTS_FULL, HIT_EFFECTS_MINIMAL, HIT_EFFECTS_OFF
from isofightr.sim.combat.knockback import launch_vector
from isofightr.sim.combat.shield import shield_centre, shield_radius
from isofightr.sim.events import (
    ClankEvent,
    HazardHitEvent,
    HitEvent,
    LaunchEvent,
    ShieldHitEvent,
)
from isofightr.sim.fighter import Fighter, Launch
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.move_def import Effect
from isofightr.sim.states.interrupts import start_move

CONTACT = Vec3(5.0, 6.0, 1.2)


def across(angle: int) -> Vec3:
    """A world direction the projection draws ``angle`` sixteenths of a turn from right."""
    turn = 2.0 * math.pi * angle / 16
    return Vec3(math.cos(turn) / 32.0, -math.cos(turn) / 32.0, math.sin(turn) / 16.0)


def hit_event(
    knockback: float = 100.0,
    hitlag: int = 11,
    effect: Effect = Effect.NORMAL,
    sweet: bool = False,
    multi: bool = False,
    target: int = 1,
) -> HitEvent:
    return HitEvent(
        attacker=0,
        target=target,
        move_id="fsmash",
        damage=12.0,
        knockback=knockback,
        position=CONTACT + Vec3(0.5, 0.0, 0.0),
        effect=effect,
        hitlag=hitlag,
        contact=CONTACT,
        sweet=sweet,
        multi=multi,
    )


def duel() -> Match:
    match = Match.create(
        load_stage("training_grid"),
        [load_character("rook"), load_character("rook")],
        rules=MatchRules(stocks=None),
    )
    place(match, match.fighters[0], 4.0, 6.0, facing=Dir8.E)
    place(match, match.fighters[1], 5.0, 6.0, facing=Dir8.W)
    return match


def frozen(target: Fighter, hitlag: int, direction: Vec3) -> None:
    """Give the target a pending launch along ``direction`` and a freeze of ``hitlag``."""
    flat = math.hypot(direction.x, direction.y)
    heading = Vec2(direction.x, direction.y) / flat if flat > 1e-12 else Vec2(1.0, 0.0)
    elevation = math.degrees(math.atan2(direction.z, flat))
    target.launch = Launch(100.0, heading, elevation, True)
    target.hitlag = hitlag


def play(
    hitlag: int,
    launch_at: int | None,
    direction: Vec3 | None = None,
    di: Vec3 | None = None,
    ticks: int = 40,
    splashes: HitSplashes | None = None,
) -> tuple[HitSplashes, list[tuple[Phase, list[hs.SplashSprite]]]]:
    """Feed a hit (and its launch at ``launch_at`` ticks, along ``di`` or the pending launch)
    to a fresh model as the battle does, and record each tick's phase and sprites."""
    match = duel()
    target = match.fighters[1]
    direction = direction or across(0)
    model = splashes or HitSplashes(forecast=lambda stage, fighter: False)
    seen = []
    for tick in range(ticks):
        if tick:
            model.tick()
        if tick == 0:
            frozen(target, hitlag, direction)
            model.hit(hit_event(hitlag=hitlag))
        elif launch_at is not None and tick == launch_at:
            model.launch(LaunchEvent(1, target.pos, (di or direction).normalized(), 100.0))
            target.launch = None
            target.hitlag = 0
        elif target.hitlag:
            target.hitlag -= 1
        model.observe(match.fighters, match.stage, 600 + tick)
        phase = model.splashes[0].phase if model.splashes else Phase.DONE
        seen.append((phase, model.sprites()))
    return model, seen


# --- tier, theme, direction -----------------------------------------------------------------


def test_the_tier_is_the_knockback_band_moved_by_sweetspots_and_multi_hits() -> None:
    assert [tier_of(kb, False, False, False) for kb in (0, 39.9, 40, 79.9, 80, 150, 400)] == [
        LIGHT,
        LIGHT,
        MEDIUM,
        MEDIUM,
        HEAVY,
        HEAVY,
        HEAVY,
    ], "KB 150 that does not KO is still heavy (D-068, agreed)"
    assert tier_of(20.0, True, False, False) == MEDIUM
    assert tier_of(100.0, True, False, False) == HEAVY, "a sweetspot makes it heavy at most"
    assert tier_of(60.0, False, True, False) == LIGHT
    assert tier_of(10.0, False, True, False) == LIGHT, "never below light"
    assert tier_of(90.0, False, False, True) == CRITICAL, "only a forecast KO is critical"
    assert tier_of(90.0, False, True, True) == CRITICAL


def test_the_theme_is_the_effect_or_the_attackers() -> None:
    assert theme_of(Effect.FIRE, "slash") == "fire"
    assert theme_of(Effect.NORMAL, "earth") == "earth"
    assert theme_of(Effect.NORMAL, "") == "normal"


def test_every_screen_direction_snaps_to_its_sixteenth() -> None:
    for angle in range(16):
        assert angle_step(screen_turn(across(angle))) == angle
    assert angle_step(screen_turn(Vec3(0.0, 0.0, 1.0))) == 4, "straight up"
    assert angle_step(screen_turn(Vec3(0.0, 0.0, -1.0))) == 12, "straight down"
    assert angle_step(screen_turn(Vec3(1.0, 0.0, 0.0))) == 15, "world +x: down and right"
    up_right = launch_vector(Dir8.E.world, 45.0)
    assert angle_step(screen_turn(up_right)) == 2, "up and right, diagonally"


def test_a_launch_at_the_camera_or_away_from_it_has_no_direction() -> None:
    toward = Vec3(1.0, 1.0, 1.0).normalized()
    assert project(toward.x, toward.y, toward.z) == pytest.approx((0.0, 0.0))
    assert screen_turn(toward) is None and screen_turn(-toward) is None
    assert angle_step(None) is None


def test_the_hold_points_where_the_launch_streak_did() -> None:
    for elevation in (-40.0, 0.0, 38.0, 75.0):
        launch = Launch(100.0, Dir8.E.world, elevation, True)
        direction = launch_vector(launch.heading, elevation)
        assert angle_step(screen_turn(direction)) == streak_angle(launch)


# --- the phases -------------------------------------------------------------------------------


@pytest.mark.parametrize("hitlag", [3, 8, 11, 30])
def test_burst_then_hold_for_exactly_the_freeze_then_dispersal_on_the_launch(
    hitlag: int,
) -> None:
    _, seen = play(hitlag, launch_at=hitlag, ticks=hitlag + 20)
    phases = [phase for phase, _ in seen]
    assert phases[:2] == [Phase.BURST, Phase.BURST], "the contact tick and the next"
    assert phases[2:hitlag] == [Phase.HOLD] * (hitlag - 2), "the rest of the freeze"
    assert phases[hitlag] is Phase.DISPERSAL, "on the tick the launch starts"
    end = hitlag + hs.DISPERSAL_TICKS[HEAVY]
    assert set(phases[hitlag:end]) == {Phase.DISPERSAL} and phases[end] is Phase.DONE
    kinds = [{sprite.key[0] for sprite in sprites} for _, sprites in seen]
    assert kinds[0] == {"burst", "split"}, "a heavy hit's burst has its chromatic split"
    assert all(kind == {"core", "lines"} for kind in kinds[2:hitlag])
    assert kinds[hitlag] == {"particle", "ring"}, "the core is gone when the launch starts"


def test_the_held_frames_spread_across_the_freeze() -> None:
    _, seen = play(30, launch_at=30)
    frames = [sprites[0].key[4] for phase, sprites in seen if phase is Phase.HOLD]
    assert frames == [0] * 10 + [1] * 10 + [2] * 8, "ceil(28 / 3) = 10 ticks each"
    _, seen = play(3, launch_at=3)
    assert [sprites[0].key[4] for phase, sprites in seen if phase is Phase.HOLD] == [0]


def test_the_hold_vibrates_by_a_pixel() -> None:
    _, seen = play(11, launch_at=11)
    places = {sprites[0].x for phase, sprites in seen if phase is Phase.HOLD}
    x, _ = project(CONTACT.x, CONTACT.y, CONTACT.z)
    assert places == {x, x + hs.VIBRATION_PIXELS}


def test_a_freeze_that_ends_without_a_launch_ends_the_splash() -> None:
    """Armour or invincibility: the hit freezes but launches nothing."""
    _, seen = play(8, launch_at=None)
    phases = [phase for phase, _ in seen]
    assert phases[7] is Phase.HOLD and phases[8] is Phase.DONE
    assert all(not sprites for _, sprites in seen[8:])


# --- the dispersal ----------------------------------------------------------------------------


def particle_turns(seen: list[tuple[Phase, list[hs.SplashSprite]]], at: int) -> list[float]:
    """The directions the particles have gone, a few ticks into the dispersal."""
    x, y = project(CONTACT.x, CONTACT.y, CONTACT.z)
    return [math.atan2(s.y - y, s.x - x) for s in seen[at + 3][1] if s.key[0] == "particle"]


def test_particles_burst_in_a_cone_around_the_launch_after_di() -> None:
    model, seen = play(11, launch_at=11, direction=across(0), di=across(2))
    turns = particle_turns(seen, 11)
    assert len(turns) == hs.PARTICLES[HEAVY]
    bent = across(2).normalized()
    screen_x, screen_y = project(bent.x, bent.y, bent.z)
    aim = math.atan2(screen_y, screen_x)
    cone = math.radians(hs.CONE_DEGREES[HEAVY]) + 0.1
    assert all(abs((turn - aim + math.pi) % (2 * math.pi) - math.pi) <= cone for turn in turns)
    hold = [s for phase, sprites in seen if phase is Phase.HOLD for s in sprites]
    assert {s.key[3] for s in hold if s.key[0] == "lines"} == {0}, "the hold showed before DI"
    del model


def test_a_launch_at_the_camera_bursts_all_round() -> None:
    toward = Vec3(1.0, 1.0, 1.0)
    _, seen = play(11, launch_at=11, direction=across(0), di=toward)
    turns = sorted(particle_turns(seen, 11))
    gaps = [b - a for a, b in zip(turns, [*turns[1:], turns[0] + 2 * math.pi], strict=True)]
    assert max(gaps) < math.pi, "spread all round, not in a cone"


def test_particles_are_the_same_every_time_and_differ_between_hits() -> None:
    _, first = play(11, launch_at=11)
    _, again = play(11, launch_at=11)
    assert first == again
    other = [hs.unit(601, 1, number, 0) for number in range(4)]
    same = [hs.unit(600, 1, number, 0) for number in range(4)]
    assert other != same and all(0.0 <= value < 1.0 for value in other + same)


def test_minimal_has_no_dispersal() -> None:
    model = HitSplashes(dispersal=False, forecast=lambda stage, fighter: False)
    _, seen = play(11, launch_at=11, splashes=model)
    assert seen[10][0] is Phase.HOLD and seen[11][0] is Phase.DONE and seen[11][1] == []


def test_one_hit_shows_at_most_twelve_sprites_and_all_at_most_160() -> None:
    _, seen = play(11, launch_at=11)
    assert max(len(sprites) for _, sprites in seen) <= hs.MAX_PER_HIT
    match = duel()
    target = match.fighters[1]
    model = HitSplashes(forecast=lambda stage, fighter: True)  # critical: the most particles
    for wave in range(30):
        frozen(target, 3, across(wave % 16))
        model.hit(hit_event(hitlag=3))
        model.observe(match.fighters, match.stage, 700 + wave)
        model.tick()
        model.launch(LaunchEvent(1, target.pos, across(wave % 16).normalized(), 200.0))
        assert model.live() <= hs.MAX_LIVE and len(model.sprites()) <= hs.MAX_LIVE
    assert model.live() > 100, "the cap is reached, not just approached"


# --- in the battle's effects ----------------------------------------------------------------


def run_fsmash(
    hit_effects: str,
    percent: float = 60.0,
    di: Dir8 | None = None,
    stage_id: str = "training_grid",
    facing: Dir8 = Dir8.E,
) -> tuple[BattleEffects, list[tuple[int, Phase | None, int]], int, int]:
    """Rook forward-smashes Rook (facing ``facing``, from the stage's respawn point); return
    the effects and, per tick from the hit, the splash's phase and tier, with the hit's
    hitlag and the tick its launch came on."""
    match = Match.create(
        load_stage(stage_id),
        [load_character("rook"), load_character("rook")],
        rules=MatchRules(stocks=None),
    )
    striker, target = match.fighters
    spot = match.stage.respawn
    target_facing = Dir8.W if facing is Dir8.E else Dir8.NW
    place(match, target, spot.x, spot.y, facing=target_facing, damage=percent)
    behind = spot - facing.world * 0.9
    place(match, striker, behind.x, behind.y, facing=facing)
    effects = BattleEffects(hit_effects=hit_effects)
    held = NEUTRAL_INPUT if di is None else InputFrame(move=di.world)
    start_move(match, striker, "fsmash")
    seen: list[tuple[int, Phase | None, int]] = []
    hit_at = hitlag = launched = -1
    for tick in range(80):
        match.tick([NEUTRAL_INPUT, held if hit_at >= 0 else NEUTRAL_INPUT])
        effects.tick()
        effects.consume(match.events)
        effects.observe(match.fighters, match.stage, match.frame)
        if hit_at < 0 and any(isinstance(e, HitEvent) for e in match.events):
            hit_at, hitlag = tick, target.hitlag
        if any(isinstance(e, LaunchEvent) for e in match.events):
            launched = tick - hit_at
        if hit_at >= 0:
            splash = effects.splashes.splashes[0] if effects.splashes.splashes else None
            seen.append((tick - hit_at, None if splash is None else splash.phase, 0))
            if splash is not None:
                seen[-1] = (tick - hit_at, splash.phase, splash.tier)
    return effects, seen, hitlag, launched


def test_a_real_hit_holds_for_its_freeze_and_disperses_on_its_launch() -> None:
    _, seen, hitlag, launched = run_fsmash(HIT_EFFECTS_FULL)
    assert launched == hitlag > 2
    phases = {tick: phase for tick, phase, _ in seen}
    assert phases[0] is phases[1] is Phase.BURST
    assert all(phases[tick] is Phase.HOLD for tick in range(2, hitlag))
    assert phases[hitlag] is Phase.DISPERSAL
    assert {tier for _, _, tier in seen if tier} == {HEAVY}, "KB 150 at 60%: heavy, no KO"


def test_a_hit_forecast_to_ko_is_critical() -> None:
    """Set up as ``tools/kill_calc.py`` (from the centre of Sky Ruins, facing SE), where the
    forward smash first KOs Rook at 124%."""
    _, seen, _, _ = run_fsmash(HIT_EFFECTS_FULL, 125.0, stage_id="sky_ruins", facing=Dir8.SE)
    assert seen[0][2] == CRITICAL
    _, seen, _, _ = run_fsmash(HIT_EFFECTS_FULL, 115.0, stage_id="sky_ruins", facing=Dir8.SE)
    assert seen[0][2] == HEAVY


def test_the_splash_replaces_the_spark_and_the_streak_unless_off() -> None:
    full, full_seen, _, _ = run_fsmash(HIT_EFFECTS_FULL)
    off, off_seen, _, _ = run_fsmash(HIT_EFFECTS_OFF)
    assert all(phase is None for _, phase, _ in off_seen) and off.splashes.splashes == []
    assert any(phase is not None for _, phase, _ in full_seen)
    del full
    effects = BattleEffects(hit_effects=HIT_EFFECTS_FULL)
    effects.consume([hit_event(), ClankEvent(0, CONTACT)])
    assert len(effects.sparks) == 1, "only the clank: hits get the splash"
    assert len(effects.splashes.splashes) == 1


def test_minimal_in_the_battle_has_no_particles() -> None:
    minimal, seen, hitlag, _ = run_fsmash(HIT_EFFECTS_MINIMAL)
    phases = {tick: phase for tick, phase, _ in seen}
    assert phases[hitlag - 1] is Phase.HOLD and phases[hitlag] in (None, Phase.DONE)
    assert not any(picture.key[0] == "particle" for picture in minimal.splashes.sprites())


def test_the_splash_never_changes_the_sim() -> None:
    match = duel()
    target = match.fighters[1]
    frozen(target, 11, across(3))
    before = match.state_hash()
    model = HitSplashes()
    model.hit(hit_event())
    model.observe(match.fighters, match.stage, 5)
    model.tick()
    model.sprites()
    assert match.state_hash() == before


def test_with_the_splash_the_launch_streak_is_not_drawn() -> None:
    """The splash's own lines point along the launch; the old streak is Off's (D-059)."""
    match = duel()
    target = match.fighters[1]
    for mode, streaks in ((HIT_EFFECTS_OFF, 1), (HIT_EFFECTS_FULL, 0), (HIT_EFFECTS_MINIMAL, 0)):
        effects = BattleEffects(hit_effects=mode)
        frozen(target, 5, across(0))
        effects.observe(match.fighters, match.stage, 1)
        assert len(effects.streaks) == streaks, mode
        assert effects.shake.direction == pytest.approx((1.0, 0.0)), "aimed in every mode"


# --- the art ----------------------------------------------------------------------------------


def all_splash_keys() -> list[tuple[str | int, ...]]:
    from isofightr.render import splash_art

    return [key for theme in splash_art.THEMES for key in splash_art.theme_keys(theme)]


def test_every_splash_picture_is_palette_locked() -> None:
    from isofightr.art.palettes import load_master
    from isofightr.render import splash_art

    master = load_master("resurrect64")
    for key in all_splash_keys():
        image = splash_art.build(key)
        assert {pixel[:3] for pixel in image.getdata() if pixel[3]} <= master, key
    with pytest.raises(ValueError, match="kind"):
        splash_art.build(("glow", "slash", 0, 0))


def test_every_theme_a_splash_can_have_has_art() -> None:
    from isofightr.config import HIT_THEMES
    from isofightr.render import splash_art

    themes = {effect.value for effect in Effect} | set(HIT_THEMES)
    assert themes <= set(splash_art.THEMES)


# --- heavy and critical extras (M17 group 2) -------------------------------------------------


def sprites_by_tick(
    knockback: float, critical: bool = False, calm: bool = False, hitlag: int = 11
) -> list[list[hs.SplashSprite]]:
    model = HitSplashes(forecast=lambda stage, fighter: critical, calm=calm)
    match = duel()
    target = match.fighters[1]
    seen = []
    for tick in range(hitlag + 16):
        if tick:
            model.tick()
        if tick == 0:
            frozen(target, hitlag, across(0))
            model.hit(hit_event(knockback=knockback, hitlag=hitlag))
        elif tick == hitlag:
            model.launch(LaunchEvent(1, target.pos, across(0).normalized(), knockback))
            target.launch = None
            target.hitlag = 0
        else:
            target.hitlag = max(0, target.hitlag - 1)
        model.observe(match.fighters, match.stage, 900 + tick)
        seen.append(model.sprites())
        if tick < 2:
            assert model.screen_flash() == (0 if calm or not critical else 2 - tick)
    return seen


def test_a_heavy_burst_has_a_split_under_it_unless_calm() -> None:
    seen = sprites_by_tick(100.0)
    x, _ = project(CONTACT.x, CONTACT.y, CONTACT.z)
    for tick in (0, 1):
        split = [s for s in seen[tick] if s.key[0] == "split"]
        assert [s.x - x for s in split] == [-hs.SPLIT_OFFSET, hs.SPLIT_OFFSET]
        assert seen[tick][-1].key[0] == "burst", "drawn over its split"
    assert not any(s.key[0] == "split" for s in sprites_by_tick(100.0, calm=True)[0])
    assert not any(s.key[0] == "split" for s in sprites_by_tick(60.0)[0]), "medium: none"


def test_a_heavy_launch_rings_and_throws_bigger_particles() -> None:
    seen = sprites_by_tick(100.0)
    rings = [[s.key[3] for s in sprites if s.key[0] == "ring"] for sprites in seen[11:]]
    assert rings[: hs.RING_FRAME_TICKS * 4] == [[0], [0], [1], [1], [2], [2], [3], [3]]
    assert all(s.key[2] == 1 for sprites in seen[11:] for s in sprites if s.key[0] == "particle")
    medium = sprites_by_tick(60.0)
    assert not any(s.key[0] == "ring" for sprites in medium for s in sprites)
    assert all(s.key[2] == 0 for sprites in medium for s in sprites if s.key[0] == "particle")


def test_a_critical_hit_flares_and_flashes_the_screen_unless_calm() -> None:
    seen = sprites_by_tick(200.0, critical=True)
    flares = [[s.key[2] for s in sprites if s.key[0] == "flare"] for sprites in seen]
    assert flares[:6] == [[0], [0], [1], [1], [2], [2]] and flares[6] == []
    assert max(len(sprites) for sprites in seen) <= hs.MAX_PER_HIT
    calm = sprites_by_tick(200.0, critical=True, calm=True)
    assert any(s.key[0] == "flare" for s in calm[0]), "the flare stays: it does not flash"


def test_particles_are_keyed_by_where_they_fly() -> None:
    seen = sprites_by_tick(100.0)
    x, y = project(CONTACT.x, CONTACT.y, CONTACT.z)
    for sprite in (s for s in seen[14] if s.key[0] == "particle"):
        heading = angle_step(math.atan2(sprite.y - y, sprite.x - x))
        assert heading is not None and abs((heading - sprite.key[3] + 8) % 16 - 8) <= 1


def test_a_match_knows_the_themes_its_hits_can_have() -> None:
    from isofightr.render.hit_splash import match_themes

    roster = [load_character(name) for name in ("rook", "bramble", "zephyr", "mote")]
    assert match_themes(roster) == ("slash", "earth", "wind", "fire", "darkness")
    assert match_themes([roster[0]], [Effect.ELECTRIC, Effect.NORMAL]) == (
        "slash",
        "electric",
        "normal",
    ), "the stage's hazards too"


def test_with_its_own_art_a_themes_old_extra_is_folded_in() -> None:
    from isofightr.render import splash_art

    for hit_effects in (HIT_EFFECTS_OFF, HIT_EFFECTS_FULL):
        effects = BattleEffects(hit_effects=hit_effects)
        effects.consume([hit_event(effect=Effect.SLASH), hit_event(effect=Effect.FIRE, target=0)])
        kinds = {effect.kind for effect in effects.fx}
        assert ("slash" in kinds) == (hit_effects == HIT_EFFECTS_OFF), "the slash draws its cut"
        embers = hit_effects == HIT_EFFECTS_OFF or not splash_art.has_art("fire")
        assert ("ember" in kinds) == embers, "until fire has its own art"


def test_fire_embers_rise_as_they_slow() -> None:
    """A theme's particles may drift (``PARTICLE_RISE``): embers curl up the screen."""
    still = hs.Particle(0.0, 2.0, 12)
    rising = hs.Particle(0.0, 2.0, 12, hs.PARTICLE_RISE["fire"])
    for age in (1, 5, 10):
        (x0, y0), (x1, y1) = still.offset(age), rising.offset(age)
        drift = hs.PARTICLE_RISE["fire"] * age * (age + 1) / 2
        assert x0 == x1 and y1 - y0 == pytest.approx(drift)
    match = duel()
    target = match.fighters[1]
    for effect, rise in ((Effect.FIRE, hs.PARTICLE_RISE["fire"]), (Effect.SLASH, 0.0)):
        model = HitSplashes(forecast=lambda stage, fighter: False)
        frozen(target, 11, across(0))
        model.hit(hit_event(effect=effect))
        model.observe(match.fighters, match.stage, 5)
        model.launch(LaunchEvent(1, target.pos, across(0).normalized(), 100.0))
        particles = model.splashes[0].particles
        assert particles and {particle.rise for particle in particles} == {rise}, effect


def test_darkness_motes_fly_out_then_are_pulled_back_in() -> None:
    """``PARTICLE_PULL``: an implosion: the motes' reach peaks, then shrinks toward the
    contact point, where a plain particle only slows."""
    plain = hs.Particle(0.0, 2.0, 12)
    pulled = hs.Particle(0.0, 2.0, 12, pull=hs.PARTICLE_PULL["darkness"])
    reach = [pulled.offset(age)[0] for age in range(13)]
    peak = reach.index(max(reach))
    assert 0 < peak < 12 and reach[-1] < reach[peak] * 0.5, "out, then back in"
    straight = [plain.offset(age)[0] for age in range(13)]
    assert straight == sorted(straight), "a plain particle never comes back"


def test_earth_chips_and_leaves_fall() -> None:
    """Earth's particles drift down the screen as they slow (a negative rise), the opposite
    of fire's embers."""
    assert hs.PARTICLE_RISE["earth"] < 0.0 < hs.PARTICLE_RISE["fire"]
    assert hs.PARTICLE_RISE["earth"] < hs.PARTICLE_RISE["ice"] < 0.0, "ice settles slower"
    falling = hs.Particle(0.0, 2.0, 12, hs.PARTICLE_RISE["earth"])
    heights = [falling.offset(age)[1] for age in range(12)]
    assert heights == sorted(heights, reverse=True) and heights[-1] < -5.0


def test_wind_wisps_curl_every_other_one_the_other_way() -> None:
    """``PARTICLE_CURL``: a wind particle turns as it flies, half of them one way and half
    the other, and its picture follows the way it is going now."""
    curl = hs.PARTICLE_CURL["wind"]
    left, right = hs.Particle(0.0, 2.0, 12, curl=curl), hs.Particle(0.0, 2.0, 12, curl=-curl)
    assert left.offset(8)[1] > 0.5 and right.offset(8)[1] < -0.5, "they curl apart"
    assert left.offset(8)[0] == pytest.approx(right.offset(8)[0])
    straight = hs.Particle(0.0, 2.0, 12)
    reach = sum(2.0 * hs.PARTICLE_DRAG**k for k in range(8))
    assert straight.offset(8) == pytest.approx((reach, 0.0)), "the sum the curl walks"
    match = duel()
    target = match.fighters[1]
    model = HitSplashes(forecast=lambda stage, fighter: True)
    frozen(target, 11, across(0))
    model.hit(hit_event(effect=Effect.NORMAL))
    model.splashes[0].attacker = None  # no hit theme: set the theme by hand below
    model.observe(match.fighters, match.stage, 5)
    model.splashes[0].theme = "wind"
    model.launch(LaunchEvent(1, target.pos, across(0).normalized(), 200.0))
    twists = [particle.curl for particle in model.splashes[0].particles]
    assert set(twists) == {curl, -curl}


def test_electric_sparks_fly_a_zigzag() -> None:
    """``PARTICLE_ZAG``: an electric spark swerves one way and then the other on alternate
    ticks, so its path zigzags about its line, and its picture follows its heading."""
    zag = hs.PARTICLE_ZAG["electric"]
    spark = hs.Particle(0.0, 2.0, 12, zag=zag)
    assert [spark.heading(age) for age in range(4)] == [-zag, zag, -zag, zag]
    sides = [spark.offset(age)[1] for age in range(1, 7)]
    assert any(side < 0.0 for side in sides) and any(side > -0.5 for side in sides)
    assert all(abs(side) < 2.0 for side in sides), "it keeps to its line"
    plain = hs.Particle(0.0, 2.0, 12)
    assert plain.heading(5) == 0.0


# --- group 3: blocks and parries ------------------------------------------------------------


def guarded(
    parry: bool, hit_effects: str = HIT_EFFECTS_FULL, calm: bool = False
) -> tuple[BattleEffects, list[dict[str, Any]]]:
    """Rook forward-tilts Rook, who shields (or, with the parry rule on, drops the shield just
    in time: the setup of ``test_parry_rule``); feed the battle's effects as the battle does
    and record, per tick from the block, the guard splash and both fighters' freezes."""
    match = Match.create(
        load_stage("training_grid"),
        [load_character("rook"), load_character("rook")],
        seed=1,
        rules=MatchRules(stocks=None, parry=parry),
    )
    attacker, defender = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.SE)
    place(match, defender, 5.0, 6.0, facing=Dir8.NW)
    effects = BattleEffects(hit_effects=hit_effects)
    effects.splashes.calm = calm
    shield = hold(buttons=Button.SHIELD, frames=1)[0]
    swing = hold(Dir8.SE, Button.ATTACK, frames=1)[0]
    blocked_at = -1
    seen: list[dict[str, Any]] = []
    for tick in range(70):
        held = tick < (3 if parry else 40)
        match.tick([swing if tick == 0 else NEUTRAL_INPUT, shield if held else NEUTRAL_INPUT])
        effects.tick()
        effects.consume(match.events)
        effects.observe(match.fighters, match.stage, match.frame)
        if blocked_at < 0 and any(isinstance(e, ShieldHitEvent) for e in match.events):
            blocked_at = tick
        if blocked_at >= 0:
            guards = effects.splashes.guards
            seen.append(
                {
                    "tick": tick - blocked_at,
                    "guard": guards[0] if guards else None,
                    "phase": guards[0].phase if guards else Phase.DONE,
                    "keys": [picture.key for picture in effects.splashes.sprites()],
                    "attacker_hitlag": attacker.hitlag,
                    "defender_hitlag": defender.hitlag,
                    "shake": effects.shake.amplitude,
                    "sparks": len(effects.sparks),
                    "fx": [effect.kind for effect in effects.fx],
                    "ripple_at": effects.fx[0].position if effects.fx else None,
                    "bubble": (shield_centre(defender), shield_radius(defender)),
                    "attacker_side": project(
                        attacker.pos.x - defender.pos.x, attacker.pos.y - defender.pos.y
                    ),
                }
            )
    assert seen, "the forward tilt was blocked"
    return effects, seen


def test_a_block_draws_an_arc_on_the_bubble_where_the_blow_met_it() -> None:
    """D-068 group 3: the splash flattens into an arc on the shield bubble's outline as it is
    drawn, on the side the blow came from (the attacker's, though the forward tilt reaches
    past the bubble's centre), in the attacker's theme."""
    _, seen = guarded(parry=False)
    guard = seen[0]["guard"]
    assert isinstance(guard, GuardSplash) and not guard.parried and guard.theme == "slash"
    centre, radius = seen[0]["bubble"]
    centre_x, centre_y = project(centre.x, centre.y, centre.z)
    width, height = sphere_screen_size(radius)
    x, y = guard.screen
    on_outline = ((x - centre_x) / (width / 2)) ** 2 + ((y - centre_y) / (height / 2)) ** 2
    assert on_outline == pytest.approx(1.0, abs=0.02)
    side_x, side_y = seen[0]["attacker_side"]
    assert (x - centre_x) * side_x + (y - centre_y) * side_y > 0, "on the attacker's side"
    assert seen[0]["keys"] == [("guard", "slash", guard.size, guard.angle, 0)]
    assert seen[0]["sparks"] == 0, "the arc replaces the spark"
    assert seen[0]["fx"] == ["ripple"], "the bubble's ripple stays"
    assert seen[0]["ripple_at"] == guard.surface, "where the arc is, not at the hitbox's centre"


def test_a_block_holds_for_the_defenders_freeze_then_sparks_skitter_along_the_bubble() -> None:
    _, seen = guarded(parry=False)
    assert seen[0]["phase"] is seen[1]["phase"] is Phase.BURST
    assert sum(1 for row in seen if row["defender_hitlag"]) > hs.BURST_TICKS
    for row in seen:
        held = row["phase"] in (Phase.BURST, Phase.HOLD)
        assert held == bool(row["defender_hitlag"]), row["tick"]
    thawed = next(row for row in seen if not row["defender_hitlag"])
    guard = thawed["guard"]
    assert isinstance(guard, GuardSplash) and thawed["phase"] is Phase.DISPERSAL
    assert len(guard.particles) == hs.GUARD_SPARKS[guard.size]
    for spark in guard.particles:
        off_tangent = min(
            abs((spark.turn - guard.turn - side + math.pi) % (2 * math.pi) - math.pi)
            for side in (math.pi / 2, -math.pi / 2)
        )
        assert off_tangent <= 0.25 + 1e-9, "along the bubble"
    assert any(key[0] == "particle" for key in thawed["keys"])
    assert seen[-1]["phase"] is Phase.DONE


def test_minimal_blocks_have_no_skittering_sparks() -> None:
    _, seen = guarded(parry=False, hit_effects=HIT_EFFECTS_MINIMAL)
    thawed = next(row for row in seen if not row["defender_hitlag"])
    guard = thawed["guard"]
    assert isinstance(guard, GuardSplash) and guard.particles == ()
    assert all(key[0] == "guard" for row in seen for key in row["keys"])


def test_a_parry_rings_for_exactly_the_attackers_freeze() -> None:
    """The ring bursts out over ``PARRY_RING_TICKS``, pulses for as long as the attacker is
    frozen (its own hitlag, longer than the parrier's), then fades; no spark and no ripple,
    and the parry's shake stays."""
    _, seen = guarded(parry=True)
    guard = seen[0]["guard"]
    assert isinstance(guard, GuardSplash) and guard.parried
    assert seen[0]["attacker_hitlag"] > seen[0]["defender_hitlag"]
    assert seen[0]["shake"] == PARRY_SHAKE_PIXELS
    fading = splash_art.PARRY_FRAME_COUNT - 1
    frames: list[int | None] = []
    for row in seen:
        rings = [key for key in row["keys"] if key[0] == "parry"]
        frames.append(rings[0][2] if rings else None)
        if row["attacker_hitlag"]:
            assert rings and rings[0][2] < fading, row["tick"]
    assert frames[: hs.PARRY_RING_TICKS] == list(range(hs.PARRY_RING_TICKS))
    pulsing = {frame for frame, row in zip(frames, seen, strict=True) if row["attacker_hitlag"]}
    assert pulsing - set(range(hs.PARRY_RING_TICKS)) == {hs.PARRY_RING_TICKS, 5}
    thawed = next(index for index, row in enumerate(seen) if not row["attacker_hitlag"])
    assert frames[thawed : thawed + hs.PARRY_FADE_TICKS] == [fading] * hs.PARRY_FADE_TICKS
    assert frames[thawed + hs.PARRY_FADE_TICKS] is None
    assert seen[0]["sparks"] == 0 and seen[0]["fx"] == [], "no spark, no ripple"


def test_reduce_flashing_holds_the_parry_ring_still() -> None:
    _, seen = guarded(parry=True, calm=True)
    held = {
        key[2]
        for row in seen
        if row["attacker_hitlag"] and row["tick"] >= hs.PARRY_RING_TICKS
        for key in row["keys"]
    }
    assert held == {hs.PARRY_RING_TICKS}


def test_blocks_and_parries_look_as_before_with_hit_effects_off() -> None:
    _, seen = guarded(parry=False, hit_effects=HIT_EFFECTS_OFF)
    assert all(row["guard"] is None for row in seen)
    assert seen[0]["sparks"] == 1 and seen[0]["fx"] == ["ripple"]
    _, seen = guarded(parry=True, hit_effects=HIT_EFFECTS_OFF)
    assert all(row["guard"] is None for row in seen)
    assert seen[0]["sparks"] == 1 and seen[0]["fx"] == ["ripple"]
    assert seen[0]["shake"] == PARRY_SHAKE_PIXELS


def test_a_blocked_hazard_gets_an_arc_in_its_effects_theme() -> None:
    match = duel()
    defender = match.fighters[1]
    blocked = HazardHitEvent(0, "lightning", 1, 4.0, 0.0, defender.pos, Effect.ELECTRIC, 6, True)
    effects = BattleEffects(hit_effects=HIT_EFFECTS_FULL)
    effects.consume([blocked])
    effects.observe(match.fighters, match.stage, 300)
    [guard] = effects.splashes.guards
    assert guard.theme == "electric" and guard.attacker is None and not effects.sparks
    off = BattleEffects(hit_effects=HIT_EFFECTS_OFF)
    off.consume([blocked])
    assert len(off.sparks) == 1 and not off.splashes.guards


def test_the_guard_splash_never_changes_the_sim() -> None:
    match = duel()
    match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
    before = match.state_hash()
    model = HitSplashes()
    model.guard(ShieldHitEvent(0, 1, 6.0, CONTACT, 9, False))
    for _ in range(20):
        model.observe(match.fighters, match.stage, 7)
        model.sprites()
        model.tick()
    assert match.state_hash() == before
