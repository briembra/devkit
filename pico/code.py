"""PICO-HID bridge.

Protocol (ASCII, een commando per regel, antwoord = "OK"):
  ID              -> "PICO-HID 1.0"
  M <dx> <dy>     -> relatieve muisbeweging (wordt gechunkt)
  C               -> linkermuisknop klik
  P               -> press+release met korte hold
  K <naam>        -> toets indrukken en loslaten
  KD <naam>       -> toets ingedrukt houden tot KU
  KU <naam>       -> toets loslaten
  KA              -> alle toetsen los
                     SP=spatie ESC=escape ENT=enter W A S D
  CAPS            -> "CAPS: KD KU 1.1" (welke hold-commando's dit board kent)
  HALT            -> release alles

Relatieve bewegingen worden opgeknipt in rapporten van <= STEP px,
want HID-muizen clampen op +/-127 en hosts droppen grotere sprongen.
"""

import time
import usb_cdc
import usb_hid
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.mouse import Mouse

STEP = 55              # px per HID-rapport
INTER_REPORT = 0.004   # sec tussen rapporten
MAX_LINE = 128         # corrupte input mag de buffer nooit laten groeien
KEY_HOLD = 0.03        # sec ingedrukt houden

KEYS = {
    "SP": Keycode.SPACE,
    "SPACE": Keycode.SPACE,
    "ESC": Keycode.ESCAPE,
    "ESCAPE": Keycode.ESCAPE,
    "ENT": Keycode.ENTER,
    "ENTER": Keycode.ENTER,
    "TAB": Keycode.TAB,
    "W": Keycode.W,
    "A": Keycode.A,
    "S": Keycode.S,
    "D": Keycode.D,
}

mouse = Mouse(usb_hid.devices)
kbd = Keyboard(usb_hid.devices)
data = usb_cdc.data
data.timeout = 0


def ack():
    data.write(b"OK\n")


def do_move(dx, dy):
    while dx or dy:
        sx = max(-STEP, min(STEP, dx))
        sy = max(-STEP, min(STEP, dy))
        mouse.move(sx, sy)
        dx -= sx
        dy -= sy
        time.sleep(INTER_REPORT)


def do_key(name):
    code = KEYS.get(name.upper())
    if code is None:
        return
    kbd.press(code)
    time.sleep(KEY_HOLD)
    kbd.release_all()


def key_down(name):
    code = KEYS.get(name.upper())
    if code is not None:
        kbd.press(code)


def key_up(name):
    code = KEYS.get(name.upper())
    if code is not None:
        kbd.release(code)


def handle(line):
    parts = line.split()
    if not parts:
        return
    op = parts[0].upper()

    if op == "ID":
        data.write(b"PICO-HID 1.1\n")
    elif op == "M":
        if len(parts) != 3:
            return
        do_move(int(parts[1]), int(parts[2]))
    elif op == "C":
        mouse.click(Mouse.LEFT_BUTTON)
    elif op == "P":
        mouse.press(Mouse.LEFT_BUTTON)
        time.sleep(0.02)
        mouse.release(Mouse.LEFT_BUTTON)
    elif op == "K":
        if len(parts) != 2:
            return
        do_key(parts[1])
    elif op == "KD":
        if len(parts) != 2:
            return
        key_down(parts[1])
    elif op == "KU":
        if len(parts) != 2:
            return
        key_up(parts[1])
    elif op == "KA":
        kbd.release_all()


buf = ""

while True:
    chunk = data.read(256)
    if not chunk:
        continue

    for b in chunk:
        ch = chr(b)
        if ch == "\n":
            cmd = buf.strip()
            buf = ""
            if not cmd:
                continue
            if cmd.upper() == "HALT":
                mouse.release_all()
                kbd.release_all()
                ack()
                continue
            # apart antwoord, zonder extra OK-regel
            if cmd.upper() == "CAPS":
                data.write(b"CAPS: KD KU 1.1\n")
                continue
            try:
                handle(cmd)
            except Exception:
                mouse.release_all()
                kbd.release_all()
            ack()
        elif ch != "\r":
            buf += ch
            if len(buf) > MAX_LINE:
                buf = ""
                mouse.release_all()
                kbd.release_all()
                ack()
