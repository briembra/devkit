"""Eén ingang voor zowel `python devkit.py` als de portable DEVKIT.exe.

    DEVKIT.exe                      launcher
    DEVKIT.exe --bot [args]         de auto-queue zelf (stdout = pipe)
    DEVKIT.exe --watch              achtergrondwacht op Pico/Arduino
    DEVKIT.exe --calibrate-leave    LEAVE MATCH-knop instellen
"""

from __future__ import annotations

import ctypes
import sys


def hide_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def main() -> int:
    argv = sys.argv[1:]

    if "--watch" in argv:
        # De wachter hoort onzichtbaar te draaien; als console-app zou de
        # exe anders een zwart venster openlaten.
        hide_console()
        import installer
        import paths
        if paths.frozen():
            installer.ensure_installed()  # vanaf usb gestart? vastzetten
        import watch_pico
        watch_pico.main()
        return 0

    if "--bot" in argv:
        # De launcher leest stdout via een pipe; line-buffering zodat elke
        # regel meteen doorkomt (in een frozen build bestaat -u niet).
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                                   line_buffering=True)
            sys.stderr.reconfigure(encoding="utf-8", errors="replace",
                                   line_buffering=True)
        except Exception:
            pass
        import main as bot
        return bot.main([a for a in argv if a != "--bot"])

    if "--calibrate-leave" in argv:
        import calibrate_leave
        return calibrate_leave.main(
            [a for a in argv if a != "--calibrate-leave"])

    # Gewone start: kijk eerst of DEVKIT al op deze pc staat. Zo nee,
    # zet hij zichzelf vast en start de wachter; daarna opent de launcher.
    import installer
    import paths
    if paths.frozen():
        exe = installer.ensure_installed()
        if exe:
            installer.start_watcher(exe)

    import launcher
    return launcher.main()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
