"""Eenmalig instellen waar de LEAVE MATCH-knop zit.

Start dit terwijl Fortnite in een potje zit. De teller loopt af; in die tijd:
  - ga naar Fortnite (Alt+Tab)
  - druk ESC (menu open)
  - houd de muis stil boven LEAVE MATCH
Na de teller leest het script je cursorpositie en slaat die op als
verhouding van het game-venster (leave.json), zodat de bot er later op
kan klikken.

    python calibrate_leave.py              # LEAVE MATCH
    python calibrate_leave.py --confirm    # bevestigingsknop (indien nodig)
"""

from __future__ import annotations

import argparse
import json
import os
import time

from link import client_rect, cursor_pos, find_window
from paths import base_dir

CFG = os.path.join(base_dir(), "leave.json")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=10.0,
                    help="seconden om naar het menu te gaan")
    ap.add_argument("--confirm", action="store_true",
                    help="leg de bevestigingsknop vast i.p.v. LEAVE MATCH")
    args = ap.parse_args(argv)

    hwnd = find_window()
    if not hwnd:
        print("[!] Fortnite-venster niet gevonden.")
        return 2
    rect = client_rect(hwnd)
    if rect is None:
        print("[!] Geen client-area gevonden.")
        return 2
    x0, y0, w, h = rect

    target = "YES / LEAVE (bevestiging)" if args.confirm else "LEAVE MATCH"
    print(f"[i] Ga naar Fortnite, open het ESC-menu en houd de muis op {target}.")
    print("[i] Niet meer bewegen tot de teller op 0 staat.")
    for left in range(int(args.wait), 0, -1):
        print(f"    {left}...", end="\r", flush=True)
        time.sleep(1.0)
    print(" " * 40, end="\r")

    cx, cy = cursor_pos()
    if not (x0 <= cx < x0 + w and y0 <= cy < y0 + h):
        print(f"[!] Cursor staat buiten het game-venster ({cx}, {cy}); "
              f"venster is {x0},{y0} {w}x{h}.")
        return 2

    data = {}
    if os.path.isfile(CFG):
        try:
            with open(CFG, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
    key = "confirm" if args.confirm else "leave"
    data[key] = [round((cx - x0) / w, 4), round((cy - y0) / h, 4)]
    with open(CFG, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    print(f"[i] opgeslagen: {key} = {data[key]}  (pixel {cx},{cy})")
    print(f"    in {CFG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
