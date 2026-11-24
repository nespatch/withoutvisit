# clip_bar.py — Mini bar next to the cursor after a copy.
# Lists actions. Does not know what any action does.

import ctypes
import os
import queue
import threading
import tkinter as tk

import core.actions as actions
import selection_watcher


def _track(name, props=None):
    try:
        import telemetry
        telemetry.send(name, props or {})
    except Exception:
        pass


class Host:
    """What an action is allowed to ask of the window thread."""

    def __init__(self, root):
        self.root = root

    def ask(self, title, note, fields):
        """Block until the user submits or cancels. Returns a dict, or None."""
        box = queue.Queue()
        selection_watcher.set_paused(True)

        def _open():
            win = tk.Toplevel(self.root)
            win.title(title)
            win.configure(bg="#202020")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            tk.Label(
                win, text=note, bg="#202020", fg="#C5C5C5",
                font=("Segoe UI Variable", 11), wraplength=360, justify="left",
            ).pack(anchor="w", padx=14, pady=(12, 4))
            entries = {}
            for field in fields:
                tk.Label(
                    win, text=field.get("label") or field["key"],
                    bg="#202020", fg="#FFFFFF", font=("Segoe UI Variable", 11),
                ).pack(anchor="w", padx=14, pady=(8, 0))
                entry = tk.Entry(
                    win, width=42, bg="#2B2B2B", fg="#FFFFFF", insertbackground="#FFFFFF",
                    relief="flat", font=("Segoe UI Variable", 12),
                    show="*" if field.get("secret") else "",
                )
                entry.pack(padx=14, pady=(4, 0), ipady=4)
                if field.get("value"):
                    entry.insert(0, field["value"])
                entries[field["key"]] = entry

            def _submit(event=None):
                box.put({key: widget.get() for key, widget in entries.items()})
                win.destroy()

            def _cancel(event=None):
                box.put(None)
                win.destroy()

            buttons = tk.Frame(win, bg="#202020")
            buttons.pack(fill="x", padx=14, pady=14)
            ok = tk.Button(
                buttons, text="OK", command=_submit,
                bg="#2B2B2B", fg="#FFFFFF", relief="flat", padx=14, pady=4,
            )
            ok.pack(side="right")
            tk.Button(
                buttons, text="Cancel", command=_cancel,
                bg="#202020", fg="#C5C5C5", relief="flat", padx=14, pady=4,
            ).pack(side="right", padx=(0, 8))
            win.bind("<Return>", _submit)
            win.bind("<Escape>", _cancel)
            win.protocol("WM_DELETE_WINDOW", _cancel)
            win.update_idletasks()
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            win.geometry(f"+{(sw - win.winfo_reqwidth()) // 2}+{(sh - win.winfo_reqheight()) // 2}")
            win.lift()
            win.focus_force()
            first = next(iter(entries.values()), None)
            if first is not None:
                first.focus_set()
            win.grab_set()

        try:
            self.root.after(0, _open)
            return box.get()
        finally:
            selection_watcher.set_paused(False)

    def notify(self, message):
        text = str(message or "").strip() or "Done."

        def _show():
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#202020")
            tk.Label(
                win, text=text, bg="#202020", fg="#FFFFFF",
                font=("Segoe UI Variable", 12), padx=14, pady=10, wraplength=320, justify="left",
            ).pack()
            win.update_idletasks()
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            win.geometry(f"+{sw - win.winfo_reqwidth() - 24}+{sh - win.winfo_reqheight() - 72}")
            win.after(2200, win.destroy)

        self.root.after(0, _show)


class ClipBar:
    def __init__(self, root):
        self.root = root
        self.host = Host(root)
        self.window = None
        self._payload = None
        self._actions = []
        self._rows = []
        self._selected = 0
        self._watch_active = False
        self._hook_cb = None
        self.composer = None
        self._composer_watch = False

    def show_composer(self):
        """Tweet-like line in the middle of the screen. Enter adds the text."""
        if self.composer is not None:
            self._dismiss_composer()
            return
        self._dismiss()
        selection_watcher.set_paused(True)

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-toolwindow", True)
        win.attributes("-topmost", True)
        win.configure(bg="#3C3C3C")

        outer = tk.Frame(win, bg="#3C3C3C", padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg="#202020")
        inner.pack(fill="both", expand=True)

        row = tk.Frame(inner, bg="#202020")
        row.pack(fill="both", expand=True)
        entry = tk.Entry(
            row, bg="#202020", fg="#FFFFFF", insertbackground="#FFFFFF",
            relief="flat", borderwidth=0, highlightthickness=0,
            font=("Segoe UI Variable", 16),
        )
        entry.pack(side="left", fill="both", expand=True, padx=(18, 8), pady=16)
        tk.Label(
            row, text="Enter", bg="#202020", fg="#5E5E5E",
            font=("Segoe UI Variable", 10),
        ).pack(side="right", padx=(0, 16))

        def _submit(event=None):
            text = entry.get().strip()
            left, top, right, bottom = _work_area_under_cursor()
            cx = (left + right) // 2
            cy = (top + bottom) // 2
            self._dismiss_composer()
            if text:
                self.show({"type": "text", "data": text}, cx, cy - 40, focus=True)
            return "break"

        entry.bind("<Return>", _submit)
        entry.bind("<Escape>", lambda e: self._dismiss_composer() or "break")
        win.bind("<Escape>", lambda e: self._dismiss_composer())
        win.protocol("WM_DELETE_WINDOW", self._dismiss_composer)

        win.update_idletasks()
        width = min(max(win.winfo_reqwidth(), 520), 640)
        height = max(win.winfo_reqheight(), 64)
        left, top, right, bottom = _work_area_under_cursor()
        self._cx = left + max((right - left - width) // 2, 8)
        self._cy = top + max((bottom - top - height) // 2, 8)
        win.geometry(f"{width}x{height}+{self._cx}+{self._cy + 8}")
        win.attributes("-alpha", 0.0)
        _round_window_corners(win)
        self.composer = win
        self._fade_composer(win)
        _focus_window(win, entry)
        _track("wv_composer_shown")
        self.root.after(200, self._arm_composer_click)

    def show(self, payload, x, y, focus=False):
        self._dismiss_composer()
        visible = []
        for action in actions.scan_actions():
            try:
                ok = action["accepts"](payload)
            except Exception:
                ok = False
            if ok:
                visible.append(action)
        if not visible:
            return
        self._dismiss()
        self._payload = payload
        self._actions = visible
        self._rows = []
        self._selected = 0

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-toolwindow", True)
        win.attributes("-topmost", True)
        win.configure(bg="#3C3C3C")

        outer = tk.Frame(win, bg="#3C3C3C", padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg="#202020")
        inner.pack(fill="both", expand=True)

        header = tk.Label(
            inner, text=_preview(payload), bg="#202020", fg="#9A9A9A",
            font=("Segoe UI Variable", 11), anchor="w", padx=10, pady=3,
        )
        header.pack(fill="x")

        for idx, action in enumerate(visible):
            row = tk.Frame(inner, bg="#202020", cursor="hand2")
            row.pack(fill="x")
            label = tk.Label(
                row, text=action["title"], bg="#202020", fg="#FFFFFF",
                font=("Segoe UI Variable", 11), anchor="w", cursor="hand2",
                padx=10, pady=3,
            )
            label.pack(fill="x")
            self._rows.append(row)
            for widget in (row, label):
                widget.bind("<Button-1>", lambda e, a=action: self._run(a))
                widget.bind("<Enter>", lambda e, i=idx: self._select(i))
            if idx < len(visible) - 1:
                tk.Frame(inner, bg="#2E2E2E", height=1).pack(fill="x", padx=12)

        self._highlight()
        win.bind("<Up>", self._prev)
        win.bind("<Down>", self._next)
        win.bind("<Return>", self._run_selected)
        win.bind("<Escape>", lambda e: self._dismiss())

        win.update_idletasks()
        width = max(win.winfo_reqwidth(), 180)
        height = win.winfo_reqheight()
        screen_w = self.root.winfo_screenwidth()
        px = min(max(x + 12, 8), screen_w - width - 8)
        py = y + 16
        if py + height > self.root.winfo_screenheight() - 8:
            py = max(y - height - 12, 8)
        self._px = px
        self._py = py
        win.geometry(f"{width}x{height}+{px}+{py + 6}")
        win.attributes("-alpha", 0.0)
        _round_window_corners(win)
        self.window = win
        self._highlight()
        self._fade_in(win)
        if focus:
            _focus_window(win)
        _track("wv_bar_shown", {
            "kind": "image" if (payload or {}).get("type") in ("image", "file") else "text",
            "has_source": bool((payload or {}).get("source_name") or (payload or {}).get("source_url")),
        })
        self.root.after(200, self._arm_click_away)

    def _fade_in(self, win, step=0):
        if self.window is not win:
            return
        total = 10
        p = _ease_out_cubic(step / total)
        try:
            win.attributes("-alpha", p)
            ny = self._py + int(6 * (1 - p))
            win.geometry(f"+{self._px}+{ny}")
            if step == 0:
                _round_window_corners(win)
        except Exception:
            return
        if step < total:
            self.root.after(16, lambda: self._fade_in(win, step + 1))

    def _fade_composer(self, win, step=0):
        if self.composer is not win:
            return
        total = 10
        p = _ease_out_cubic(step / total)
        try:
            win.attributes("-alpha", p)
            win.geometry(f"+{self._cx}+{self._cy + int(8 * (1 - p))}")
            if step == 0:
                _round_window_corners(win)
        except Exception:
            return
        if step < total:
            self.root.after(16, lambda: self._fade_composer(win, step + 1))

    def _fade_out(self, win, alpha):
        alpha = max(alpha - 0.1, 0.0)
        try:
            win.attributes("-alpha", alpha)
        except Exception:
            try:
                win.destroy()
            except Exception:
                pass
            return
        if alpha > 0.0:
            self.root.after(16, lambda: self._fade_out(win, alpha))
        else:
            try:
                win.destroy()
            except Exception:
                pass

    def _run(self, action):
        payload = self._payload
        _track("wv_action_clicked", {
            "action": action.get("name") or "",
            "kind": "image" if (payload or {}).get("type") in ("image", "file") else "text",
        })
        self._dismiss()
        threading.Thread(target=lambda: action["run"](payload, self.host), daemon=True).start()

    def _run_selected(self, event=None):
        if self._actions:
            self._run(self._actions[self._selected])

    def _select(self, idx):
        self._selected = idx
        self._highlight()

    def _next(self, event=None):
        if self._rows:
            self._selected = min(self._selected + 1, len(self._rows) - 1)
            self._highlight()

    def _prev(self, event=None):
        if self._rows:
            self._selected = max(self._selected - 1, 0)
            self._highlight()

    def _highlight(self):
        for i, row in enumerate(self._rows):
            bg = "#2E2E2E" if i == self._selected else "#202020"
            try:
                row.config(bg=bg)
            except Exception:
                pass
            for child in row.winfo_children():
                try:
                    child.config(bg=bg)
                except Exception:
                    pass

    def _arm_click_away(self):
        if not self.window:
            return
        self._watch_active = True
        self._button_was_down = False
        self._poll_click_away()

    def _poll_click_away(self):
        if not self._watch_active or not self.window:
            return
        down = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        down = down or bool(ctypes.windll.user32.GetAsyncKeyState(0x02) & 0x8000)
        if down and not self._button_was_down:
            point = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            try:
                left = self.window.winfo_rootx()
                top = self.window.winfo_rooty()
                right = left + self.window.winfo_width()
                bottom = top + self.window.winfo_height()
            except Exception:
                return
            if not (left <= point.x <= right and top <= point.y <= bottom):
                self._dismiss()
                return
        self._button_was_down = down
        self.root.after(80, self._poll_click_away)

    def _arm_composer_click(self):
        if not self.composer:
            return
        self._composer_watch = True
        self._composer_down = False
        self._poll_composer_click()

    def _poll_composer_click(self):
        if not self._composer_watch or not self.composer:
            return
        down = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        down = down or bool(ctypes.windll.user32.GetAsyncKeyState(0x02) & 0x8000)
        if down and not self._composer_down:
            point = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            try:
                left = self.composer.winfo_rootx()
                top = self.composer.winfo_rooty()
                right = left + self.composer.winfo_width()
                bottom = top + self.composer.winfo_height()
            except Exception:
                return
            if not (left <= point.x <= right and top <= point.y <= bottom):
                self._dismiss_composer()
                return
        self._composer_down = down
        self.root.after(80, self._poll_composer_click)

    def _dismiss_composer(self):
        self._composer_watch = False
        win = self.composer
        self.composer = None
        if win is None:
            return "break"
        selection_watcher.set_paused(False)
        try:
            alpha = float(win.attributes("-alpha"))
        except Exception:
            alpha = 1.0
        self._fade_out(win, alpha)
        return "break"

    def _dismiss(self):
        self._watch_active = False
        win = self.window
        self.window = None
        if win is not None:
            try:
                alpha = float(win.attributes("-alpha"))
            except Exception:
                alpha = 1.0
            self._fade_out(win, alpha)


def _focus_window(window, widget=None):
    """Pull a borderless window to the front so typing reaches it."""
    try:
        window.lift()
        window.focus_force()
        user32 = ctypes.windll.user32
        hwnd = user32.GetAncestor(window.winfo_id(), 2)
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        tid = ctypes.windll.kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(fg_tid, tid, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(fg_tid, tid, False)
        user32.keybd_event(0x12, 0, 2, 0)
    except Exception:
        pass
    if widget is not None:
        try:
            widget.focus_set()
        except Exception:
            pass


def _work_area_under_cursor():
    """Work rectangle of the monitor under the pointer: left, top, right, bottom."""
    user32 = ctypes.windll.user32
    point = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    try:
        user32.MonitorFromPoint.argtypes = [ctypes.wintypes.POINT, ctypes.c_uint]
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.GetMonitorInfoW.restype = ctypes.c_int

        class _RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long),
            ]

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", _RECT),
                ("rcWork", _RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        monitor = user32.MonitorFromPoint(point, 2)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            area = info.rcWork
            return area.left, area.top, area.right, area.bottom
    except Exception:
        pass
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _ease_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _round_window_corners(window):
    """Native Windows 11 rounded corners, same call as the main mini bar."""
    try:
        hwnd = ctypes.windll.user32.GetAncestor(window.winfo_id(), 2)
        pref = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref),
        )
    except Exception:
        pass


def _preview(payload):
    kind = (payload or {}).get("type")
    if kind == "image":
        return "Image"
    data = str((payload or {}).get("data") or "").strip()
    if kind == "file":
        data = os.path.basename(data)
    data = " ".join(data.split())
    if len(data) > 28:
        data = data[:25] + "..."
    return data or "Copied"
