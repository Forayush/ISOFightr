"""Entry point of the packaged game (PyInstaller needs a script, not ``python -m``).

Decision D-056. Built by ``tools/package.py``.
"""

from isofightr.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
