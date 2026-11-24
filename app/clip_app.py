# clip_app.py — Clipboard utility. Copy something, pick an action.
# The full skill bar stays in main.main and is not started.

import ctypes
import os
import queue
import threading
import time
import tkinter as tk

import selection_watcher
import updater
from clip_bar import ClipBar
from config import APP_VERSION, HOTKEY

_RELEASES = "https://api.github.com/repos/newJenius/withoutvisit/releases/latest"
_RELEASES_PAGE = "https://github.com/newJenius/withoutvisit/releases/latest"


def _tray_image():
    """The tray icon is packaging/icon.ico, not a picture drawn in code."""
    from PIL import Image, ImageDraw
    try:
        from tray import _load_icon
        image = _load_icon().convert("RGBA")
        if max(image.size) != 64:
            image = image.resize((64, 64), Image.Resampling.LANCZOS)
        return image
    except Exception:
        image = Image.new("RGB", (64, 64), "#2536EB")
        ImageDraw.Draw(image).rounded_rectangle((8, 8, 56, 56), radius=12, fill="#FFFFFF")
        return image


def _tray(root):
    import pystray

    image = _tray_image()

    def _quit(icon, item):
        selection_watcher.stop()
        icon.stop()
        root.after(0, root.quit)

    icon = pystray.Icon(
        "withoutvisit",
        image,
        "withoutvisit",
        pystray.Menu(pystray.MenuItem("Quit", _quit)),
    )
    icon.run()


def _own_window(hwnd):
    if not hwnd:
        return False
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
    return pid.value == os.getpid()


def _track(name, props=None):
    try:
        import telemetry
        telemetry.send(name, props or {})
    except Exception:
        pass


def _version_ge(a, b):
    def parts(value):
        try:
            return tuple(int(x) for x in str(value).strip().lstrip("v").split("."))
        except Exception:
            return (0,)
    left, right = parts(a), parts(b)
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return left >= right


def _start_updates(root, bar):
    """Same updater as the full app: download the installer, apply when idle."""
    pending = {"path": None, "version": None, "since": None, "fallback_shown": False}

    def _fallback(version):
        if pending["fallback_shown"]:
            return
        pending["fallback_shown"] = True
        try:
            import tray
            tray.show_update_popup(version, _RELEASES_PAGE, root)
        except Exception:
            print(f"[withoutvisit] Update {version} is available.")

    def _apply():
        try:
            ready = pending["path"] and os.path.exists(pending["path"])
            busy = bool(getattr(bar, "window", None) or getattr(bar, "composer", None))
            if ready and not busy and updater.idle_seconds() >= 120:
                print(f"[withoutvisit] Applying update {pending['version']}.")
                _track("wv_update_applying", {"version": pending["version"]})
                updater.launch_installer(pending["path"])
                try:
                    selection_watcher.stop()
                except Exception:
                    pass
                # Hard-exit so the installer can replace this exe. root.quit()
                # only ends the Tk loop and can leave the process locking files.
                os._exit(0)
            since = pending["since"]
            if since and (time.time() - since) >= 6 * 60 * 60:
                _fallback(pending["version"])
        except Exception:
            pass
        root.after(60000, _apply)

    def _download(latest, assets):
        def _run():
            try:
                url = updater.find_setup_url(assets)
                if not url:
                    root.after(0, lambda: _fallback(latest))
                    return
                dest = os.path.join(updater.updates_dir(), f"withoutvisit_Setup_{latest}.exe")
                if not os.path.exists(dest):
                    updater.download(url, dest)
                pending["path"] = dest
                pending["version"] = latest
                pending["since"] = time.time()
                _track("wv_update_downloaded", {"version": latest})
                print(f"[withoutvisit] Update {latest} downloaded. It will apply when idle.")
            except Exception as exc:
                print(f"[withoutvisit] Update download failed: {exc}")
                pending["version"] = latest
                root.after(0, lambda: _fallback(latest))

        threading.Thread(target=_run, daemon=True).start()
        root.after(60000, _apply)

    def _check():
        try:
            from urllib import request
            import json
            import ssl
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ctx = ssl.create_default_context()
            req = request.Request(_RELEASES, headers={"User-Agent": "withoutvisit"})
            data = json.loads(request.urlopen(req, timeout=5, context=ctx).read())
            latest = str(data.get("tag_name") or "").lstrip("v")
            current = str(APP_VERSION).lstrip("v")
            newer = latest and _version_ge(latest, current) and not _version_ge(current, latest)
            if not newer:
                return
            _track("wv_update_available", {"version": latest})
            if updater.is_frozen():
                root.after(0, lambda: _download(latest, data.get("assets") or []))
            else:
                root.after(0, lambda: _fallback(latest))
        except Exception:
            pass

    def _schedule():
        threading.Thread(target=_check, daemon=True).start()
        root.after(5 * 60 * 60 * 1000, _schedule)

    root.after(15000, _schedule)


def _vk_down(vk):
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _chord_release(state, held, other):
    """True once when a modifier chord is released and no other key joined it."""
    if held:
        if not state["down"]:
            state["down"] = True
            state["other"] = False
        if other:
            state["other"] = True
        return False
    if not state["down"]:
        return False
    fire = not state["other"]
    state["down"] = False
    state["other"] = False
    return fire


def _watch_hotkey(root, on_fire):
    """Ctrl+Alt alone opens the composer. Ctrl+Alt plus another key does not."""
    parts = {p.strip().lower() for p in str(HOTKEY).split("+") if p.strip()}
    want_ctrl = bool(parts & {"ctrl", "control"})
    want_alt = "alt" in parts
    want_shift = "shift" in parts
    state = {"down": False, "other": False}
    skip = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}

    def _tick():
        ctrl = _vk_down(0x11) or _vk_down(0xA2) or _vk_down(0xA3)
        alt = _vk_down(0x12) or _vk_down(0xA4) or _vk_down(0xA5)
        shift = _vk_down(0x10) or _vk_down(0xA0) or _vk_down(0xA1)
        held = (ctrl if want_ctrl else not ctrl)
        held = held and (alt if want_alt else not alt)
        held = held and (shift if want_shift else True)
        other = (shift and not want_shift) or any(
            _vk_down(vk) for vk in range(1, 256) if vk not in skip
        )
        if _chord_release(state, held, other):
            on_fire()
        root.after(40, _tick)

    root.after(40, _tick)


def main_clip():
    updater.hold_app_mutex()
    root = tk.Tk()
    root.withdraw()
    bar = ClipBar(root)
    copied = queue.Queue()

    def _on_copy(payload, x, y, hwnd):
        if _own_window(hwnd):
            return
        copied.put((payload, x, y))

    def _poll():
        try:
            while True:
                payload, x, y = copied.get_nowait()
                bar.show(payload, x, y)
        except queue.Empty:
            pass
        root.after(150, _poll)

    selection_watcher.start(_on_copy)
    root.after(150, _poll)
    _watch_hotkey(root, bar.show_composer)
    _start_updates(root, bar)
    threading.Thread(target=_tray, args=(root,), daemon=True).start()
    _track("wv_started")
    print("[withoutvisit] Copy something, or press Ctrl+Alt to write. Quit from the tray icon.")

    import signal
    signal.signal(signal.SIGINT, lambda *_: root.quit())
    try:
        root.mainloop()
    finally:
        selection_watcher.stop()
        print("[withoutvisit] Stopped.")
