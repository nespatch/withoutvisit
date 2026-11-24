# updater.py — silent auto-update through the Inno Setup installer.
#
# Flow (only when running as the installed .exe):
#   1) The app detects a newer GitHub release.
#   2) It downloads the withoutvisit_Setup.exe asset in the background.
#   3) When the user is idle, it launches
#      withoutvisit_Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /AUTOUPDATE
#      and exits immediately. The installer waits until this process is gone
#      (mutex "withoutvisit"), replaces the app folder, and starts withoutvisit.exe.
#
# User data lives in %LOCALAPPDATA%\withoutvisit and is outside the install
# folder, so an update never touches it.

import os
import sys
import ssl
import tempfile
import subprocess
import ctypes
from urllib import request

SETUP_ASSET = "withoutvisit_Setup.exe"
APP_MUTEX = "withoutvisit"

# Held for the life of the process. The installer waits until it disappears
# before replacing files, so a silent update does not copy over a running exe.
_mutex_handle = None

# Windows process-creation flags: run the installer detached so it survives
# after the main app exits.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def is_frozen() -> bool:
    """True only when running as the packaged .exe (not from source)."""
    return bool(getattr(sys, "frozen", False))


def hold_app_mutex() -> None:
    """Create the named mutex the installer looks for. Never close the handle."""
    global _mutex_handle
    if _mutex_handle:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = kernel32.CreateMutexW(None, False, APP_MUTEX)


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input. Returns 0.0 on failure."""
    try:
        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return max(0.0, millis / 1000.0)
    except Exception:
        return 0.0


def find_setup_url(assets):
    """Pick the full Inno installer from a GitHub release's assets list.

    Matches only withoutvisit_Setup.exe. Any other setup file, including a
    website stub with a similar name, must not be chosen.
    """
    for a in assets or []:
        if (a.get("name") or "") == SETUP_ASSET:
            return a.get("browser_download_url")
    return None


def updates_dir() -> str:
    """Per-user folder where downloaded installers are staged."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = os.path.join(base, "withoutvisit", "updates")
    os.makedirs(d, exist_ok=True)
    return d


def download(url: str, dest: str) -> str:
    """Download url to dest atomically (writes .part, then renames)."""
    req = request.Request(url, headers={"User-Agent": "withoutvisit"})
    tmp = dest + ".part"
    with request.urlopen(req, timeout=60, context=_ssl_ctx()) as resp, open(tmp, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, dest)
    return dest


def launch_installer(setup_path: str) -> None:
    """Start the installer silently in auto-update mode, detached from us."""
    subprocess.Popen(
        [setup_path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/AUTOUPDATE"],
        close_fds=True,
        creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
    )
