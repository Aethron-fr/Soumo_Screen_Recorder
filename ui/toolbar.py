"""
ui/toolbar.py
Soumo Screen Recorder PRO — Premium Floating Toolbar.

A pill-shaped, frameless, always-on-top Canvas window.
Every element drawn directly on Canvas for pixel-perfect control.
Uses the Windows transparent-color trick for true pill shape.

Features:
  - True pill shape via transparentcolor window attribute
  - Canvas-drawn icons (no emoji — vector-style lines/arcs)
  - Inline FPS + Quality pill selectors with slide animation
  - Smooth hover/press/release animations (spring physics)
  - Record pulse, digit crossfade, screen flash
  - Thread-safe via root.after(0, ...)
  - Capture exclusion (WDA_EXCLUDEFROMCAPTURE)
"""
from __future__ import annotations
import tkinter as tk
import ctypes
import threading
import time
import os
import sys
import logging
import datetime
from typing import Optional, Tuple, List, Callable

from core.recorder      import ScreenRecorder
from core.screenshot    import take_screenshot
from ui.region_selector import RegionSelector
from ui.settings_panel  import SettingsPanel
from ui.toast           import notify
from ui.countdown       import CountdownOverlay
from utils.state        import AppState
from utils.settings     import Settings, save_settings, load_settings
from utils.hotkeys      import HotkeyManager
from utils.animations   import (
    Animator, ColorAnimator, PulseLoop,
    ease_out_cubic, ease_in_out_sine, lerp_color, lerp
)

log = logging.getLogger(__name__)

WDA_EXCLUDEFROMCAPTURE = 0x00000011

# ── Palette ────────────────────────────────────────────────────────────────────
_HOLE     = "#010203"   # transparent key — NEVER use this color elsewhere
BG_MAIN   = "#0D0D14"
BG_GRAD_T = "#111118"
BG_GRAD_B = "#0A0A10"
DIVIDER   = "#1A1A2A"
HIGHLIGHT = "#1E1E2C"   # top rim 1px highlight
TEXT_P    = "#F0F0F5"
TEXT_S    = "#8888AA"
TEXT_DIM  = "#444460"
TEXT_VDM  = "#555570"
BORDER    = "#1C1C28"

# Button idle backgrounds
BTN_SHOT_IDLE  = "#1A2030"
BTN_REC_IDLE   = "#2A1515"
BTN_PAUSE_IDLE = "#2A2010"
BTN_REG_IDLE   = "#1A1A2A"
BTN_FOLD_IDLE  = "#142014"

# Button hover backgrounds
BTN_SHOT_HOV   = "#1A5080"
BTN_REC_HOV    = "#8B1A1A"
BTN_PAUSE_HOV  = "#7A5510"
BTN_REG_HOV    = "#3A2A6A"
BTN_FOLD_HOV   = "#1A5A1A"

# Accent colors
RED    = "#C0392B"
RED2   = "#E74C3C"
BLUE   = "#3498DB"
GREEN  = "#27AE60"
AMBER  = "#F39C12"
PURPLE = "#8B5CF6"

# Bar geometry
BAR_H  = 52
BAR_W  = 860
RADIUS = BAR_H // 2   # = 26 — full pill


# ══════════════════════════════════════════════════════════════════════════════
# Drawing Utilities
# ══════════════════════════════════════════════════════════════════════════════

def _fill_pill(cvs: tk.Canvas, x1, y1, x2, y2, color: str, tags="") -> List[int]:
    """Fill a pill (fully rounded rectangle) on canvas. Returns list of item IDs."""
    r  = (y2 - y1) // 2
    co = color
    ids = [
        cvs.create_oval(x1, y1, x1+2*r, y2, fill=co, outline=co, tags=tags),
        cvs.create_oval(x2-2*r, y1, x2, y2, fill=co, outline=co, tags=tags),
        cvs.create_rectangle(x1+r, y1, x2-r, y2, fill=co, outline=co, tags=tags),
    ]
    return ids


def _outline_pill(cvs: tk.Canvas, x1, y1, x2, y2, color: str,
                  width: int = 1, tags="") -> List[int]:
    """Draw pill outline on canvas."""
    r = (y2 - y1) // 2
    ids = [
        cvs.create_arc(x1, y1, x1+2*r, y2, start=90, extent=180,
                       style="arc", outline=color, width=width, tags=tags),
        cvs.create_arc(x2-2*r, y1, x2, y2, start=270, extent=180,
                       style="arc", outline=color, width=width, tags=tags),
        cvs.create_line(x1+r, y1, x2-r, y1, fill=color, width=width, tags=tags),
        cvs.create_line(x1+r, y2, x2-r, y2, fill=color, width=width, tags=tags),
    ]
    return ids


def _recolor_items(cvs: tk.Canvas, ids: List[int], color: str) -> None:
    """Recolor a list of canvas items (fill + outline)."""
    for iid in ids:
        try:
            cvs.itemconfigure(iid, fill=color, outline=color)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Canvas Icon Drawing
# ══════════════════════════════════════════════════════════════════════════════

def draw_icon_camera(cvs: tk.Canvas, cx: int, cy: int, color: str, tags="") -> None:
    """Camera icon — rounded body + lens circle + viewfinder bump."""
    s = 9
    hw, hh = s, int(s * 0.65)
    r = 3
    # Body
    cvs.create_rectangle(cx-hw, cy-hh, cx+hw, cy+hh,
                          outline=color, width=1.5, fill="", tags=tags)
    # Viewfinder bump
    cvs.create_rectangle(cx-4, cy-hh-3, cx+4, cy-hh,
                          outline=color, width=1, fill="", tags=tags)
    # Lens
    lr = 4
    cvs.create_oval(cx-lr, cy-lr, cx+lr, cy+lr,
                    outline=color, width=1.5, fill="", tags=tags)


def draw_icon_record(cvs: tk.Canvas, cx: int, cy: int, color: str, tags="") -> None:
    """Record icon — filled circle."""
    r = 7
    cvs.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline="", tags=tags)


def draw_icon_pause(cvs: tk.Canvas, cx: int, cy: int, color: str, tags="") -> None:
    """Pause icon — two vertical bars."""
    w, h = 4, 9
    cvs.create_rectangle(cx-w-1, cy-h, cx-1, cy+h, fill=color, outline="", tags=tags)
    cvs.create_rectangle(cx+1, cy-h, cx+w+1, cy+h, fill=color, outline="", tags=tags)


def draw_icon_region(cvs: tk.Canvas, cx: int, cy: int, color: str, tags="") -> None:
    """Region icon — four corner bracket lines."""
    s, arm = 9, 5
    for (dx, dy) in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        ox, oy = cx + dx*s, cy + dy*s
        cvs.create_line(ox, oy, ox - dx*arm, oy,
                        fill=color, width=1.5, tags=tags)
        cvs.create_line(ox, oy, ox, oy - dy*arm,
                        fill=color, width=1.5, tags=tags)


def draw_icon_folder(cvs: tk.Canvas, cx: int, cy: int, color: str, tags="") -> None:
    """Folder icon — body rectangle + tab at top-left."""
    hw, hh = 10, 7
    cvs.create_rectangle(cx-hw, cy-hh+2, cx+hw, cy+hh,
                          outline=color, width=1.5, fill="", tags=tags)
    cvs.create_rectangle(cx-hw, cy-hh-1, cx-hw//2, cy-hh+4,
                          outline=color, width=1.2, fill="", tags=tags)


def draw_icon_gear(cvs: tk.Canvas, cx: int, cy: int, color: str, tags="") -> None:
    """Gear icon — circle + 6 tick marks around perimeter."""
    import math
    r_inner, r_outer = 4, 9
    cvs.create_oval(cx-r_inner, cy-r_inner, cx+r_inner, cy+r_inner,
                    outline=color, width=1.5, fill="", tags=tags)
    for i in range(6):
        angle = math.radians(i * 60)
        x1 = cx + r_inner * math.cos(angle)
        y1 = cy + r_inner * math.sin(angle)
        x2 = cx + r_outer * math.cos(angle)
        y2 = cy + r_outer * math.sin(angle)
        cvs.create_line(x1, y1, x2, y2, fill=color, width=2.5, tags=tags,
                        capstyle="round")


# ══════════════════════════════════════════════════════════════════════════════
# Canvas Button
# ══════════════════════════════════════════════════════════════════════════════

class CanvasButton:
    """
    A 36×36 circular button drawn entirely on Canvas.

    Features smooth hover color animation (ColorAnimator),
    press scale-down, and spring-physics release.

    Args:
        cvs:        The canvas to draw on.
        cx, cy:     Center coordinates.
        idle_bg:    Background color when idle.
        hover_bg:   Background color when hovered.
        icon_fn:    Function(cvs, cx, cy, color, tags) that draws the icon.
        command:    Callable invoked on click.
        tag:        Unique Canvas tag for this button.
        radius:     Circle radius (default 18 = 36px diameter).
    """
    R          = 18
    ICON_IDLE  = "#9999BB"
    ICON_HOVER = "#FFFFFF"

    def __init__(self, cvs: tk.Canvas, cx: int, cy: int,
                 idle_bg: str, hover_bg: str,
                 icon_fn: Callable, command: Callable = None,
                 tag: str = "", radius: int = 18):
        self.cvs      = cvs
        self.cx       = cx
        self.cy       = cy
        self.r        = radius
        self._idle    = idle_bg
        self._hover   = hover_bg
        self._icon_fn = icon_fn
        self._cmd     = command
        self._tag     = tag
        self._cur_bg  = idle_bg
        self._hovered = False
        self._anim: Optional[ColorAnimator] = None
        self._circle_id: Optional[int] = None
        self._hidden  = False

        self._draw_circle(idle_bg)
        self._draw_icon(self.ICON_IDLE)

        cvs.tag_bind(tag, "<Enter>",           self._on_enter)
        cvs.tag_bind(tag, "<Leave>",           self._on_leave)
        cvs.tag_bind(tag, "<ButtonPress-1>",   self._on_press)
        cvs.tag_bind(tag, "<ButtonRelease-1>", self._on_release)

    def _draw_circle(self, color: str, scale: float = 1.0) -> None:
        if self._circle_id:
            self.cvs.delete(self._circle_id)
        r  = max(2, int(self.r * scale))
        cx, cy = self.cx, self.cy
        self._circle_id = self.cvs.create_oval(
            cx-r, cy-r, cx+r, cy+r,
            fill=color, outline="", tags=self._tag
        )
        self.cvs.tag_lower(self._circle_id)

    def _draw_icon(self, color: str) -> None:
        self.cvs.delete(f"{self._tag}_icon")
        self._icon_fn(self.cvs, self.cx, self.cy, color, tags=f"{self._tag}_icon")
        self.cvs.tag_bind(f"{self._tag}_icon", "<Enter>",           self._on_enter)
        self.cvs.tag_bind(f"{self._tag}_icon", "<Leave>",           self._on_leave)
        self.cvs.tag_bind(f"{self._tag}_icon", "<ButtonPress-1>",   self._on_press)
        self.cvs.tag_bind(f"{self._tag}_icon", "<ButtonRelease-1>", self._on_release)

    def _animate_bg(self, target: str) -> None:
        if self._anim:
            self._anim.stop()
        self._anim = ColorAnimator(
            self.cvs, self._cur_bg, target, 130,
            setter=self._set_bg
        ).start()

    def _set_bg(self, color: str) -> None:
        self._cur_bg = color
        self._draw_circle(color)

    def _on_enter(self, _=None) -> None:
        if self._hidden:
            return
        self._hovered = True
        self._animate_bg(self._hover)
        self._draw_icon(self.ICON_HOVER)

    def _on_leave(self, _=None) -> None:
        if self._hidden:
            return
        self._hovered = False
        self._animate_bg(self._idle)
        self._draw_icon(self.ICON_IDLE)

    def _on_press(self, _=None) -> None:
        if self._hidden:
            return
        self._draw_circle(self._hover, scale=0.86)

    def _on_release(self, _=None) -> None:
        if self._hidden:
            return
        self._draw_circle(self._hover if self._hovered else self._idle, scale=1.0)
        if self._cmd and not self._hidden:
            self._cmd()

    def set_icon_color(self, color: str) -> None:
        """Override the icon draw color."""
        self.ICON_IDLE  = color
        self.ICON_HOVER = color
        self._draw_icon(color)

    def hide(self) -> None:
        """Make the button invisible and non-interactive."""
        self._hidden = True
        self.cvs.delete(self._tag)
        self.cvs.delete(f"{self._tag}_icon")
        self._circle_id = None

    def show(self) -> None:
        """Make the button visible again."""
        self._hidden = False
        self._draw_circle(self._idle)
        self._draw_icon(self.ICON_IDLE)


# ══════════════════════════════════════════════════════════════════════════════
# Pill Selector (Inline FPS / Quality)
# ══════════════════════════════════════════════════════════════════════════════

class PillSelector:
    """
    Inline pill-button selector drawn on Canvas.

    Displays a label + N option pills. The active option has a filled
    pill background. Clicking a new option instantly redraws the selector
    with the new active option highlighted.

    Args:
        cvs:        Canvas to draw on.
        lx:         Left x position.
        cy:         Center y position.
        options:    List of option strings.
        active_idx: Initially active index.
        color:      Active pill fill color.
        label:      Short label text (e.g. "FPS" or "Q").
        on_change:  Callback(new_idx: int) when selection changes.
    """
    PILL_H   = 20
    FONT     = ("Segoe UI Variable", 9, "bold")
    OPT_PAD  = 9    # horizontal padding per option
    GAP      = 2    # gap between option pills
    LABEL_W  = 24   # space reserved for label

    def __init__(self, cvs: tk.Canvas, lx: int, cy: int,
                 options: List[str], active_idx: int,
                 color: str, label: str, on_change: Callable = None):
        self.cvs        = cvs
        self.lx         = lx
        self.cy         = cy
        self.options    = options
        self.active_idx = active_idx
        self.color      = color
        self.label      = label
        self._on_change = on_change
        self._all_ids: List[int] = []

        # Calculate option widths
        self._opt_w = [max(len(o) * 7 + self.OPT_PAD * 2, 28) for o in options]

        self._draw()

    def _opt_lx(self, idx: int) -> int:
        """Left x of option at given index."""
        x = self.lx + self.LABEL_W
        for i in range(idx):
            x += self._opt_w[i] + self.GAP
        return x

    @property
    def total_width(self) -> int:
        return self.LABEL_W + sum(self._opt_w) + self.GAP * (len(self.options) - 1)

    def _draw(self) -> None:
        """Full redraw of the selector."""
        for iid in self._all_ids:
            try:
                self.cvs.delete(iid)
            except Exception:
                pass
        self._all_ids.clear()

        cy = self.cy
        h  = self.PILL_H

        # Label
        lid = self.cvs.create_text(
            self.lx, cy,
            text=self.label,
            fill=TEXT_VDM,
            font=("Segoe UI", 9),
            anchor="w"
        )
        self._all_ids.append(lid)

        # Options
        for i, opt in enumerate(self.options):
            ox = self._opt_lx(i)
            ow = self._opt_w[i]
            tag = f"psel_{id(self)}_{i}"
            active = (i == self.active_idx)

            if active:
                pill_ids = _fill_pill(self.cvs, ox, cy-h//2, ox+ow, cy+h//2,
                                      self.color, tags=tag)
                self._all_ids.extend(pill_ids)

            text_color = TEXT_P if active else TEXT_DIM
            tid = self.cvs.create_text(
                ox + ow // 2, cy,
                text=opt,
                fill=text_color,
                font=self.FONT,
                anchor="center",
                tags=tag
            )
            self._all_ids.append(tid)

            # Invisible hit area
            hit = self.cvs.create_rectangle(
                ox, cy - h//2 - 2, ox+ow, cy + h//2 + 2,
                fill="", outline="", tags=tag
            )
            self._all_ids.append(hit)

            def _make_cb(idx):
                return lambda e: self.select(idx)
            self.cvs.tag_bind(tag, "<Button-1>", _make_cb(i))
            self.cvs.tag_bind(tag, "<Enter>",
                lambda e: self.cvs.configure(cursor="hand2"))
            self.cvs.tag_bind(tag, "<Leave>",
                lambda e: self.cvs.configure(cursor=""))

    def select(self, new_idx: int) -> None:
        """Change the active selection and redraw."""
        if new_idx == self.active_idx:
            return
        self.active_idx = new_idx
        self._draw()
        if self._on_change:
            self._on_change(new_idx)

    @property
    def value(self) -> str:
        """Current selected option string."""
        return self.options[self.active_idx]


# ══════════════════════════════════════════════════════════════════════════════
# Tooltip
# ══════════════════════════════════════════════════════════════════════════════

class CanvasTooltip:
    """
    Hover tooltip for Canvas items.

    Args:
        cvs:   The canvas.
        tags:  Canvas tag(s) that trigger the tooltip.
        text:  Text to display.
        delay: Milliseconds before the tooltip appears.
    """
    def __init__(self, cvs: tk.Canvas, tags, text: str, delay: int = 500):
        self._cvs   = cvs
        self._text  = text
        self._delay = delay
        self._win   = None
        self._job   = None

        if isinstance(tags, str):
            tags = [tags]
        for tag in tags:
            cvs.tag_bind(tag, "<Enter>", self._schedule)
            cvs.tag_bind(tag, "<Leave>", self._cancel)

    def update(self, text: str) -> None:
        self._text = text

    def _schedule(self, e):
        self._cancel()
        self._last_e = e
        self._job = self._cvs.after(self._delay, lambda: self._show(e))

    def _cancel(self, _=None):
        if self._job:
            self._cvs.after_cancel(self._job)
            self._job = None
        self._hide()

    def _show(self, e):
        x = self._cvs.winfo_rootx() + e.x
        y = self._cvs.winfo_rooty() + e.y + 22
        self._win = tk.Toplevel(self._cvs)
        self._win.wm_overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0)
        self._win.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._win, text=self._text,
            bg="#1C1C28", fg="#D0D0E0",
            font=("Segoe UI", 9),
            padx=10, pady=5, relief="flat"
        ).pack()
        def _fade(t):
            try:
                self._win.attributes("-alpha", t * 0.95)
            except Exception:
                pass
        Animator(self._win, 180, _fade).start()

    def _hide(self):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


# ══════════════════════════════════════════════════════════════════════════════
# Screen Flash
# ══════════════════════════════════════════════════════════════════════════════

def screen_flash(root: tk.Tk) -> None:
    """White full-screen flash simulating a camera shutter."""
    try:
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.0)
        win.configure(bg="#FFFFFF")
        try:
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass
        def _fade(t):
            try:
                win.attributes("-alpha", 0.16 * (1 - t))
            except Exception:
                pass
        Animator(win, 260, _fade, on_complete=win.destroy).start()
    except Exception as e:
        log.error("Screen flash error: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# The Toolbar
# ══════════════════════════════════════════════════════════════════════════════

class Toolbar(tk.Tk):
    """
    Main floating toolbar for Soumo Screen Recorder PRO.

    A pill-shaped, frameless, always-on-top window built entirely
    on a single Canvas. Every button, label, and selector is a Canvas
    drawing item — no Tkinter frames or standard widgets.

    Uses Windows transparentcolor to achieve the true pill shape by
    making the canvas background (_HOLE color) transparent.
    """

    H  = BAR_H
    W  = BAR_W
    R  = RADIUS

    def __init__(self):
        super().__init__()

        log.info("Toolbar init — Python %s", sys.version.split()[0])

        self._settings   = load_settings()
        self._recorder   = ScreenRecorder()
        self._recorder.set_timer_callback(self._on_timer)
        self._hotkeys    = HotkeyManager()
        self._region: Optional[Tuple[int, int, int, int]] = None
        self._settings_win: Optional[SettingsPanel] = None
        self._rec_lock   = threading.Lock()
        self._drag_ox    = self._drag_oy = 0
        self._rec_pulse: Optional[PulseLoop] = None
        self._rec_bar_pulse: Optional[PulseLoop] = None
        self._pause_btn: Optional[CanvasButton] = None
        self._enabled    = True

        # Window setup
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.wm_attributes("-transparentcolor", _HOLE)
        self.configure(bg=_HOLE)

        # Initial position
        sw = self.winfo_screenwidth()
        sx = self._settings.toolbar_x
        sy = self._settings.toolbar_y
        if sx < 0 or sx + self.W > sw:
            sx = (sw - self.W) // 2
        if sy < 0:
            sy = 12
        self.geometry(f"{self.W}x{self.H}+{sx}+{sy}")

        # Main canvas
        self.cvs = tk.Canvas(
            self, width=self.W, height=self.H,
            bg=_HOLE, highlightthickness=0, bd=0
        )
        self.cvs.pack()

        self._build()
        self._apply_capture_exclusion()
        self._register_hotkeys()
        self.after(80, self._animate_in)
        self.bind("<Configure>", self._on_configure)

    # ── Capture exclusion ─────────────────────────────────────────────────────

    def _apply_capture_exclusion(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            result = ctypes.windll.user32.SetWindowDisplayAffinity(
                hwnd, WDA_EXCLUDEFROMCAPTURE)
            log.info("SetWindowDisplayAffinity: %d", result)
        except Exception as e:
            log.error("Capture exclusion failed: %s", e)

    # ── Build the toolbar ─────────────────────────────────────────────────────

    def _build(self):
        cvs = self.cvs
        W, H, R = self.W, self.H, self.R
        cy = H // 2

        # ── Background pill ───────────────────────────────────────────────────
        # Main fill
        _fill_pill(cvs, 0, 0, W, H, BG_MAIN, tags="bg")
        # Top 1px highlight line (simulates light on top rim)
        cvs.create_line(R, 1, W-R, 1, fill=HIGHLIGHT, width=1, tags="bg")
        # Top-left arc highlight
        cvs.create_arc(0, 0, 2*R, H, start=90, extent=90,
                       style="arc", outline=HIGHLIGHT, width=1, tags="bg")
        # Top-right arc highlight
        cvs.create_arc(W-2*R, 0, W, H, start=0, extent=90,
                       style="arc", outline=HIGHLIGHT, width=1, tags="bg")
        # Outer border
        _outline_pill(cvs, 0, 0, W, H, BORDER, width=1, tags="bg")

        cvs.tag_bind("bg", "<ButtonPress-1>",  self._drag_start)
        cvs.tag_bind("bg", "<B1-Motion>",      self._drag_move)

        # ── Layout x positions ────────────────────────────────────────────────
        x = 14   # left cursor

        # Grip (6 dots in 2x3 grid)
        gx = x + 2
        for row in range(3):
            for col in range(2):
                dot = cvs.create_oval(
                    gx + col*5, cy - 6 + row*6,
                    gx + col*5 + 2, cy - 6 + row*6 + 2,
                    fill=TEXT_DIM, outline="", tags="grip"
                )
        cvs.tag_bind("grip", "<ButtonPress-1>",  self._drag_start)
        cvs.tag_bind("grip", "<B1-Motion>",      self._drag_move)
        cvs.tag_bind("grip", "<Enter>", lambda _: cvs.configure(cursor="fleur"))
        cvs.tag_bind("grip", "<Leave>", lambda _: cvs.configure(cursor=""))
        x += 20

        # Red dot (macOS style — your brand color)
        cvs.create_oval(x, cy-4, x+8, cy+4, fill=RED, outline="", tags="dot")
        x += 14

        # Brand text
        cvs.create_text(x, cy, text="SOUMO",
                        fill="#5A5A8A",
                        font=("Segoe UI Variable", 10, "bold"),
                        anchor="w", tags="brand",
                        spacing1=4)
        cvs.tag_bind("brand", "<ButtonPress-1>",  self._drag_start)
        cvs.tag_bind("brand", "<B1-Motion>",      self._drag_move)
        x += 62

        # Divider
        x = self._divider(cvs, x, H)
        x += 8

        # ── Action buttons ────────────────────────────────────────────────────
        btn_y = cy
        gap   = 6

        # Screenshot button
        self._btn_shot = CanvasButton(
            cvs, x + 18, btn_y,
            BTN_SHOT_IDLE, BTN_SHOT_HOV,
            draw_icon_camera, command=self._take_screenshot,
            tag="btn_shot"
        )
        CanvasTooltip(cvs, ["btn_shot", "btn_shot_icon"],
                      "Screenshot  [Ctrl+Shift+S]")
        x += 36 + gap

        # Record button
        self._btn_rec = CanvasButton(
            cvs, x + 18, btn_y,
            BTN_REC_IDLE, BTN_REC_HOV,
            draw_icon_record, command=self._toggle_record,
            tag="btn_rec"
        )
        self._btn_rec.set_icon_color(RED)
        self._tt_rec = CanvasTooltip(cvs, ["btn_rec", "btn_rec_icon"],
                                      "Start Recording  [Ctrl+Shift+R]")
        x += 36 + gap

        # Pause button (hidden until recording)
        self._pause_cx = x + 18
        self._pause_cy = btn_y
        self._btn_pause = CanvasButton(
            cvs, x + 18, btn_y,
            BTN_PAUSE_IDLE, BTN_PAUSE_HOV,
            draw_icon_pause, command=self._toggle_pause,
            tag="btn_pause"
        )
        self._btn_pause.hide()
        x += 36 + gap

        # Region button
        self._btn_reg = CanvasButton(
            cvs, x + 18, btn_y,
            BTN_REG_IDLE, BTN_REG_HOV,
            draw_icon_region, command=self._select_region,
            tag="btn_reg"
        )
        cvs.tag_bind("btn_reg", "<Button-3>", lambda _: self._clear_region())
        self._tt_reg = CanvasTooltip(cvs, ["btn_reg", "btn_reg_icon"],
                                      "Select region  [Right-click to clear]")
        x += 36 + gap

        # Folder button
        self._btn_folder = CanvasButton(
            cvs, x + 18, btn_y,
            BTN_FOLD_IDLE, BTN_FOLD_HOV,
            draw_icon_folder, command=self._open_folder,
            tag="btn_folder"
        )
        CanvasTooltip(cvs, ["btn_folder", "btn_folder_icon"], "Open Recordings folder")
        x += 36 + 8

        # Region label
        self._region_tid = cvs.create_text(
            x, cy, text="Full Screen",
            fill=TEXT_VDM, font=("Segoe UI", 8),
            anchor="w"
        )
        x += 68

        # Divider
        x = self._divider(cvs, x, H)
        x += 10

        # ── FPS selector ──────────────────────────────────────────────────────
        fps_opts = ["30", "60", "120", "144"]
        fps_vals = [30, 60, 120, 144]
        try:
            fps_active = fps_vals.index(self._settings.fps)
        except ValueError:
            fps_active = 1  # default 60

        self._fps_sel = PillSelector(
            cvs, x, cy,
            options=fps_opts,
            active_idx=fps_active,
            color=RED,
            label="FPS",
            on_change=lambda idx: self._on_fps_change(fps_vals[idx])
        )
        x += self._fps_sel.total_width + 12

        # ── Quality selector ──────────────────────────────────────────────────
        q_opts   = ["Lo", "Med", "Hi", "Ultra"]
        q_vals   = ["Low", "Medium", "High", "Ultra"]
        try:
            q_active = q_vals.index(self._settings.quality)
        except ValueError:
            q_active = 2  # default High

        self._q_sel = PillSelector(
            cvs, x, cy,
            options=q_opts,
            active_idx=q_active,
            color=BLUE,
            label="Q",
            on_change=lambda idx: self._on_quality_change(q_vals[idx])
        )
        x += self._q_sel.total_width + 8

        # Divider
        x = self._divider(cvs, x, H)
        x += 12

        # ── Timer ─────────────────────────────────────────────────────────────
        self._timer_color = TEXT_DIM
        self._timer_text  = "00:00:00"
        self._timer_tid   = cvs.create_text(
            x, cy, text="00:00:00",
            fill=TEXT_DIM,
            font=("Consolas", 14, "bold"),
            anchor="w"
        )
        x += 86

        # Divider
        x = self._divider(cvs, x, H)
        x += 8

        # ── Gear / Settings ───────────────────────────────────────────────────
        self._btn_gear = CanvasButton(
            cvs, x + 16, cy,
            "#1A1A28", "#2A2A40",
            draw_icon_gear, command=self._open_settings,
            tag="btn_gear", radius=14
        )
        CanvasTooltip(cvs, ["btn_gear", "btn_gear_icon"], "Settings")
        x += 36

        # ── Close button ──────────────────────────────────────────────────────
        self._close_tid = cvs.create_text(
            x + 4, cy, text="✕",
            fill=TEXT_DIM,
            font=("Segoe UI", 12),
            anchor="w",
            tags="close_btn"
        )
        cvs.tag_bind("close_btn", "<Button-1>", lambda _: self._quit())
        cvs.tag_bind("close_btn", "<Enter>",
                     lambda _: cvs.itemconfigure(self._close_tid, fill=RED2))
        cvs.tag_bind("close_btn", "<Leave>",
                     lambda _: cvs.itemconfigure(self._close_tid, fill=TEXT_DIM))
        CanvasTooltip(cvs, "close_btn", "Quit Soumo Recorder")

        # ── Recording bottom bar ──────────────────────────────────────────────
        self._rec_bar_ids: List[int] = []
        self._rec_bar_visible = False

        log.info("Toolbar built. Total width used: ~%d / %d", x, self.W)

    def _divider(self, cvs: tk.Canvas, x: int, H: int) -> int:
        """Draw a 1px vertical divider and return the right edge x."""
        mid = H // 2
        cvs.create_line(x+1, mid-10, x+1, mid+10, fill=DIVIDER, width=1)
        return x + 2

    # ── Slide-in animation ────────────────────────────────────────────────────

    def _animate_in(self):
        x     = self.winfo_x()
        y_end = self.winfo_y()
        y_st  = -self.H - 20
        def _upd(t):
            yy = int(y_st + (y_end - y_st) * ease_out_cubic(t))
            self.geometry(f"+{x}+{yy}")
            self.attributes("-alpha", t)
        Animator(self, 400, _upd).start()

    # ── Drag ──────────────────────────────────────────────────────────────────

    def _drag_start(self, e):
        self._drag_ox = e.x_root - self.winfo_x()
        self._drag_oy = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        x = e.x_root - self._drag_ox
        y = e.y_root - self._drag_oy
        self.geometry(f"+{x}+{y}")

    def _on_configure(self, _=None):
        try:
            self._settings.toolbar_x = self.winfo_x()
            self._settings.toolbar_y = self.winfo_y()
            save_settings(self._settings)
        except Exception:
            pass

    # ── Hotkeys ───────────────────────────────────────────────────────────────

    def _register_hotkeys(self):
        self._hotkeys.register("ctrl+shift+r",
                               lambda: self.after(0, self._toggle_record))
        self._hotkeys.register("ctrl+shift+s",
                               lambda: self.after(0, self._take_screenshot))

    # ── Inline selectors ──────────────────────────────────────────────────────

    def _on_fps_change(self, fps: int):
        self._settings.fps = fps
        save_settings(self._settings)
        log.info("FPS changed to %d", fps)

    def _on_quality_change(self, quality: str):
        self._settings.quality = quality
        save_settings(self._settings)
        log.info("Quality changed to %s", quality)

    # ── Thread-safe UI helpers ────────────────────────────────────────────────

    def _ui(self, fn: Callable) -> None:
        """Run fn on the main thread. Safe to call from any background thread."""
        self.after(0, fn)

    def _set_timer(self, text: str, color: str = TEXT_DIM) -> None:
        """Update timer display (must be called on main thread)."""
        self._timer_text  = text
        self._timer_color = color
        self.cvs.itemconfigure(self._timer_tid, text=text, fill=color)

    def _set_region_label(self, text: str, color: str = TEXT_VDM) -> None:
        self.cvs.itemconfigure(self._region_tid, text=text, fill=color)

    def _show_rec_bar(self) -> None:
        """Show the 2px red bottom recording bar."""
        for iid in self._rec_bar_ids:
            try:
                self.cvs.delete(iid)
            except Exception:
                pass
        # Draw a thin line at the bottom of the pill
        ids = []
        ids.append(self.cvs.create_line(
            self.R, self.H-2, self.W-self.R, self.H-2,
            fill=RED, width=2, tags="recbar"
        ))
        self._rec_bar_ids = ids
        self._rec_bar_visible = True
        # Pulse it
        self._rec_bar_pulse = PulseLoop(
            self, 1600,
            on_update=lambda t: self.cvs.itemconfigure(
                "recbar", fill=lerp_color(RED, RED2, t))
        )
        self._rec_bar_pulse.start()

    def _hide_rec_bar(self) -> None:
        if self._rec_bar_pulse:
            self._rec_bar_pulse.stop()
            self._rec_bar_pulse = None
        for iid in self._rec_bar_ids:
            try:
                self.cvs.delete(iid)
            except Exception:
                pass
        self._rec_bar_ids = []
        self._rec_bar_visible = False

    # ── Actions ───────────────────────────────────────────────────────────────

    def _open_folder(self):
        path = self._settings.output_folder
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus()
            return
        self._settings_win = SettingsPanel(
            self, self._settings, self._recorder,
            on_close=lambda: setattr(self, "_settings_win", None)
        )

    def _select_region(self):
        if self._recorder.is_recording:
            notify("Cannot Change Region", "Stop recording first.", kind="error")
            return
        self._ui(lambda: self._set_timer("SELECT", AMBER))
        self.iconify()
        self.after(220, self._launch_selector)

    def _launch_selector(self):
        rs = RegionSelector(self._on_region_done)
        rs.run()

    def _on_region_done(self, region):
        self.deiconify()
        self._region = region
        if region:
            l, t, r, b = region
            w, h = r-l, b-t
            self._ui(lambda: (
                self._set_region_label(f"{w}×{h}", AMBER),
                self._set_timer("00:00:00", TEXT_DIM)
            ))
            notify("Region Selected", f"{w}×{h} pixels", kind="info", duration=2000)
        else:
            self._ui(lambda: (
                self._set_region_label("Full Screen", TEXT_VDM),
                self._set_timer("00:00:00", TEXT_DIM)
            ))

    def _clear_region(self):
        self._region = None
        self._ui(lambda: self._set_region_label("Full Screen", TEXT_VDM))
        notify("Region Cleared", "Now capturing full screen.", kind="info", duration=1500)

    def _take_screenshot(self):
        idx  = self._settings.monitor
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self._settings.output_folder,
                            f"Screenshot_{ts}.png")
        os.makedirs(self._settings.output_folder, exist_ok=True)

        screen_flash(self)
        self._ui(lambda: self._set_timer("SNAP!", BLUE))

        def _do():
            ok = take_screenshot(
                monitor_index=idx,
                output_path=path,
                region=self._region,
                copy_to_clipboard=self._settings.copy_screenshot,
            )
            if ok:
                notify("Screenshot Saved", os.path.basename(path), kind="info")
            else:
                notify("Screenshot Failed",
                       "Could not capture frame. Check log.", kind="error")
            self._ui(lambda: self._set_timer("00:00:00", TEXT_DIM))

        threading.Thread(target=_do, daemon=True, name="soumo-ss").start()

    def _toggle_record(self):
        if not self._rec_lock.acquire(blocking=False):
            return
        try:
            if self._recorder.is_recording:
                self._stop_recording()
            else:
                if self._settings.countdown_enabled:
                    CountdownOverlay(on_done=self._start_recording).show()
                else:
                    self._start_recording()
        finally:
            self.after(600, self._rec_lock.release)

    def _start_recording(self):
        self._enabled = False
        ts   = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fps  = self._settings.fps
        qual = self._settings.quality
        ext  = {"MP4": "mp4", "MKV": "mkv", "WebM": "webm"}.get(
                   self._settings.output_format, "mp4")
        name = f"soumo_{ts}_{qual}_{fps}fps.{ext}"
        path = os.path.join(self._settings.output_folder, name)
        os.makedirs(self._settings.output_folder, exist_ok=True)

        def _do():
            try:
                self._recorder.start_recording(
                    monitor_index=self._settings.monitor,
                    fps=fps,
                    output_path=path,
                    quality=qual,
                    color_grading=self._settings.color_grade,
                    region=self._region,
                    audio_enabled=self._settings.audio_enabled,
                    mic_enabled=self._settings.mic_enabled,
                    output_format=self._settings.output_format,
                )
                self._ui(lambda: (
                    self._btn_rec.set_icon_color(RED2),
                    self._show_rec_bar(),
                    self._start_rec_pulse(),
                    self._btn_pause.show(),
                    self._tt_rec.update("Stop Recording  [Ctrl+Shift+R]"),
                ))
                self._enabled = True
            except RuntimeError as e:
                notify("Recording Failed", str(e), kind="error")
                self._ui(lambda: self._set_timer("ERROR", RED))
                self._enabled = True
            except Exception as e:
                log.exception("Unexpected recording start error: %s", e)
                notify("Recording Error", str(e), kind="error")
                self._enabled = True

        threading.Thread(target=_do, daemon=True, name="soumo-start").start()

    def _stop_recording(self):
        self._enabled = False
        self._ui(lambda: (
            self._stop_rec_pulse(),
            self._hide_rec_bar(),
            self._btn_rec.set_icon_color(RED),
            self._btn_pause.hide(),
            self._set_timer("SAVING", AMBER),
            self._tt_rec.update("Start Recording  [Ctrl+Shift+R]"),
        ))

        def _do():
            try:
                self._recorder.stop_recording()
                fname = os.path.basename(self._recorder.output_file)
                self._ui(lambda: self._set_timer("✓ SAVED", GREEN))
                notify("Recording Saved", fname, kind="success")
                if self._settings.auto_open and self._recorder.output_file:
                    try:
                        os.startfile(self._recorder.output_file)
                    except Exception:
                        pass
            except Exception as e:
                log.exception("Stop error: %s", e)
                notify("Save Error", str(e), kind="error")
                self._ui(lambda: self._set_timer("ERROR", RED))
            finally:
                self._enabled = True
                self.after(2500, lambda: self._set_timer("00:00:00", TEXT_DIM))

        threading.Thread(target=_do, daemon=True, name="soumo-stop").start()

    def _toggle_pause(self):
        if not self._recorder.is_recording:
            return
        if self._recorder.is_paused:
            self._recorder.resume_recording()
            self._ui(lambda: self._set_timer("REC…", RED))
            self._start_rec_pulse()
        else:
            self._recorder.pause_recording()
            self._stop_rec_pulse()
            self._ui(lambda: self._set_timer("PAUSED", AMBER))

    # ── Record pulse ──────────────────────────────────────────────────────────

    def _start_rec_pulse(self):
        if self._rec_pulse:
            self._rec_pulse.stop()
        self._rec_pulse = PulseLoop(
            self, 1800,
            on_update=lambda t: self._btn_rec.set_icon_color(
                lerp_color(RED, "#FF8080", t))
        )
        self._rec_pulse.start()

    def _stop_rec_pulse(self):
        if self._rec_pulse:
            self._rec_pulse.stop()
            self._rec_pulse = None
        self._btn_rec.set_icon_color(RED)

    # ── Timer callback ────────────────────────────────────────────────────────

    def _on_timer(self, time_str: str):
        if self._recorder.is_recording and not self._recorder.is_paused:
            self._ui(lambda: self._set_timer(time_str, RED))

    # ── Quit ──────────────────────────────────────────────────────────────────

    def _quit(self):
        log.info("Quit requested")
        self._hotkeys.unregister_all()
        if self._recorder.is_recording:
            threading.Thread(
                target=self._recorder.stop_recording,
                daemon=True
            ).start()
        save_settings(self._settings)
        self.after(300, self.destroy)
