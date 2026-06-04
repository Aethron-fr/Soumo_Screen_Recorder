"""
ui/settings_panel.py
Settings panel — slides in from the right edge of the screen.

Design philosophy:
  - Same dark glass material as the toolbar
  - 300px wide, full screen height
  - Slides in 280ms ease_out_cubic, slides out 220ms ease_in_out_sine
  - Canvas-drawn pill toggles with animated knob
  - Segmented selectors for multi-choice settings
  - No CustomTkinter dependency — pure Tkinter + canvas
"""
from __future__ import annotations
import tkinter as tk
import os
import logging
from typing import Optional, Callable

from utils.animations import Animator, interpolate_color
from utils.settings   import Settings, save_settings

log = logging.getLogger(__name__)

# ── Design tokens ─────────────────────────────────────────────────────────────
BG       = "#0D0D16"
SURFACE  = "#0F0F18"
ELEVATED = "#16161F"
BORDER   = "#1E1E2E"
BORDER2  = "#2A2A3C"
TP       = "#E8E8F0"
TS       = "#6B6B8A"
TD       = "#3A3A55"
RED      = "#E5383B"
BLUE     = "#4A9EFF"
GREEN    = "#3DDC84"
AMBER    = "#FFB800"
PURPLE   = "#A78BFA"

PANEL_W  = 300

# ── Pill Toggle ───────────────────────────────────────────────────────────────

class PillToggle(tk.Canvas):
    """
    Canvas-drawn animated pill toggle.
    Knob slides smoothly between off (left) and on (right).
    """
    W, H    = 44, 24
    ON_CLR  = GREEN
    OFF_CLR = "#1E1E2E"

    def __init__(self, parent, value: bool = False,
                 on_change: Callable[[bool], None] = None, **kw):
        kw.setdefault("bg", ELEVATED)
        kw.setdefault("highlightthickness", 0)
        super().__init__(parent, width=self.W, height=self.H, **kw)
        self._value     = value
        self._on_change = on_change
        self._knob_x    = self._target_x()
        self.bind("<Button-1>", self._click)
        self._draw()
        self._anim = Animator(self)

    def _target_x(self) -> int:
        return (self.W - self.H // 2) if self._value else (self.H // 2)

    def _draw(self, knob_x: Optional[float] = None):
        self.delete("all")
        kx  = int(knob_x if knob_x is not None else self._knob_x)
        col = self.ON_CLR if self._value else self.OFF_CLR
        r   = self.H // 2
        # Track
        self.create_oval(0, 0, self.H, self.H,           fill=col, outline="")
        self.create_oval(self.W-self.H, 0, self.W, self.H, fill=col, outline="")
        self.create_rectangle(r, 0, self.W-r, self.H,   fill=col, outline="")
        # Knob
        p = 3
        self.create_oval(kx-r+p, p, kx+r-p, self.H-p, fill="#F0F0FA", outline="")

    def _click(self, _=None):
        start_x = self._knob_x
        self._value = not self._value
        end_x = self._target_x()
        self._anim.animate(
            "knob", start_x, end_x, 180, "ease_out_cubic",
            on_update=lambda v: (setattr(self, "_knob_x", v), self._draw(v))
        )
        if self._on_change:
            self._on_change(self._value)

    def get(self) -> bool:
        return self._value

    def set(self, val: bool):
        if self._value != val:
            self._value = val
            self._knob_x = self._target_x()
            self._draw()


# ── Settings Panel ────────────────────────────────────────────────────────────

class SettingsPanel:
    """
    Right-sliding settings panel.

    Args:
        root:     Parent Tk window.
        settings: Shared Settings dataclass.
        on_close: Called when panel is dismissed.
    """

    def __init__(self, root: tk.Tk, settings: Settings,
                 on_close: Callable = None):
        self._root     = root
        self._settings = settings
        self._on_close = on_close
        self.is_visible = False
        self._win: Optional[tk.Toplevel] = None
        self._animator = Animator(root)

    def show(self):
        """Build and slide in the panel."""
        if self._win and self._win.winfo_exists():
            self._win.lift()
            return

        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()

        self._win = tk.Toplevel(self._root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0.0)
        self._win.geometry(f"{PANEL_W}x{sh}+{sw}+0")
        self._win.configure(bg=BG)
        self._win.protocol("WM_DELETE_WINDOW", self.hide)

        self._build(sh)
        self._win.update_idletasks()
        self._win.attributes("-alpha", 0.97)

        end_x = sw - PANEL_W
        self._animator.animate(
            "panel_slide", float(sw), float(end_x), 280, "ease_out_cubic",
            on_update=lambda x: (
                self._win.geometry(f"{PANEL_W}x{sh}+{int(x)}+0")
                if self._win and self._win.winfo_exists() else None
            )
        )
        self.is_visible = True

    def hide(self):
        """Slide out and destroy."""
        if not self._win or not self._win.winfo_exists():
            self.is_visible = False
            return
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        cur_x = float(self._win.winfo_x())

        self._animator.animate(
            "panel_slide", cur_x, float(sw), 220, "ease_in_out_sine",
            on_update=lambda x: (
                self._win.geometry(f"{PANEL_W}x{sh}+{int(x)}+0")
                if self._win and self._win.winfo_exists() else None
            ),
            on_done=self._destroy
        )
        self.is_visible = False
        if self._on_close:
            self._on_close()

    def _destroy(self):
        try:
            if self._win:
                self._win.destroy()
                self._win = None
        except Exception:
            pass

    def toggle(self):
        if self.is_visible:
            self.hide()
        else:
            self.show()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self, sh: int):
        win = self._win

        # Header
        hdr = tk.Frame(win, bg="#0A0A14", height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="SETTINGS",
                 bg="#0A0A14", fg=TP,
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=18, pady=16)

        close_btn = tk.Label(hdr, text="✕", bg="#0A0A14", fg=TS,
                              font=("Segoe UI", 12), cursor="hand2", padx=14)
        close_btn.pack(side="right")
        close_btn.bind("<Enter>", lambda _: close_btn.configure(fg=RED))
        close_btn.bind("<Leave>", lambda _: close_btn.configure(fg=TS))
        close_btn.bind("<Button-1>", lambda _: self.hide())

        # 1px separator
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x")

        # Scrollable body
        container = tk.Frame(win, bg=SURFACE)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, bg=SURFACE, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._body = tk.Frame(canvas, bg=SURFACE)
        canvas_window = canvas.create_window(0, 0, anchor="nw", window=self._body)

        def _resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_window, width=canvas.winfo_width())
        self._body.bind("<Configure>", _resize)
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        self._build_body()

        # Apply button
        apply_row = tk.Frame(win, bg="#0A0A14", height=60)
        apply_row.pack(fill="x", side="bottom")
        apply_row.pack_propagate(False)
        apply_btn = tk.Label(apply_row, text="APPLY  CHANGES",
                              bg=RED, fg="#FFFFFF",
                              font=("Segoe UI", 11, "bold"),
                              cursor="hand2", pady=0)
        apply_btn.pack(fill="both", padx=16, pady=12, expand=True)
        apply_btn.bind("<Enter>", lambda _: apply_btn.configure(bg="#FF4040"))
        apply_btn.bind("<Leave>", lambda _: apply_btn.configure(bg=RED))
        apply_btn.bind("<Button-1>", lambda _: self._apply())

    def _build_body(self):
        s = self._settings

        # Capture
        f = self._section("CAPTURE")
        self._mon_var = tk.StringVar(value=f"Monitor {s.monitor}")
        self._row_combo(f, "Monitor",
                        ["Monitor 0", "Monitor 1", "Monitor 2"],
                        self._mon_var)
        self._fps_var = tk.StringVar(value=str(s.fps))
        self._row_combo(f, "FPS",
                        ["30", "60", "120", "144"],
                        self._fps_var)

        # Encoding
        f = self._section("ENCODING")
        self._q_var = tk.StringVar(value=s.quality)
        self._row_combo(f, "Quality",
                        ["Low", "Medium", "High", "Ultra"],
                        self._q_var)
        self._color_var = tk.StringVar(value=s.color_grade)
        self._row_combo(f, "Color Grade",
                        ["Neutral", "Vibrant", "Cinematic", "Warm", "Cool"],
                        self._color_var)
        self._fmt_var = tk.StringVar(value=s.output_format)
        self._row_combo(f, "Format",
                        ["MP4", "MKV", "WebM"],
                        self._fmt_var)

        # Audio
        f = self._section("AUDIO")
        self._audio_tog = self._row_toggle(f, "System Audio (WASAPI)", s.audio_enabled)
        self._mic_tog   = self._row_toggle(f, "Microphone Input",      s.mic_enabled)

        # Recording
        f = self._section("RECORDING")
        self._countdown_tog  = self._row_toggle(f, "3-2-1 Countdown",           s.countdown_enabled)
        self._auto_open_tog  = self._row_toggle(f, "Auto-open after save",       s.auto_open)
        self._copy_ss_tog    = self._row_toggle(f, "Copy screenshot to clipboard", s.copy_screenshot)

        # Output
        f = self._section("OUTPUT")
        path_row = tk.Frame(f, bg=ELEVATED)
        path_row.pack(fill="x", padx=12, pady=6)
        tk.Label(path_row, text="Save To", bg=ELEVATED, fg=TS,
                 font=("Segoe UI", 9), width=14, anchor="w").pack(side="left")
        self._path_lbl = tk.Label(path_row,
                                   text=self._shorten(s.output_folder),
                                   bg=ELEVATED, fg=TD,
                                   font=("Segoe UI", 8),
                                   anchor="e")
        self._path_lbl.pack(side="right", fill="x", expand=True)

        btn_row = tk.Frame(f, bg=ELEVATED)
        btn_row.pack(fill="x", padx=12, pady=(0, 8))
        self._action_btn(btn_row, "Browse…",     self._browse)
        self._action_btn(btn_row, "Open Folder",
                          lambda: os.startfile(s.output_folder)
                          if os.path.exists(s.output_folder) else None)

        # Hotkeys
        f = self._section("HOTKEYS")
        for label, key in [
            ("Start / Stop Recording", "Ctrl+Shift+R"),
            ("Take Screenshot",        "Ctrl+Shift+S"),
            ("Cancel Region",          "Escape"),
        ]:
            r = tk.Frame(f, bg=ELEVATED)
            r.pack(fill="x", padx=12, pady=5)
            tk.Label(r, text=label, bg=ELEVATED, fg=TS,
                     font=("Segoe UI", 9)).pack(side="left")
            tk.Label(r, text=key, bg="#0A0A14", fg=TP,
                     font=("Consolas", 9), padx=6, pady=2).pack(side="right")

    # ── Section + Row builders ─────────────────────────────────────────────

    def _section(self, title: str) -> tk.Frame:
        tk.Frame(self._body, bg=BORDER, height=1).pack(fill="x", pady=(14, 0))
        tk.Label(self._body, text=title, bg=SURFACE, fg=TD,
                 font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x", padx=16, pady=(6, 2))
        f = tk.Frame(self._body, bg=ELEVATED)
        f.pack(fill="x", padx=16, pady=(0, 4))
        return f

    def _row_combo(self, parent, label, values, var):
        r = tk.Frame(parent, bg=ELEVATED)
        r.pack(fill="x", padx=12, pady=5)
        tk.Label(r, text=label, bg=ELEVATED, fg=TS,
                 font=("Segoe UI", 9), width=14, anchor="w").pack(side="left")
        om = tk.OptionMenu(r, var, *values)
        om.configure(bg="#0A0A14", fg=TP, activebackground=ELEVATED,
                     activeforeground=TP, highlightthickness=0,
                     relief="flat", font=("Segoe UI", 9),
                     indicatoron=False, padx=8)
        om["menu"].configure(bg="#0A0A14", fg=TP,
                              activebackground=ELEVATED,
                              activeforeground=TP,
                              relief="flat")
        om.pack(side="right")

    def _row_toggle(self, parent, label, initial) -> PillToggle:
        r = tk.Frame(parent, bg=ELEVATED)
        r.pack(fill="x", padx=12, pady=7)
        tk.Label(r, text=label, bg=ELEVATED, fg=TS,
                 font=("Segoe UI", 9)).pack(side="left")
        tog = PillToggle(r, value=initial, bg=ELEVATED)
        tog.pack(side="right")
        return tog

    def _action_btn(self, parent, text, cmd):
        btn = tk.Label(parent, text=text, bg="#0A0A14", fg=TS,
                       font=("Segoe UI", 8), padx=8, pady=3, cursor="hand2")
        btn.pack(side="left", padx=(0, 6), pady=4)
        btn.bind("<Enter>", lambda _: btn.configure(fg=TP))
        btn.bind("<Leave>", lambda _: btn.configure(fg=TS))
        btn.bind("<Button-1>", lambda _: cmd())

    def _shorten(self, path: str, max_len: int = 28) -> str:
        if len(path) <= max_len:
            return path
        return "…" + path[-(max_len-1):]

    def _browse(self):
        folder = tk.filedialog.askdirectory(
            initialdir=self._settings.output_folder,
            parent=self._win
        )
        if folder:
            self._settings.output_folder = folder
            self._path_lbl.configure(text=self._shorten(folder))

    def _apply(self):
        s = self._settings
        try:
            mon_str = self._mon_var.get()
            s.monitor = int(''.join(c for c in mon_str if c.isdigit()) or "0")
        except Exception:
            s.monitor = 0
        try:
            s.fps = int(self._fps_var.get())
        except Exception:
            s.fps = 60

        s.quality           = self._q_var.get()
        s.color_grade       = self._color_var.get()
        s.output_format     = self._fmt_var.get()
        s.audio_enabled     = self._audio_tog.get()
        s.mic_enabled       = self._mic_tog.get()
        s.countdown_enabled = self._countdown_tog.get()
        s.auto_open         = self._auto_open_tog.get()
        s.copy_screenshot   = self._copy_ss_tog.get()
        save_settings(s)
        log.info("Settings applied and saved")
        self.hide()
