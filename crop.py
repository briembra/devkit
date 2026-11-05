"""Knip-hulp: zet de clipboard-afbeelding als template-PNG neer.

Workflow:
    Win+Shift+S  ->  knip de knop strak  ->  python crop.py -n play
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "assets")

NAMES = ["close", "claim", "return", "start", "play"]

HINTS = {
    "play": "de PLAY-knop in de lobby (rechtsonder)",
    "start": "de groene PLAY-knop in het mode-menu",
    "return": "de RETURN TO LOBBY-knop na een potje",
    "claim": "optioneel: een CLAIM-knop in een reward-popup",
    "close": "optioneel: een X / CLOSE op een popup",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--name", required=True, choices=NAMES)
    ap.add_argument("--min-size", type=int, default=18,
                    help="waarschuw als de knip kleiner is dan dit")
    args = ap.parse_args(argv)

    img = ImageGrab.grabclipboard()
    if img is None or isinstance(img, list):
        print("[!] Geen afbeelding op de clipboard. Doe eerst Win+Shift+S.")
        return 2

    os.makedirs(TPL, exist_ok=True)
    path = os.path.join(TPL, f"{args.name}.png")
    img.convert("RGB").save(path)

    w, h = img.size
    print(f"[ok] {path}  ({w}x{h})")
    print(f"     verwacht: {HINTS[args.name]}")

    if w < args.min_size or h < args.min_size:
        print("[!] Erg klein. Knip iets ruimer, anders matcht het niet betrouwbaar.")
    if max(w, h) > 400:
        print("[!] Erg groot. Knip strakker: alleen de knop, geen achtergrond.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

