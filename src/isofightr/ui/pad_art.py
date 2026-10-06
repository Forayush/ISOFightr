"""The controller diagram on the Controls screen: a gamepad whose buttons can light up.

Plan note "08 - Controls and Input" (decision D-061). Original art, drawn with Pillow from
theme colours (so every pixel is a Resurrect 64 entry): a generic two-stick pad, not any
maker's. A control that is held is drawn lit; a control bound to the tile under the cursor
is drawn marked.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from typing import Final

from PIL import Image, ImageDraw

from isofightr.ui import theme
from isofightr.ui.theme import Rgb

PAD_ART_SIZE: Final[tuple[int, int]] = (150, 86)
Box = tuple[int, int, int, int]
STICK_RADIUS: Final[int] = 9
FACE_RADIUS: Final[int] = 4

SHOULDERS: Final[dict[str, Box]] = {
    "lefttrigger": (26, 2, 48, 10),
    "righttrigger": (101, 2, 123, 10),
    "leftshoulder": (20, 12, 54, 19),
    "rightshoulder": (95, 12, 129, 19),
}
STICKS: Final[dict[str, tuple[int, int]]] = {"leftstick": (38, 38), "rightstick": (94, 56)}
FACES: Final[dict[str, tuple[int, int]]] = {
    "y": (112, 29),
    "a": (112, 47),
    "x": (103, 38),
    "b": (121, 38),
}
DPAD_CENTRE: Final[tuple[int, int]] = (56, 56)
DPAD_ARM: Final[int] = 6
"""Each arm of the d-pad is a square this big."""
DPAD: Final[dict[str, tuple[int, int]]] = {
    "dpup": (0, -1),
    "dpdown": (0, 1),
    "dpleft": (-1, 0),
    "dpright": (1, 0),
}
START: Final[Box] = (71, 34, 78, 37)
CONTROLS: Final[tuple[str, ...]] = (*SHOULDERS, *STICKS, *FACES, *DPAD, "start")
"""Every control the diagram draws."""

BODY: Final[Rgb] = theme.STEEL
BODY_EDGE: Final[Rgb] = theme.ICE
IDLE: Final[Rgb] = theme.NIGHT
EDGE: Final[Rgb] = theme.INK
LIT: Final[Rgb] = theme.MINT
MARKED: Final[Rgb] = theme.GOLD


def control_color(control: str, lit: frozenset[str], marked: frozenset[str]) -> Rgb:
    """Return a control's colour: lit while held, marked when the cursor's tile uses it."""
    if control in lit:
        return LIT
    if control in marked:
        return MARKED
    return IDLE


def control_box(control: str) -> Box:
    """Return the pixels a control covers in the diagram: left, top, right, bottom."""
    if control in SHOULDERS:
        return SHOULDERS[control]
    if control in STICKS:
        x, y = STICKS[control]
        return (x - STICK_RADIUS, y - STICK_RADIUS, x + STICK_RADIUS, y + STICK_RADIUS)
    if control in FACES:
        x, y = FACES[control]
        return (x - FACE_RADIUS, y - FACE_RADIUS, x + FACE_RADIUS, y + FACE_RADIUS)
    if control in DPAD:
        dx, dy = DPAD[control]
        half = DPAD_ARM // 2
        reach = DPAD_ARM + 1  # a clear pixel from the centre square: arms never touch
        x, y = DPAD_CENTRE[0] + dx * reach, DPAD_CENTRE[1] + dy * reach
        return (x - half, y - half, x + half, y + half)
    if control == "start":
        return START
    raise KeyError(control)


def build_pad(
    lit: frozenset[str] = frozenset(), marked: frozenset[str] = frozenset()
) -> Image.Image:
    """Return the diagram with the ``lit`` controls bright and the ``marked`` ones gold."""
    image = Image.new("RGBA", PAD_ART_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def color(control: str) -> Rgb:
        return control_color(control, lit, marked)

    # Triggers and shoulders first: the body overlaps their lower edge.
    for control, box in SHOULDERS.items():
        draw.rectangle(box, fill=color(control), outline=BODY_EDGE)
    # The body: a bar with a grip hanging from each end.
    for grip in ((6, 34, 48, 85), (101, 34, 143, 85)):
        draw.ellipse(grip, fill=BODY, outline=BODY_EDGE)
    draw.rounded_rectangle((8, 18, 141, 66), radius=14, fill=BODY, outline=BODY_EDGE)
    draw.rectangle((30, 50, 119, 66), fill=BODY)
    draw.line((40, 66, 109, 66), fill=BODY_EDGE)

    for control in STICKS:
        draw.ellipse(control_box(control), fill=color(control), outline=EDGE)
        x, y = STICKS[control]
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), outline=EDGE)
    half = DPAD_ARM // 2
    centre = (
        DPAD_CENTRE[0] - half,
        DPAD_CENTRE[1] - half,
        DPAD_CENTRE[0] + half,
        DPAD_CENTRE[1] + half,
    )
    draw.rectangle(centre, fill=IDLE)
    for control in DPAD:
        draw.rectangle(control_box(control), fill=color(control), outline=EDGE)
    for control in FACES:
        draw.ellipse(control_box(control), fill=color(control), outline=EDGE)
    draw.rectangle(START, fill=color("start"), outline=EDGE)
    return image
