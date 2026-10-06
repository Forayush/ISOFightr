"""Where the cursor can be on a screen, and how it moves there.

Plan note "13 - Game Modes UI and Flow" (decision D-061): every screen works the same with a
stick, keys and a mouse. A screen lists its focusable things as named rectangles in native
pixels; a direction moves to the nearest one that way, and a mouse position picks the one
under it. Coordinates are y-up from the bottom-left, as the UI is drawn.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from isofightr.ui.menu import MenuAction

SIDEWAYS_COST: Final[int] = 3
"""How much a step off the axis of travel counts against a candidate, per pixel."""
_STEPS: Final[dict[MenuAction, tuple[int, int]]] = {
    MenuAction.LEFT: (-1, 0),
    MenuAction.RIGHT: (1, 0),
    MenuAction.UP: (0, 1),
    MenuAction.DOWN: (0, -1),
}


@dataclass(frozen=True, slots=True)
class Rect:
    """A rectangle in native pixels: bottom-left corner and size."""

    left: int
    bottom: int
    width: int
    height: int

    @property
    def right(self) -> int:
        """One past the last column."""
        return self.left + self.width

    @property
    def top(self) -> int:
        """One past the last row."""
        return self.bottom + self.height

    @property
    def centre(self) -> tuple[float, float]:
        """The middle of the rectangle."""
        return (self.left + self.width / 2, self.bottom + self.height / 2)

    def contains(self, x: float, y: float) -> bool:
        """Return whether a point is inside."""
        return self.left <= x < self.right and self.bottom <= y < self.top

    def inset(self, amount: int) -> "Rect":
        """Return the rectangle shrunk by ``amount`` on every side."""
        return Rect(
            self.left + amount,
            self.bottom + amount,
            max(self.width - 2 * amount, 0),
            max(self.height - 2 * amount, 0),
        )

    def overlaps(self, other: "Rect") -> bool:
        """Return whether two rectangles share any pixel."""
        return (
            self.left < other.right
            and other.left < self.right
            and self.bottom < other.top
            and other.bottom < self.top
        )


class FocusMap:
    """The focusable things of a screen, by name, in the order they were listed."""

    def __init__(self, rects: Mapping[str, Rect], wrap: bool = False) -> None:
        """Create the map. With ``wrap`` a move off one edge lands on the far side."""
        self.rects = dict(rects)
        self.wrap = wrap

    def at(self, x: float, y: float) -> str | None:
        """Return the name of the thing under a point, or ``None``."""
        for name, rect in self.rects.items():
            if rect.contains(x, y):
                return name
        return None

    def move(self, current: str, action: MenuAction) -> str:
        """Return where a direction takes the cursor from ``current``: the nearest thing that
        way, preferring one straight ahead. Stays put when there is nothing (unless wrapping)."""
        step = _STEPS.get(action)
        if step is None or current not in self.rects:
            return current
        origin = self.rects[current].centre
        best = self._nearest(current, origin, step)
        if best is None and self.wrap:
            # Start again from far behind the current spot, on the same line.
            span = max(max(rect.right, rect.top) for rect in self.rects.values()) * 2
            behind = (origin[0] - step[0] * span, origin[1] - step[1] * span)
            best = self._nearest(None, behind, step)
        return best if best is not None else current

    def _nearest(
        self, skip: str | None, origin: tuple[float, float], step: tuple[int, int]
    ) -> str | None:
        best: str | None = None
        best_cost = 0.0
        for name, rect in self.rects.items():
            if name == skip:
                continue
            dx, dy = rect.centre[0] - origin[0], rect.centre[1] - origin[1]
            ahead = dx * step[0] + dy * step[1]
            if ahead <= 0:
                continue
            sideways = abs(dx * step[1]) + abs(dy * step[0])
            cost = ahead + sideways * SIDEWAYS_COST
            if best is None or cost < best_cost:
                best, best_cost = name, cost
        return best
