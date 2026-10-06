"""Gameplay tips for the loading screen.

Plan note "13 - Game Modes UI and Flow" (decision D-061): a tip rotates under the progress
bar while a match loads. Tips are hint templates (:mod:`isofightr.ui.hints`), so they name
the reader's own controls.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Mapping
from typing import Final

from isofightr.ui.hints import hint_text

TIPS: Final[tuple[str, ...]] = (
    "{jump} and {attack} together: a short-hop aerial.",
    "{strong} with a direction is a smash attack. Hold it to charge.",
    "{up} or {down} with {attack}: up and down tilts. In the air: aerials.",
    "{up} + {special} is your recovery. Save it for getting back.",
    "Launched? Hold a direction to bend your path (DI) and live longer.",
    "Tap a direction while a hit freezes you to shift a little (SDI).",
    "Tumbling? Press {shield} just before you land to tech.",
    "{shield} + down: spot dodge. {shield} + a flick: roll.",
    "{shield} in the air is an air dodge: one per airtime.",
    "{grab}, then flick a direction to throw.",
    "A shield shrinks as it is hit. Let it break and you are stunned.",
    "Tap down in the air to fast fall, or on a platform to drop.",
    "Hits do more knockback the more damage the target has taken.",
    "The same move over and over gets weaker. Mix your attacks.",
)
"""Every tip. Short enough for one line of body text."""
TIP_TICKS: Final[int] = 100
"""A tip stays up this long before the next one."""
TIP_PREFIX: Final[str] = "TIP: "


def tip_at(first: int, tick: int, labels: Mapping[str, str]) -> str:
    """Return the tip shown ``tick`` ticks into a loading screen that started on tip number
    ``first`` (so successive matches start on different tips), in a device's own words."""
    index = (first + max(tick, 0) // TIP_TICKS) % len(TIPS)
    return TIP_PREFIX + hint_text(TIPS[index], labels)
