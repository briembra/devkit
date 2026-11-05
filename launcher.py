"""DEVKIT launcher -- het gezicht van de auto-queue.

Opent een eigen console met status, menu en live output. Start de bot als
subprocess en kleurt de regels onderweg zodat je in een oogopslag ziet wat
hij doet.

    python launcher.py
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time

from installer import (ensure_installed, start_watcher, startup_file,
                       write_startup)
from paths import base_dir, firmware_dir as bundled_firmware, frozen

HERE = base_dir()

# In de portable exe is DEVKIT.exe zichzelf; als script starten we de .py
# bestanden met de huidige interpreter.
def bot_cmd(args):
    if frozen():
        return [sys.executable, "--bot", *args]
    return [sys.executable, "-u", os.path.join(HERE, "main.py"), *args]


def calibrate_cmd():
    if frozen():
        return [sys.executable, "--calibrate-leave"]
    return [sys.executable, os.path.join(HERE, "calibrate_leave.py")]

# ---------------------------------------------------------------- terminal

R = "\x1b[0m"
B = "\x1b[1m"
D = "\x1b[2m"
CYAN = "\x1b[96m"
BLUE = "\x1b[94m"
GREEN = "\x1b[92m"
YELLOW = "\x1b[93m"
MAGENTA = "\x1b[95m"
RED = "\x1b[91m"
WHITE = "\x1b[97m"
GREY = "\x1b[90m"


def setup_console():
    k32 = ctypes.windll.kernel32
    k32.SetConsoleOutputCP(65001)
    k32.SetConsoleCP(65001)
    k32.SetConsoleTitleW("DEVKIT  -  Fortnite auto-queue")
    handle = k32.GetStdHandle(-11)
    mode = ctypes.c_uint32()
    if k32.GetConsoleMode(handle, ctypes.byref(mode)):
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        k32.SetConsoleMode(handle, mode.value | 0x0004)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.system("mode con: cols=110 lines=44")  # groot genoeg voor de banner
    os.system("")  # forceert ANSI-ondersteuning in oudere consoles


BANNER = r"""
  ██████╗ ███████╗██╗   ██╗██╗  ██╗██╗████████╗
  ██╔══██╗██╔════╝██║   ██║██║ ██╔╝██║╚══██╔══╝
  ██║  ██║█████╗  ██║   ██║█████╔╝ ██║   ██║
  ██║  ██║██╔══╝  ╚██╗ ██╔╝██╔═██╗ ██║   ██║
  ██████╔╝███████╗ ╚████╔╝ ██║  ██╗██║   ██║
  ╚═════╝ ╚══════╝  ╚═══╝  ╚═╝  ╚═╝╚═╝   ╚═╝
"""


# ------------------------------------------------------------------ status

def pico_ports():
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    return [p.device for p in list_ports.comports() if p.vid == 0x239A]


def arduino_ports():
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    return [p.device for p in list_ports.comports()
            if (p.vid, p.pid) == (0x1A86, 0x7523)]


def fortnite_hwnd():
    try:
        return ctypes.windll.user32.FindWindowW("UnrealWindow", None)
    except Exception:
        return 0


def dot(ok: bool) -> str:
    return f"{GREEN}●{R}" if ok else f"{RED}●{R}"


def show_status():
    ports = pico_ports()
    ard = arduino_ports()
    hwnd = fortnite_hwnd()
    print(f"  {GREY}┌─────────────────────────────────────────────┐{R}")
    print(f"  {GREY}│{R}  Pico HID    {dot(bool(ports))} "
          f"{WHITE}{(', '.join(ports) if ports else 'niet gevonden')}{R}")
    print(f"  {GREY}│{R}  Arduino     {dot(bool(ard))} "
          f"{WHITE}{(', '.join(ard) if ard else 'niet gevonden')}{R}"
          f"  {GREY}start alleen de launcher{R}")
    print(f"  {GREY}│{R}  Fortnite    {dot(bool(hwnd))} "
          f"{WHITE}{'venster gevonden' if hwnd else 'niet gevonden'}{R}")
    print(f"  {GREY}│{R}  Modus       {CYAN}Squad · Fill{R}  "
          f"{GREY}(in-game zo instellen){R}")
    print(f"  {GREY}└─────────────────────────────────────────────┘{R}")
    return bool(ports), bool(hwnd)


# ------------------------------------------------------------------ output

def paint(line: str) -> str:
    low = line.lower()
    if "traceback" in low or "error" in low or "[!]" in low:
        return f"{RED}{line}{R}"
    if "return to lobby" in low:
        return f"{MAGENTA}{line}{R}"
    if "leave" in low:
        return f"{MAGENTA}{line}{R}"
    if "play " in low or "sprong" in low or "bus begint" in low:
        return f"{YELLOW}{line}{R}"
    if "status phase" in low:
        return f"{GREY}{line}{R}"
    if "kan fortnite niet" in low:
        return f"{RED}{line}{R}"
    if line.startswith("[i]"):
        return f"{CYAN}{line}{R}"
    return line


def kill_with_me(proc):
    """Windows-job: sluit het launcher-venster (ook met X) -> bot gaat mee.

    Zonder dit blijft de bot doorlopen wanneer de console hard wordt
    gesloten, want hij heeft geen eigen venster en dus geen Ctrl-close.
    """
    try:
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount",
                "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                    wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
                job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return None
        ph = k32.OpenProcess(0x001F0FFF, False, proc.pid)
        if not ph:
            k32.CloseHandle(job)
            return None
        ok = k32.AssignProcessToJobObject(job, ph)
        k32.CloseHandle(ph)
        if not ok:
            k32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def run_bot(args):
    print()
    print(f"  {D}──────────────────────────────────────────────────────{R}")
    print(f"  {B}{GREEN}LIVE{R}  {GREY}Ctrl+C stopt en gaat terug naar het menu{R}")
    print(f"  {D}──────────────────────────────────────────────────────{R}")
    print()

    proc = subprocess.Popen(
        bot_cmd(args), cwd=HERE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    job = kill_with_me(proc)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(paint(line.rstrip("\n")) + "\n")
            sys.stdout.flush()
    except KeyboardInterrupt:
        print(f"\n  {YELLOW}stoppen...{R}")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if job:
            ctypes.windll.kernel32.CloseHandle(job)
    print(f"  {GREY}bot gestopt (exit {proc.returncode}){R}")


def pico_test():
    print()
    try:
        sys.path.insert(0, HERE)
        from link import open_mouse
        m = open_mouse()
    except Exception as e:
        print(f"  {RED}Pico niet bereikbaar: {e}{R}")
        return
    try:
        print(f"  {CYAN}{m.ident}{R} gevonden, muis wiebelt...")
        m.move_rel(120, 0)
        time.sleep(0.15)
        m.move_rel(-120, 0)
        time.sleep(0.15)
        m.press_key("SP")
        print(f"  {GREEN}klik + spatie gestuurd{R}  "
              f"{GREY}(cursor moet bewogen zijn){R}")

        m.key_down("W")
        time.sleep(0.4)
        down = m.key_is_down("W")
        time.sleep(0.8)
        m.key_up("W")
        time.sleep(0.2)
        up = not m.key_is_down("W")
        if down and up:
            print(f"  {GREEN}W 1.2s vastgehouden en losgelaten{R}  "
                  f"{GREY}(je zag 'w's in dit venster){R}")
        elif not down:
            print(f"  {RED}Pico houdt W niet vast{R}  "
                  f"{GREY}-> [7] firmware bijwerken{R}")
        else:
            print(f"  {RED}W bleef hangen na loslaten{R}")
        # de getypte w's uit de console-buffer halen
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getwch()
    finally:
        m.close()


def calibrate_leave():
    print()
    try:
        subprocess.run(calibrate_cmd(), cwd=HERE, check=False)
    except Exception as e:
        print(f"  {RED}kon calibratie niet starten: {e}{R}")


def circuitpy_drive():
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        try:
            if os.path.isfile(os.path.join(root, "boot_out.txt")):
                return root
        except OSError:
            pass
    return None


def update_firmware():
    """Kopieert de meegeleverde boot.py/code.py naar de CIRCUITPY-schijf."""
    src_dir = bundled_firmware()
    drive = circuitpy_drive()
    if drive is None:
        print(f"  {RED}CIRCUITPY-schijf niet gevonden.{R}")
        print(f"  {GREY}Plug de Pico in en wacht tot de schijf verschijnt.{R}")
        return
    print(f"  {CYAN}Pico gevonden op {drive}{R}")
    for name in ("boot.py", "code.py"):
        src = os.path.join(src_dir, name)
        dst = os.path.join(drive, name)
        if not os.path.isfile(src):
            print(f"  {RED}{name} ontbreekt in DEVKIT{R}")
            continue
        try:
            shutil.copyfile(src, dst)
            print(f"  {GREEN}{name} bijgewerkt{R}")
        except OSError as e:
            print(f"  {RED}kon {name} niet schrijven: {e}{R}")
    print(f"  {GREY}De Pico herstart vanzelf; wacht tot COM terug is.{R}")


def show_log():
    path = os.path.join(HERE, "run.log")
    if not os.path.isfile(path):
        print(f"  {GREY}nog geen run.log{R}")
        return
    print()
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()[-40:]
    for line in lines:
        print("  " + paint(line.rstrip("\n")))


# -------------------------------------------------------------- opstarten

def install_startup():
    """Zet DEVKIT vast op deze pc; sla over wat er al staat."""
    if frozen():
        exe = ensure_installed(verbose=True)
        if exe is None:
            print(f"  {RED}installeren mislukt{R}")
            return
        start_watcher(exe)
        print(f"  {GREEN}klaar{R}  {GREY}voortaan opent de launcher zodra "
              f"je de Pico of Arduino inplugt{R}")
        return

    # dev-modus: pythonw + watch_pico.py in de opstartmap
    path = startup_file()
    if not path:
        print(f"  {RED}APPDATA niet gevonden{R}")
        return
    if os.path.isfile(path):
        print(f"  {GREY}staat er al -- niets gewijzigd{R}")
        return
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-len("python.exe")] + "pythonw.exe"
    try:
        write_startup(path, f'"{exe}" "{os.path.join(HERE, "watch_pico.py")}"')
        print(f"  {GREEN}wachter in opstart gezet{R}")
    except OSError as e:
        print(f"  {RED}kon opstart niet instellen: {e}{R}")


# -------------------------------------------------------------------- menu

def key() -> str:
    import msvcrt
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        msvcrt.getwch()
        return ""
    return ch


MENU = f"""
  {B}{WHITE}WAT GAAN WE DOEN{R}

    {B}{GREEN}[1]{R}  Start auto-queue        {GREY}lobby -> potje -> lobby{R}
    {B}{CYAN}[2]{R}  Dry-run                 {GREY}kijkt mee, klikt niet{R}
    {B}{YELLOW}[3]{R}  Pico test               {GREY}muis + W vasthouden{R}
    {B}{BLUE}[4]{R}  Laatste log             {GREY}40 regels{R}
    {B}{MAGENTA}[5]{R}  Leave-knop instellen    {GREY}eenmalig, in een potje{R}
    {B}{WHITE}[6]{R}  Installeer op deze pc   {GREY}eenmalig · daarna inpluggen{R}
    {B}{GREEN}[7]{R}  Pico firmware bijwerken {GREY}eenmalig / na update{R}
    {B}{GREY}[0]{R}  Sluiten

  {GREY}enter of [1] = meteen starten{R}
"""


def main() -> int:
    setup_console()
    autostart = "--start" in sys.argv[1:]
    while True:
        os.system("cls")
        print(f"{CYAN}{B}{BANNER}{R}")
        print(f"  {GREY}Fortnite AFK auto-queue · RP2040 HID · squad fill{R}")
        print()
        pico_ok, game_ok = show_status()

        if autostart:
            autostart = False
            if pico_ok and game_ok:
                run_bot([])
                print(f"\n  {GREY}enter = sluiten{R}")
                key()
                return 0

        print(MENU)

        try:
            choice = key()
        except KeyboardInterrupt:
            return 0

        if choice == "0" or choice.lower() == "q":
            return 0
        if choice == "1" or choice in ("\r", "\n", "s", "S"):
            if not pico_ok:
                print(f"\n  {RED}Geen Pico gevonden. Plug hem in.{R}")
                time.sleep(2)
                continue
            if not game_ok:
                print(f"\n  {RED}Fortnite staat niet open.{R}")
                time.sleep(2)
                continue
            run_bot([])
            print(f"\n  {GREY}enter = terug naar menu{R}")
            key()
        elif choice == "2":
            if not game_ok:
                print(f"\n  {RED}Fortnite staat niet open.{R}")
                time.sleep(2)
                continue
            run_bot(["--dry-run"])
            print(f"\n  {GREY}enter = terug naar menu{R}")
            key()
        elif choice == "3":
            pico_test()
            print(f"\n  {GREY}enter = terug naar menu{R}")
            key()
        elif choice == "4":
            show_log()
            print(f"\n  {GREY}enter = terug naar menu{R}")
            key()
        elif choice == "5":
            calibrate_leave()
            print(f"\n  {GREY}enter = terug naar menu{R}")
            key()
        elif choice == "6":
            print()
            install_startup()
            print(f"\n  {GREY}enter = terug naar menu{R}")
            key()
        elif choice == "7":
            print()
            update_firmware()
            print(f"\n  {GREY}enter = terug naar menu{R}")
            key()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
