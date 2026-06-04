import customtkinter as ctk
import tkinter as tk
from recorder import ScreenRecorder
from region_selector import RegionSelector
import os
import threading
import ctypes
import datetime

# ── Windows API: hide toolbar from capture ─────────────────────────────────────
WDA_EXCLUDEFROMCAPTURE = 0x00000011

# ── Default save path ──────────────────────────────────────────────────────────
SAVE_FOLDER = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "Soumo Recordings")
if not os.path.exists(SAVE_FOLDER):
    SAVE_FOLDER = os.path.join(os.path.expanduser("~"), "Desktop", "Soumo Recordings")
os.makedirs(SAVE_FOLDER, exist_ok=True)

# ── Color palette ──────────────────────────────────────────────────────────────
BG          = "#0d0d0d"      # near-black background
BAR_BG      = "#131313"      # toolbar fill
BTN_HOVER   = "#2a2a2a"      # button hover
ACCENT_RED  = "#e74c3c"      # recording red
ACCENT_BLUE = "#3b82f6"      # screenshot / region blue
TEXT_DIM    = "#555555"      # dim text
TEXT_BRIGHT = "#e0e0e0"      # normal icon text
GREEN       = "#22c55e"      # done green
YELLOW      = "#f59e0b"      # warning/snap yellow

# ═══════════════════════════════════════════════════════════════════════════════
class Tooltip:
    """Lightweight tooltip that appears below a widget on hover."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text   = text
        self.tip    = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _=None):
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        self.tip.attributes("-topmost", True)
        lbl = tk.Label(
            self.tip, text=self.text,
            bg="#1e1e1e", fg="#e0e0e0",
            font=("Segoe UI", 9),
            padx=8, pady=4,
            relief="flat", bd=0
        )
        lbl.pack()

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ═══════════════════════════════════════════════════════════════════════════════
class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent, ui):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("320x420")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color="#111111")
        self.ui = ui

        self._build()

    def _row(self, label, var, values, default):
        ctk.CTkLabel(self, text=label,
                     text_color=TEXT_BRIGHT,
                     font=ctk.CTkFont("Segoe UI", 12)).pack(
            anchor="w", padx=20, pady=(12, 0))
        var.set(default)
        ctk.CTkComboBox(self, variable=var, values=values,
                        fg_color="#1e1e1e", border_color="#333",
                        button_color="#333", dropdown_fg_color="#1e1e1e",
                        text_color=TEXT_BRIGHT).pack(
            fill="x", padx=20, pady=(2, 0))

    def _build(self):
        ctk.CTkLabel(self, text="Settings",
                     font=ctk.CTkFont("Segoe UI", 16, "bold"),
                     text_color=TEXT_BRIGHT).pack(pady=(16, 4))

        self.monitor_var = ctk.StringVar()
        self.fps_var     = ctk.StringVar()
        self.quality_var = ctk.StringVar()
        self.color_var   = ctk.StringVar()

        monitors = self.ui.recorder.get_monitors()
        if isinstance(monitors, dict):
            mon_names = [f"Display {i}" for i in monitors]
        elif isinstance(monitors, list):
            mon_names = [f"Monitor {i}" for i in range(len(monitors))]
        else:
            mon_names = ["Primary Monitor"]

        self._row("Monitor",       self.monitor_var, mon_names,                         mon_names[0])
        self._row("Target FPS",    self.fps_var,     ["30","60","120","144"],            "120")
        self._row("Quality",       self.quality_var, ["Low","Medium","High","Ultra"],    "High")
        self._row("Color Grading", self.color_var,   ["Neutral","Vibrant","Cinematic"],  "Neutral")

        # Output folder
        ctk.CTkLabel(self, text="Output Folder",
                     text_color=TEXT_BRIGHT,
                     font=ctk.CTkFont("Segoe UI", 12)).pack(
            anchor="w", padx=20, pady=(12, 0))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(2, 0))

        self.path_label = ctk.CTkLabel(
            row, text=self.ui.output_directory,
            text_color=TEXT_DIM,
            font=ctk.CTkFont("Segoe UI", 10),
            anchor="w", wraplength=200)
        self.path_label.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(row, text="Browse…", width=70,
                      fg_color="#1e1e1e", hover_color=BTN_HOVER,
                      text_color=TEXT_BRIGHT,
                      command=self._browse).pack(side="right")

        ctk.CTkButton(self, text="Open Recordings Folder",
                      fg_color="#1e1e1e", hover_color=BTN_HOVER,
                      text_color=ACCENT_BLUE,
                      command=lambda: os.startfile(self.ui.output_directory)
                      ).pack(fill="x", padx=20, pady=(16, 0))

    def _browse(self):
        folder = ctk.filedialog.askdirectory(initialdir=self.ui.output_directory)
        if folder:
            self.ui.output_directory = folder
            self.path_label.configure(text=folder)


# ═══════════════════════════════════════════════════════════════════════════════
class RecorderUI(ctk.CTk):
    BAR_W = 440
    BAR_H = 58

    def __init__(self):
        super().__init__()

        # ── Frameless, always-on-top ───────────────────────────────────────────
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=BG)

        # Position: top-center of screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        self.geometry(f"{self.BAR_W}x{self.BAR_H}+{(sw - self.BAR_W)//2}+16")

        ctk.set_appearance_mode("dark")

        # ── State ─────────────────────────────────────────────────────────────
        self.recorder         = ScreenRecorder()
        self.recorder.set_duration_callback(self._update_timer)
        self.output_directory = SAVE_FOLDER
        self.current_region   = None
        self.settings_window  = None
        self._drag_x          = 0
        self._drag_y          = 0

        # ── Build ─────────────────────────────────────────────────────────────
        self._build_ui()
        self._hide_from_capture()

        # Global hotkeys
        try:
            import keyboard
            keyboard.add_hotkey("ctrl+shift+r", lambda: self.after(0, self._toggle_video))
            keyboard.add_hotkey("ctrl+shift+s", lambda: self.after(0, self._take_screenshot))
        except Exception as e:
            print("Hotkey error:", e)

    # ── Windows capture exclusion ──────────────────────────────────────────────
    def _hide_from_capture(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception as e:
            print("Capture-hide error:", e)

    # ── UI Construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        # Outer frame with rounded border feel
        outer = ctk.CTkFrame(self, fg_color=BAR_BG,
                             corner_radius=14,
                             border_width=1, border_color="#2a2a2a")
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        # ── Drag grip ─────────────────────────────────────────────────────────
        grip = ctk.CTkLabel(outer, text="⠿",
                            font=ctk.CTkFont("Segoe UI", 18),
                            text_color=TEXT_DIM, cursor="fleur",
                            width=28)
        grip.pack(side="left", padx=(10, 4))
        grip.bind("<ButtonPress-1>",   self._drag_start)
        grip.bind("<B1-Motion>",       self._drag_move)
        Tooltip(grip, "Drag to move")

        # ── Separator ─────────────────────────────────────────────────────────
        def sep():
            ctk.CTkLabel(outer, text="│",
                         text_color="#2a2a2a",
                         font=ctk.CTkFont(size=20)).pack(side="left", padx=2)

        # ── Icon button factory ────────────────────────────────────────────────
        def btn(icon, tip, cmd, color=TEXT_BRIGHT):
            b = ctk.CTkButton(
                outer, text=icon,
                font=ctk.CTkFont("Segoe UI Emoji", 22),
                width=42, height=42,
                fg_color="transparent",
                hover_color=BTN_HOVER,
                text_color=color,
                command=cmd
            )
            b.pack(side="left", padx=3)
            Tooltip(b, tip)
            return b

        self.btn_shot   = btn("📷", "Screenshot  (Ctrl+Shift+S)", self._take_screenshot, ACCENT_BLUE)
        self.btn_rec    = btn("⏺",  "Start / Stop Recording  (Ctrl+Shift+R)", self._toggle_video, TEXT_BRIGHT)
        sep()
        self.btn_region = btn("⛶",  "Select capture region", self._select_region, TEXT_BRIGHT)
        sep()
        self.btn_folder = btn("📁",  "Open Recordings folder", self._open_folder, TEXT_BRIGHT)
        self.btn_gear   = btn("⚙",  "Settings  (FPS · Quality · Color)", self._open_settings, TEXT_BRIGHT)
        sep()

        # ── Timer ─────────────────────────────────────────────────────────────
        self.timer_lbl = ctk.CTkLabel(
            outer, text="00:00:00",
            font=ctk.CTkFont("Courier New", 15, "bold"),
            text_color=TEXT_DIM, width=90)
        self.timer_lbl.pack(side="left", padx=(4, 6))

        # ── Close ─────────────────────────────────────────────────────────────
        close_btn = ctk.CTkButton(
            outer, text="✕",
            font=ctk.CTkFont("Segoe UI", 14),
            width=32, height=32,
            fg_color="transparent",
            hover_color="#4a0000",
            text_color=TEXT_DIM,
            command=self.quit
        )
        close_btn.pack(side="right", padx=(0, 8))
        Tooltip(close_btn, "Quit")

    # ── Drag logic ────────────────────────────────────────────────────────────
    def _drag_start(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ── Actions ───────────────────────────────────────────────────────────────
    def _open_folder(self):
        os.startfile(self.output_directory)

    def _open_settings(self):
        if self.settings_window is None or not self.settings_window.winfo_exists():
            self.settings_window = SettingsWindow(self, self)
        else:
            self.settings_window.focus()

    def _select_region(self):
        self.timer_lbl.configure(text="Draw…", text_color=YELLOW)
        self.iconify()                          # hide bar while selecting
        self.after(200, self._launch_selector)  # small delay so bar hides first

    def _launch_selector(self):
        rs = RegionSelector(self._on_region_selected)
        rs.run()

    def _on_region_selected(self, region):
        self.deiconify()
        self.current_region = region
        if region:
            l, t, r, b = region
            self.btn_region.configure(text_color=ACCENT_BLUE)
            Tooltip(self.btn_region,
                    f"Region: {r-l}×{b-t} px  (click to reselect)")
        else:
            self.btn_region.configure(text_color=TEXT_BRIGHT)
        self.timer_lbl.configure(text="00:00:00", text_color=TEXT_DIM)

    def _take_screenshot(self):
        idx = self._monitor_idx()
        fname = f"Screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path  = os.path.join(self.output_directory, fname)
        self.timer_lbl.configure(text="SNAP!", text_color=ACCENT_BLUE)
        self.update()
        self.recorder.take_screenshot(monitor_index=idx,
                                      output_path=path,
                                      region=self.current_region)
        self.after(1200, lambda: self.timer_lbl.configure(text="00:00:00",
                                                          text_color=TEXT_DIM))

    def _toggle_video(self):
        if self.recorder.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        sw = self.settings_window
        fps     = int(sw.fps_var.get())     if (sw and sw.winfo_exists()) else 120
        quality = sw.quality_var.get()       if (sw and sw.winfo_exists()) else "High"
        color   = sw.color_var.get()         if (sw and sw.winfo_exists()) else "Neutral"
        idx     = self._monitor_idx()

        fname = f"Video_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        path  = os.path.join(self.output_directory, fname)

        self.btn_rec.configure(text_color=ACCENT_RED)
        self.timer_lbl.configure(text_color=ACCENT_RED)

        try:
            self.recorder.start_recording(
                monitor_index=idx, fps=fps,
                output_path=path, quality=quality,
                color_grading=color, region=self.current_region
            )
        except Exception as e:
            self.timer_lbl.configure(text="ERR", text_color=ACCENT_RED)
            self.btn_rec.configure(text_color=TEXT_BRIGHT)
            print("Recording error:", e)

    def _stop_recording(self):
        self.btn_rec.configure(text_color=TEXT_BRIGHT)
        self.timer_lbl.configure(text="Saving…", text_color=YELLOW)
        threading.Thread(target=self._stop_thread, daemon=True).start()

    def _stop_thread(self):
        self.recorder.stop_recording()
        self.after(0, lambda: self.timer_lbl.configure(text="✓ Saved",
                                                       text_color=GREEN))
        self.after(2500, lambda: self.timer_lbl.configure(text="00:00:00",
                                                          text_color=TEXT_DIM))

    def _update_timer(self, time_str):
        self.after(0, lambda: self.timer_lbl.configure(text=time_str))

    def _monitor_idx(self):
        sw = self.settings_window
        if sw and sw.winfo_exists():
            raw = sw.monitor_var.get()
            digits = ''.join(filter(str.isdigit, raw))
            return int(digits) if digits else 0
        return 0
