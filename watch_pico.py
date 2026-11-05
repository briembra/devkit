"""Achtergrondwacht: opent de launcher zodra de Pico of Arduino aankomt.

Draait zonder console (pythonw). Pollt elke 2s naar USB-apparaten met
VID 0x239A (Raspberry Pi / CircuitPython) of een CH340 (VID:PID
0x1A86:0x7523, de Arduino). Zodra er een verschijnt, start de launcher
in een eigen consolevenster.

    pythonw watch_pico.py
    DEVKIT.exe --watch
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time

from installer import ensure_installed, installed_exe
from paths import base_dir, frozen

HERE = base_dir()
LOG = os.path.join(HERE, "watch.log")
POLL = 2.0
MUTEX = "Local\\devkit_pico_watch"
LAUNCHER_TITLE = "DEVKIT  -  Fortnite auto-queue"

PICO_VID = 0x239A
ARDUINO_IDS = {(0x1A86, 0x7523)}  # CH340 (ATmega328P-bordjes)


def log(msg: str):
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def trigger_present() -> bool:
    try:
        from serial.tools import list_ports
    except Exception:
        return False
    try:
        for p in list_ports.comports():
            if p.vid == PICO_VID:
                return True
            if (p.vid, p.pid) in ARDUINO_IDS:
                return True
    except Exception:
        pass
    return False


def bring_to_front():
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, LAUNCHER_TITLE)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)       # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


def launch_ui():
    if bring_to_front():
        log("launcher stond al open, naar voorgrond")
        return
    if frozen():
        # Staat DEVKIT al op deze pc? Open die vaste kopie. Nog niet?
        # Zet hem er dan eerst neer (eenmalig) en open die.
        exe = installed_exe()
        if not exe or not os.path.isfile(exe):
            exe = ensure_installed()
        cmd = [exe or sys.executable]
    else:
        exe = sys.executable
        if exe.lower().endswith("pythonw.exe"):
            exe = exe[:-len("pythonw.exe")] + "python.exe"
        cmd = [exe, os.path.join(HERE, "launcher.py")]

    # De wachter draait onzichtbaar (pythonw / opstart-minimalized). Zonder
    # deze STARTUPINFO erft de nieuwe console die verborgen staat en zie je
    # dus niets. SW_SHOWNORMAL = 1.
    si = subprocess.STARTUPINFO()
    si.dwFlags = subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 1

    subprocess.Popen(
        cmd, cwd=HERE, startupinfo=si,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    log("launcher gestart")

    # En hem daarna echt naar voren halen / uit de taakbalk restoren.
    # Eerst even wachten: Windows past de startup-showstate van het kind pas
    # toe nadat het venster bestaat, dus een enkele ShowWindow is te vroeg.
    user32 = ctypes.windll.user32
    time.sleep(1.5)
    for _ in range(24):
        hwnd = user32.FindWindowW(None, LAUNCHER_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)       # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            if not user32.IsIconic(hwnd):
                log("launcher naar voorgrond")
                return
        time.sleep(0.25)


def main():
    # maar één wachter tegelijk (startup + handmatig starten)
    kernel32 = ctypes.windll.kernel32
    _mutex = kernel32.CreateMutexW(None, False, MUTEX)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        log("wacht draait al")
        return

    log("wacht gestart")
    # Al aangesloten bij het starten = geen "inpluggen": niet meteen openen.
    seen = trigger_present()
    while True:
        now = trigger_present()
        if now and not seen:
            # even wachten tot Windows de COM-poorten heeft opgesomd
            time.sleep(2.0)
            launch_ui()
        seen = now
        time.sleep(POLL)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"crash: {e!r}")
