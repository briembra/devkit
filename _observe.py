"""Tijdelijke observatie: legt frames vast om de bus-fase te kunnen bekijken.

Schrijft kleine JPEG's + een csv met tijd, gemiddelde helderheid en of de
health-balk linksonder zichtbaar is. Niet onderdeel van de bot.
"""

import csv
import os
import time

import cv2
import mss
import numpy as np

OUT = r"C:\Users\Bram Reurink\AppData\Local\Temp\opencode\frames"
os.makedirs(OUT, exist_ok=True)
CSV = os.path.join(OUT, "log.csv")

HUD_LO = np.array((48, 140, 140), np.uint8)
HUD_HI = np.array((70, 235, 235), np.uint8)


def hud_visible(frame):
    h, w = frame.shape[:2]
    sub = frame[int(h * 0.84):h, 0:min(320, w)]
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, HUD_LO, HUD_HI)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(mask, 4)
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if area >= 1800 and 60 <= bw <= 280 and 14 <= bh <= 70:
            if area / float(bw * bh) >= 0.55:
                return True
    return False


def main():
    factory = getattr(mss, "MSS", None) or mss.mss
    t0 = time.monotonic()
    with open(CSV, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["t", "file", "mean", "hud", "diff"])
        prev = None
        with factory() as sct:
            while time.monotonic() - t0 < 900:
                raw = np.array(sct.grab(sct.monitors[1]))
                frame = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
                small = cv2.resize(frame, (480, 270), interpolation=cv2.INTER_AREA)
                t = time.monotonic() - t0
                mean = float(frame.mean())
                diff = 0.0 if prev is None else float(
                    np.abs(small.astype(np.int16) - prev.astype(np.int16)).mean())
                prev = small
                name = f"{int(t*10):05d}.jpg"
                cv2.imwrite(os.path.join(OUT, name), small,
                            [cv2.IMWRITE_JPEG_QUALITY, 70])
                wr.writerow([f"{t:.1f}", name, f"{mean:.1f}",
                             int(hud_visible(frame)), f"{diff:.1f}"])
                fh.flush()
                time.sleep(0.9)


if __name__ == "__main__":
    main()
