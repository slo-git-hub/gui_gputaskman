"""Start gtm-gui with Windows: one value under the user's own Run key (HKCU, no admin needed).

The installer writes the same value name (and removes it on uninstall), so the tray menu toggle and
the installer's "Start with Windows" task agree on one setting.
"""

from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "GPU Task Manager"


def supported() -> bool:
    return sys.platform == "win32"


def command() -> str:
    """What Windows runs at logon: this executable, starting hidden in the tray."""
    if getattr(sys, "frozen", False):  # PyInstaller build: gtm-gui.exe itself
        return f'"{sys.executable}" --tray'
    # From source: pythonw.exe (no console window) next to the running interpreter, when there is one.
    folder, name = os.path.split(sys.executable)
    pythonw = os.path.join(folder, "pythonw.exe")
    exe = pythonw if name.lower() == "python.exe" and os.path.isfile(pythonw) else sys.executable
    return f'"{exe}" -m gputaskman.gui --tray'


def _read() -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, VALUE)[0]
    except FileNotFoundError:
        return None


def _write(value: str) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, value)


def _delete() -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE)
    except FileNotFoundError:
        pass


def is_enabled() -> bool:
    return supported() and _read() is not None


def set_enabled(enabled: bool) -> None:
    if not supported():
        raise OSError("Start with Windows is only available on Windows")
    if enabled:
        _write(command())
    else:
        _delete()
