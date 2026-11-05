"""Waar staan de bestanden -- als script of als ingepakte DEVKIT.exe.

In de portable exe zit de code in een tijdelijk uitpakmapje (_MEIPASS),
maar leave.json en watch.log moeten naast de exe blijven staan zodat ze
bewaard blijven.
"""

from __future__ import annotations

import os
import sys


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> str:
    """Map van de exe (portable) of van dit script."""
    if frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def assets_dir() -> str:
    """Bundled assets (alleen-lezen) of de assets-map naast het script."""
    if frozen():
        return os.path.join(getattr(sys, "_MEIPASS", base_dir()), "assets")
    return os.path.join(base_dir(), "assets")


def firmware_dir() -> str:
    """De Pico-bestanden (boot.py / code.py) die mee in de exe zitten."""
    if frozen():
        return os.path.join(getattr(sys, "_MEIPASS", base_dir()), "pico")
    return os.path.join(base_dir(), "pico")
