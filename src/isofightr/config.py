"""Compile-time constants shared by the sim and the presentation layers.

Implements the "Configuration" section of the plan note "02 - Technical Architecture" and
the projection constants of "03 - Isometric World and Rendering". This module must stay free
of ``arcade`` and ``pyglet`` imports because ``isofightr.sim`` reads it.

User settings (``settings.toml``: window scale, fullscreen, volumes, bindings) arrive in M7.
"""

from typing import Final

# --- Simulation clock ---------------------------------------------------------------------
TICK_RATE: Final[int] = 60
"""Simulation ticks per second. All gameplay timing is counted in these frames."""

TICK_SECONDS: Final[float] = 1.0 / TICK_RATE
"""Wall-clock length of one simulation tick. Only the presentation loop may use it."""

MAX_FRAME_SECONDS: Final[float] = 0.25
"""Largest wall-clock step fed to the accumulator in one update (spiral-of-death clamp)."""

# --- Isometric projection (2:1 dimetric) --------------------------------------------------
TILE_W: Final[int] = 32
"""Width in native pixels of one tile's top diamond."""

TILE_H: Final[int] = 16
"""Height in native pixels of one tile's top diamond."""

Z_PX: Final[int] = 16
"""Native pixels per world unit of height."""

# --- Input ---------------------------------------------------------------------------------
FACING_HYSTERESIS_DEGREES: Final[float] = 5.0
"""Extra angle the stick must travel past a 45-degree boundary before 8-way facing changes."""

# --- Input devices (plan note "08 - Controls and Input", "Analog processing") --------------
STICK_DEADZONE: Final[float] = 0.20
"""Radial deadzone: stick magnitudes at or below this read as zero."""

STICK_SATURATION: Final[float] = 0.95
"""Stick magnitudes at or above this read as fully pushed."""

MODIFIER_THRESHOLD: Final[float] = 0.5
"""How far the right stick must be pushed up or down to act as the up or down modifier."""

TRIGGER_THRESHOLD: Final[float] = 0.5
"""How far an analog trigger must be pulled to count as held."""

# --- Stage defaults (used when a stage.toml omits the value) -------------------------------
LEDGE_MIN_DROP: Final[float] = 2.0
"""A solid neighbour lower by more than this many units still leaves a grabbable ledge."""

DEFAULT_BLAST_SIDE: Final[float] = 7.0
"""Horizontal blast-zone margin beyond the stage's solid bounding box, in units."""

DEFAULT_BLAST_TOP: Final[float] = 14.0
"""Height of the top blast zone, in units above the main floor."""

DEFAULT_BLAST_BOTTOM: Final[float] = -8.0
"""Height of the bottom blast zone, in units (negative = below the main floor)."""

DEFAULT_CAMERA_MARGIN: Final[float] = 4.0
"""How far beyond the stage's solid bounding box the camera may look, in units."""

MIN_PLATFORM_CLEARANCE: Final[float] = 1.0
"""A soft platform must sit at least this far above every solid cell beneath it, in units."""

SURFACE_EPSILON: Final[float] = 1e-4
"""Height tolerance when deciding whether something is on, above or below a surface."""

PLAYER_SPAWN_COUNT: Final[int] = 4
"""Every stage defines spawn points ``p1`` to ``p4``."""

# --- Stage geometry shared by physics, the depth sorter and the tile art -------------------
ISLAND_THICKNESS: Final[float] = 1.0
"""How far the island extends below its lowest cell top, in units. Solid for physics too:
fighters can pass under the island below this depth."""

DECK_THICKNESS: Final[float] = 0.25
AMBIENT_KINDS: Final[tuple[str, ...]] = (
    "leaves",
    "petals",
    "motes",
    "snow",
    "embers",
    "fireflies",
    "sand",
    "rain",
    "sparks",
    "spores",
)
"""What a stage's ``[ambient]`` table may drift across the screen (decision D-063)."""
HIT_THEMES: Final[tuple[str, ...]] = (
    "slash",
    "fire",
    "darkness",
    "earth",
    "wind",
    "electric",
    "ice",
)
"""What a character's ``hit_theme`` may be: the look of its hits whose effect is ``normal``
(decision D-068; presentation only, the sim never reads it)."""
AMBIENT_MAX: Final[int] = 16
"""The most ambient sprites a stage may ask for."""
PROP_LAYERS: Final[tuple[str, ...]] = ("world", "below", "ground")
"""Where a stage prop is: standing on the ground, hanging under the island, or lying flat
on the ground (a decal: fighters stand on it)."""
PROP_DEFAULT_PERIOD: Final[int] = 14
"""Ticks an animated prop shows each of its frames for, unless the stage says otherwise."""
BACKDROP_FRAME_TICKS: Final[int] = 12
"""Ticks an animated backdrop layer shows each frame for, unless the stage says otherwise."""
UNDERSIDE_MAX_DEPTH: Final[float] = 3.0
"""The deepest a stage's generated underside may hang below the island, in units."""
"""Visual thickness of a soft platform deck, in units (4 px)."""

# --- Camera ---------------------------------------------------------------------------------
CAMERA_LERP: Final[float] = 0.1
"""Fraction of the remaining distance the camera pans toward its target each tick."""
CAMERA_ZOOM_STEP: Final[int] = 2
"""Stepped zoom (an M8 experiment, decision D-048): the world is drawn at 1x or exactly 2x."""
CAMERA_ZOOM_MARGIN: Final[int] = 56
"""Room kept around the fighters, in native pixels, when deciding whether 2x still fits."""
CAMERA_ZOOM_IN_TICKS: Final[int] = 45
"""How long everyone must fit the zoomed view before the camera zooms in."""

# --- Fighter presentation -------------------------------------------------------------------
OCCLUDED_FIGHTER_ALPHA: Final[int] = 96
"""Opacity (0-255) of the "x-ray" copy of each fighter drawn over the world, so a fighter
behind a platform or the island stays visible. 0 turns it off (decision D-025)."""

INVINCIBLE_BLINK_FRAMES: Final[int] = 4
"""An invincible fighter's sprite is hidden for this many frames, then shown for as many."""

# --- Match defaults -------------------------------------------------------------------------
DEFAULT_STAGE_ID: Final[str] = "sky_ruins"
"""Stage loaded when ``--stage`` is not given."""

TRAINING_STAGE_ID: Final[str] = "training_grid"
"""Stage loaded for ``--training`` when ``--stage`` is not given."""

DEFAULT_CHARACTER_ID: Final[str] = "rook"
"""Character used for a player slot when ``--p1``/``--p2`` are not given."""

DEFAULT_PLAYER_COUNT: Final[int] = 2
"""Players in a match started from the command line without ``--p3``/``--p4``."""

MAX_PLAYERS: Final[int] = 4

# --- Native resolution and window ---------------------------------------------------------
NATIVE_W: Final[int] = 640
"""Width of the offscreen pixel-art buffer."""

NATIVE_H: Final[int] = 360
"""Height of the offscreen pixel-art buffer."""

DEFAULT_WINDOW_SCALE: Final[int] = 2
"""Default integer upscale of the native buffer (2x = 1280x720)."""

MIN_WINDOW_SCALE: Final[int] = 1
"""Smallest integer upscale; also used when the window is smaller than the native buffer."""

WINDOW_TITLE: Final[str] = "ISOFightr"

# --- CPU AI (plan note "15 - CPU AI") ------------------------------------------------------
# Per-level parameters are given at the plan's anchor levels 1, 3, 5, 7 and 9; the even
# levels sit halfway between their neighbours (``isofightr.ai.levels``).
CPU_MIN_LEVEL: Final[int] = 1
CPU_MAX_LEVEL: Final[int] = 9
CPU_DEFAULT_LEVEL: Final[int] = 5
CPU_LEVEL_ANCHORS: Final[tuple[int, ...]] = (1, 3, 5, 7, 9)
CPU_REACTION_FRAMES: Final[tuple[float, ...]] = (40, 28, 20, 15, 12)
"""How old the CPU's view of its opponents is, in frames."""
CPU_TRACKING_FRAMES: Final[tuple[float, ...]] = (10, 8, 6, 4, 2)
"""M20 (decision D-071): how late a CPU sees what changes smoothly (where an opponent is,
how fast it moves, its damage). What starts suddenly (a move, a jump, a shield) takes the
longer reaction time. Used by ``ai/belief.py``; the M10 decisions do not read it."""
CPU_REACTION_SPREAD: Final[int] = 4
"""A reaction takes its level's frames plus up to this many, drawn per event: never fewer."""
CPU_ATTENTION_FRAMES: Final[int] = 8
"""Extra reaction time for an opponent the CPU is not focused on (a free-for-all)."""
CPU_CHOICE_TEMPERATURE: Final[tuple[float, ...]] = (8.0, 5.0, 3.0, 2.0, 1.0)
"""M20: how loosely a CPU picks among the things worth doing, in value points: at 1 it
almost always takes the best, at 8 it often takes something a good deal worse."""

# The expected-value formula of ``ai/intercept.py`` (decision D-071). Values are in percent
# of damage: a candidate is worth the damage it is likely to deal, plus and minus the rest.
CPU_KO_VALUE: Final[float] = 45.0
CPU_KO_WITHOUT_DI_SHARE: Final[float] = 0.5
"""Share of ``CPU_KO_VALUE`` a launch is worth when it KOs only if the victim does not DI."""
CPU_OFF_STAGE_VALUE: Final[float] = 8.0
"""What sending an opponent off the stage (and not out of it) is worth: an edgeguard."""
CPU_SHIELD_BREAK_VALUE: Final[float] = 40.0
"""What breaking a shield is worth: a free hit of anything, often a stock."""
CPU_CHASE_FRAMES: Final[int] = 40
"""A launched or landing opponent is chased to where it will be in this many frames at most."""
CPU_LEDGE_TRAP_INSET: Final[float] = 1.5
"""A CPU waits this far inside a ledge an opponent hangs from: its getup, attack and roll all
end within reach."""
CPU_RETURN_SAFETY: Final[float] = 0.7
"""Share of its jumps and up special a CPU counts on to get back from an off-stage edgeguard."""
CPU_EDGEGUARD_DEPTH: Final[tuple[float, ...]] = (0.0, 0.0, 0.0, 0.5, 1.0)
"""M20: whether a level goes off the stage to edgeguard (0 = never; above 0 it may, when the
return check passes); levels 1 to 5 stay on the stage."""
"""What taking a stock is worth on top of the hit's damage."""
CPU_HIT_VALUE: Final[float] = 6.0
"""What landing any clean hit is worth beyond its damage: it stops whatever the opponent
was about to do and hands the CPU the next move. Without it a jab is never worth throwing."""
CPU_ADVANTAGE_VALUE: Final[float] = 0.4
"""What each frame of advantage on hit is worth (counted between -15 and +15 frames)."""
CPU_STARTER_VALUE: Final[float] = 3.0
"""What each frame of advantage on hit is worth when the CPU is ahead (a combo starter)."""
CPU_FOLLOW_SLACK: Final[float] = 0.5
"""A launched victim within the CPU's striking reach plus this when it can act again is
follow-up range."""
CPU_PUNISH_VALUE: Final[float] = 14.0
"""What a full punish costs: about one solid hit."""
CPU_PUNISH_FRAMES: Final[float] = 20.0
"""Frames handed to an opponent that amount to a full punish (fewer cost in proportion)."""
CPU_GUARD_GUESS: Final[float] = 0.15
"""How likely a free, grounded opponent is taken to block (the habit model replaces it)."""
CPU_STUFF_GUESS: Final[float] = 0.7
"""How likely a slow move started inside a free opponent's reach is taken to be hit first
(a move as quick as the opponent's quickest: not at all; ``CPU_STUFF_FRAMES`` slower: this)."""
CPU_STUFF_FRAMES: Final[float] = 14.0
CPU_STUFF_REACH: Final[float] = 0.5
CPU_PASSIVE_DISCOUNT: Final[float] = 0.8
"""How much of that risk goes once the opponent has not attacked for ``CPU_PATIENCE_FRAMES``:
someone who never swings is not about to. Without it two careful CPUs stood a jab apart
for minutes, each waiting for the other."""
CPU_CLOSE_INSIDE: Final[float] = 0.3
"""When it closes in, it comes this far inside the reach of its own jab."""
"""An opponent this far outside its quick reach still counts as inside it (it steps in)."""
CPU_TARGET_MOBILITY: Final[float] = 0.5
"""Share of the distance a free target could cover that it is assumed to: at 1 nothing ever
looks likely to hit a free opponent, at 0 everything in reach looks certain."""
CPU_REACH_MARGIN: Final[float] = 0.1
"""Overlap a hitbox needs with the target before it counts as reaching (as the M10 CPU's slack
did: a move that only grazes on paper whiffs in play)."""
CPU_MIN_CHANCE: Final[float] = 0.25
"""A candidate less likely than this to reach is not weighed at all."""
CPU_PROJECTILE_MIN_CHANCE: Final[float] = 0.5
"""A projectile needs a better chance than that: thrown at nothing it is only noise."""
CPU_ACT_VALUE: Final[float] = 1.5
CPU_FREE_ACT_VALUE: Final[float] = 5.0
"""M20 group 7: the least value worth doing against a target that is free to act."""
"""A candidate must be worth more than this to be done."""
CPU_TIME_COST: Final[float] = 0.03
"""Value lost per frame a hit takes to arrive: sooner is better, all else equal."""
CPU_CAUTION_PERCENT: Final[float] = 150.0
"""Costs grow with the CPU's own damage: doubled at this percent."""
CPU_IMPATIENCE_VALUE: Final[float] = 7.0
"""Added to a likely hit's value after a long wait, so that two careful CPUs still fight."""
CPU_PATIENCE_FRAMES: Final[int] = 100
"""Frames without attacking after which the impatience is full."""

# Spacing in neutral.
CPU_HOVER_MARGIN: Final[float] = 0.35
"""How far outside an opponent's quick reach a CPU stands while it waits."""
CPU_HOVER_BAND: Final[float] = 0.35
"""It does not move while it is within this of where it wants to stand."""
CPU_HOVER_MAX: Final[float] = 3.2
"""The farthest a brawler stands off, however long the opponent's reach."""
CPU_SWAY: Final[tuple[float, float]] = (-0.3, 0.5)
"""The standing distance drifts within this range, so the CPU does not stand still."""
CPU_SWAY_FRAMES: Final[tuple[int, int]] = (25, 60)
"""How long one drift lasts, at least and at most."""
CPU_RESPECT_RANGE: Final[float] = 4.0
"""Distance kept from an opponent that cannot be hit (just respawned)."""
CPU_OPENING_FRAMES: Final[int] = 10
"""An opponent locked for this long is walked up to instead of kept at arm's length."""
CPU_ABORT_DRIFT: Final[float] = 1.0
CPU_CLIMB_RETRY_FRAMES: Final[int] = 300
"""After a climb toward an opponent on other ground drops it over a gap, a CPU waits this long
before it tries that again (a route on Frostpeak looped a Zephyr between a jump and the ledge)."""
CPU_DRIFT_LOOKAHEAD: Final[int] = 8
"""During a move in the air, a CPU checks for ground where its speed carries it this many
frames ahead before drifting on toward its goal."""
CPU_PATH_STEP: Final[float] = 0.25
"""Spacing of the checks for ground along the way to a place to stand."""
CPU_PATH_CHECK: Final[int] = 4
"""An action's recorded path is checked against the blast zone and the ground every this many
frames."""
CPU_BLAST_MARGIN: Final[float] = 2.0
"""No action may carry the CPU nearer than this to a blast zone."""
CPU_FOOTED_HEIGHT: Final[float] = 0.05
"""Feet this close to where an action started count as still on the ground in its recording."""
CPU_STILL_SPEED: Final[float] = 0.03
"""A CPU moving slower than this counts as standing still (run-ups and walk-ups are recorded
from a standstill)."""
"""Spacing of the checks for ground along the way to a place to stand."""
CPU_GUARD_HORIZON: Final[int] = 30
"""How far ahead a CPU looks for a hit of a move it has noticed (M10 looked 8 frames)."""
CPU_GUARD_NOW: Final[int] = 12
"""A hit this close is guarded at once; one further off may still be beaten to the punch."""
CPU_OUT_OF_SHIELD_CHANCE: Final[float] = 0.9
"""How sure a grab out of shield must be before it is tried."""
"""A run-up is called off if its target turns out this far from where it was expected."""
CPU_DECISION_FRAMES: Final[tuple[float, ...]] = (30, 20, 12, 8, 4)
"""How often a CPU in neutral picks a new plan, in frames."""
CPU_DEFEND_CHANCE: Final[tuple[float, ...]] = (0.05, 0.20, 0.40, 0.60, 0.80)
"""Chance to shield or dodge an attack it sees coming."""
CPU_DI_QUALITY: Final[tuple[float, ...]] = (0.0, 0.2, 0.5, 0.8, 1.0)
"""Chance to DI a launch toward survival (otherwise it holds nothing)."""
CPU_TECH_CHANCE: Final[tuple[float, ...]] = (0.0, 0.15, 0.40, 0.70, 0.90)
CPU_AIM_JITTER_DEGREES: Final[tuple[float, ...]] = (40.0, 22.0, 10.0, 4.0, 0.0)
"""Random error added to every direction the CPU aims."""
CPU_AGGRESSION: Final[tuple[float, ...]] = (0.25, 0.45, 0.65, 0.85, 0.95)
"""Chance to attack when one of its moves reaches the target."""
CPU_PREDICTION: Final[tuple[float, ...]] = (0.0, 0.3, 0.6, 0.85, 1.0)
"""Share of its reaction delay the CPU makes up for by extrapolating the target's motion."""
CPU_EDGEGUARD_CHANCE: Final[tuple[float, ...]] = (0.0, 0.0, 0.4, 0.8, 1.0)
"""Chance to go and guard the ledge while the target recovers."""
CPU_RECOVERY_MIXUP: Final[tuple[float, ...]] = (0.0, 0.0, 0.4, 0.6, 0.8)
"""Chance to vary recovery timing (jump late, up special early) instead of the plain route."""
CPU_LEDGE_WAIT_MAX: Final[tuple[float, ...]] = (10, 20, 35, 45, 50)
"""Longest the CPU waits on a ledge before picking an option, in frames."""
CPU_MASH_EVERY: Final[tuple[float, ...]] = (8, 6, 4, 3, 2)
"""Frames between presses while mashing out of a grab."""
CPU_PUNISH_MARGIN: Final[tuple[float, ...]] = (0, 1, 2, 3, 4)
"""Frames of an opponent's end lag the CPU leaves spare when it picks a punish."""

CPU_THREAT_SLACK: Final[float] = 0.15
"""Units added to an opponent's hitbox reach when the CPU judges whether it is in danger."""
CPU_THREAT_FRAMES: Final[int] = 8
"""How far ahead the CPU looks for hitboxes and projectiles that will reach it."""
CPU_CLOSE_RANGE: Final[float] = 1.4
"""Distance a brawler tries to keep from its target."""
CPU_ZONER_RANGE: Final[float] = 4.5
"""Distance a character with a long-range projectile tries to keep."""
CPU_ZONER_REACH: Final[float] = 8.0
"""A projectile that hits this far away makes its character a zoner."""
CPU_ZONER_HEIGHT: Final[float] = 1.0
"""A zoner only keeps its distance from a target at about its own height."""
CPU_WALK_RANGE: Final[float] = 2.5
"""Closer than this the CPU walks instead of dashing."""
CPU_WALK_TILT: Final[float] = 0.55
CPU_TURN_TILT: Final[float] = 0.3
"""A light push behind the CPU: enough to turn around without walking off."""
CPU_EDGE_LOOKAHEAD: Final[float] = 0.9
"""How far ahead of its feet a grounded CPU checks for ground before moving on, at least."""
CPU_EDGE_MARGIN: Final[float] = 0.15
"""Added to a character's skid distance (run speed squared over twice its traction): a CPU
looks at least that far ahead, so a fast runner can still stop before an edge."""
CPU_STEP_HEIGHT: Final[float] = 0.4
"""A height difference the CPU treats as level ground (anything more needs a jump)."""
CPU_REGION_SNAP: Final[float] = 0.75
"""A fighter belongs to a region if one of its cell centres is this close (per axis)."""
CPU_JUMP_REACH_SHARE: Final[float] = 0.6
"""Share of its full-hop-plus-air-jump distance a CPU counts on when planning a jump."""
CPU_JUMP_REACH_STRETCH: Final[float] = 0.75
"""When no route fits ``CPU_JUMP_REACH_SHARE``, the share tried next (M20 group 6)."""
CPU_JUMP_RISE_SHARE: Final[float] = 0.7
"""Share of its full-hop-plus-air-jump height a CPU counts on when planning a jump."""
CPU_ROUTE_HEIGHT_COST: Final[float] = 0.5
"""Route cost of a unit of height, against a unit of distance."""
CPU_TAKEOFF_RADIUS: Final[float] = 0.4
"""How close to a route's takeoff point the CPU gets before it jumps."""
CPU_SAFE_INSET: Final[float] = 0.8
"""How far inside a ledge the CPU stands when its target is off the stage."""
CPU_LEDGE_APPROACH_OUT: Final[float] = 0.3
"""While below a ledge, the CPU aims this far outside it so it does not slide under."""
CPU_LEDGE_APPROACH_IN: Final[float] = 0.8
"""Once level with a ledge, the CPU aims this far inside it to land on the stage."""
CPU_DESTINATION_BIAS: Final[float] = 0.6
"""Weight of "toward where I am going" against "nearest" when picking a ledge to recover to."""
CPU_UPSPECIAL_SAFETY: Final[float] = 0.7
"""Share of its up special's measured rise the CPU counts on when deciding to use it."""
CPU_TECH_PRESS_FRAMES: Final[int] = 5
"""A tumbling CPU presses shield this many frames (or fewer) before it lands."""
CPU_AIR_DODGE_FRAMES: Final[int] = 5
"""An airborne CPU air dodges a hit it sees landing within this many frames."""
CPU_SHIELD_HOLD_EXTRA: Final[int] = 4
"""Frames the CPU keeps its shield up after the threat it saw has passed."""
CPU_GETUP_MIN_LOCK: Final[int] = 2
# M20 group 4: the disadvantage state (D-071).
CPU_DI_SURVIVE: Final[float] = 100.0
"""DI score for a choice that does not KO (survival outranks everything else)."""
CPU_DI_ON_STAGE: Final[float] = 10.0
"""DI score for a choice whose flight ends over ground."""
CPU_DI_AWAY_SHARE: Final[float] = 0.5
"""DI score per unit the flight ends from the attacker (against one per unit nearer the
stage's middle when it ends off the stage)."""
CPU_SDI_LEVEL: Final[int] = 9
"""Levels from this one up SDI out of multi-hits (a flick every other hitlag frame)."""
CPU_SDI_MAX_KB: Final[float] = 60.0
"""A pending launch weaker than this is treated as part of a string or multi-hit: SDI away
from the attacker. A stronger one is SDIed along the chosen DI."""
CPU_TECH_AWAY_MARGIN: Final[float] = 0.6
"""An opponent within its striking reach plus this of a tumble's landing: tech away."""
CPU_EXPOSED_SLACK: Final[int] = 4
"""Frames added to the time an option leaves the CPU open (the opponent's own start-up)."""
CPU_OPTION_PUNISHED: Final[float] = 30.0
"""What a getup or ledge option that is certain to be punished costs."""
CPU_LOW_SHIELD: Final[float] = 20.0
"""Shield health at which a shield is worth less than a dodge."""
CPU_HIT_ACTIVE_GUESS: Final[int] = 2
"""Frames a hit on its way is assumed to stay out, when judging whether a dodge covers it."""
CPU_SHIELD_VALUE: Final[float] = 10.0
"""Value of shielding a hit on its way."""
CPU_DODGE_VALUE: Final[float] = 8.0
"""Value of spot dodging a hit on its way (more against a grab)."""
CPU_ROLL_VALUE: Final[float] = 6.0
"""Value of rolling away from a hit on its way."""
CPU_JUMP_AWAY_VALUE: Final[float] = 9.0
"""Value of jumping away from a grab on its way."""
CPU_GUARDED_LEDGE: Final[float] = 2.0
"""An opponent this close to a ledge (on the stage, free) is guarding it: recover elsewhere."""
CPU_GUARDED_COST: Final[float] = 3.0
# M20 group 5: habits and styles (D-071).
CPU_HABIT_ADAPT: Final[tuple[float, ...]] = (0.0, 0.0, 0.5, 1.0, 1.0)
"""How much a CPU acts on what it learned of its opponents (levels 1, 3, 5, 7, 9)."""
CPU_HABIT_FIRST_LEVEL: Final[int] = 5
"""Levels below this do not adapt at all."""
CPU_HABIT_DECAY: Final[float] = 0.7
"""Each new observation of a habit scales the older ones by this (recent ones count most)."""
CPU_HABIT_CONFIDENCE: Final[float] = 1.5
"""Observations (decayed) at which the CPU half trusts a habit."""
CPU_HABIT_SURE: Final[float] = 0.5
"""A choice must be at least this share of what was seen to be expected."""
CPU_HABIT_TRUST: Final[float] = 0.3
"""The trust (share times confidence times adapt) above which the CPU plays for a habit."""
CPU_HABIT_NEAR: Final[float] = 2.5
"""The CPU's own move starting this close to an opponent counts as approaching it."""
CPU_HABIT_GUARD_FRAMES: Final[int] = 12
"""Frames after such a move in which a shield counts as shielding the approach."""
CPU_HABIT_STAND_OFF: Final[float] = 0.6
"""How far beyond where an expected roll or getup ends the CPU waits for it."""
CPU_HABIT_ZONER_SHARE: Final[float] = 0.4
"""An opponent whose trusted share of projectile moves is above this is rushed down."""
CPU_HABIT_GRAB_VALUE: Final[float] = 20.0
"""Value a grab gains per unit an opponent is seen shielding above ``CPU_GUARD_GUESS``
(learned shielding only raises grabs: lowering every other move cost wins)."""
CPU_REPEAT_PENALTY: Final[float] = 8.0
"""Value taken off a move per unit of its share among the CPU's own recent moves."""
CPU_STYLE_GRAB_VALUE: Final[float] = 6.0
"""Value a grab gains per unit of ``grab_rate`` above 1 (loses below)."""
CPU_STYLE_ZONING_VALUE: Final[float] = 8.0
"""Value a projectile gains per unit of ``zoning`` above 1."""
CPU_STYLE_AIR_VALUE: Final[float] = 5.0
"""Value an aerial gains per unit of ``air_bias`` above 1."""
CPU_FAVOURITE_VALUE: Final[float] = 2.0
"""Value a favourite move gains (an avoided one loses)."""
CPU_STYLE_STAY: Final[float] = 0.5
"""A style ``edgeguard_depth`` below this never leaves the stage after an opponent."""
CPU_STYLE_RUN_SPEED: Final[float] = 0.12
"""Run speed at which a character's default aggression is 1."""
CPU_STYLE_WEIGHT: Final[float] = 100.0
"""Weight at which a character's default risk is 1."""
CPU_STYLE_DEFAULT_BOUNDS: Final[tuple[float, float]] = (0.8, 1.25)
"""Defaults from the character's data stay within these."""
CPU_TEMPERAMENT: Final[float] = 0.1
# M20 group 7: levels by skill (D-071; the table in note 15, "Levels").
CPU_SKILL_RUN: Final[int] = 3
"""From this level a CPU runs up to a move (below, it only walks up)."""
CPU_SKILL_EXTRAS: Final[int] = 5
"""From this level: jab chains and charged smashes."""
CPU_SKILL_COMBOS: Final[int] = 5
"""From this level a hit's frames ahead count (follow-ups); below, every move is one hit."""
CPU_SKILL_DODGE: Final[int] = 5
"""From this level a CPU spot dodges, rolls and jumps away; below, it only shields."""
CPU_SKILL_BEST_OUT_OF_SHIELD: Final[int] = 7
"""From this level the up smash and up special out of shield; levels 5 and 6 only grab."""
CPU_SKILL_TECH_CHOICE: Final[int] = 7
"""From this level the tech is chosen (in place or away); below, in place or a random roll."""
CPU_SKILL_GUARD_AVOID: Final[int] = 9
"""From this level a recovery avoids a guarded ledge."""
CPU_HESITATE_FRAMES: Final[tuple[float, ...]] = (8, 4, 0, 0, 0)
"""Frames a CPU waits before an attack it has chosen comes out (levels 1, 3, 5, 7, 9): slow
hands, the other half of how a beginner plays."""
CPU_MISJUDGE: Final[tuple[float, ...]] = (0.45, 0.2, 0.06, 0.02, 0.0)
"""The share of the distance to its target a CPU misjudges where the target is by, a new
direction every decision (levels 1, 3, 5, 7, 9): a weak CPU misses by a little instead of
standing idle on a dice roll."""
# M20 group 6: several opponents, teams, stages (D-071).
CPU_TARGET_INVINCIBLE_COST: Final[float] = 6.0
"""Target cost (units of distance) of an opponent that cannot be hurt."""
CPU_TARGET_PERCENT_VALUE: Final[float] = 0.02
"""Target cost taken off per percent of damage (a KO waiting)..."""
CPU_TARGET_PERCENT_CAP: Final[float] = 150.0
"""...up to this percent."""
CPU_TARGET_LEADER_VALUE: Final[float] = 1.5
"""Target cost taken off the leader in a timed match (the best score)."""
CPU_TARGET_HOLD: Final[float] = 1.5
"""Target cost taken off the current target, so it is only dropped for a clearly better one."""
CPU_BRAWL_PERCENT: Final[float] = 100.0
"""At this percent or more, the CPU keeps out of two opponents fighting each other..."""
CPU_BRAWL_RANGE: Final[float] = 2.5
"""...that is, a target with another opponent this close to it..."""
CPU_BRAWL_COST: Final[float] = 4.0
"""...costs this much more."""
CPU_ALLY_CLEARANCE: Final[float] = 0.2
"""A hitbox this close to a teammate's hurtbox counts as passing over it."""
CPU_FRIENDLY_FIRE_COST: Final[float] = 30.0
"""Value taken off an action whose every hit frame passes over a teammate."""
CPU_HAZARD_LOOKAHEAD: Final[int] = 90
"""A hazard that hits, turning active within this many frames, is a place to keep out of."""
CPU_HAZARD_MARGIN: Final[float] = 0.4
"""Room kept around a hazard's cylinder."""
CPU_HAZARD_STEP: Final[float] = 0.3
CPU_HAZARD_ACTIVE_GUESS: Final[int] = 30
CPU_INVINCIBLE_KEEP: Final[float] = 2.5
"""Any opponent that cannot be hit and stands this close is backed away from."""
"""Frames a hazard that is not yet active is taken to stay active once it is."""
"""How far past that the CPU goes to stand clear."""
"""Each CPU's style numbers are moved up to this share either way (seeded)."""
"""Recovery score added per unit a place on a ledge is inside a guard's radius."""
CPU_LEDGE_SAMPLE: Final[float] = 1.0
"""Places along a ledge line are tried this far apart when one part of it is guarded."""
CPU_SOFTLOCK_FRAMES: Final[int] = 20 * 60
"""The soak test's soft-lock limit: no fighter may stay in one state longer than this."""

# --- Audio (plan note "14 - Audio") ----------------------------------------------------------
AUDIO_HIT_TIERS: Final[tuple[float, float, float]] = (40.0, 80.0, 120.0)
"""Knockback at which a hit sounds medium, heavy and KO-level."""
AUDIO_HEAVY_LANDING_SPEED: Final[float] = 0.2
"""A landing at this fall speed or more (units per frame) uses the heavy landing sound."""
AUDIO_PITCH_VARIATION: Final[float] = 0.05
"""Repeated sounds are played up to this much faster or slower, so they do not machine-gun."""
AUDIO_MAX_PAN: Final[float] = 0.5
"""Stereo pan of a sound at the edge of the screen."""
AUDIO_MAX_INSTANCES: Final[int] = 3
"""How many copies of one sound may start within ``AUDIO_INSTANCE_TICKS``."""
AUDIO_INSTANCE_TICKS: Final[int] = 6
AUDIO_DUCK_VOLUME: Final[float] = 0.5
"""Music volume factor while ducked (about -6 dB), on KOs and at "GAME!"."""
AUDIO_DUCK_TICKS: Final[int] = 70
AUDIO_MENU_SONG: Final[str] = "menu"
AUDIO_VICTORY_SONG: Final[str] = "victory"
