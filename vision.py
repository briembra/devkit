"""Detectie: kleur-blobs en template-matching op een screenshot.

Twee soorten targets:
  rgb   - exacte kleur met tolerantie (Fortnite's PLAY-knop is (247,255,26))
  hsv   - kleurbereik, voor dingen waarvan de exacte tint per monitor verschilt
  tpl   - klassieke matchTemplate, voor optionele popups

Elke detectie filtert op vorm (breedte/hoogte/aspect), zodat een paarse
schatkist geen "RETURN TO LOBBY" wordt.
"""

from __future__ import annotations

import gc
import os

import cv2
import numpy as np


def grab(sct, region):
    """BGR-frame van een schermregio."""
    left, top, w, h = region
    raw = np.array(sct.grab({"left": left, "top": top, "width": w, "height": h}))
    return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)


def grab_frame(sct, rect):
    """Eenmalige BGR-kopie van de hele client-area.

    Een tick doet 3-4 detecties; die delen dit ene frame. Zonder dit doet
    elke detectie zijn eigen grab en dat is 4x 8 MB per seconde aan kopieen.
    """
    x, y, w, h = rect
    raw = np.array(sct.grab({"left": x, "top": y, "width": w, "height": h}))
    return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)


def sub_region(rect, which):
    x, y, w, h = rect
    if which == "br":
        cw, ch = int(w * 0.55), int(h * 0.50)
        return (x + w - cw, y + h - ch, cw, ch)
    if which == "bl":
        cw, ch = int(w * 0.55), int(h * 0.50)
        return (x, y + h - ch, cw, ch)
    if which == "bottom":
        top = y + int(h * 0.78)
        return (x, top, w, y + h - top)
    if which == "lobby":
        # alleen het linker mode-paneel: daar staat de echte PLAY. De
        # recap heeft rechts een even gele PLAY AGAIN, die mag nooit
        # als lobby-knop gelden.
        cw = int(w * 0.50)
        ch = int(h * 0.28)
        return (x, y + h - ch, cw, ch)
    if which == "hud":
        ch = int(h * 0.16)
        return (x, y + h - ch, min(320, w), ch)
    if which == "recap":
        # alleen de rechterkolom van het recap-scherm: daar staat RETURN TO
        # LOBBY. Zo kunnen lavendel-knoppen onderin de lobby geen valse
        # treffer meer zijn.
        x0 = x + int(w * 0.55)
        y0 = y + int(h * 0.15)
        return (x0, y0, x + w - x0, y + int(h * 0.70) - y0)
    return (x, y, w, h)


def _blobs(mask, min_area):
    """Alle blokken >= min_area, grootste eerst.

    Niet alleen de grootste teruggeven: een groot lavendel-vlak op de
    achtergrond mag een kleinere maar wel correcte knop niet verbergen.
    """
    n, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=4
    )
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area >= min_area:
            out.append((x, y, w, h, area))
    out.sort(key=lambda b: -b[4])
    return out


def _shape_ok(w, h, min_w, min_h, max_h, min_aspect, max_aspect,
              max_w=10 ** 6):
    if w < min_w or w > max_w or h < min_h or h > max_h:
        return False
    aspect = w / h if h else 0.0
    return min_aspect <= aspect <= max_aspect


def detect_rgb(frame, offset, rgb, tol, min_area, min_w, min_h, max_h,
               min_aspect, max_aspect, max_w=10 ** 6):
    target = np.array([rgb[2], rgb[1], rgb[0]], dtype=np.int16)
    dist = np.abs(frame.astype(np.int16) - target).max(axis=2)
    mask = (dist <= tol).astype(np.uint8)
    for x, y, w, h, _area in _blobs(mask, min_area):
        if not _shape_ok(w, h, min_w, min_h, max_h, min_aspect, max_aspect,
                         max_w):
            continue
        return (offset[0] + x + w // 2, offset[1] + y + h // 2, f"{w}x{h}")
    return None


def detect_hsv(frame, offset, lo, hi, min_area, min_w, min_h, max_h,
               min_aspect, max_aspect, min_fill=None, max_w=10 ** 6):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    # gradienten en zwarte tekst splitsen de balk; closing lijmt hem weer aan elkaar
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    for x, y, w, h, area in _blobs(mask, min_area):
        if not _shape_ok(w, h, min_w, min_h, max_h, min_aspect, max_aspect,
                         max_w):
            continue
        if min_fill is not None and area / float(w * h) < min_fill:
            continue
        return (offset[0] + x + w // 2, offset[1] + y + h // 2, f"{w}x{h}")
    return None


def detect_template(frame, offset, template, threshold):
    th, tw = template.shape[:2]
    if frame.shape[0] < th or frame.shape[1] < tw:
        return None
    res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    _minv, best, _minloc, loc = cv2.minMaxLoc(res)
    if best < threshold:
        return None
    return (offset[0] + loc[0] + tw // 2,
            offset[1] + loc[1] + th // 2,
            f"score={best:.3f}")


def locate(target, frame, rect, templates, threshold):
    """Geeft (x, y, info) of None. Werkt op een al gegrabbed frame."""
    try:
        return _locate(target, frame, rect, templates, threshold)
    except (cv2.error, MemoryError, OSError):
        # tijdelijk geheugentekort of een grab die naast het scherm valt:
        # deze tik overslaan, de volgende mag het opnieuw proberen.
        gc.collect()
        return None


def _scaled(target, frame):
    """Vervang *_frac drempels door pixels voor deze frame-grootte.

    Zo blijft dezelfde target werken op 1080p, 1440p en ultrawide: de bot
    kijkt naar verhoudingen, niet naar absolute pixelmaten.
    """
    h, w = frame.shape[:2]
    t = dict(target)
    for key, dim in (("min_area", w * h), ("min_w", w), ("max_w", w),
                     ("min_h", h), ("max_h", h)):
        frac = target.get(key + "_frac")
        if frac is not None:
            t[key] = int(frac * dim)
    return t


def _locate(target, frame, rect, templates, threshold):
    region = sub_region(rect, target.get("region", "full"))
    ox, oy = rect[0], rect[1]
    x0 = max(0, region[0] - ox)
    y0 = max(0, region[1] - oy)
    sub = frame[y0:y0 + region[3], x0:x0 + region[2]]
    offset = (region[0], region[1])
    kind = target["kind"]

    if kind == "tpl":
        template = templates.get(target["key"])
        if template is None:
            return None
        return detect_template(sub, offset, template,
                               target.get("threshold", threshold))

    target = _scaled(target, frame)
    common = dict(
        min_area=target["min_area"],
        min_w=target["min_w"],
        min_h=target["min_h"],
        max_h=target["max_h"],
        min_aspect=target["min_aspect"],
        max_aspect=target["max_aspect"],
        max_w=target.get("max_w", 10 ** 6),
    )

    if kind == "rgb":
        return detect_rgb(sub, offset, target["rgb"], target["tol"], **common)

    if kind == "hsv":
        return detect_hsv(sub, offset, target["lo"], target["hi"],
                          min_fill=target.get("min_fill"), **common)

    return None


def load_template(folder, fname):
    path = os.path.join(folder, fname)
    if not os.path.isfile(path):
        return None
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    return img if img is not None else None
