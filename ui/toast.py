"""
ui/toast.py
Premium stacking toast notification system.

Features:
  - Slides up from bottom-right corner
  - Color-coded left border (green/blue/red)
  - Action buttons: Open file + Open folder
  - Auto-dismiss after configurable duration
  - Stacks multiple toasts with 8px gap
  - Invisible to screen capture (WDA_EXCLUDEFROMCAPTURE)
  - Thread-safe: safe to call notify() from any thread
"""
from __future__ import annotations
import tkinter as tk
import ctypes
import os
import logging
import threading
from typing import Optional

from utils.animations import Animator, ease_out_cubic

log = logging.getLogger(__name__)

WDA_EXCLUDEFROMCAPTURE = 0x00000011

# ── Palette ────────────────────────────────────────────────────────────────────
BG        = "#13131E"
TEXT_P    = "#F0F0F5"
TEXT_S    = "#9999BB"
BTN_BG    = "#1E1E2E"
BTN_HOVER = "#2A2A3E"

BORDER_SUCCESS = "#27AE60"
BORDER_INFO    = "#3498DB"
BORDER_ERROR   = "#E74C3C"
BORDER_WARNING = "#F39C12"

# ── State ──────────────────────────────────────────────────────────────────────
_lock    = threading.Lock()
_toasts: list["_Toast"] = []
_root_ref = None         # set by first toast; reused for scheduling


# ══════════════════════════════════════════════════════════════════════════════

def notify(
    title:     str,
    message:   str = "",
    kind:      str = "info",
    file_path: Optional[str] = None,
    duration:  int  = 4000,
) -> None:
    """
    Show a toast notification.

    Thread-safe. Can be called from any thread.

    Args:
        title:     Bold title line.
        message:   Secondary message line.
        kind:      "success" | "info" | "error" | "warning"
        file_path: If set, shows Open + Folder action buttons.
        duration:  Milliseconds before auto-dismiss. 0 = no auto-dismiss.
    """
    def _create():
        _Toast(title=title, message=message, kind=kind,
               file_path=file_path, duration=duration)

    # If called from non-main thread, schedule on main thread
    if _root_ref and _root_ref.winfo_exists():
        _root_ref.after(0, _create)
    else:
        # First toast — create directly (must be on main thread)
        _create()


def _get_border_color(kind: str) -> str:
    return {
        "success": BORDER_SUCCESS,
        "info":    BORDER_INFO,
        "error":   BORDER_ERROR,
        "warning": BORDER_WARNING,
    }.get(kind, BORDER_INFO)


def _get_icon(kind: str) -> str:
    return {
        "success": "✓",
        "info":    "ℹ",
        "error":   "✕",
        "warning": "⚠",
    }.get(kind, "ℹ")


def _reposition_all() -> None:
    """Recalculate vertical positions for all visible toasts."""
    margin_r = 16
    margin_b = 16
    gap      = 8

    try:
        sw = _root_ref.winfo_screenwidth()
        sh = _root_ref.winfo_screenheight()
    except Exception:
        return

    y_cursor = sh - margin_b
    for toast in reversed(_toasts):
        if not toast._dismissed:
            h = toast._win.winfo_height() or toast.ESTIMATED_H
            y_cursor -= h
            target_x = sw - toast.W - margin_r
            target_y = y_cursor
            toast._set_target_pos(target_x, target_y)
            y_cursor -= gap


# ══════════════════════════════════════════════════════════════════════════════

class _Toast:
    W           = 300
    ESTIMATED_H = 80

    def __init__(self, title: str, message: str, kind: str,
                 file_path: Optional[str], duration: int):
        global _root_ref

        self._file_path = file_path
        self._dismissed = False
        self._target_x  = 0
        self._target_y  = 0

        border_color = _get_border_color(kind)
        icon         = _get_icon(kind)

        try:
            # Create Toplevel (needs a root)
            if _root_ref is None or not _root_ref.winfo_exists():
                # Create a hidden root
                _root_ref = tk.Tk()
                _root_ref.withdraw()

            self._win = tk.Toplevel(_root_ref)
            self._win.overrideredirect(True)
            self._win.attributes("-topmost", True)
            self._win.attributes("-alpha", 0.0)
            self._win.configure(bg=BG)

            # Exclude from screen capture
            try:
                hwnd = ctypes.windll.user32.GetParent(self._win.winfo_id())
                ctypes.windll.user32.SetWindowDisplayAffinity(
                    hwnd, WDA_EXCLUDEFROMCAPTURE)
            except Exception:
                pass

            # ── Layout ────────────────────────────────────────────────────────
            outer = tk.Frame(self._win, bg=BG, bd=0)
            outer.pack(fill="both", expand=True)

            # Left color border
            tk.Frame(outer, bg=border_color, width=4).pack(side="left", fill="y")

            # Content area
            content = tk.Frame(outer, bg=BG, padx=12, pady=10)
            content.pack(side="left", fill="both", expand=True)

            # Title row
            title_row = tk.Frame(content, bg=BG)
            title_row.pack(fill="x")
            tk.Label(title_row, text=icon,
                     bg=BG, fg=border_color,
                     font=("Segoe UI Variable", 12, "bold")).pack(side="left")
            tk.Label(title_row, text=f"  {title}",
                     bg=BG, fg=TEXT_P,
                     font=("Segoe UI Variable", 11, "bold")).pack(side="left")

            # Message
            if message:
                msg_lbl = tk.Label(content, text=message,
                                   bg=BG, fg=TEXT_S,
                                   font=("Segoe UI", 9),
                                   wraplength=self.W - 40,
                                   anchor="w", justify="left")
                msg_lbl.pack(fill="x", pady=(2, 0))

            # Action buttons (Open + Folder) if file_path is given
            if file_path and os.path.exists(file_path):
                btn_row = tk.Frame(content, bg=BG)
                btn_row.pack(fill="x", pady=(6, 0))
                self._make_action_btn(btn_row, "Open",   lambda: self._open_file())
                self._make_action_btn(btn_row, "Folder", lambda: self._open_folder())

            self._win.update_idletasks()

            # ── Initial position (off-screen bottom-right) ─────────────────
            with _lock:
                _toasts.append(self)
            _reposition_all()

            sw = _root_ref.winfo_screenwidth()
            sh = _root_ref.winfo_screenheight()
            start_y = sh + 20

            self._win.geometry(
                f"{self.W}x{self._win.winfo_reqheight()}+{self._target_x}+{start_y}")
            self._win.deiconify()

            # ── Slide up + fade in ─────────────────────────────────────────
            end_x = self._target_x
            end_y = self._target_y

            def _in(t):
                yy = int(start_y + (end_y - start_y) * ease_out_cubic(t))
                try:
                    self._win.geometry(f"+{end_x}+{yy}")
                    self._win.attributes("-alpha", min(t * 1.5, 0.96))
                except Exception:
                    pass

            Animator(self._win, 320, _in).start()

            # ── Auto-dismiss ───────────────────────────────────────────────
            if duration > 0:
                self._win.after(duration, self.dismiss)

        except Exception as e:
            log.exception("Toast creation error: %s", e)

    def _make_action_btn(self, parent: tk.Frame, text: str,
                         command) -> tk.Label:
        btn = tk.Label(parent, text=text,
                       bg=BTN_BG, fg=TEXT_P,
                       font=("Segoe UI", 9),
                       padx=10, pady=3, cursor="hand2",
                       relief="flat")
        btn.pack(side="left", padx=(0, 6))
        btn.bind("<Enter>", lambda _: btn.configure(bg=BTN_HOVER))
        btn.bind("<Leave>", lambda _: btn.configure(bg=BTN_BG))
        btn.bind("<Button-1>", lambda _: command())
        return btn

    def _set_target_pos(self, x: int, y: int) -> None:
        self._target_x = x
        self._target_y = y
        if not self._dismissed:
            try:
                self._win.geometry(f"+{x}+{y}")
            except Exception:
                pass

    def _open_file(self):
        if self._file_path and os.path.exists(self._file_path):
            os.startfile(self._file_path)

    def _open_folder(self):
        if self._file_path:
            folder = os.path.dirname(self._file_path)
            if os.path.exists(folder):
                os.startfile(folder)

    def dismiss(self) -> None:
        """Slide down and fade out, then destroy."""
        if self._dismissed:
            return
        self._dismissed = True

        with _lock:
            if self in _toasts:
                _toasts.remove(self)
        _reposition_all()

        start_x = self._target_x
        start_y = self._target_y
        end_y   = start_y + 60

        def _out(t):
            yy = int(start_y + (end_y - start_y) * t)
            try:
                self._win.geometry(f"+{start_x}+{yy}")
                self._win.attributes("-alpha", 0.96 * (1 - t))
            except Exception:
                pass

        def _done():
            try:
                self._win.destroy()
            except Exception:
                pass

        try:
            Animator(self._win, 260, _out, on_complete=_done,
                     easing=ease_out_cubic).start()
        except Exception:
            try:
                self._win.destroy()
            except Exception:
                pass
