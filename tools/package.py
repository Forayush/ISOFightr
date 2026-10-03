"""Build the packaged Windows game with PyInstaller, and smoke test it.

Usage::

    uv run python tools/package.py            # build dist/ISOFightr/ISOFightr.exe and test it
    uv run python tools/package.py --no-test  # build only
    uv run python tools/package.py --test-only

A one-folder build (plan note "17 - Roadmap", M11; decision D-056): ``dist/ISOFightr/`` holds
``ISOFightr.exe``, the Python runtime and the game's ``assets/``. The source art
(``art_src/``), the tools and the tests are not shipped. The smoke test runs the packaged
program four ways: a headless match that records a replay, a headless check that the replay
plays back to the same state, an audio check (one sound and one song at zero volume), and a
short windowed battle against a CPU (muted).
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "ISOFightr"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
EXE = DIST / NAME / f"{NAME}.exe"
SMOKE_TIMEOUT = 180


def build() -> None:
    """Run PyInstaller."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        NAME,
        "--windowed",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(WORK),
        "--paths",
        str(ROOT / "src"),
        "--add-data",
        f"{ROOT / 'assets'};assets",
        str(ROOT / "packaging" / "isofightr_main.py"),
    ]
    subprocess.run(command, check=True, cwd=ROOT)


def run(arguments: list[str]) -> int:
    """Run the packaged game with ``arguments`` and return its exit code."""
    done = subprocess.run([str(EXE), *arguments], timeout=SMOKE_TIMEOUT, check=False)
    return done.returncode


def smoke_test() -> None:
    """Check that the packaged game finds its assets, simulates and opens a window."""
    if not EXE.exists():
        raise SystemExit(f"{EXE} is missing: build it first")
    with tempfile.TemporaryDirectory() as folder:
        replay = Path(folder) / "smoke.json"
        steps = [
            (
                "headless CPU match, recorded",
                [
                    "--headless",
                    "--frames",
                    "900",
                    "--cpu",
                    "1:9",
                    "--cpu",
                    "2:9",
                    "--p1",
                    "bramble",
                    "--p2",
                    "mote",
                    "--stage",
                    "lily_pads",
                    "--record",
                    str(replay),
                ],
            ),
            ("the replay plays back to the same state", ["--replay", str(replay), "--headless"]),
            ("sound effects and music load and play", ["--check-audio"]),
            (
                "a windowed battle against a CPU",
                ["--cpu", "2:5", "--stage", "sky_ruins", "--frames", "240", "--mute"],
            ),
        ]
        for label, arguments in steps:
            code = run(arguments)
            print(f"{'ok  ' if code == 0 else 'FAIL'} {label} (exit {code})")
            if code != 0:
                raise SystemExit(1)
        if not replay.exists():
            raise SystemExit("the packaged game did not write its replay")
    size = sum(path.stat().st_size for path in (DIST / NAME).rglob("*") if path.is_file())
    print(f"{EXE} works; the folder is {size / 1_000_000:.0f} MB")


def main() -> None:
    """Parse arguments, build and test."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-test", action="store_true", help="build without the smoke test")
    parser.add_argument("--test-only", action="store_true", help="smoke test an existing build")
    args = parser.parse_args()
    if not args.test_only:
        build()
    if not args.no_test:
        smoke_test()


if __name__ == "__main__":
    main()
