# core/actions.py — Action scanner.
#
# An action is a folder under actions/ with action.py.
# The bar lists whatever this scanner returns. It does not know what an
# action does. Contract:
#
#   TITLE = "Send somewhere"
#   def accepts(payload) -> bool   # optional; missing means always
#   def run(payload, host)         # payload is {"type", "data"} from the clipboard
#
# host.ask(title, fields) -> dict | None
# host.notify(message)

import importlib.util
import os
import sys

from config import BASE_DIR


def _actions_root():
    """Installed builds read actions from the app folder so an update can
    replace action.py. device.json next to it is not in the installer, so
    Inno leaves it in place. Source runs keep using the project tree.
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return BASE_DIR


ACTIONS_DIR = os.path.join(_actions_root(), "actions")


def _load(name, filepath):
    try:
        spec = importlib.util.spec_from_file_location(f"actions.{name}", filepath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        print(f"[withoutvisit] Failed to load action {name}: {e}")
        return None


def scan_actions():
    """Return action dicts in folder order: title, accepts, run."""
    if not os.path.isdir(ACTIONS_DIR):
        return []
    found = []
    for name in sorted(os.listdir(ACTIONS_DIR)):
        path = os.path.join(ACTIONS_DIR, name, "action.py")
        if not os.path.isfile(path):
            continue
        module = _load(name, path)
        if module is None or not callable(getattr(module, "run", None)):
            continue
        title = getattr(module, "TITLE", None) or name
        accepts = getattr(module, "accepts", None)
        if not callable(accepts):
            accepts = lambda payload: True
        found.append({
            "name": name,
            "title": str(title),
            "accepts": accepts,
            "run": module.run,
        })
    return found
