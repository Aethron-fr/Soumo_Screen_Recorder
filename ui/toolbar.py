"""
ui/toolbar.py
Soumo Screen Recorder PRO — Premium Floating Toolbar.
Rebuilt from scratch. No legacy code. No compromises.

Architecture:
  - Single tk.Canvas covers the entire window — no widget children
  - True pill shape via Windows transparentcolor key (_HOLE)
  - Every button, label and selector is a canvas item group
  - New key-based Animator drives all motion (hover, press, pulse)
  - No emoji used as icons — all icons built from canvas lines/arcs
  - WDA_EXCLUDEFROMCAPTURE: toolbar is invisible in all recordings
"""
from __future__ import annotations
import tkinter as tk
import ctypes
import math
import threading
import datetime
import os
import sys
import logging
from typing import Optional, Tuple, Callable, Dict, Any

from core.recorder      import ScreenRecorder
from core.screenshot    import take_screenshot
from ui.region_selector import RegionSelector
from ui.settings_panel  import SettingsPanel
from ui.toast           import ToastManager
from ui.countdown       import CountdownOverlay
from utils.settings     import Settings, load_settings, save_settings
from utils.hotkeys      import HotkeyManager
from utils.animations   import Animator, interpolate_color

log = logging.getLogger(__name__)

WDA_EXCLUDEFROMCAPTURE = 0x00000011
_HOLE = "#010203"  # transparentcolor key — never draw with this color

# ── Design tokens (Vercel / Linear / Nothing OS inspired) ─────────────────────
C = {
    "bg_base":        "#080810",
    "bg_surface":     "#0F0F18",
    "bg_elevated":    "#16161F",
    "bg_sunken":      "#06060D",
    "border_subtle":  "#1E1E2E",
    "border_dim":     "#2A2A3C",
    "border_active":  "#3A3A52",
    "text_primary":   "#E8E8F0",
    "text_secondary": "#6B6B8A",
    "text_dim":       "#3A3A55",
    "red":            "#E5383B",
    "red_dim":        "#2D0E0F",
    "red_glow":       "#FF4444",
    "blue":           "#4A9EFF",
    "blue_dim":       "#0D1F35",
    "green":          "#3DDC84",
    "green_dim":      "#0D2B1A",
    "amber":          "#FFB800",
    "amber_dim":      "#2B2000",
    "purple":         "#A78BFA",
    "purple_dim":     "#1A1228",
}

F = {
    "brand":    ("Segoe UI", 9, "bold"),
    "label":    ("Segoe UI", 9, "normal"),
    "timer":    ("Consolas", 13, "normal"),
    "button":   ("Segoe UI", 8, "normal"),
    "status":   ("Consolas", 11, "bold"),
}

BAR_H = 48
BAR_R = 24   # half of height — true pill
BAR_W = 820  # calculated from layout below


# ── Canvas primitive helpers ──────────────────────────────────────────────────

def _fill_pill(cvs, x1, y1, x2, y2, color, tags=""):
    """Fill a pill (fully rounded rectangle where r = h/2)."""
    r = (y2 - y1) // 2
    cvs.create_oval(x1, y1, x1+2*r, y2,        fill=color, outline=color, tags=tags)
    cvs.create_oval(x2-2*r, y1, x2, y2,         fill=color, outline=color, tags=tags)
    cvs.create_rectangle(x1+r, y1, x2-r, y2,   fill=color, outline=color, tags=tags)


def _outline_pill(cvs, x1, y1, x2, y2, color, width=1, tags=""):
    """Draw the outline of a pill shape."""
    r = (y2 - y1) // 2
    cvs.create_arc(x1, y1, x1+2*r, y2, start=90, extent=180,
                   style="arc", outline=color, width=width, tags=tags)
    cvs.create_arc(x2-2*r, y1, x2, y2, start=270, extent=180,
                   style="arc", outline=color, width=width, tags=tags)
    cvs.create_line(x1+r, y1,   x2-r, y1,   fill=color, width=width, tags=tags)
    cvs.create_line(x1+r, y2-1, x2-r, y2-1, fill=color, width=width, tags=tags)


def _fill_rrect(cvs, x1, y1, x2, y2, r, color, tags=""):
    """Fill a rounded rectangle with arbitrary radius."""
    r = min(r, (x2-x1)//2, (y2-y1)//2)
    cvs.create_oval(x1,     y1,     x1+2*r, y1+2*r, fill=color, outline=color, tags=tags)
    cvs.create_oval(x2-2*r, y1,     x2,     y1+2*r, fill=color, outline=color, tags=tags)
    cvs.create_oval(x1,     y2-2*r, x1+2*r, y2,     fill=color, outline=color, tags=tags)
    cvs.create_oval(x2-2*r, y2-2*r, x2,     y2,     fill=color, outline=color, tags=tags)
    cvs.create_rectangle(x1+r, y1,   x2-r, y2,     fill=color, outline=color, tags=tags)
    cvs.create_rectangle(x1,   y1+r, x2,   y2-r,   fill=color, outline=color, tags=tags)


# ── Icon functions ────────────────────────────────────────────────────────────
# Rules:
#   - Only create_line and create_arc(style='arc') for outlines
#   - create_oval with fill=color for solid circles (record icon)
#   - itemconfig(fill=c, outline=c) correctly updates ALL item types

def _icon_camera(cvs, cx, cy, color, tags):
    s = 7
    # Body outline
    cvs.create_line(cx-s, cy-s+2, cx+s, cy-s+2,
                    cx+s, cy+s, cx-s, cy+s, cx-s, cy-s+2,
                    fill=color, width=1.5, joinstyle="round", tags=tags)
    # Lens
    cvs.create_arc(cx-3, cy-1, cx+3, cy+5,
                   start=0, extent=359, style="arc",
                   outline=color, width=1.5, tags=tags)
    # Viewfinder bump
    cvs.create_line(cx-3, cy-s+2, cx-3, cy-s-2,
                    cx+3, cy-s-2, cx+3, cy-s+2,
                    fill=color, width=1, tags=tags)


def _icon_record(cvs, cx, cy, color, tags):
    r = 5
    cvs.create_oval(cx-r, cy-r, cx+r, cy+r, fill=color, outline=color, tags=tags)


def _icon_pause(cvs, cx, cy, color, tags):
    bw, bh = 3, 10
    cvs.create_rectangle(cx-5,    cy-bh//2, cx-5+bw, cy+bh//2,
                         fill=color, outline=color, tags=tags)
    cvs.create_rectangle(cx+2,    cy-bh//2, cx+2+bw, cy+bh//2,
                         fill=color, outline=color, tags=tags)


def _icon_region(cvs, cx, cy, color, tags):
    s, arm = 7, 5
    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        ox, oy = cx + dx * s, cy + dy * s
        cvs.create_line(ox, oy, ox - dx*arm, oy,
                        fill=color, width=1.5, capstyle="round", tags=tags)
        cvs.create_line(ox, oy, ox, oy - dy*arm,
                        fill=color, width=1.5, capstyle="round", tags=tags)


def _icon_folder(cvs, cx, cy, color, tags):
    s = 7
    # Body
    cvs.create_line(cx-s, cy-s+3, cx+s, cy-s+3,
                    cx+s, cy+s, cx-s, cy+s, cx-s, cy-s+3,
                    fill=color, width=1.5, joinstyle="round", tags=tags)
    # Tab
    cvs.create_line(cx-s, cy-s+3, cx-s, cy-s-1,
                    cx-s+7, cy-s-1, cx-s+7, cy-s+3,
                    fill=color, width=1, tags=tags)


def _icon_settings(cvs, cx, cy, color, tags):
    # Center circle
    cvs.create_arc(cx-3, cy-3, cx+3, cy+3,
                   start=0, extent=359, style="arc",
                   outline=color, width=1.5, tags=tags)
    # 6 tick marks
    for i in range(6):
        a  = math.radians(i * 60)
        x1 = cx + math.cos(a) * 4.5
        y1 = cy + math.sin(a) * 4.5
        x2 = cx + math.cos(a) * 7.5
        y2 = cy + math.sin(a) * 7.5
        cvs.create_line(x1, y1, x2, y2,
                        fill=color, width=2.2, capstyle="round", tags=tags)


# ── Tooltip ───────────────────────────────────────────────────────────────────

class _Tooltip:
    def __init__(self, cvs: tk.Canvas, tags, text: str):
        self._cvs  = cvs
        self._text = text
        self._win: Optional[tk.Toplevel] = None
        self._job  = None
        if isinstance(tags, str):
            tags = [tags]
        for tag in tags:
            cvs.tag_bind(tag, "<Enter>", self._schedule)
            cvs.tag_bind(tag, "<Leave>", self._cancel)

    def update(self, text: str):
        self._text = text

    def _schedule(self, e):
        self._cancel()
        self._job = self._cvs.after(500, lambda: self._show(e))

    def _cancel(self, _=None):
        if self._job:
            self._cvs.after_cancel(self._job)
            self._job = None
        self._hide()

    def _show(self, e):
        x = self._cvs.winfo_rootx() + e.x + 14
        y = self._cvs.winfo_rooty() + e.y + 26
        self._win = tk.Toplevel(self._cvs)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.geometry(f"+{x}+{y}")
        self._win.configure(bg="#0A0A14")
        tk.Frame(self._win, bg=C["border_dim"], height=1).pack(fill="x")
        tk.Label(self._win, text=self._text,
                 bg="#0A0A14", fg="#C0C0D8",
                 font=F["button"],
                 padx=10, pady=5).pack()

    def _hide(self):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


# ── Pill Selector (inline FPS / Quality) ─────────────────────────────────────

class _PillSelector:
    """
    Inline pill-button selector drawn directly on the toolbar canvas.
    Displays a label + N fixed-width option pills.
    The active option is highlighted with a filled pill behind its text.
    Clicking redraws instantly.
    """
    OPT_W   = 30    # px per option
    OPT_H   = 20    # pill height
    OPT_GAP = 2     # gap between options
    LBL_W   = 22    # label reserve

    def __init__(self, cvs: tk.Canvas, x: int, cy: int,
                 options, active_idx: int,
                 accent: str, label: str,
                 on_change: Callable[[int], None] = None):
        self.cvs        = cvs
        self.x          = x
        self.cy         = cy
        self.options    = options
        self.active_idx = active_idx
        self.accent     = accent
        self.label_str  = label
        self._on_change = on_change
        self._ids       = []
        self._draw()

    @property
    def total_width(self) -> int:
        n = len(self.options)
        return self.LBL_W + n * self.OPT_W + (n - 1) * self.OPT_GAP

    def _opt_x(self, i: int) -> int:
        return self.x + self.LBL_W + i * (self.OPT_W + self.OPT_GAP)

    def _draw(self):
        for iid in self._ids:
            try:
                self.cvs.delete(iid)
            except Exception:
                pass
        self._ids.clear()

        cy  = self.cy
        h   = self.OPT_H

        # Label
        self._ids.append(self.cvs.create_text(
            self.x, cy, text=self.label_str,
            fill=C["text_dim"], font=F["label"], anchor="w"
        ))

        # Track background
        n = len(self.options)
        tx1 = self.x + self.LBL_W - 2
        tx2 = self.x + self.total_width + 2
        _fill_rrect(self.cvs, tx1, cy-h//2, tx2, cy+h//2,
                    h//2, C["bg_sunken"])

        # Options
        for i, opt in enumerate(self.options):
            ox  = self._opt_x(i)
            tag = f"psel_{id(self)}_{i}"
            is_active = (i == self.active_idx)

            if is_active:
                # Active pill fill
                _fill_rrect(self.cvs,
                            ox+1, cy-h//2+2,
                            ox+self.OPT_W-1, cy+h//2-2,
                            h//2-2, self.accent)

            tc = C["text_primary"] if is_active else C["text_secondary"]
            tid = self.cvs.create_text(
                ox + self.OPT_W // 2, cy,
                text=opt, fill=tc,
                font=F["button"],
                anchor="center", tags=tag
            )
            self._ids.append(tid)

            hit = self.cvs.create_rectangle(
                ox, cy-h//2-2, ox+self.OPT_W, cy+h//2+2,
                fill="", outline="", tags=tag
            )
            self._ids.append(hit)

            def _make_cb(idx):
                return lambda _: self.select(idx)
            self.cvs.tag_bind(tag, "<Button-1>", _make_cb(i))
            self.cvs.tag_bind(tag, "<Enter>",
                              lambda e: self.cvs.configure(cursor="hand2"))
            self.cvs.tag_bind(tag, "<Leave>",
                              lambda e: self.cvs.configure(cursor=""))

    def select(self, idx: int):
        if idx == self.active_idx:
            return
        self.active_idx = idx
        self._draw()
        if self._on_change:
            self._on_change(idx)

    @property
    def value(self) -> str:
        return self.options[self.active_idx]


# ══════════════════════════════════════════════════════════════════════════════
# Toolbar
# ══════════════════════════════════════════════════════════════════════════════

class Toolbar(tk.Tk):
    """
    Main floating toolbar for Soumo Screen Recorder PRO.

    A frameless, always-on-top pill-shaped window.
    The entire UI is drawn on a single Canvas.
    Every button uses the new Animator with hover/press/spring physics.
    """

    H = BAR_H
    W = BAR_W
    R = BAR_R

    def __init__(self):
        super().__init__()
        log.info("Toolbar starting — Python %s", sys.version.split()[0])

        self._settings  = load_settings()
        self._recorder  = ScreenRecorder()
        self._recorder.set_timer_callback(self._on_timer_tick)
        self._hotkeys   = HotkeyManager()
        self._toasts    = ToastManager(self)
        self._region:   Optional[Tuple[int,int,int,int]] = None
        self._settings_panel: Optional[SettingsPanel] = None
        self._rec_lock  = threading.Lock()
        self._drag_ox   = 0
        self._drag_oy   = 0

        self.animator   = Animator(self)
        self._btn_info: Dict[str, Dict] = {}

        # ── Window ────────────────────────────────────────────────────────
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.wm_attributes("-transparentcolor", _HOLE)
        self.configure(bg=_HOLE)

        sw  = self.winfo_screenwidth()
        sx  = self._settings.toolbar_x
        sy  = self._settings.toolbar_y
        if sx < 0 or sx + self.W > sw:
            sx = (sw - self.W) // 2
        sy = max(sy, 10)
        self.geometry(f"{self.W}x{self.H}+{sx}+{sy}")

        # ── Canvas ─────────────────────────────────────────────────────────
        self.cvs = tk.Canvas(
            self, width=self.W, height=self.H,
            bg=_HOLE, highlightthickness=0, bd=0
        )
        self.cvs.pack()

        self._build()
        self._apply_capture_exclusion()
        self._register_hotkeys()
        self.after(100, self._slide_in)
        self.bind("<Configure>", self._save_pos)

    # ── Setup ──────────────────────────────────────────────────────────────

    def _apply_capture_exclusion(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            log.info("WDA_EXCLUDEFROMCAPTURE applied")
        except Exception as e:
            log.warning("Capture exclusion failed: %s", e)

    def _register_hotkeys(self):
        self._hotkeys.register("ctrl+shift+r",
                               lambda: self.after(0, self._toggle_record))
        self._hotkeys.register("ctrl+shift+s",
                               lambda: self.after(0, self._do_screenshot))

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self):
        cvs = self.cvs
        W, H, R = self.W, self.H, self.R
        cy = H // 2

        # ── Background layers ──────────────────────────────────────────────
        # Drop shadow (slightly offset, slightly larger dark pill)
        _fill_pill(cvs, 2, 4, W-2, H+4, "#020208")
        # Main surface
        _fill_pill(cvs, 0, 0, W, H, C["bg_surface"], tags="bg")
        # Top rim light (simulates glass catching top light)
        cvs.create_line(R, 1, W-R, 1, fill="#FFFFFF0F", width=1)
        # Bottom rim dark
        cvs.create_line(R, H-1, W-R, H-1, fill="#00000055", width=1)
        # Outer border
        _outline_pill(cvs, 0, 0, W, H, C["border_subtle"], width=1)

        # Drag on background
        cvs.tag_bind("bg", "<ButtonPress-1>", self._drag_start)
        cvs.tag_bind("bg", "<B1-Motion>",     self._drag_move)

        x = 14

        # ── Grip dots ──────────────────────────────────────────────────────
        gx = x + 1
        for row in range(3):
            for col in range(2):
                cvs.create_oval(
                    gx + col*5, cy-5+row*5,
                    gx + col*5+2, cy-5+row*5+2,
                    fill=C["text_dim"], outline="", tags="grip"
                )
        cvs.tag_bind("grip", "<ButtonPress-1>", self._drag_start)
        cvs.tag_bind("grip", "<B1-Motion>",     self._drag_move)
        cvs.tag_bind("grip", "<Enter>", lambda _: cvs.configure(cursor="fleur"))
        cvs.tag_bind("grip", "<Leave>", lambda _: cvs.configure(cursor=""))
        x += 16

        # ── Brand dot (macOS-style red dot = your brand color) ────────────
        cvs.create_oval(x, cy-4, x+8, cy+4,
                        fill=C["red"], outline="")
        x += 14

        # ── Brand text ─────────────────────────────────────────────────────
        cvs.create_text(x, cy, text="SOUMO",
                        fill=C["text_secondary"],
                        font=F["brand"],
                        anchor="w", tags="brand_text")
        cvs.tag_bind("brand_text", "<ButtonPress-1>", self._drag_start)
        cvs.tag_bind("brand_text", "<B1-Motion>",     self._drag_move)
        x += 56

        # ── Divider ────────────────────────────────────────────────────────
        x = self._divider(x) + 12

        # ── Buttons ────────────────────────────────────────────────────────
        R_BTN = 16  # button circle radius

        # Screenshot
        self._btn(
            x + R_BTN, cy, R_BTN, "btn_cam",
            _icon_camera,
            bg=(C["blue_dim"],   "#1A3A5C"),
            bd=(C["border_dim"], C["blue"]),
            ic=(C["text_secondary"], C["blue"]),
            cmd=self._do_screenshot
        )
        self._tt_cam = _Tooltip(cvs,
            ["btn_cam", "btn_cam_bg", "btn_cam_icon"],
            "Screenshot   Ctrl+Shift+S")
        x += R_BTN*2 + 5

        # Record  (shares position with Pause — one is hidden at all times)
        self._btn(
            x + R_BTN, cy, R_BTN, "btn_rec",
            _icon_record,
            bg=(C["red_dim"],  "#4A1515"),
            bd=("#4A1515",     C["red"]),
            ic=(C["red"],      C["red_glow"]),
            cmd=self._toggle_record
        )
        self._tt_rec = _Tooltip(cvs,
            ["btn_rec", "btn_rec_bg", "btn_rec_icon"],
            "Start Recording   Ctrl+Shift+R")

        self._btn(
            x + R_BTN, cy, R_BTN, "btn_pause",
            _icon_pause,
            bg=(C["amber_dim"], "#3A2C00"),
            bd=("#3A2C00",      C["amber"]),
            ic=(C["amber"],     "#FFD040"),
            cmd=self._toggle_pause
        )
        _Tooltip(cvs,
            ["btn_pause", "btn_pause_bg", "btn_pause_icon"],
            "Pause / Resume recording")
        self._hide_btn("btn_pause")
        x += R_BTN*2 + 5

        # Region select
        self._btn(
            x + R_BTN, cy, R_BTN, "btn_region",
            _icon_region,
            bg=(C["purple_dim"], "#2A1A48"),
            bd=("#2A1A48",       C["purple"]),
            ic=(C["text_secondary"], C["purple"]),
            cmd=self._do_region
        )
        cvs.tag_bind("btn_region", "<Button-3>",
                     lambda _: self._clear_region())
        _Tooltip(cvs,
            ["btn_region", "btn_region_bg", "btn_region_icon"],
            "Select capture region   Right-click clears")
        x += R_BTN*2 + 5

        # Open folder
        self._btn(
            x + R_BTN, cy, R_BTN, "btn_folder",
            _icon_folder,
            bg=(C["green_dim"], "#1A3A28"),
            bd=("#1A3A28",      C["green"]),
            ic=(C["text_secondary"], C["green"]),
            cmd=self._open_folder
        )
        _Tooltip(cvs,
            ["btn_folder", "btn_folder_bg", "btn_folder_icon"],
            "Open recordings folder")
        x += R_BTN*2 + 5

        # Settings
        self._btn(
            x + R_BTN, cy, R_BTN, "btn_settings",
            _icon_settings,
            bg=(C["bg_elevated"], "#1E1E2C"),
            bd=(C["border_dim"],  C["purple"]),
            ic=(C["text_secondary"], C["purple"]),
            cmd=self._open_settings
        )
        _Tooltip(cvs,
            ["btn_settings", "btn_settings_bg", "btn_settings_icon"],
            "Settings")
        x += R_BTN*2 + 10

        # Region label (shows "Full Screen" or "1920×1080")
        self._region_tid = cvs.create_text(
            x, cy, text="Full Screen",
            fill=C["text_dim"],
            font=("Segoe UI", 8),
            anchor="w"
        )
        x += 66

        # ── Divider ────────────────────────────────────────────────────────
        x = self._divider(x) + 12

        # ── FPS Selector ───────────────────────────────────────────────────
        fps_opts = ["30", "60", "120", "144"]
        fps_vals = [30,   60,  120,  144]
        fps_idx  = 1
        try:
            fps_idx = fps_vals.index(self._settings.fps)
        except ValueError:
            pass

        self._fps_sel = _PillSelector(
            cvs, x, cy,
            options=fps_opts,
            active_idx=fps_idx,
            accent=C["red"],
            label="FPS",
            on_change=lambda i: self._on_fps(fps_vals[i])
        )
        x += self._fps_sel.total_width + 10

        # ── Quality Selector ───────────────────────────────────────────────
        q_opts = ["Lo",   "Med",    "Hi",    "4K"]
        q_vals = ["Low",  "Medium", "High",  "Ultra"]
        q_idx  = 2
        try:
            q_idx = q_vals.index(self._settings.quality)
        except ValueError:
            pass

        self._q_sel = _PillSelector(
            cvs, x, cy,
            options=q_opts,
            active_idx=q_idx,
            accent=C["blue"],
            label="Q",
            on_change=lambda i: self._on_quality(q_vals[i])
        )
        x += self._q_sel.total_width + 10

        # ── Divider ────────────────────────────────────────────────────────
        x = self._divider(x) + 12

        # ── Timer ─────────────────────────────────────────────────────────
        self._timer_tid = cvs.create_text(
            x, cy, text="00:00:00",
            fill=C["text_dim"],
            font=F["timer"],
            anchor="w"
        )
        x += 94

        # ── Close ─────────────────────────────────────────────────────────
        self._close_tid = cvs.create_text(
            x, cy, text="✕",
            fill=C["text_dim"],
            font=("Segoe UI", 11),
            anchor="w", tags="close_btn"
        )
        cvs.tag_bind("close_btn", "<Button-1>", lambda _: self._quit())
        cvs.tag_bind("close_btn", "<Enter>",
                     lambda _: cvs.itemconfig(self._close_tid, fill=C["red"]))
        cvs.tag_bind("close_btn", "<Leave>",
                     lambda _: cvs.itemconfig(self._close_tid, fill=C["text_dim"]))

        # ── Recording bottom bar ───────────────────────────────────────────
        self._rec_bar = cvs.create_line(
            R, H-1, W-R, H-1,
            fill=C["red"], width=2,
            state="hidden"
        )

        log.info("Toolbar built. Width cursor: %d / %d", x, self.W)

    def _divider(self, x: int) -> int:
        mid = self.H // 2
        self.cvs.create_line(x+1, mid-10, x+1, mid+10,
                              fill=C["border_subtle"], width=1)
        return x + 2

    # ── Button system ──────────────────────────────────────────────────────

    def _btn(self, cx, cy, r, tag,
             icon_fn: Callable,
             bg: Tuple[str, str],
             bd: Tuple[str, str],
             ic: Tuple[str, str],
             cmd: Optional[Callable] = None):
        """
        Draw a circular button and bind hover/press/release animations.

        Args:
            cx, cy:  Center coordinates.
            r:       Radius in pixels.
            tag:     Unique tag string.
            icon_fn: Icon drawing function(cvs, cx, cy, color, tags).
            bg:      (idle_fill, hover_fill) hex colors.
            bd:      (idle_border, hover_border) hex colors.
            ic:      (idle_icon, hover_icon) hex colors.
            cmd:     Click command callable.
        """
        self._btn_info[tag] = {
            "cx": cx, "cy": cy, "r": r,
            "bg_idle": bg[0], "bg_hover": bg[1],
            "bd_idle": bd[0], "bd_hover": bd[1],
            "ic_idle": ic[0], "ic_hover": ic[1],
        }

        # Circle background
        self.cvs.create_oval(
            cx-r, cy-r, cx+r, cy+r,
            fill=bg[0], outline=bd[0], width=1,
            tags=(tag, tag+"_bg")
        )

        # Icon
        icon_fn(self.cvs, cx, cy, ic[0], tags=(tag, tag+"_icon"))

        # Bind events on all sub-items
        for sub in (tag, tag+"_bg", tag+"_icon"):
            self.cvs.tag_bind(sub, "<Enter>",
                lambda e, t=tag: self._enter(t))
            self.cvs.tag_bind(sub, "<Leave>",
                lambda e, t=tag: self._leave(t))
            self.cvs.tag_bind(sub, "<ButtonPress-1>",
                lambda e, t=tag: self._press(t))
            self.cvs.tag_bind(sub, "<ButtonRelease-1>",
                lambda e, t=tag, c=cmd: self._release(t, c))

    def _enter(self, tag: str):
        self.animator.animate(f"{tag}_h", 0.0, 1.0, 120, "ease_out_cubic",
            on_update=lambda v: self._color_btn(tag, v))

    def _leave(self, tag: str):
        self.animator.animate(f"{tag}_h", 1.0, 0.0, 200, "ease_in_out_sine",
            on_update=lambda v: self._color_btn(tag, v))

    def _press(self, tag: str):
        self.animator.animate(f"{tag}_s", 1.0, 0.86, 80, "ease_out_cubic",
            on_update=lambda v: self._scale_btn(tag, v))

    def _release(self, tag: str, cmd: Optional[Callable]):
        self.animator.animate(f"{tag}_s", 0.86, 1.0, 300, "spring",
            on_update=lambda v: self._scale_btn(tag, v))
        if cmd:
            self.after(20, cmd)

    def _color_btn(self, tag: str, t: float):
        info = self._btn_info.get(tag)
        if not info:
            return
        bg = interpolate_color(info["bg_idle"], info["bg_hover"], t)
        bd = interpolate_color(info["bd_idle"], info["bd_hover"], t)
        ic = interpolate_color(info["ic_idle"], info["ic_hover"], t)
        try:
            self.cvs.itemconfig(tag+"_bg",   fill=bg, outline=bd)
            self.cvs.itemconfig(tag+"_icon", fill=ic, outline=ic)
        except Exception:
            pass

    def _scale_btn(self, tag: str, scale: float):
        info = self._btn_info.get(tag)
        if not info:
            return
        cx, cy, r = info["cx"], info["cy"], info["r"]
        sr = r * scale
        try:
            self.cvs.coords(tag+"_bg", cx-sr, cy-sr, cx+sr, cy+sr)
        except Exception:
            pass

    def _hide_btn(self, tag: str):
        for sub in (tag, tag+"_bg", tag+"_icon"):
            try:
                self.cvs.itemconfig(sub, state="hidden")
            except Exception:
                pass

    def _show_btn(self, tag: str):
        for sub in (tag, tag+"_bg", tag+"_icon"):
            try:
                self.cvs.itemconfig(sub, state="normal")
            except Exception:
                pass

    # ── Recording bar & pulse ──────────────────────────────────────────────

    def _show_rec_bar(self):
        self.cvs.itemconfig(self._rec_bar, state="normal")
        self.animator.pulse(
            "rec_bar", period_ms=1600,
            on_update=lambda v: self.cvs.itemconfig(
                self._rec_bar,
                fill=interpolate_color(C["red"], C["red_glow"], v)
            )
        )

    def _hide_rec_bar(self):
        self.animator.stop("rec_bar")
        self.cvs.itemconfig(self._rec_bar, state="hidden")

    def _start_rec_pulse(self):
        self.animator.pulse(
            "rec_pulse", period_ms=1800,
            on_update=self._apply_rec_glow
        )

    def _apply_rec_glow(self, v: float):
        bg = interpolate_color("#2D0E0F", "#5A1818", v)
        bd = interpolate_color("#4A1515", C["red"],      v)
        ic = interpolate_color("#8B1A1A", C["red_glow"], v)
        try:
            self.cvs.itemconfig("btn_rec_bg",   fill=bg, outline=bd)
            self.cvs.itemconfig("btn_rec_icon", fill=ic, outline=ic)
        except Exception:
            pass

    def _stop_rec_pulse(self):
        self.animator.stop("rec_pulse")
        info = self._btn_info.get("btn_rec", {})
        try:
            self.cvs.itemconfig("btn_rec_bg",
                fill=info.get("bg_idle", C["red_dim"]),
                outline=info.get("bd_idle", "#4A1515"))
            self.cvs.itemconfig("btn_rec_icon",
                fill=C["red"], outline=C["red"])
        except Exception:
            pass

    # ── Slide-in animation ─────────────────────────────────────────────────

    def _slide_in(self):
        x     = self.winfo_x()
        y_end = self.winfo_y()
        self.animator.animate(
            "slide_in",
            start=float(-self.H - 10),
            end=float(y_end),
            duration_ms=420,
            easing="ease_out_cubic",
            on_update=lambda y: (
                self.geometry(f"+{x}+{int(y)}"),
                self.attributes("-alpha", max(0.0, min(1.0,
                    (y + self.H + 10) / max(y_end + self.H + 10, 1))))
            )
        )

    # ── Drag ──────────────────────────────────────────────────────────────

    def _drag_start(self, e):
        self._drag_ox = e.x_root - self.winfo_x()
        self._drag_oy = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._drag_ox}+{e.y_root - self._drag_oy}")

    def _save_pos(self, _=None):
        try:
            self._settings.toolbar_x = self.winfo_x()
            self._settings.toolbar_y = self.winfo_y()
            save_settings(self._settings)
        except Exception:
            pass

    # ── Timer (called from recorder background thread) ─────────────────────

    def _on_timer_tick(self, time_str: str):
        if self._recorder.is_paused:
            return
        self.after(0, lambda: self._set_timer(time_str, C["red"]))

    def _set_timer(self, text: str, color: str = None):
        if color is None:
            color = C["text_dim"]
        try:
            self.cvs.itemconfig(self._timer_tid, text=text, fill=color)
        except Exception:
            pass

    # ── Selectors ──────────────────────────────────────────────────────────

    def _on_fps(self, fps: int):
        self._settings.fps = fps
        save_settings(self._settings)

    def _on_quality(self, quality: str):
        self._settings.quality = quality
        save_settings(self._settings)

    # ── Actions ────────────────────────────────────────────────────────────

    def _open_folder(self):
        p = self._settings.output_folder
        os.makedirs(p, exist_ok=True)
        os.startfile(p)

    def _open_settings(self):
        if not self._settings_panel:
            self._settings_panel = SettingsPanel(
                self, self._settings,
                on_close=lambda: setattr(self, "_settings_panel", None)
            )
        self._settings_panel.toggle()

    def _do_region(self):
        if self._recorder.is_recording:
            self._toasts.show("Region Locked", "Stop recording first.", "error")
            return
        self._set_timer("SELECT", C["purple"])
        self.iconify()
        self.after(200, lambda: RegionSelector(self._on_region_done).run())

    def _on_region_done(self, region):
        self.deiconify()
        self._region = region
        if region:
            l, t, r, b = region
            w, h = r-l, b-t
            self.after(0, lambda: (
                self.cvs.itemconfig(self._region_tid,
                    text=f"{w}\u00d7{h}", fill=C["amber"]),
                self._set_timer("00:00:00")
            ))
            self._toasts.show("Region Set", f"{w}\u00d7{h} px", "info")
        else:
            self.after(0, lambda: (
                self.cvs.itemconfig(self._region_tid,
                    text="Full Screen", fill=C["text_dim"]),
                self._set_timer("00:00:00")
            ))

    def _clear_region(self):
        self._region = None
        self.cvs.itemconfig(self._region_tid,
            text="Full Screen", fill=C["text_dim"])
        self._toasts.show("Region Cleared", "Capturing full screen.", "info")

    def _do_screenshot(self):
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self._settings.output_folder,
                            f"Screenshot_{ts}.png")
        os.makedirs(self._settings.output_folder, exist_ok=True)
        self._flash()
        self._set_timer("SNAP!", C["blue"])

        def _do():
            ok = take_screenshot(
                monitor_index=self._settings.monitor,
                output_path=path,
                region=self._region,
                copy_to_clipboard=self._settings.copy_screenshot,
            )
            self.after(0, lambda: self._set_timer("00:00:00"))
            if ok:
                self._toasts.show("Screenshot Saved", os.path.basename(path),
                                  "success", file_path=path)
            else:
                self._toasts.show("Screenshot Failed",
                                  "Could not capture frame.", "error")

        threading.Thread(target=_do, daemon=True, name="ss").start()

    def _flash(self):
        """White full-screen flash (camera shutter effect)."""
        try:
            win = tk.Toplevel(self)
            win.overrideredirect(True)
            win.attributes("-fullscreen", True)
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.0)
            win.configure(bg="#FFFFFF")
            try:
                hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
                ctypes.windll.user32.SetWindowDisplayAffinity(
                    hwnd, WDA_EXCLUDEFROMCAPTURE)
            except Exception:
                pass
            self.animator.animate(
                "flash", 0.18, 0.0, 280, "ease_out_cubic",
                on_update=lambda v: win.attributes("-alpha", max(0, v)),
                on_done=win.destroy
            )
        except Exception:
            pass

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
            self.after(800, self._rec_lock.release)

    def _start_recording(self):
        ts   = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fps  = self._settings.fps
        qual = self._settings.quality
        ext  = {"MP4": "mp4", "MKV": "mkv", "WebM": "webm"}.get(
                   self._settings.output_format, "mp4")
        path = os.path.join(self._settings.output_folder,
                            f"soumo_{ts}_{qual}_{fps}fps.{ext}")
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
                self.after(0, lambda: (
                    self._hide_btn("btn_rec"),
                    self._show_btn("btn_pause"),
                    self._start_rec_pulse(),
                    self._show_rec_bar(),
                    self._tt_rec.update("Stop Recording   Ctrl+Shift+R"),
                ))
            except RuntimeError as e:
                self._toasts.show("Recording Failed", str(e), "error")
                self.after(0, lambda: self._set_timer("ERROR", C["red"]))
            except Exception as e:
                log.exception("start_recording exception")
                self._toasts.show("Error", str(e), "error")

        threading.Thread(target=_do, daemon=True, name="rec-start").start()

    def _stop_recording(self):
        self.after(0, lambda: (
            self._show_btn("btn_rec"),
            self._hide_btn("btn_pause"),
            self._stop_rec_pulse(),
            self._hide_rec_bar(),
            self._set_timer("SAVING", C["amber"]),
            self._tt_rec.update("Start Recording   Ctrl+Shift+R"),
        ))

        def _do():
            try:
                self._recorder.stop_recording()
                fname = os.path.basename(self._recorder.output_file)
                self.after(0, lambda: self._set_timer("\u2713 SAVED", C["green"]))
                self._toasts.show("Recording Saved", fname, "success",
                                  file_path=self._recorder.output_file)
                if self._settings.auto_open:
                    try:
                        os.startfile(self._recorder.output_file)
                    except Exception:
                        pass
            except Exception as e:
                log.exception("stop_recording exception")
                self._toasts.show("Save Failed", str(e), "error")
                self.after(0, lambda: self._set_timer("ERROR", C["red"]))
            finally:
                self.after(2800, lambda: self._set_timer("00:00:00"))

        threading.Thread(target=_do, daemon=True, name="rec-stop").start()

    def _toggle_pause(self):
        if not self._recorder.is_recording:
            return
        if self._recorder.is_paused:
            self._recorder.resume_recording()
            self._start_rec_pulse()
        else:
            self._recorder.pause_recording()
            self.animator.stop("rec_pulse")
            self._set_timer("PAUSED", C["amber"])
            # Reset button colors to idle
            self._stop_rec_pulse()

    # ── Quit ──────────────────────────────────────────────────────────────

    def _quit(self):
        self._hotkeys.unregister_all()
        self.animator.stop_all()
        if self._recorder.is_recording:
            threading.Thread(target=self._recorder.stop_recording,
                            daemon=True).start()
        save_settings(self._settings)
        self.after(300, self.destroy)
