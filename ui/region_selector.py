"""
ui/region_selector.py
Full-screen crosshair region selection overlay — FIXED VERSION.

Fixes:
  - Uses the full virtual desktop dimensions
  - Canvas binds all mouse events (not window)
  - Returns normalized (left, top, right, bottom) pixel coords
  - Escape key cleanly destroys overlay
  - Animated marching-dashes border
  - Custom crosshair drawn on canvas (OS cursor hidden)
  - Live W×H dimension label inside selection
"""

import tkinter as tk
import logging
from typing import Callable, Optional, Tuple

log = logging.getLogger(__name__)

_OVERLAY_ALPHA = 0.50
_BORDER_COLOR  = "#E74C3C"
_KNOB_COLOR    = "#FFFFFF"
_FILL_STIPPLE  = "gray12"
_DASH_LEN      = 10
_DASH_GAP      = 6
_DASH_SPEED_MS = 30   # ms per marching-ant frame


class RegionSelector:
    """
    Presents a full-screen transparent overlay for click-drag region selection.

    The selected (left, top, right, bottom) tuple in screen pixels is
    delivered to `on_selected`. If the user cancels (Escape / tiny drag),
    `on_selected(None)` is called.

    Args:
        on_selected: Callback receiving region tuple or None.
    """

    def __init__(self, on_selected: Callable[[Optional[Tuple[int, int, int, int]]], None]):
        self._cb       = on_selected
        self._root     = None
        self._canvas   = None
        self._start    = (0, 0)
        self._rect_id  = None
        self._fill_id  = None
        self._label_bg = None
        self._label_id = None
        self._cross_h  = None
        self._cross_v  = None
        self._dash_off = 0
        self._dragging = False
        self._anim_id  = None

    def run(self) -> None:
        """Block the calling thread while the overlay is active."""
        self._root = tk.Tk()
        self._root.withdraw()

        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        log.info("Region selector: screen size %dx%d", sw, sh)

        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", _OVERLAY_ALPHA)
        self._root.attributes("-fullscreen", True)
        self._root.configure(bg="#000000")
        self._root.config(cursor="none")   # hide OS cursor; we draw custom crosshair

        self._canvas = tk.Canvas(
            self._root,
            bg="#000000",
            highlightthickness=0,
            cursor="none",
            width=sw, height=sh,
        )
        self._canvas.pack(fill="both", expand=True)

        # Instruction text
        self._hint = self._canvas.create_text(
            sw // 2, 36,
            text="Click and drag to select capture region  •  Esc to cancel",
            fill="#AAAAAA",
            font=("Segoe UI", 13),
        )

        # Bind to CANVAS (not root window)
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",        self._on_drag)
        self._canvas.bind("<ButtonRelease-1>",  self._on_release)
        self._canvas.bind("<Motion>",           self._on_motion)
        self._root.bind("<Escape>",             self._on_cancel)

        self._root.deiconify()
        self._root.mainloop()

    # ── Crosshair ─────────────────────────────────────────────────────────────

    def _update_crosshair(self, x: int, y: int) -> None:
        size = 18
        sw   = self._root.winfo_screenwidth()
        sh   = self._root.winfo_screenheight()

        if self._cross_h:
            self._canvas.delete(self._cross_h)
        if self._cross_v:
            self._canvas.delete(self._cross_v)

        self._cross_h = self._canvas.create_line(
            x - size, y, x + size, y,
            fill=_KNOB_COLOR, width=1, tags="crosshair"
        )
        self._cross_v = self._canvas.create_line(
            x, y - size, x, y + size,
            fill=_KNOB_COLOR, width=1, tags="crosshair"
        )

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_motion(self, e):
        self._update_crosshair(e.x, e.y)

    def _on_press(self, e):
        self._start   = (e.x, e.y)
        self._dragging = True

        if self._hint:
            self._canvas.delete(self._hint)
            self._hint = None

        self._fill_id = self._canvas.create_rectangle(
            e.x, e.y, e.x, e.y,
            fill="white", stipple=_FILL_STIPPLE, outline="",
        )
        self._rect_id = self._canvas.create_rectangle(
            e.x, e.y, e.x, e.y,
            outline=_BORDER_COLOR, width=2,
            dash=(_DASH_LEN, _DASH_GAP),
        )
        # Dimension label background + text
        self._label_bg = self._canvas.create_rectangle(
            0, 0, 0, 0, fill="#1C1C26", outline="", state="hidden"
        )
        self._label_id = self._canvas.create_text(
            0, 0, text="", fill="#F0F0F5",
            font=("Segoe UI Variable", 10, "bold"),
            state="hidden",
        )
        self._anim_id = None
        self._dash_off = 0
        self._march()

    def _on_drag(self, e):
        if not self._dragging:
            return
        x0, y0 = self._start
        x1, y1 = e.x, e.y

        self._canvas.coords(self._fill_id, x0, y0, x1, y1)
        self._canvas.coords(self._rect_id, x0, y0, x1, y1)
        self._update_crosshair(e.x, e.y)

        # Live dimension label
        w = abs(x1 - x0)
        h = abs(y1 - y0)
        if w > 30 and h > 20:
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            label_text = f" {w} × {h} "
            self._canvas.coords(self._label_id, cx, cy)
            self._canvas.itemconfigure(self._label_id,
                                       text=label_text,
                                       state="normal")
            # Label background bounding box approximation
            half_w, half_h = len(label_text) * 3 + 10, 12
            self._canvas.coords(self._label_bg,
                                 cx - half_w, cy - half_h,
                                 cx + half_w, cy + half_h)
            self._canvas.itemconfigure(self._label_bg, state="normal")
            # Keep label above rect
            self._canvas.lift(self._label_bg)
            self._canvas.lift(self._label_id)

    def _on_release(self, e):
        self._dragging = False
        if self._anim_id:
            self._root.after_cancel(self._anim_id)

        x0, y0 = self._start
        x1, y1 = e.x, e.y

        # Normalize coordinates
        left   = min(x0, x1)
        top    = min(y0, y1)
        right  = max(x0, x1)
        bottom = max(y0, y1)

        log.info("Region selected: (%d,%d,%d,%d) size=%dx%d",
                 left, top, right, bottom, right - left, bottom - top)

        if right - left < 10 or bottom - top < 10:
            log.warning("Region too small, cancelling")
            self._finish(None)
            return

        # Brief white flash on canvas, then close
        self._canvas.configure(bg="#FFFFFF")
        self._root.update()
        self._root.after(70, lambda: self._canvas.configure(bg="#000000"))
        self._root.after(180, lambda: self._finish((left, top, right, bottom)))

    def _on_cancel(self, _=None):
        log.info("Region selection cancelled by user")
        if self._anim_id:
            try:
                self._root.after_cancel(self._anim_id)
            except Exception:
                pass
        self._finish(None)

    def _finish(self, region):
        try:
            self._root.quit()
            self._root.destroy()
        except Exception:
            pass
        self._cb(region)

    # ── Marching ants animation ────────────────────────────────────────────────

    def _march(self):
        if not self._dragging or not self._rect_id:
            return
        self._dash_off = (self._dash_off + 1) % (_DASH_LEN + _DASH_GAP)
        try:
            self._canvas.itemconfigure(
                self._rect_id,
                dashoffset=self._dash_off,
                dash=(_DASH_LEN, _DASH_GAP),
            )
        except Exception:
            return
        self._anim_id = self._root.after(_DASH_SPEED_MS, self._march)
