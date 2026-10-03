"""The offline art pipeline: Blender renders in, indexed sprite sheets out.

Plan note "10 - Animation and Asset Pipeline" (decisions D-044 to D-047). Nothing here is
used while the game runs; ``tools/build_art.py`` drives it. Pure Python plus Pillow (no
``arcade``), so it is tested in the default test run.
"""
