"""Auto-queue loop.

Detecteert knoppen op kleur en vorm -- geen handmatig geknipte plaatjes nodig
voor de twee die er echt toe doen.

  PLAY            : neon-geel (247,255,26), brede knop
  RETURN TO LOBBY : lavendel balk, breed en plat

Optioneel kunnen claim.png / close.png alsnog als template gebruikt worden
voor popups.

De PC leest alleen pixels; de klikken komen van de RP2040 via link.py.

    python main.py
    python main.py --dry-run --verbose
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import random
import sys
import time

from link import (PicoLost, client_rect, find_window, focus, is_foreground,
                  open_mouse)
from paths import assets_dir, base_dir
from vision import grab_frame, load_template, locate

ASSETS = assets_dir()
LEAVE_CFG = os.path.join(base_dir(), "leave.json")

# Volgorde = prioriteit. Eerste treffer wint, daarna opnieuw scannen.
TARGETS = [
    dict(key="claim", kind="tpl", file="claim.png", region="full",
         label="claim"),
    dict(key="close", kind="tpl", file="close.png", region="full",
         label="popup close"),
    dict(key="return", kind="hsv", region="recap", label="return to lobby",
         lo=(112, 20, 170), hi=(140, 120, 255),
         # verhoudingen i.p.v. vaste pixels: werkt op elke resolutie
         min_area_frac=0.006, min_w_frac=0.18,
         min_h_frac=0.032, max_h_frac=0.14,
         min_aspect=6.0, max_aspect=30.0, min_fill=0.55),
    dict(key="play", kind="rgb", region="lobby", label="play",
         rgb=(247, 255, 26), tol=16,
         min_area=9000, min_w=200, min_h=40, max_h=140,
         min_aspect=2.0, max_aspect=7.0),
]

# Health-balk linksonder. Verschijnt pas als je uit de bus bent: solide
# groene rechthoek, verzadigd en helder. Gras in de hoek haalt die
# saturatie niet, dus dit is een redelijke "ik sta op de grond"-vlag.
HUD = dict(key="hud", kind="hsv", region="hud", label="hud",
           lo=(48, 140, 140), hi=(70, 235, 235),
           min_area=1800, min_w=60, min_h=14, max_h=70,
           min_aspect=1.5, max_aspect=12.0, max_w=280, min_fill=0.55)


def stamp():
    return time.strftime("%H:%M:%S")


def load_templates():
    tpl = {}
    for t in TARGETS:
        if t["kind"] != "tpl":
            continue
        img = load_template(ASSETS, t["file"])
        if img is not None:
            tpl[t["key"]] = img
    return tpl


def apply_overrides():
    """assets/return.png bestaat? Dan template i.p.v. kleurdetectie."""
    img = load_template(ASSETS, "return.png")
    if img is None:
        return None
    for t in TARGETS:
        if t["key"] == "return":
            t["kind"] = "tpl"
            t["file"] = "return.png"
    return img


def load_leave_cfg():
    """leave.json: waar de LEAVE MATCH-knop zit, als fractie van het venster."""
    try:
        with open(LEAVE_CFG, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    leave = data.get("leave")
    if not (isinstance(leave, (list, tuple)) and len(leave) == 2):
        return None
    confirm = data.get("confirm")
    if not (isinstance(confirm, (list, tuple)) and len(confirm) == 2):
        confirm = None
    return {"leave": leave, "confirm": confirm}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="COM-poort van het PICO-HID data-kanaal")
    ap.add_argument("--threshold", type=float, default=0.86,
                    help="alleen voor template-targets")
    ap.add_argument("--guard", type=float, default=3.5,
                    help="sec voordat dezelfde knop weer geklikt mag")
    ap.add_argument("--poll-min", type=float, default=0.55)
    ap.add_argument("--poll-max", type=float, default=1.15)
    ap.add_argument("--max-minutes", type=float, default=0.0, help="0 = oneindig")
    ap.add_argument("--heartbeat", type=float, default=60.0,
                    help="sec tussen statusregels, 0 = uit")
    ap.add_argument("--drop-min", type=float, default=7.0,
                    help="min sec na de bus-start voordat er gesprongen wordt")
    ap.add_argument("--drop-max", type=float, default=17.0,
                    help="max sec na de bus-start voordat er gesprongen wordt")
    ap.add_argument("--no-drop", action="store_true",
                    help="spatie uit de bus overslaan")
    ap.add_argument("--hold-min", type=float, default=17.0,
                    help="min sec dat W ingedrukt blijft na de sprong")
    ap.add_argument("--hold-max", type=float, default=25.0,
                    help="max sec dat W ingedrukt blijft na de sprong")
    ap.add_argument("--w-delay-min", type=float, default=0.2,
                    help="min sec tussen de sprong en W indrukken")
    ap.add_argument("--w-delay-max", type=float, default=1.3,
                    help="max sec tussen de sprong en W indrukken")
    ap.add_argument("--leave-min", type=float, default=10.0,
                    help="min minuten in een potje voordat hij leavet")
    ap.add_argument("--leave-max", type=float, default=15.0,
                    help="max minuten in een potje voordat hij leavet")
    ap.add_argument("--leave-wait", type=float, default=0.9,
                    help="sec wachten tot het ESC-menu open is")
    ap.add_argument("--no-leave", action="store_true",
                    help="10-15 min leave uitzetten")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    leave_cfg = None if args.no_leave else load_leave_cfg()
    if leave_cfg is not None:
        print(f"[i] leave na {args.leave_min:g}-{args.leave_max:g} min "
              f"per potje")
    elif not args.no_leave:
        print("[i] leave-knop niet ingesteld -- launcher [5], "
              "eenmalig in een potje")

    hwnd = find_window()
    if not hwnd:
        print("[!] Fortnite-venster niet gevonden (class UnrealWindow).")
        print("    Start Fortnite op Windowed Fullscreen.")
        return 2

    tpl = load_templates()
    override = apply_overrides()
    if override is not None:
        tpl["return"] = override
        print("[i] return: template (assets/return.png)")
    if tpl:
        print("[i] templates: " + ", ".join(sorted(tpl)))

    return_target = next(t for t in TARGETS if t["key"] == "return")
    play_target = next(t for t in TARGETS if t["key"] == "play")

    if args.dry_run:
        mouse = None
        print("[i] dry-run: er wordt niet geklikt")
    else:
        try:
            mouse = open_mouse(args.port)
        except RuntimeError as e:
            print(f"[!] {e}")
            return 2
        print(f"[i] Pico: {mouse.ident or '(onbekend)'}")
        if "KD" not in (getattr(mouse, "caps", "") or "").upper():
            print("[!] Pico-firmware kan W niet vasthouden (verouderd).")
            print("    Launcher [7] = firmware bijwerken, daarna opnieuw.")

    last_click: dict[str, float] = {}
    cycles = 0
    phase = "unknown"      # unknown | lobby | match
    last_hit = time.monotonic()
    t0 = time.monotonic()
    elapsed_min = 0.0
    last_beat = time.monotonic()
    last_focus_warn = 0.0
    focus_fails = 0
    # drop_state: idle -> island (wacht op spawn-eiland) -> bus (wacht tot
    # de HUD weer weg is = bus) -> armed (timer loopt) -> done
    drop_state = "idle"
    drop_at = 0.0
    drop_presses = 0
    drop_t0 = 0.0
    hold_until = 0.0
    holding_w = False
    quiet_until = 0.0
    seen: dict[str, int] = {}
    leave_gap = random.uniform(args.leave_min, args.leave_max) * 60.0
    leave_at = 0.0
    errors = 0
    restart = False

    def arm_leave(t: float):
        nonlocal leave_at
        if leave_cfg is None or leave_at:
            return
        leave_at = t + leave_gap
        print(f"[{stamp()}] leave over {leave_gap / 60:.1f} min")

    # Een tweede bot zou dezelfde muis besturen; dat wordt een rommeltje.
    kernel32 = ctypes.windll.kernel32
    _mutex = kernel32.CreateMutexW(None, False, "Local\\devkit_autoqueue")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("[!] Er draait al een auto-queue. Stop die eerst.")
        return 2

    import mss

    factory = getattr(mss, "MSS", None) or mss.mss
    try:
        with factory() as sct:
            while True:
                elapsed_min = (time.monotonic() - t0) / 60.0
                if args.max_minutes and elapsed_min >= args.max_minutes:
                    print(f"[i] sessielimiet {args.max_minutes:g} min bereikt")
                    break

                # in dry-run het spel niet naar de voorgrond trekken: alleen
                # meekijken, de pc blijft bruikbaar
                if not args.dry_run and not focus(hwnd):
                    focus_fails += 1
                    mono = time.monotonic()
                    # niet elke 1.5s spammen; 1x per 30s is genoeg om te weten
                    if mono - last_focus_warn > 30:
                        last_focus_warn = mono
                        print(f"[{stamp()}] kan Fortnite niet naar voorgrond "
                              f"krijgen ({focus_fails}x totaal)")
                    time.sleep(1.5)
                    continue

                rect = client_rect(hwnd)
                if rect is None:
                    time.sleep(0.5)
                    continue

                try:
                    frame = grab_frame(sct, rect)
                except Exception:
                    # scherm tijdelijk niet leesbaar (fullscreen-wissel, lock)
                    errors += 1
                    time.sleep(0.5)
                    continue

                now = time.monotonic()

                # Net terug in de lobby: even niets aanklikken, anders pakt
                # hij tijdens de overgang het verkeerde element.
                if now < quiet_until:
                    time.sleep(random.uniform(args.poll_min, args.poll_max))
                    continue

                hit = False

                # Schermherkenning: de recap heeft rechts een gele PLAY
                # AGAIN die op de lobby-PLAY lijkt. Eerst kijken wat er
                # staat, dan pas klikken.
                recap_hit = None
                if drop_state not in ("island", "bus", "armed"):
                    recap_hit = locate(return_target, frame, rect, tpl,
                                       args.threshold)
                if recap_hit is not None:
                    phase = "match"
                play_hit = None
                if recap_hit is None and drop_state in ("idle", "done"):
                    play_hit = locate(play_target, frame, rect, tpl,
                                      args.threshold)
                    if (play_hit is not None
                            and now - last_click.get("play", -1e9) > 6.0):
                        phase = "lobby"

                for target in TARGETS:
                    key = target["key"]
                    # In een potje (of op de recap) alleen op RETURN letten:
                    # geel in de wereld en PLAY AGAIN mogen geen klik worden.
                    if phase == "match" and key != "return":
                        continue
                    # Op het spawn-eiland en in de bus is er geen recap, dus
                    # een treffer daar is ruis (en sloopt de fase).
                    if key == "return" and drop_state in ("island", "bus",
                                                          "armed"):
                        continue
                    if now - last_click.get(key, -1e9) < args.guard:
                        continue
                    if key == "return":
                        found = recap_hit
                    elif key == "play":
                        found = play_hit
                    else:
                        found = locate(target, frame, rect, tpl,
                                       args.threshold)
                    if not found:
                        seen.pop(key, None)
                        continue
                    if key == "return":
                        # twee keer achter elkaar gezien = echt, geen ruis
                        count = seen.get(key, 0) + 1
                        seen[key] = count
                        if count < 2:
                            last_hit = now
                            hit = True
                            if args.verbose:
                                print(f"[{stamp()}] return gezien "
                                      f"({count}/2), nog niet klikken")
                            # niet doorvallen naar PLAY op de recap
                            break
                        seen.pop(key, None)

                    x, y, info = found
                    if mouse is not None:
                        if is_foreground(hwnd):
                            mouse.click_at(x, y)
                        else:
                            print(f"[{stamp()}] klik overgeslagen: game niet vooraan")
                            continue
                    last_click[key] = now
                    last_hit = now
                    if key == "play":
                        cycles += 1
                        phase = "match"
                        drop_state = "island"
                        drop_presses = 0
                        drop_t0 = now
                        seen.clear()
                        leave_gap = (random.uniform(args.leave_min,
                                                    args.leave_max) * 60.0)
                        leave_at = 0.0
                    elif key == "return":
                        phase = "lobby"
                        drop_state = "idle"
                        leave_at = 0.0
                        # lobby laten laden voordat er weer geklikt wordt
                        quiet_until = now + 5.0
                        if holding_w:
                            mouse.key_up("W")
                            holding_w = False
                            print(f"[{stamp()}] W los (terug in lobby)")
                    print(f"[{stamp()}] {target['label']:<16s} {info:<12s} "
                          f"@ {x},{y}   matches={cycles}")
                    hit = True
                    break

                if not hit:
                    idle = now - last_hit
                    if phase == "unknown" and idle > 25:
                        phase = "match"
                        arm_leave(now)
                        print(f"[{stamp()}] niets gevonden, aanname: in potje")
                    elif phase == "lobby" and idle > 90:
                        phase = "match"
                        arm_leave(now)
                        print(f"[{stamp()}] lobby stil, aanname: in potje")

                # Uit de bus stappen. De health-balk linksonder is zichtbaar op
                # het spawn-eiland en op de grond, maar niet in de bus. Dus:
                # eerst wachten tot de balk er is (spawn-eiland), dan wachten
                # tot hij weg is (= bus begint), dan random 7-17s wachten.
                if (not args.no_drop and phase == "match"
                        and drop_state != "done" and mouse is not None):
                    hud = bool(locate(HUD, frame, rect, tpl, args.threshold))

                    if drop_state == "island" and hud:
                        drop_state = "bus"
                        print(f"[{stamp()}] spawn-eiland, wacht op de bus")
                    elif drop_state == "bus" and not hud:
                        delay = random.uniform(args.drop_min, args.drop_max)
                        drop_at = now + delay
                        drop_state = "armed"
                        arm_leave(now)
                        print(f"[{stamp()}] bus begint, sprong over "
                              f"{delay:.0f}s")
                    elif ((drop_state == "armed" and now >= drop_at)
                          or (drop_state == "island"
                              and now - drop_t0 > 150)):
                        # bij een late start nooit het eiland gezien: alsnog
                        # springen, anders blijft hij hangen
                        note = ("" if drop_state == "armed"
                                else " (noodgreep, geen eiland gezien)")
                        drop_state = "done"
                        drop_presses += 1
                        arm_leave(now)
                        mouse.press_key("SP")
                        w_gap = random.uniform(args.w_delay_min,
                                               args.w_delay_max)
                        print(f"[{stamp()}] sprong{note}, W over "
                              f"{w_gap:.1f}s")
                        # de hoofdlus pollt te traag om dit korte venster
                        # precies te raken; hier even strak wachten
                        if w_gap > 0:
                            time.sleep(w_gap)
                        hold = random.uniform(args.hold_min, args.hold_max)
                        hold_until = time.monotonic() + hold
                        holding_w = True
                        mouse.key_down("W")
                        time.sleep(0.15)
                        if not mouse.key_is_down("W"):
                            print(f"[{stamp()}] [!] Pico houdt W niet vast "
                                  f"-- launcher [7] firmware bijwerken")
                        print(f"[{stamp()}] W vast voor {hold:.0f}s")

                # Na de sprong W vasthouden zolang de timer loopt.
                if holding_w and now >= hold_until:
                    if mouse is not None:
                        mouse.key_up("W")
                    holding_w = False
                    print(f"[{stamp()}] W los")

                # Potje duurt te lang: zelf terug naar de lobby via ESC.
                if (leave_cfg is not None and phase == "match"
                        and leave_at and now >= leave_at):
                    if recap_hit is not None:
                        # recap staat al klaar: de normale return-flow doet het
                        pass
                    elif mouse is None:
                        leave_at = 0.0
                        print(f"[{stamp()}] leave (dry-run)")
                    elif is_foreground(hwnd) or focus(hwnd):
                        leave_at = 0.0
                        if holding_w:
                            mouse.key_up("W")
                            holding_w = False
                        mouse.press_key("ESC")
                        time.sleep(args.leave_wait)
                        lx, ly = leave_cfg["leave"]
                        mouse.click_at(rect[0] + int(lx * rect[2]),
                                       rect[1] + int(ly * rect[3]))
                        if leave_cfg["confirm"]:
                            time.sleep(args.leave_wait)
                            cx, cy = leave_cfg["confirm"]
                            mouse.click_at(rect[0] + int(cx * rect[2]),
                                           rect[1] + int(cy * rect[3]))
                        phase = "lobby"
                        drop_state = "idle"
                        seen.clear()
                        quiet_until = time.monotonic() + 6.0
                        print(f"[{stamp()}] leave via ESC-menu")

                if args.heartbeat and now - last_beat >= args.heartbeat:
                    last_beat = now
                    leave_txt = (f" leave_in={max(0.0, leave_at - now):.0f}s"
                                 if leave_at else "")
                    print(f"[{stamp()}] status phase={phase:<7s} "
                          f"matches={cycles} up={elapsed_min:.1f}m "
                          f"idle={now - last_hit:.0f}s focus_fails={focus_fails}"
                          f" drop={drop_state} err={errors}{leave_txt}")

                time.sleep(random.uniform(args.poll_min, args.poll_max))
    except KeyboardInterrupt:
        print("\n[i] gestopt met Ctrl+C")
    except PicoLost:
        # kabel eruit of Pico gereset: even wachten tot hij terugkomt en
        # daarna gewoon doorgaan i.p.v. crashen
        print("\n[!] Pico losgekoppeld -- wachten tot hij terug is...")
        restart = True
        try:
            kernel32.CloseHandle(_mutex)  # anders blokkeert de herstart zichzelf
        except Exception:
            pass
        while True:
            try:
                probe = open_mouse(args.port)
                probe.close()
                break
            except RuntimeError:
                time.sleep(2.0)
        print("[i] Pico weer verbonden, ga verder")
    finally:
        if holding_w and mouse is not None:
            try:
                mouse.key_up("W")
            except Exception:
                pass
        if mouse is not None:
            mouse.close()

    if restart:
        return main(argv)

    print(f"[i] klaar: {cycles} matches in {elapsed_min:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
