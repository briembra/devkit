"""PC-kant van de Pico bridge.

Draait volledig buiten het spel om: leest geen game-geheugen, opent geen
game-handle, installeert geen hooks. Het enige wat dit doet is pixels
lezen (mss) en ASCII over een COM-poort schrijven.

De muisinput komt van de RP2040 zelf, dus de host ziet HID-rapporten van
echte USB-hardware.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import serial
from serial.tools import list_ports

user32 = ctypes.windll.user32

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
except Exception:
    pass

CIRCUITPY_VID = 0x239A
FORTNITE_CLASS = "UnrealWindow"
MAGIC = b"PICO-HID"


class PicoLost(RuntimeError):
    """De COM-poort is weg (Pico losgekoppeld of gereset)."""


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def find_window(class_name: str = FORTNITE_CLASS):
    hwnd = user32.FindWindowW(class_name, None)
    return hwnd or None


def client_rect(hwnd):
    """(x, y, w, h) van de client-area in schermcoordinaten, of None."""
    r = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    w = r.right - r.left
    h = r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    return (pt.x, pt.y, w, h)


def is_foreground(hwnd) -> bool:
    return user32.GetForegroundWindow() == hwnd


def focus(hwnd, tries: int = 3) -> bool:
    """Naar voorgrond zonder synthetische toetsaanslag."""
    for _ in range(tries):
        if is_foreground(hwnd):
            return True

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE

        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None)
        tg_thread = user32.GetWindowThreadProcessId(hwnd, None)

        attached = False
        if fg_thread and tg_thread and fg_thread != tg_thread:
            attached = bool(user32.AttachThreadInput(fg_thread, tg_thread, True))

        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

        if attached:
            user32.AttachThreadInput(fg_thread, tg_thread, False)

        end = time.time() + 0.4
        while time.time() < end:
            if is_foreground(hwnd):
                return True
            time.sleep(0.02)

    return is_foreground(hwnd)


def cursor_pos():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


class PicoMouse:
    def __init__(self, ser: serial.Serial, ident: str = ""):
        self.ser = ser
        self.ident = ident
        self.caps = ""

    def read_caps(self) -> str:
        """Welke commando's het geflashte board kent ("CAPS: KD KU 1.1")."""
        try:
            self.ser.reset_input_buffer()  # geen oude ID/OK-regel meelezen
            self.ser.write(b"CAPS\n")
            self.ser.flush()
            end = time.time() + 0.4
            buf = b""
            while time.time() < end:
                chunk = self.ser.read(128)
                if not chunk:
                    time.sleep(0.01)
                    continue
                buf += chunk
                if b"\n" in buf:
                    break
            return buf.decode(errors="ignore").strip()
        except Exception:
            # oude firmware antwoordt "OK"; leeg/onbekend is ook goed
            return ""

    def key_is_down(self, name: str) -> bool:
        """Leest bij Windows of de HID-toets echt ingedrukt is."""
        vk = {"SP": 0x20, "ESC": 0x1B, "ENT": 0x0D, "TAB": 0x09,
              "W": 0x57, "A": 0x41, "S": 0x53, "D": 0x44}.get(name.upper())
        if vk is None:
            return False
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def _cmd(self, line: str):
        try:
            self.ser.write((line + "\n").encode())
            self.ser.flush()
            self.ser.readline()  # wacht op "OK"
        except (serial.SerialException, OSError) as e:
            # kabel eruit / Pico gereset: de handle is niet meer geldig
            raise PicoLost(str(e)) from e

    def move_rel(self, dx: int, dy: int):
        dx, dy = int(dx), int(dy)
        if dx or dy:
            self._cmd(f"M {dx} {dy}")

    def click(self):
        self._cmd("C")

    def press_key(self, name: str):
        """Toets via de Pico. name: SP, ESC, ENT, TAB, W, A, S, D."""
        self._cmd(f"K {name.upper()}")

    def key_down(self, name: str):
        self._cmd(f"KD {name.upper()}")

    def key_up(self, name: str):
        self._cmd(f"KU {name.upper()}")

    def click_at(self, x: int, y: int, settle: float = 0.03,
                 tolerance: int = 2, tries: int = 4):
        """Beweeg naar (x, y) en klik.

        Relatieve HID-bewegingen worden door Windows-versnelling soms
        versterkt, dus na elke beweging wordt de cursorpositie herlezen en
        de restfout opnieuw gestuurd. Zo landt de klik op de knop i.p.v.
        er net naast.
        """
        for _ in range(tries):
            cx, cy = cursor_pos()
            dx, dy = x - cx, y - cy
            if abs(dx) <= tolerance and abs(dy) <= tolerance:
                break
            self.move_rel(dx, dy)
            time.sleep(settle)
        self.click()

    def halt(self):
        try:
            self._cmd("HALT")
        except Exception:
            pass

    def close(self):
        self.halt()
        try:
            self.ser.close()
        except Exception:
            pass


def _probe(dev: str, wait: float = 1.5):
    try:
        s = serial.Serial(dev, 115200, timeout=0.2, write_timeout=1.0)
    except Exception:
        return None
    try:
        time.sleep(0.25)
        s.reset_input_buffer()
        s.write(b"ID\n")
        s.flush()
        end = time.time() + wait
        buf = b""
        while time.time() < end:
            chunk = s.read(64)
            if not chunk:
                continue
            buf += chunk
            if MAGIC in buf:
                return s, buf.decode(errors="ignore").strip()
    except Exception:
        pass
    try:
        s.close()
    except Exception:
        pass
    return None


def _connect(hit) -> PicoMouse:
    mouse = PicoMouse(*hit)
    mouse.caps = mouse.read_caps()
    return mouse


def open_mouse(port: str | None = None) -> PicoMouse:
    """Zoekt het data-kanaal. De REPL-console antwoordt niet met PICO-HID."""
    if port:
        hit = _probe(port)
        if not hit:
            raise RuntimeError(f"{port}: geen PICO-HID antwoord")
        return _connect(hit)

    ports = list(list_ports.comports())
    ordered = [p.device for p in ports if p.vid == CIRCUITPY_VID]
    ordered += [p.device for p in ports if p.device not in ordered]

    for dev in ordered:
        hit = _probe(dev)
        if hit:
            return _connect(hit)

    raise RuntimeError(
        "Geen PICO-HID kanaal gevonden. Check: CircuitPython geflasht, "
        "boot.py met usb_cdc data=True, en of de REPL niet in raw mode staat."
    )
