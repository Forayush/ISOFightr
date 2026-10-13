"""The halo and the cast shadow that keep a stage apart from its backdrop (decision D-065).
Pure: no window."""

from PIL import Image

from isofightr.data.stage_loader import load_stage
from isofightr.render.separation import (
    HALO_REACH,
    WATER_STAGES,
    build_cast_shadow,
    build_halo,
    halo_colours,
)

LIGHT, DARK = (0xFB, 0xB9, 0x54), (0x32, 0x33, 0x53)


def test_the_halos_colours_are_the_skys_lightest_and_darkest() -> None:
    sky = Image.new("RGBA", (100, 100), (*DARK, 255))
    sky.paste((*LIGHT, 255), (0, 50, 100, 100))
    sky.paste((0x48, 0x4A, 0x77, 255), (0, 40, 100, 50))
    sky.putpixel((3, 3), (255, 255, 255, 255))
    assert halo_colours(sky) == (LIGHT, DARK), "one white star is not the sky's colour"


def test_the_halo_rims_dark_edges_light_and_light_edges_dark() -> None:
    stage = Image.new("RGBA", (40, 40))
    stage.paste((255, 255, 255, 255), (8, 8, 32, 20))
    stage.paste((0x2E, 0x22, 0x2F, 255), (8, 20, 32, 32))
    halo = build_halo(stage, LIGHT, DARK)
    assert halo.size == (40 + 2 * HALO_REACH, 40 + 2 * HALO_REACH)
    at = HALO_REACH
    assert halo.getpixel((at + 20, at + 20))[3] == 0, "nothing where the stage is"
    assert halo.getpixel((at + 20, at + 7)) == (*DARK, 255), "over the white top: dark"
    assert halo.getpixel((at + 20, at + 32)) == (*LIGHT, 255), "under the dark side: light"
    assert halo.getpixel((at + 20, at + 2))[3] == 0, "it reaches three pixels, no further"
    colours = {pixel[:3] for pixel in halo.getdata() if pixel[3]}
    assert colours == {LIGHT, DARK}, "two colours of the sky and no blend"
    second = [halo.getpixel((x, at + 6))[3] for x in range(at + 10, at + 30)]
    assert 0 < second.count(255) < len(second), "the second pixel out is dithered"


def test_the_cast_shadow_is_the_footprint_on_the_water_below() -> None:
    from isofightr.render.iso import project
    from isofightr.render.underside import lowest_point

    stage = load_stage("lily_pads")
    shadow, (left, top) = build_cast_shadow(stage, DARK)
    solid = [pixel for pixel in shadow.getdata() if pixel[3]]
    assert solid and set(solid) == {(*DARK, 255)}
    cells = sum(1 for row in stage.cells for cell in row if cell)
    assert cells * 100 < len(solid) < cells * 150, "about half of each cell's diamond: dithered"
    highest = max(
        project(cx, cy, lowest_point(stage))[1]
        for cy, row in enumerate(stage.cells)
        for cx, cell in enumerate(row)
        if cell
    )
    assert top < highest, "below the stage's lowest point on the screen"
    assert left < 0 < left + shadow.width
    assert {"lily_pads", "storm_galleon"} == WATER_STAGES
