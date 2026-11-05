"""DEVKIT vastzetten op deze pc -- alleen wat er nog niet staat.

De portable exe controleert bij het starten:
  - staat hij al in %LOCALAPPDATA%\\DEVKIT?  -> niets kopieren
  - anders                                   -> zichzelf daar neerzetten
  - staat de wachter al in de opstartmap?    -> niets wijzigen
  - anders                                   -> wachter toevoegen en starten
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys

import paths

WATCH_MUTEX = "Local\\devkit_pico_watch"


def startup_file():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup", "DEVKIT watch.cmd")


def installed_exe():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    return os.path.join(local, "DEVKIT", "DEVKIT.exe")


def write_startup(path, command):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("@echo off\r\n")
        fh.write(f'start "" {command}\r\n')


def ensure_installed(verbose: bool = False):
    """Kopieer de exe en zet de wachter in opstart; sla over wat bestaat.

    Geeft het pad van de vaste exe terug, of None als dit geen exe-build is.
    """
    if not paths.frozen():
        return None
    target = installed_exe()
    if target is None:
        return None
    try:
        same = (os.path.normcase(os.path.abspath(sys.executable))
                == os.path.normcase(os.path.abspath(target)))
        if not same and not os.path.isfile(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(sys.executable, target)
            if verbose:
                print(f"  DEVKIT.exe geinstalleerd  {target}")
        exe = target if os.path.isfile(target) else sys.executable
        sf = startup_file()
        if sf and not os.path.isfile(sf):
            write_startup(sf, f'"{exe}" --watch')
            if verbose:
                print("  wachter in opstart gezet")
        return exe
    except OSError as e:
        if verbose:
            print(f"  installeren mislukt: {e}")
        return target if os.path.isfile(target) else None


def watcher_running() -> bool:
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.CreateMutexW(None, False, WATCH_MUTEX)
        exists = k32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        if handle:
            k32.CloseHandle(handle)
        return exists
    except Exception:
        return False


def start_watcher(exe) -> bool:
    """Start de wachter los van dit proces; een bestaande telt ook."""
    if watcher_running():
        return True
    env = dict(os.environ)
    # eigen uitpakmap: de wachter moet blijven draaien als de launcher sluit
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        subprocess.Popen(
            [exe, "--watch"],
            cwd=os.path.dirname(os.path.abspath(exe)), env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except OSError:
        return False
