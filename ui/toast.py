"""
ui/toast.py
Lightweight always-on-top toast notification system.
Invisible to screen capture via WDA_EXCLUDEFROMCAPTURE.
Supports stacking multiple notifications.
"""

import tkinter as tk
import threading
import ctypes
import logging
from utils.animations import Animator, ease_out_cubic, ease_out_back

log = logging.getLogger(__name__)

WDA_EXCLUDEFROMCAPTURE = 0x00000011

# Palette
_BG       = "#111118"
_BORDER   = "#2A2A3A"
_TEXT     = "#F0F0F5"
_SUBTEXT  = "#8888AA"
_GREEN    = "#27AE60"
_RED      = "#C0392B"
_BLUE     = "#3498DB"
_YELLOW   = "#F39C12"

COLORS = {
    "success": _GREEN,
    "error":   _RED,
    "info":    _BLUE,
    "warning": _YELLOW,
}

_TOAST_HEIGHT  = 72
_TOAST_WIDTH   = 340
_MARGIN        = 14      # pixels from screen edge
_STACK_GAP     = 8       # gap between stacked toasts
_AUTO_DISMISS  = 3500    # ms

# Shared state for stacking
_active_toasts: list = []
_lock = threading.Lock()


def _screen_size():
    root = tk.Tk()
    root.withdraw()
    w, h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.destroy()
    return w, h


class Toast:
    """
    A single toast notification window.

    Args:
        title:    Bold headline text.
        subtitle: Smaller detail text below.
        kind:     Visual accent type: 'success' | 'error' | 'info' | 'warning'.
        duration: Auto-dismiss delay in milliseconds.
    """

    def __init__(self, title: str, subtitle: str = "", kind: str = "info",
                 duration: int = _AUTO_DISMISS):
        self._title    = title
        self._subtitle = subtitle
        self._kind     = kind
        self._duration = duration
        self._win      = None
        self._after_id = None
        self._dismissed = False

    def show(self, y_offset: int = 0) -> None:
        """
        Display the toast at the correct stacked position.

        Args:
            y_offset: Additional upward offset in pixels for stacking.
        """
        sw, sh = _screen_size()
        x = sw - _TOAST_WIDTH - _MARGIN
        y_final = sh - _MARGIN - _TOAST_HEIGHT - y_offset
        y_start = sh + _TOAST_HEIGHT  # off-screen below

        self._win = tk.Toplevel()
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.geometry(f"{_TOAST_WIDTH}x{_TOAST_HEIGHT}+{x}+{y_start}")
        self._win.configure(bg=_BG)
        self._hide_from_capture()
        self._build_ui()

        # Slide up
        def _set_y(t):
            import math
            yy = int(y_start + (y_final - y_start) * ease_out_cubic(t))
            self._win.geometry(f"{_TOAST_WIDTH}x{_TOAST_HEIGHT}+{x}+{yy}")

        anim = Animator(self._win, 280, _set_y)
        anim.start()

        # Auto-dismiss
        self._after_id = self._win.after(self._duration, self.dismiss)

    def dismiss(self) -> None:
        """Slide the toast down and destroy it."""
        if self._dismissed or not self._win:
            return
        self._dismissed = True

        if self._after_id:
            try:
                self._win.after_cancel(self._after_id)
            except Exception:
                pass

        sw, sh = _screen_size()
        x     = sw - _TOAST_WIDTH - _MARGIN
        y_now = self._win.winfo_y()
        y_end = sh + _TOAST_HEIGHT

        def _slide_down(t):
            yy = int(y_now + (y_end - y_now) * ease_out_cubic(t))
            if self._win:
                self._win.geometry(f"{_TOAST_WIDTH}x{_TOAST_HEIGHT}+{x}+{yy}")

        def _destroy():
            with _lock:
                if self in _active_toasts:
                    _active_toasts.remove(self)
            if self._win:
                self._win.destroy()
                self._win = None

        anim = Animator(self._win, 250, _slide_down, on_complete=_destroy)
        anim.start()

    def _hide_from_capture(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self._win.winfo_id())
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    def _build_ui(self):
        """Draw the toast UI: colored left bar, icon, title, subtitle."""
        accent = COLORS.get(self._kind, _BLUE)

        # Left accent bar
        bar = tk.Frame(self._win, bg=accent, width=4)
        bar.pack(side="left", fill="y")

        # Content area
        body = tk.Frame(self._win, bg=_BG, padx=12, pady=10)
        body.pack(side="left", fill="both", expand=True)

        title_lbl = tk.Label(body, text=self._title,
                             bg=_BG, fg=_TEXT,
                             font=("Segoe UI Variable", 11, "bold"),
                             anchor="w")
        title_lbl.pack(fill="x")

        if self._subtitle:
            sub_lbl = tk.Label(body, text=self._subtitle,
                               bg=_BG, fg=_SUBTEXT,
                               font=("Segoe UI", 9),
                               anchor="w", wraplength=270)
            sub_lbl.pack(fill="x")

        # Click to dismiss
        self._win.bind("<Button-1>", lambda _: self.dismiss())

    @property
    def height(self) -> int:
        """Height of this toast including gap."""
        return _TOAST_HEIGHT + _STACK_GAP


def notify(title: str, subtitle: str = "", kind: str = "info",
           duration: int = _AUTO_DISMISS) -> None:
    """
    Show a toast notification from any thread.

    Args:
        title:    Bold headline.
        subtitle: Detail text.
        kind:     'success' | 'error' | 'info' | 'warning'
        duration: Auto-dismiss delay in milliseconds.
    """
    def _show():
        toast = Toast(title, subtitle, kind, duration)
        with _lock:
            y_offset = sum(t.height for t in _active_toasts)
            _active_toasts.append(toast)
        toast.show(y_offset=y_offset)

    # Must run on main thread — schedule via global root if available
    try:
        import customtkinter as ctk
        ctk.get_default_root().after(0, _show)
    except Exception:
        try:
            _show()
        except Exception as e:
            log.error("Toast error: %s", e)
