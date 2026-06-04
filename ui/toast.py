"""
ui/toast.py
Premium stacking toast notification system — rebuilt from scratch.

Design:
  - Slides up from bottom-right
  - Color-coded 3px left border
  - Open + Folder action buttons when file_path given
  - Stacks multiple toasts with 8px gap
  - Auto-dismiss after 4 seconds
  - WDA_EXCLUDEFROMCAPTURE — invisible in recordings
  - Thread-safe: call ToastManager.show() from any thread
"""
from __future__ import annotations
import tkinter as tk
import ctypes
import os
import threading
import logging
from typing import Optional, List, Callable

from utils.animations import Animator, interpolate_color

log = logging.getLogger(__name__)

WDA_EXCLUDEFROMCAPTURE = 0x00000011

# ── Design tokens ─────────────────────────────────────────────────────────────
BG      = "#0F0F18"
SURFACE = "#16161F"
BORDER  = "#1E1E2E"
TP      = "#E8E8F0"
TS      = "#6B6B8A"
TD      = "#3A3A55"

KIND_COLORS = {
    "success": "#3DDC84",
    "error":   "#E5383B",
    "info":    "#4A9EFF",
    "warning": "#FFB800",
}
KIND_ICONS = {
    "success": "✓",
    "error":   "✕",
    "info":    "i",
    "warning": "!",
}

TOAST_W = 300
TOAST_MARGIN = 16
TOAST_GAP    = 8


# ══════════════════════════════════════════════════════════════════════════════
# Toast Manager
# ══════════════════════════════════════════════════════════════════════════════

class ToastManager:
    """
    Manages a stack of Toast notifications.

    Thread-safe. Call show() from any thread.

    Args:
        root: Tkinter root window (used for .after() scheduling).
    """

    def __init__(self, root: tk.Tk):
        self.root   = root
        self._stack: List[Toast] = []
        self._lock  = threading.Lock()

    def show(
        self,
        title:     str,
        subtitle:  str = "",
        kind:      str = "info",
        file_path: Optional[str] = None,
        duration:  int = 4000,
    ) -> None:
        """
        Show a toast notification. Safe to call from any thread.

        Args:
            title:     Bold title line.
            subtitle:  Secondary smaller line.
            kind:      "success" | "error" | "info" | "warning"
            file_path: If given, shows Open + Folder buttons.
            duration:  Auto-dismiss delay in ms. 0 = no auto-dismiss.
        """
        self.root.after(0, lambda: self._create(title, subtitle, kind, file_path, duration))

    def _create(self, title, subtitle, kind, file_path, duration):
        toast = Toast(
            root=self.root,
            title=title,
            subtitle=subtitle,
            kind=kind,
            file_path=file_path,
            duration=duration,
            on_remove=self._remove,
        )
        with self._lock:
            self._stack.append(toast)
        self._restack()
        toast.appear()

    def _remove(self, toast: "Toast"):
        with self._lock:
            if toast in self._stack:
                self._stack.remove(toast)
        self._restack()

    def _restack(self):
        """Recalculate target Y for all visible toasts."""
        sh = self.root.winfo_screenheight()
        y_cursor = sh - TOAST_MARGIN
        with self._lock:
            stack = list(reversed(self._stack))
        for toast in stack:
            h = toast.height
            y_cursor -= h
            toast.move_to(sh - TOAST_W - TOAST_MARGIN, y_cursor)
            y_cursor -= TOAST_GAP


# ══════════════════════════════════════════════════════════════════════════════
# Toast
# ══════════════════════════════════════════════════════════════════════════════

class Toast:
    """A single toast notification window."""

    def __init__(
        self,
        root:       tk.Tk,
        title:      str,
        subtitle:   str,
        kind:       str,
        file_path:  Optional[str],
        duration:   int,
        on_remove:  Callable,
    ):
        self.root      = root
        self.file_path = file_path
        self._on_remove = on_remove
        self._dismissed = False
        self.kind_color = KIND_COLORS.get(kind, KIND_COLORS["info"])

        # Estimate height before building
        has_sub   = bool(subtitle)
        has_btns  = bool(file_path and os.path.exists(file_path))
        self.height = 56 + (16 if has_sub else 0) + (32 if has_btns else 0)

        sh = root.winfo_screenheight()
        self._x = sh - TOAST_W - TOAST_MARGIN  # will be corrected in move_to
        self._y = sh + self.height              # starts off-screen

        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0.0)
        self._win.geometry(f"{TOAST_W}x{self.height}+{self._x}+{self._y}")
        self._win.configure(bg=BG)

        self._exclude_from_capture()
        self._build(title, subtitle, kind, has_btns)
        self.animator = Animator(root)

        if duration > 0:
            root.after(duration, self.dismiss)

    def _exclude_from_capture(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self._win.winfo_id())
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    def _build(self, title: str, subtitle: str, kind: str, has_btns: bool):
        W = TOAST_W
        color = self.kind_color

        # Left accent border
        border_frame = tk.Frame(self._win, bg=color, width=3)
        border_frame.pack(side="left", fill="y")

        # Content
        content = tk.Frame(self._win, bg=BG)
        content.pack(side="left", fill="both", expand=True, padx=(10, 12), pady=10)

        # Header row
        hdr = tk.Frame(content, bg=BG)
        hdr.pack(fill="x")

        icon_lbl = tk.Label(hdr, text=KIND_ICONS.get(kind, "i"),
                             bg=BG, fg=color,
                             font=("Segoe UI", 10, "bold"))
        icon_lbl.pack(side="left")

        tk.Label(hdr, text=f"  {title}",
                 bg=BG, fg=TP,
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        # Dismiss X
        x_lbl = tk.Label(hdr, text="✕", bg=BG, fg=TD,
                          font=("Segoe UI", 9), cursor="hand2")
        x_lbl.pack(side="right")
        x_lbl.bind("<Enter>", lambda _: x_lbl.configure(fg="#E5383B"))
        x_lbl.bind("<Leave>", lambda _: x_lbl.configure(fg=TD))
        x_lbl.bind("<Button-1>", lambda _: self.dismiss())

        # Subtitle
        if subtitle:
            tk.Label(content, text=subtitle, bg=BG, fg=TS,
                     font=("Segoe UI", 9),
                     wraplength=TOAST_W - 40,
                     anchor="w", justify="left").pack(fill="x", pady=(2, 0))

        # Action buttons
        if has_btns:
            btn_row = tk.Frame(content, bg=BG)
            btn_row.pack(fill="x", pady=(8, 0))
            self._make_btn(btn_row, "Open",
                           lambda: os.startfile(self.file_path))
            self._make_btn(btn_row, "Folder",
                           lambda: os.startfile(os.path.dirname(self.file_path)))

        # Outer border
        self._win.configure(highlightbackground=BORDER,
                             highlightthickness=1,
                             highlightcolor=BORDER)

    def _make_btn(self, parent: tk.Frame, text: str, cmd: Callable) -> tk.Label:
        btn = tk.Label(parent, text=text, bg=SURFACE, fg=TP,
                       font=("Segoe UI", 8), padx=10, pady=3, cursor="hand2")
        btn.pack(side="left", padx=(0, 6))
        btn.bind("<Enter>", lambda _: btn.configure(bg="#20202E"))
        btn.bind("<Leave>", lambda _: btn.configure(bg=SURFACE))
        btn.bind("<Button-1>", lambda _: cmd())
        return btn

    def appear(self):
        """Slide up from below screen edge."""
        sh  = self.root.winfo_screenheight()
        tx  = self._x
        ty  = self._y
        end_y = ty  # _y is already the target, set by move_to before appear()

        start_y = sh + self.height + 10

        self.animator.animate(
            f"toast_{id(self)}_in",
            start=float(start_y), end=float(end_y),
            duration_ms=320, easing="ease_out_cubic",
            on_update=lambda y: self._set_pos(tx, int(y)),
        )
        self.animator.animate(
            f"toast_{id(self)}_fade_in",
            start=0.0, end=0.97,
            duration_ms=200, easing="ease_out_cubic",
            on_update=lambda a: self._set_alpha(a),
        )

    def dismiss(self):
        """Slide down off screen and destroy."""
        if self._dismissed:
            return
        self._dismissed = True
        self._on_remove(self)

        sh    = self.root.winfo_screenheight()
        cur_y = self._y
        end_y = sh + self.height + 10

        self.animator.animate(
            f"toast_{id(self)}_out",
            start=float(cur_y), end=float(end_y),
            duration_ms=260, easing="ease_in_out_sine",
            on_update=lambda y: self._set_pos(self._x, int(y)),
            on_done=self._destroy,
        )
        self.animator.animate(
            f"toast_{id(self)}_fade_out",
            start=0.97, end=0.0,
            duration_ms=220, easing="ease_in_out_sine",
            on_update=lambda a: self._set_alpha(a),
        )

    def move_to(self, x: int, y: int):
        """Update target position (called by manager during restack)."""
        self._x = x
        self._y = y
        if not self._dismissed:
            try:
                self._win.geometry(f"{TOAST_W}x{self.height}+{x}+{y}")
            except Exception:
                pass

    def _set_pos(self, x: int, y: int):
        try:
            self._win.geometry(f"{TOAST_W}x{self.height}+{x}+{y}")
        except Exception:
            pass

    def _set_alpha(self, a: float):
        try:
            self._win.attributes("-alpha", max(0.0, min(1.0, a)))
        except Exception:
            pass

    def _destroy(self):
        try:
            self._win.destroy()
        except Exception:
            pass
