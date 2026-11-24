# Send copied text to the person's chat with the app bot.
# The bot token stays on the worker. This module only holds a device code.

import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
import webbrowser

TITLE = "Send to Telegram"


def _track(name, props=None):
    try:
        import telemetry
        telemetry.send(name, props or {})
    except Exception:
        pass


def _kind(payload):
    if (payload or {}).get("type") == "image" or _image_file(payload):
        return "image"
    return "text"

_DIR = os.path.dirname(os.path.abspath(__file__))
_DEVICE = os.path.join(_DIR, "device.json")
_LOCK = threading.Lock()
_WORKER = os.environ.get("CLIP_BOT_URL") or "https://clip-bot.nurlannapo.workers.dev"
_WAIT_SECONDS = 90


_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def _image_file(payload):
    if not payload or payload.get("type") != "file":
        return False
    path = str(payload.get("data") or "")
    return os.path.isfile(path) and path.lower().endswith(_IMAGE_EXT)


def accepts(payload):
    if not payload:
        return False
    if payload.get("type") == "image":
        return isinstance(payload.get("data"), (bytes, bytearray)) and len(payload.get("data")) > 0
    if _image_file(payload):
        return True
    if payload.get("type") != "text":
        return False
    return bool(str(payload.get("data") or "").strip())


def _load_code():
    try:
        with open(_DEVICE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("code") or "")


def _save_code(code):
    with open(_DEVICE, "w", encoding="utf-8") as handle:
        json.dump({"code": code}, handle)


def _forget_code():
    try:
        os.remove(_DEVICE)
    except Exception:
        pass


def _request(method, path, body=None, content_type=None):
    data = None
    headers = {"user-agent": "Mozilla/5.0"}
    if isinstance(body, (bytes, bytearray)):
        data = bytes(body)
        headers["content-type"] = content_type or "application/octet-stream"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    request = urllib.request.Request(
        _WORKER.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            if "1010" in raw:
                parsed = {"error": "Cloudflare blocked the app (1010)."}
            else:
                parsed = {"error": raw[:200] or "Request failed"}
        parsed["_status"] = exc.code
        return parsed
    except Exception as exc:
        return {"error": str(exc)[:200] or "Could not reach the bot"}


def _linked(code):
    result = _request("GET", "/link?code=" + code)
    return bool(result.get("linked"))


def _open_bot(username, code):
    link = "tg://resolve?domain=" + username + "&start=" + code
    try:
        os.startfile(link)
    except Exception:
        webbrowser.open("https://t.me/" + username + "?start=" + code)


def _connect(host):
    bot = _request("GET", "/bot")
    username = str(bot.get("username") or "").strip()
    if not username:
        host.notify(bot.get("error") or "The Telegram bot is not set up yet.")
        _track("wv_failed", {"error": str(bot.get("error") or "bot is not set up")[:200]})
        return ""
    code = secrets.token_hex(16)
    _open_bot(username, code)
    _track("wv_connect_opened")
    host.notify("Press Start in Telegram.")
    deadline = time.time() + _WAIT_SECONDS
    while time.time() < deadline:
        if _linked(code):
            _save_code(code)
            _track("wv_connected")
            return code
        time.sleep(1)
    host.notify("Telegram was not confirmed.")
    _track("wv_failed", {"error": "Telegram was not confirmed."})
    return ""


def _source_line(payload):
    name = str((payload or {}).get("source_name") or "").strip()
    link = str((payload or {}).get("source_url") or "").strip()
    parts = []
    if name:
        parts.append("source: " + name)
    if link:
        parts.append("link: " + link)
    return "\n".join(parts)


def _with_source(text, payload):
    line = _source_line(payload)
    if not line:
        return text
    return text.rstrip() + "\n\n" + line


def _caption(payload):
    return _source_line(payload)


def _photo_bytes(payload):
    if payload.get("type") == "image":
        return bytes(payload.get("data") or b""), "image.png"
    path = str(payload.get("data") or "")
    with open(path, "rb") as handle:
        return handle.read(), os.path.basename(path) or "image.png"


def _send_photo(code, payload):
    raw, filename = _photo_bytes(payload)
    if not raw:
        return "Missing image"
    if len(raw) > 10 * 1024 * 1024:
        return "Image is too big."
    boundary = "withoutvisit" + secrets.token_hex(8)
    caption = _caption(payload)
    parts = [
        "--" + boundary + "\r\n" + 'Content-Disposition: form-data; name="code"\r\n\r\n' + code + "\r\n",
        "--" + boundary + "\r\n" + 'Content-Disposition: form-data; name="caption"\r\n\r\n' + caption + "\r\n",
    ]
    head = (
        "--" + boundary + "\r\n"
        + 'Content-Disposition: form-data; name="photo"; filename="' + filename + '"\r\n'
        + "Content-Type: image/png\r\n\r\n"
    ).encode("utf-8")
    body = "".join(parts).encode("utf-8") + head + raw + ("\r\n--" + boundary + "--\r\n").encode("utf-8")
    result = _request(
        "POST",
        "/send",
        body=body,
        content_type="multipart/form-data; boundary=" + boundary,
    )
    if result.get("ok"):
        return ""
    return result.get("error") or "Could not send."


def _send(code, text):
    result = _request("POST", "/send", {"code": code, "text": text})
    if result.get("ok"):
        return ""
    return result.get("error") or "Could not send."


def run(payload, host):
    if not _LOCK.acquire(blocking=False):
        host.notify("Already sending.")
        return
    try:
        image = payload.get("type") == "image" or _image_file(payload)
        text = "" if image else _with_source(str(payload.get("data") or ""), payload)
        code = _load_code()
        if not code or not _linked(code):
            _forget_code()
            code = _connect(host)
        if not code:
            return
        error = _send_photo(code, payload) if image else _send(code, text)
        if error == "Not linked":
            _forget_code()
            code = _connect(host)
            if not code:
                return
            error = _send_photo(code, payload) if image else _send(code, text)
        if error:
            host.notify(error)
            _track("wv_failed", {"kind": _kind(payload), "error": str(error)[:200]})
            return
        _track("wv_sent", {"kind": _kind(payload)})
        host.notify("Sent to Telegram.")
    except Exception as exc:
        message = str(exc)[:200] or "Could not send."
        host.notify(message)
        _track("wv_failed", {"kind": _kind(payload), "error": message})
    finally:
        _LOCK.release()
