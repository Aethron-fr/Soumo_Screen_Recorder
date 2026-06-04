"""
ui/settings_panel.py
Settings panel — slides in from the right side of the screen.

Design:
  - 320px wide, full screen height
  - Same dark glass material as toolbar
  - Slides in from right edge with ease_out_cubic, 320ms
  - Sections with clear headers and dividers
  - Custom pill toggles (animated)
  - Pill selectors for multi-value settings
  - Persists all settings on Apply
"""
from __future__ import annotations
import customtkinter as ctk
import tkinter as tk
import os
import logging
from typing import Optional, Callable

from utils.settings  import Settings, save_settings
from utils.animations import Animator, ease_out_cubic

log = logging.getLogger(__name__)

# ── Palette ────────────────────────────────────────────────────────────────────
BG       = "#0D0D14"
SURFACE  = "#13131E"
ELEVATED = "#1C1C2A"
BORDER   = "#222232"
TEXT_P   = "#F0F0F5"
TEXT_S   = "#8888AA"
TEXT_DIM = "#555570"
RED      = "#C0392B"
BLUE     = "#3498DB"
GREEN    = "#27AE60"
AMBER    = "#F39C12"
PURPLE   = "#8B5CF6"


SIZE_EST = {
    "Low":    "~300 MB/min",
    "Medium": "~700 MB/min",
    "High":   "~1.2 GB/min",
    "Ultra":  "~2.0 GB/min",
}


# ══════════════════════════════════════════════════════════════════════════════
# Custom pill toggle
# ══════════════════════════════════════════════════════════════════════════════

class PillToggle(tk.Canvas):
    """
    Animated pill-shaped on/off toggle.
    The knob slides left/right on state change.
    """
    W, H    = 44, 24
    ON_COL  = GREEN
    OFF_COL = "#2A2A3A"

    def __init__(self, parent, initial: bool = False, on_change: Callable = None,
                 **kwargs):
        kwargs.setdefault("bg", ELEVATED)
        super().__init__(parent, width=self.W, height=self.H,
                         highlightthickness=0, **kwargs)
        self._state     = initial
        self._on_change = on_change
        self._knob_x    = self._target_x()
        self._draw()
        self.bind("<Button-1>", self._toggle)

    def _target_x(self) -> int:
        return (self.W - self.H // 2) if self._state else (self.H // 2)

    def _draw(self, knob_x: int = None) -> None:
        self.delete("all")
        kx = knob_x if knob_x is not None else self._knob_x
        color = self.ON_COL if self._state else self.OFF_COL
        r     = self.H // 2
        # Track
        self.create_oval(0, 0, self.H, self.H, fill=color, outline="")
        self.create_rectangle(r, 0, self.W-r, self.H, fill=color, outline="")
        self.create_oval(self.W-self.H, 0, self.W, self.H, fill=color, outline="")
        # Knob
        pad = 3
        self.create_oval(kx-r+pad, pad, kx+r-pad, self.H-pad,
                         fill="#F0F0F5", outline="")

    def _toggle(self, _=None) -> None:
        self._state = not self._state
        # Animate knob
        start_x = self._knob_x
        end_x   = self._target_x()

        def _upd(t):
            x = int(start_x + (end_x - start_x) * ease_out_cubic(t))
            self._knob_x = x
            self._draw(x)

        Animator(self, 180, _upd).start()
        if self._on_change:
            self._on_change(self._state)

    @property
    def value(self) -> bool:
        return self._state

    def set(self, val: bool) -> None:
        if self._state != val:
            self._state = val
            self._knob_x = self._target_x()
            self._draw()


# ══════════════════════════════════════════════════════════════════════════════
# Settings Panel
# ══════════════════════════════════════════════════════════════════════════════

class SettingsPanel(ctk.CTkToplevel):
    """
    Settings panel that slides in from the right side of the screen.

    Args:
        parent:   Parent window (toolbar).
        settings: Shared Settings dataclass to read/write.
        recorder: ScreenRecorder (for monitor list).
        on_close: Optional callback when panel is dismissed.
    """
    W = 320

    def __init__(self, parent, settings: Settings, recorder,
                 on_close: Callable = None):
        super().__init__(parent)

        self._settings = settings
        self._recorder = recorder
        self._on_close = on_close

        sh = self.winfo_screenheight()
        sw = self.winfo_screenwidth()
        self.H = sh

        self.title("Settings")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=SURFACE)
        self.overrideredirect(True)

        # Start off-screen to the right
        self.geometry(f"{self.W}x{sh}+{sw}+0")
        self.attributes("-alpha", 0.0)

        self._build()
        self._load_values()
        self.protocol("WM_DELETE_WINDOW", self.close)

        # Slide in
        self._slide_in(sw)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        sh = self.winfo_screenheight()

        # Header bar
        hdr = tk.Frame(self, bg=BG, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="⚙  SETTINGS", bg=BG, fg=TEXT_P,
                 font=("Segoe UI Variable", 13, "bold")).pack(
                     side="left", padx=20, pady=14)
        close_btn = tk.Label(hdr, text="✕", bg=BG, fg=TEXT_S,
                              font=("Segoe UI", 13), cursor="hand2", padx=12)
        close_btn.pack(side="right")
        close_btn.bind("<Enter>", lambda _: close_btn.configure(fg="#E74C3C"))
        close_btn.bind("<Leave>", lambda _: close_btn.configure(fg=TEXT_S))
        close_btn.bind("<Button-1>", lambda _: self.close())

        # Separator
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Scrollable content
        self._body = ctk.CTkScrollableFrame(
            self, fg_color=SURFACE,
            scrollbar_button_color=ELEVATED,
            width=self.W - 20,
        )
        self._body.pack(fill="both", expand=True, padx=0, pady=0)

        self._build_capture()
        self._build_encoding()
        self._build_audio()
        self._build_recording_options()
        self._build_output()
        self._build_hotkeys()

        # Apply button
        apply_btn = tk.Frame(self, bg=BG, height=60)
        apply_btn.pack(fill="x", side="bottom")
        apply_btn.pack_propagate(False)
        tk.Button(apply_btn, text="  APPLY CHANGES  ",
                  bg=RED, fg=TEXT_P,
                  font=("Segoe UI Variable", 12, "bold"),
                  relief="flat", cursor="hand2",
                  activebackground="#E74C3C",
                  command=self._apply).pack(
                      fill="x", padx=16, pady=12)

    def _section(self, icon: str, title: str):
        """Add section header + return content frame."""
        sp = tk.Frame(self._body, bg=BORDER, height=1)
        sp.pack(fill="x", padx=16, pady=(14, 0))

        hdr = tk.Frame(self._body, bg=SURFACE)
        hdr.pack(fill="x", padx=16, pady=(8, 4))
        tk.Label(hdr, text=f"{icon}  {title}", bg=SURFACE, fg=TEXT_P,
                 font=("Segoe UI Variable", 11, "bold")).pack(side="left")

        frame = tk.Frame(self._body, bg=ELEVATED,
                          relief="flat", bd=0)
        frame.pack(fill="x", padx=16, pady=(0, 4))
        return frame

    def _row(self, parent, label: str, widget) -> None:
        r = tk.Frame(parent, bg=ELEVATED)
        r.pack(fill="x", padx=12, pady=6)
        tk.Label(r, text=label, bg=ELEVATED, fg=TEXT_S,
                 font=("Segoe UI", 10), width=14, anchor="w").pack(side="left")
        widget.pack(side="right")

    def _toggle_row(self, parent, label: str,
                    initial: bool, cb=None) -> PillToggle:
        r = tk.Frame(parent, bg=ELEVATED)
        r.pack(fill="x", padx=12, pady=8)
        tk.Label(r, text=label, bg=ELEVATED, fg=TEXT_S,
                 font=("Segoe UI", 10)).pack(side="left")
        tog = PillToggle(r, initial=initial, on_change=cb, bg=ELEVATED)
        tog.pack(side="right")
        return tog

    def _combo(self, parent, values: list, var) -> ctk.CTkComboBox:
        return ctk.CTkComboBox(
            parent, values=values, variable=var,
            fg_color=BG, border_color=BORDER,
            button_color=BORDER, dropdown_fg_color=ELEVATED,
            text_color=TEXT_P, width=150
        )

    def _pill_row(self, parent, label: str, options: list,
                  initial: str, cb: Callable) -> ctk.CTkSegmentedButton:
        r = tk.Frame(parent, bg=ELEVATED)
        r.pack(fill="x", padx=12, pady=8)
        tk.Label(r, text=label, bg=ELEVATED, fg=TEXT_S,
                 font=("Segoe UI", 10)).pack(side="left")
        seg = ctk.CTkSegmentedButton(
            r, values=options,
            fg_color=BG, selected_color=RED,
            text_color=TEXT_S, selected_hover_color="#E74C3C",
            font=("Segoe UI Variable", 9, "bold"),
            command=cb
        )
        seg.set(initial)
        seg.pack(side="right")
        return seg

    # ── Sections ──────────────────────────────────────────────────────────────

    def _build_capture(self):
        f = self._section("🖥", "CAPTURE")
        monitors = ["Monitor 0", "Monitor 1", "Monitor 2"]

        self._mon_var = tk.StringVar(value=f"Monitor {self._settings.monitor}")
        self._row(f, "Monitor", self._combo(f, monitors, self._mon_var))

        self._fps_var = tk.StringVar(value=str(self._settings.fps))
        self._row(f, "FPS", self._combo(f, ["30", "60", "120", "144"], self._fps_var))

    def _build_encoding(self):
        f = self._section("🎬", "ENCODING")

        self._quality_var = tk.StringVar(value=self._settings.quality)
        self._row(f, "Quality",
                  self._combo(f, ["Low", "Medium", "High", "Ultra"], self._quality_var))

        self._color_var = tk.StringVar(value=self._settings.color_grade)
        self._row(f, "Color Grade",
                  self._combo(f, ["Neutral", "Vibrant", "Cinematic",
                                  "Warm", "Cool"], self._color_var))

        self._format_var = tk.StringVar(value=self._settings.output_format)
        self._row(f, "Format",
                  self._combo(f, ["MP4", "MKV", "WebM"], self._format_var))

        # Size estimate
        self._est_lbl = tk.Label(f, text="", bg=ELEVATED, fg=TEXT_DIM,
                                  font=("Segoe UI", 8))
        self._est_lbl.pack(anchor="e", padx=12, pady=(0, 6))
        self._quality_var.trace_add("write", self._update_estimate)
        self._update_estimate()

    def _update_estimate(self, *_):
        q = self._quality_var.get()
        self._est_lbl.configure(text=SIZE_EST.get(q, ""))

    def _build_audio(self):
        f = self._section("🎙", "AUDIO")
        self._audio_tog = self._toggle_row(f, "System Audio (WASAPI)",
                                            self._settings.audio_enabled)
        self._mic_tog   = self._toggle_row(f, "Microphone Input",
                                            self._settings.mic_enabled)

    def _build_recording_options(self):
        f = self._section("⏱", "RECORDING")
        self._countdown_tog = self._toggle_row(f, "3-2-1 Countdown",
                                                self._settings.countdown_enabled)
        self._auto_open_tog = self._toggle_row(f, "Auto-open after save",
                                                self._settings.auto_open)
        self._copy_ss_tog   = self._toggle_row(f, "Copy screenshot to clipboard",
                                                self._settings.copy_screenshot)

    def _build_output(self):
        f = self._section("💾", "OUTPUT")

        # Folder display
        path_row = tk.Frame(f, bg=ELEVATED)
        path_row.pack(fill="x", padx=12, pady=6)
        tk.Label(path_row, text="Save To", bg=ELEVATED, fg=TEXT_S,
                 font=("Segoe UI", 10)).pack(side="left")

        self._path_lbl = tk.Label(
            path_row,
            text=self._settings.output_folder,
            bg=ELEVATED, fg=TEXT_DIM,
            font=("Segoe UI", 8),
            wraplength=150, anchor="e", justify="right"
        )
        self._path_lbl.pack(side="right")

        btn_row = tk.Frame(f, bg=ELEVATED)
        btn_row.pack(fill="x", padx=12, pady=(0, 8))
        self._make_action_btn(btn_row, "Browse…", self._browse)
        self._make_action_btn(btn_row, "Open Folder",
                               lambda: os.startfile(self._settings.output_folder))

    def _build_hotkeys(self):
        f = self._section("⌨", "HOTKEYS")
        for action, key in [
            ("Start / Stop Recording", "Ctrl+Shift+R"),
            ("Take Screenshot",        "Ctrl+Shift+S"),
            ("Cancel Region",          "Escape"),
        ]:
            r = tk.Frame(f, bg=ELEVATED)
            r.pack(fill="x", padx=12, pady=5)
            tk.Label(r, text=action, bg=ELEVATED, fg=TEXT_S,
                     font=("Segoe UI", 9)).pack(side="left")
            tk.Label(r, text=key, bg=BG, fg=TEXT_P,
                     font=("Courier New", 9),
                     padx=6, pady=2, relief="flat").pack(side="right")

    def _make_action_btn(self, parent, text: str, cmd: Callable) -> tk.Label:
        btn = tk.Label(parent, text=text, bg=BG, fg=TEXT_P,
                       font=("Segoe UI", 9), padx=8, pady=3, cursor="hand2")
        btn.pack(side="left", padx=(0, 6), pady=2)
        btn.bind("<Enter>", lambda _: btn.configure(bg=ELEVATED))
        btn.bind("<Leave>", lambda _: btn.configure(bg=BG))
        btn.bind("<Button-1>", lambda _: cmd())
        return btn

    # ── Load & Apply ──────────────────────────────────────────────────────────

    def _load_values(self):
        s = self._settings
        self._fps_var.set(str(s.fps))
        self._quality_var.set(s.quality)
        self._color_var.set(s.color_grade)
        self._format_var.set(s.output_format)
        self._audio_tog.set(s.audio_enabled)
        self._mic_tog.set(s.mic_enabled)
        self._countdown_tog.set(s.countdown_enabled)
        self._auto_open_tog.set(s.auto_open)
        self._copy_ss_tog.set(s.copy_screenshot)
        self._path_lbl.configure(text=s.output_folder)

    def _apply(self):
        s = self._settings
        try:
            s.fps = int(self._fps_var.get())
        except ValueError:
            s.fps = 60
        try:
            mon_str = self._mon_var.get()
            s.monitor = int(''.join(filter(str.isdigit, mon_str)) or "0")
        except Exception:
            s.monitor = 0
        s.quality           = self._quality_var.get()
        s.color_grade       = self._color_var.get()
        s.output_format     = self._format_var.get()
        s.audio_enabled     = self._audio_tog.value
        s.mic_enabled       = self._mic_tog.value
        s.countdown_enabled = self._countdown_tog.value
        s.auto_open         = self._auto_open_tog.value
        s.copy_screenshot   = self._copy_ss_tog.value
        save_settings(s)
        log.info("Settings saved.")
        self.close()

    def _browse(self):
        folder = ctk.filedialog.askdirectory(
            initialdir=self._settings.output_folder)
        if folder:
            self._settings.output_folder = folder
            self._path_lbl.configure(text=folder)

    # ── Slide animation ───────────────────────────────────────────────────────

    def _slide_in(self, sw: int):
        start_x = sw
        end_x   = sw - self.W
        self.attributes("-alpha", 0.96)

        def _upd(t):
            xx = int(start_x + (end_x - start_x) * ease_out_cubic(t))
            try:
                self.geometry(f"+{xx}+0")
            except Exception:
                pass

        Animator(self, 320, _upd).start()

    def close(self):
        sw     = self.winfo_screenwidth()
        end_x  = sw
        start_x = self.winfo_x()

        def _upd(t):
            xx = int(start_x + (end_x - start_x) * ease_out_cubic(t))
            try:
                self.geometry(f"+{xx}+0")
                self.attributes("-alpha", 0.96 * (1 - t))
            except Exception:
                pass

        Animator(self, 260, _upd, on_complete=self.destroy).start()
        if self._on_close:
            self._on_close()
