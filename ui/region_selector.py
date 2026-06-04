"""
ui/region_selector.py
Full-screen region selection overlay.
Rebuilt from scratch — dark, clean, precise.
"""
from __future__ import annotations
import tkinter as tk
from typing import Optional, Tuple, Callable
import logging

log = logging.getLogger(__name__)

_BG         = "#060610"
_OVERLAY_A  = 0.65       # background alpha
_SEL_BORDER = "#A78BFA"  # purple selection border
_SEL_FILL   = "#A78BFA"  # fill tag for interior tint
_DIM_BG     = "#1A1228"
_DIM_FG     = "#E8E8F0"
_FONT       = ("Segoe UI", 11, "normal")
_FONT_HINT  = ("Segoe UI", 9, "normal")


class RegionSelector:
    """
    Click-and-drag region selector.

    Shows a near-black fullscreen overlay. The user clicks and drags
    to define a rectangle. On mouse release, calls on_done with the
    (left, top, right, bottom) tuple. Escape cancels (calls on_done(None)).

    Args:
        on_done: Callable receiving Optional[Tuple[int,int,int,int]].
    """

    def __init__(self, on_done: Callable[[Optional[Tuple[int,int,int,int]]], None]):
        self._on_done   = on_done
        self._start_xy  = (0, 0)
        self._dragging  = False
        self._sel_ids   = []
        self._dim_id    = None
        self._cross_ids = []
        self._win: Optional[tk.Toplevel] = None
        self._cvs: Optional[tk.Canvas]  = None

    def run(self) -> None:
        """Launch the selector. Blocks the calling thread (Tkinter modal)."""
        try:
            self._create_window()
        except Exception as e:
            log.exception("RegionSelector failed: %s", e)
            self._on_done(None)

    def _create_window(self):
        self._win = tk.Toplevel()
        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()

        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", _OVERLAY_A)
        self._win.geometry(f"{sw}x{sh}+0+0")
        self._win.configure(bg=_BG)
        self._win.focus_force()

        self._cvs = tk.Canvas(
            self._win,
            width=sw, height=sh,
            bg=_BG,
            highlightthickness=0, bd=0,
            cursor="crosshair"
        )
        self._cvs.pack(fill="both", expand=True)

        # Instructions
        self._hint_id = self._cvs.create_text(
            sw // 2, 28,
            text="Click and drag to select a region   ·   Escape to cancel",
            fill="#6B6B8A",
            font=_FONT_HINT,
            anchor="center"
        )

        # Crosshair (drawn by _on_motion)
        self._win.bind("<ButtonPress-1>",   self._on_press)
        self._win.bind("<B1-Motion>",       self._on_motion)
        self._win.bind("<ButtonRelease-1>", self._on_release)
        self._win.bind("<Escape>",          self._cancel)

    def _clear_selection(self):
        for iid in self._sel_ids:
            try:
                self._cvs.delete(iid)
            except Exception:
                pass
        self._sel_ids.clear()

    def _draw_crosshair(self, x: int, y: int):
        for iid in self._cross_ids:
            try:
                self._cvs.delete(iid)
            except Exception:
                pass
        self._cross_ids.clear()
        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()
        col = "#3A3A55"
        self._cross_ids.append(
            self._cvs.create_line(x, 0, x, sh, fill=col, width=1))
        self._cross_ids.append(
            self._cvs.create_line(0, y, sw, y, fill=col, width=1))

    def _on_press(self, e):
        self._start_xy = (e.x, e.y)
        self._dragging = True
        self._clear_selection()

    def _on_motion(self, e):
        self._draw_crosshair(e.x, e.y)
        if not self._dragging:
            return
        x0, y0 = self._start_xy
        x1, y1 = e.x, e.y
        self._clear_selection()

        # Semi-bright interior
        self._sel_ids.append(
            self._cvs.create_rectangle(x0, y0, x1, y1,
                fill="#FFFFFF", outline="", stipple="gray12",
                tags="sel_fill")
        )
        # Border
        self._sel_ids.append(
            self._cvs.create_rectangle(x0, y0, x1, y1,
                fill="", outline=_SEL_BORDER, width=1)
        )

        # Corner handles
        for hx, hy in [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]:
            self._sel_ids.append(
                self._cvs.create_oval(hx-4, hy-4, hx+4, hy+4,
                    fill=_SEL_BORDER, outline="")
            )

        # Dimension label
        w, h = abs(x1 - x0), abs(y1 - y0)
        lx = min(x0, x1) + w // 2
        ly = min(y0, y1) - 18
        if ly < 10:
            ly = max(y0, y1) + 8

        bg_pad = 6
        label = f"{w} × {h}"
        # Label background
        self._sel_ids.append(
            self._cvs.create_rectangle(
                lx - len(label)*3.5 - bg_pad, ly - 10,
                lx + len(label)*3.5 + bg_pad, ly + 10,
                fill=_DIM_BG, outline=_SEL_BORDER, width=1
            )
        )
        self._sel_ids.append(
            self._cvs.create_text(lx, ly,
                text=label, fill=_DIM_FG,
                font=_FONT, anchor="center")
        )

    def _on_release(self, e):
        if not self._dragging:
            return
        self._dragging = False
        x0, y0 = self._start_xy
        x1, y1 = e.x, e.y

        # Minimum size check
        l, t = min(x0, x1), min(y0, y1)
        r, b = max(x0, x1), max(y0, y1)
        if r - l < 16 or b - t < 16:
            self._clear_selection()
            return

        self._close()
        self._on_done((l, t, r, b))

    def _cancel(self, _=None):
        self._close()
        self._on_done(None)

    def _close(self):
        try:
            if self._win:
                self._win.destroy()
                self._win = None
        except Exception:
            pass
