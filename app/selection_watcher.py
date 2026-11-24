# selection_watcher.py — Shows the mini bar when anything is copied.
# Polls the clipboard so it catches both Ctrl+C and right-click → Copy.
# The callback receives the clipboard payload {"type", "data"}, plus x, y, hwnd.

import threading
import time
import ctypes
import source_detect

_on_selection_cb = None
_running = False
_paused = False
# _last_path = None  # dedup disabled (caused re-copy of same file to be ignored)

# Only show the mini-bar for video links, not arbitrary URLs.
_VIDEO_DOMAINS = (
    "youtube.com", "youtu.be", "vimeo.com", "tiktok.com",
    "twitter.com", "x.com", "instagram.com", "facebook.com", "fb.watch",
    "twitch.tv", "dailymotion.com", "reddit.com",
)


def _is_video_url(url):
    try:
        host = url.split("//")[-1].split("/")[0].split("?")[0].lower()
        if host.startswith("www."):
            host = host[4:]
        return any(host == d or host.endswith("." + d) for d in _VIDEO_DOMAINS)
    except Exception:
        return False


def _read_clipboard_input():
    """Return the clipboard payload, or None when the clipboard is empty."""
    from core.input import get_input
    try:
        result = get_input()
    except Exception:
        return None
    if not result or not result.get("data"):
        return None
    # Old filter: only a copied file, or a video link. The bar now opens for any copy.
    # if result.get("type") == "file":
    #     return result.get("data")
    # if result.get("type") == "text":
    #     data = (result.get("data") or "").strip()
    #     if data.lower().startswith(("http://", "https://")) and _is_video_url(data):
    #         return data
    # return None
    return result


def _poll():
    # global _last_path  # dedup disabled
    try:
        last_seq = ctypes.windll.user32.GetClipboardSequenceNumber()
    except Exception:
        last_seq = 0
    while _running:
        try:
            seq = ctypes.windll.user32.GetClipboardSequenceNumber()
        except Exception:
            seq = 0
        if seq != last_seq:
            last_seq = seq
            if _paused:
                continue
            payload = _read_clipboard_input()
            if payload:
                try:
                    pt = ctypes.wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    cx, cy = pt.x, pt.y
                    hwnd = source_detect.get_source_window()
                except Exception:
                    cx, cy, hwnd = 0, 0, 0
                if isinstance(payload, dict) and hwnd:
                    try:
                        info = source_detect.get_source_info(hwnd)
                    except Exception:
                        info = {}
                    if info.get("source_name"):
                        payload["source_name"] = info["source_name"]
                    if info.get("source_url"):
                        payload["source_url"] = info["source_url"]
                if _on_selection_cb:
                    _on_selection_cb(payload, cx, cy, hwnd)
        time.sleep(0.2)


def start(on_selection, ignore_hwnd=None):
    """Start clipboard watcher. on_selection(payload, x, y, hwnd) on each copy."""
    global _on_selection_cb, _running
    _on_selection_cb = on_selection
    _running = True
    threading.Thread(target=_poll, daemon=True).start()


def set_paused(value):
    """Ignore copies while an action is asking the user something."""
    global _paused
    _paused = bool(value)


def stop():
    global _running
    _running = False
