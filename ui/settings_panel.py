"""
ui/settings_panel.py
Settings popup window for Soumo Screen Recorder.
Premium styled with sections, custom toggles, and settings persistence.
"""

import customtkinter as ctk
import tkinter as tk
import os
import logging
from utils.settings import Settings, save_settings
from utils.animations import Animator, ease_out_back

log = logging.getLogger(__name__)

# ── Palette ────────────────────────────────────────────────────────────────────
BG        = "#0A0A0F"
SURFACE   = "#13131A"
ELEVATED  = "#1C1C26"
ACCENT    = "#C0392B"
ACCENT2   = "#3498DB"
TEXT_P    = "#F0F0F5"
TEXT_S    = "#8888AA"
BORDER    = "#2A2A3A"
SUCCESS   = "#27AE60"
PURPLE    = "#8B5CF6"


SIZE_ESTIMATES = {
    "Low":    "~300 MB/min",
    "Medium": "~700 MB/min",
    "High":   "~1.2 GB/min",
    "Ultra":  "~2.0 GB/min",
}


class PillToggle(tk.Canvas):
    """
    A pill-shaped on/off toggle switch drawn on a Canvas.

    Args:
        parent:   Parent widget.
        initial:  Initial state (True=ON).
        on_change: Callback receiving the new bool state.
    """

    W, H   = 44, 24
    RADIUS  = 12
    ON_COL  = "#27AE60"
    OFF_COL = "#2A2A3A"
    KNOB    = "#F0F0F5"

    def __init__(self, parent, initial: bool = False,
                 on_change=None, **kwargs):
        kwargs.setdefault("bg", SURFACE)
        super().__init__(parent, width=self.W, height=self.H,
                         highlightthickness=0, **kwargs)
        self._state     = initial
        self._on_change = on_change
        self._knob_x    = self.H // 2 if not initial else self.W - self.H // 2
        self._draw()
        self.bind("<Button-1>", self._toggle)

    def _draw(self):
        self.delete("all")
        color = self.ON_COL if self._state else self.OFF_COL
        r = self.H // 2
        # Track
        self.create_oval(0, 0, self.H, self.H, fill=color, outline="")
        self.create_rectangle(r, 0, self.W - r, self.H, fill=color, outline="")
        self.create_oval(self.W - self.H, 0, self.W, self.H, fill=color, outline="")
        # Knob
        kx = self._knob_x
        ky = self.H // 2
        pad = 3
        self.create_oval(kx - r + pad, ky - r + pad,
                         kx + r - pad, ky + r - pad,
                         fill=self.KNOB, outline="")

    def _toggle(self, _=None):
        self._state = not self._state
        self._knob_x = self.H // 2 if not self._state else self.W - self.H // 2
        self._draw()
        if self._on_change:
            self._on_change(self._state)

    @property
    def value(self) -> bool:
        """Current toggle state."""
        return self._state

    def set(self, val: bool):
        """Programmatically set the toggle state without triggering callback."""
        if self._state != val:
            self._state = val
            self._knob_x = self.H // 2 if not val else self.W - self.H // 2
            self._draw()


class SectionLabel(ctk.CTkLabel):
    """Small all-caps section header label."""
    def __init__(self, parent, text: str, **kwargs):
        super().__init__(
            parent,
            text=text.upper(),
            font=ctk.CTkFont("Segoe UI Variable", 9, "bold"),
            text_color=TEXT_S,
            **kwargs
        )


class SettingsPanel(ctk.CTkToplevel):
    """
    Settings popup panel.

    Displays and persists all user-configurable options, grouped into
    logical sections. Opens with a scale-from-center animation.

    Args:
        parent:   Parent window (toolbar).
        settings: Shared Settings dataclass instance.
        recorder: ScreenRecorder instance (for monitor enumeration).
        on_close: Optional callback when panel is closed.
    """

    W = 380
    H = 540

    def __init__(self, parent, settings: Settings, recorder, on_close=None):
        super().__init__(parent)

        self._settings  = settings
        self._recorder  = recorder
        self._on_close  = on_close

        self.title("Settings")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=SURFACE)

        # Center on screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - self.W) // 2
        y  = (sh - self.H) // 2
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

        self._build()
        self._load_values()

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._animate_open()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=ELEVATED, corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="⚙  Settings",
                     font=ctk.CTkFont("Segoe UI Variable", 16, "bold"),
                     text_color=TEXT_P).pack(side="left", padx=20, pady=14)

        close_x = ctk.CTkButton(hdr, text="✕", width=32, height=32,
                                 fg_color="transparent", hover_color="#2A2A3A",
                                 text_color=TEXT_S,
                                 command=self._close)
        close_x.pack(side="right", padx=12)

        # Scrollable body
        self._body = ctk.CTkScrollableFrame(self, fg_color=SURFACE,
                                             scrollbar_button_color=ELEVATED)
        self._body.pack(fill="both", expand=True, padx=0, pady=0)

        self._build_capture_section()
        self._build_encoding_section()
        self._build_audio_section()
        self._build_output_section()
        self._build_hotkeys_section()

        # Apply button
        ctk.CTkButton(
            self, text="Apply & Close",
            font=ctk.CTkFont("Segoe UI Variable", 13, "bold"),
            fg_color=ACCENT, hover_color="#E74C3C",
            text_color=TEXT_P, height=42,
            corner_radius=8,
            command=self._apply
        ).pack(fill="x", padx=16, pady=(8, 14))

    def _section(self, icon: str, title: str):
        """Add a section header and return a frame for its content."""
        sep = ctk.CTkFrame(self._body, fg_color=BORDER, height=1)
        sep.pack(fill="x", padx=16, pady=(14, 0))

        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(10, 4))
        ctk.CTkLabel(row, text=f"{icon}  {title}",
                     font=ctk.CTkFont("Segoe UI Variable", 12, "bold"),
                     text_color=TEXT_P).pack(side="left")

        frame = ctk.CTkFrame(self._body, fg_color=ELEVATED, corner_radius=10)
        frame.pack(fill="x", padx=16, pady=(0, 4))
        return frame

    def _row(self, parent, label: str, widget: ctk.CTkBaseClass):
        """Add a label + widget row inside a section frame."""
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(r, text=label, text_color=TEXT_S,
                     font=ctk.CTkFont("Segoe UI", 11),
                     width=130, anchor="w").pack(side="left")
        widget.pack(side="right")

    def _toggle_row(self, parent, label: str, initial: bool, cb=None) -> PillToggle:
        """Add a label + PillToggle row. Returns the toggle widget."""
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=8)
        ctk.CTkLabel(r, text=label, text_color=TEXT_S,
                     font=ctk.CTkFont("Segoe UI", 11)).pack(side="left")
        tog = PillToggle(r, initial=initial, on_change=cb, bg=ELEVATED)
        tog.pack(side="right")
        return tog

    def _combo(self, parent, values, **kwargs) -> ctk.CTkComboBox:
        return ctk.CTkComboBox(
            parent, values=values,
            fg_color=SURFACE, border_color=BORDER,
            button_color=BORDER, dropdown_fg_color=ELEVATED,
            text_color=TEXT_P, width=160,
            **kwargs
        )

    # ── Sections ───────────────────────────────────────────────────────────────

    def _build_capture_section(self):
        f = self._section("🖥", "Capture")

        monitors = self._recorder.get_monitors()
        if isinstance(monitors, dict):
            mon_names = [f"Display {i}" for i in monitors]
        elif isinstance(monitors, list):
            mon_names = [f"Monitor {i}" for i in range(len(monitors))]
        else:
            mon_names = ["Primary Monitor"]

        self._mon_var = ctk.StringVar(value=mon_names[0])
        self._fps_var = ctk.StringVar(value="120")

        self._row(f, "Monitor",    self._combo(f, mon_names, variable=self._mon_var))
        self._row(f, "Target FPS", self._combo(f, ["30","60","120","144"], variable=self._fps_var))

    def _build_encoding_section(self):
        f = self._section("🎬", "Encoding")

        self._quality_var    = ctk.StringVar(value="High")
        self._color_var      = ctk.StringVar(value="Neutral")
        self._format_var     = ctk.StringVar(value="MP4")

        self._row(f, "Quality",     self._combo(f, ["Low","Medium","High","Ultra"], variable=self._quality_var))
        self._row(f, "Color Grade", self._combo(f, ["Neutral","Vibrant","Cinematic"], variable=self._color_var))
        self._row(f, "Format",      self._combo(f, ["MP4","MKV","WebM"], variable=self._format_var))

        # Estimate label
        self._est_lbl = ctk.CTkLabel(f, text="", text_color=TEXT_S,
                                      font=ctk.CTkFont("Segoe UI", 9))
        self._est_lbl.pack(anchor="e", padx=14, pady=(0, 6))
        self._quality_var.trace_add("write", self._update_estimate)
        self._update_estimate()

    def _update_estimate(self, *_):
        q   = self._quality_var.get()
        est = SIZE_ESTIMATES.get(q, "")
        self._est_lbl.configure(text=f"Estimated size: {est}")

    def _build_audio_section(self):
        f = self._section("🎙", "Audio")
        self._audio_tog = self._toggle_row(f, "System Audio (WASAPI)",
                                            initial=True)
        self._mic_tog   = self._toggle_row(f, "Microphone Input",
                                            initial=False)

    def _build_output_section(self):
        f = self._section("💾", "Output")

        path_row = ctk.CTkFrame(f, fg_color="transparent")
        path_row.pack(fill="x", padx=14, pady=8)
        ctk.CTkLabel(path_row, text="Save To", text_color=TEXT_S,
                     font=ctk.CTkFont("Segoe UI", 11)).pack(side="left")

        self._path_lbl = ctk.CTkLabel(path_row, text=self._settings.output_folder,
                                       text_color=TEXT_S,
                                       font=ctk.CTkFont("Segoe UI", 9),
                                       wraplength=160, anchor="e")
        self._path_lbl.pack(side="right", padx=(0, 4))

        ctk.CTkButton(f, text="Browse…", width=90,
                      fg_color=ELEVATED, hover_color=BORDER,
                      text_color=TEXT_P,
                      command=self._browse).pack(anchor="e", padx=14, pady=(0, 4))

        ctk.CTkButton(f, text="📁 Open Folder", width=130,
                      fg_color="transparent", hover_color=ELEVATED,
                      text_color=ACCENT2,
                      command=lambda: os.startfile(self._settings.output_folder)
                      ).pack(anchor="w", padx=10, pady=(0, 8))

        self._auto_open_tog    = self._toggle_row(f, "Auto-open after save",      False)
        self._countdown_tog    = self._toggle_row(f, "3-2-1 Countdown before rec", False)
        self._copy_ss_tog      = self._toggle_row(f, "Copy screenshot to clipboard", True)

    def _build_hotkeys_section(self):
        f = self._section("⌨", "Hotkeys")
        hotkeys = [
            ("Start / Stop Recording", "Ctrl + Shift + R"),
            ("Take Screenshot",        "Ctrl + Shift + S"),
            ("Cancel Region",          "Escape"),
        ]
        for action, key in hotkeys:
            r = ctk.CTkFrame(f, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=5)
            ctk.CTkLabel(r, text=action, text_color=TEXT_S,
                         font=ctk.CTkFont("Segoe UI", 11)).pack(side="left")
            ctk.CTkLabel(r, text=key, text_color=TEXT_P,
                         font=ctk.CTkFont("Courier New", 10),
                         fg_color=ELEVATED,
                         corner_radius=4,
                         padx=6, pady=2).pack(side="right")

    # ── Load & Apply ───────────────────────────────────────────────────────────

    def _load_values(self):
        """Populate all controls from the current Settings object."""
        s = self._settings
        self._fps_var.set(str(s.fps))
        self._quality_var.set(s.quality)
        self._color_var.set(s.color_grade)
        self._format_var.set(s.output_format)
        self._audio_tog.set(s.audio_enabled)
        self._mic_tog.set(s.mic_enabled)
        self._auto_open_tog.set(s.auto_open)
        self._countdown_tog.set(s.countdown_enabled)
        self._copy_ss_tog.set(s.copy_screenshot)
        self._path_lbl.configure(text=s.output_folder)

    def _apply(self):
        """Write UI values back to Settings and persist to disk."""
        s = self._settings
        try:
            s.fps = int(self._fps_var.get())
        except ValueError:
            s.fps = 120

        raw_mon = self._mon_var.get()
        digits  = ''.join(filter(str.isdigit, raw_mon))
        s.monitor = int(digits) if digits else 0

        s.quality         = self._quality_var.get()
        s.color_grade     = self._color_var.get()
        s.output_format   = self._format_var.get()
        s.audio_enabled   = self._audio_tog.value
        s.mic_enabled     = self._mic_tog.value
        s.auto_open       = self._auto_open_tog.value
        s.countdown_enabled = self._countdown_tog.value
        s.copy_screenshot   = self._copy_ss_tog.value

        save_settings(s)
        log.info("Settings saved.")
        self._close()

    def _browse(self):
        folder = ctk.filedialog.askdirectory(initialdir=self._settings.output_folder)
        if folder:
            self._settings.output_folder = folder
            self._path_lbl.configure(text=folder)

    # ── Animation & Close ─────────────────────────────────────────────────────

    def _animate_open(self):
        """Scale-from-center open animation."""
        # We just fade alpha from 0 to 1 for simplicity
        self.attributes("-alpha", 0)
        def _fade(t):
            self.attributes("-alpha", t)
        Animator(self, 180, _fade, easing=ease_out_back).start()

    def _close(self):
        def _fade(t):
            self.attributes("-alpha", 1 - t)
        Animator(self, 140, _fade, on_complete=self.destroy).start()
        if self._on_close:
            self._on_close()
