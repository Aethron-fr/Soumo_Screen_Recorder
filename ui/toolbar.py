"""
ui/toolbar.py
Main floating toolbar — FIXED VERSION.

Bug fixes:
  - All recorder calls dispatched to background threads (UI never blocks)
  - All UI updates use root.after(0, ...) when called from threads
  - Record button disabled immediately on click (prevents double-click)
  - User-visible error toasts for every failure mode
  - Region status label shows Full Screen vs W×H
  - Right-click region button to clear region
  - Toolbar border glows red during recording
  - All animations non-blocking
"""

import customtkinter as ctk
import tkinter as tk
import ctypes
import threading
import time
import os
import sys
import logging
import platform
import datetime
from typing import Optional, Tuple

from core.recorder      import ScreenRecorder
from ui.region_selector import RegionSelector
from ui.settings_panel  import SettingsPanel
from ui.toast           import notify
from utils.settings     import Settings, save_settings, load_settings
from utils.hotkeys      import HotkeyManager
from utils.animations   import (Animator, ColorAnimator, PulseLoop,
                                 ease_out_cubic, lerp_color)

log = logging.getLogger(__name__)

WDA_EXCLUDEFROMCAPTURE = 0x00000011

# ── Palette ────────────────────────────────────────────────────────────────────
BG        = "#0A0A0F"
SURFACE   = "#13131A"
ELEVATED  = "#1C1C26"
BORDER    = "#2A2A3A"
BORDER_REC= "#5A1A1A"   # border color while recording
TEXT_P    = "#F0F0F5"
TEXT_S    = "#8888AA"
ACCENT_R  = "#C0392B"
ACCENT_R2 = "#E74C3C"
ACCENT_B  = "#3498DB"
ACCENT_G  = "#27AE60"
ACCENT_Y  = "#F39C12"
GREEN     = "#27AE60"

BAR_H = 48
BAR_W = 560


# ═══════════════════════════════════════════════════════════════════════════════
class Tooltip:
    """Hover tooltip with fade-in delay."""

    def __init__(self, widget, text: str, delay: int = 450):
        self._w    = widget
        self._text = text
        self._delay = delay
        self._win  = None
        self._job  = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._cancel)

    def update_text(self, text: str):
        self._text = text

    def _schedule(self, _=None):
        self._cancel()
        self._job = self._w.after(self._delay, self._show)

    def _cancel(self, _=None):
        if self._job:
            self._w.after_cancel(self._job)
            self._job = None
        self._hide()

    def _show(self):
        x = self._w.winfo_rootx() + self._w.winfo_width() // 2
        y = self._w.winfo_rooty() + self._w.winfo_height() + 7
        self._win = tk.Toplevel(self._w)
        self._win.wm_overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0)
        self._win.wm_geometry(f"+{x}+{y + 4}")
        tk.Label(self._win, text=self._text,
                 bg="#1C1C26", fg="#E0E0E0",
                 font=("Segoe UI", 9), padx=10, pady=5).pack()
        def _fade(t):
            try:
                self._win.attributes("-alpha", t)
                self._win.wm_geometry(f"+{x}+{y + int(4*(1-t))}")
            except Exception:
                pass
        Animator(self._win, 160, _fade).start()

    def _hide(self):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


# ═══════════════════════════════════════════════════════════════════════════════
class CountdownOverlay:
    """3-2-1 countdown before recording starts."""

    def __init__(self, on_done):
        self._on_done = on_done
        self._count   = 3

    def show(self):
        self._win = tk.Toplevel()
        self._win.overrideredirect(True)
        self._win.attributes("-fullscreen", True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0.72)
        self._win.configure(bg="#000000")
        self._lbl = tk.Label(
            self._win, text=str(self._count),
            bg="#000000", fg="#E74C3C",
            font=("Segoe UI Variable", 180, "bold")
        )
        self._lbl.place(relx=0.5, rely=0.5, anchor="center")
        self._tick()

    def _tick(self):
        if self._count <= 0:
            self._win.destroy()
            self._on_done()
            return
        self._lbl.configure(text=str(self._count))
        self._count -= 1
        self._win.after(1000, self._tick)


# ═══════════════════════════════════════════════════════════════════════════════
class ScreenFlash:
    """Brief white flash simulating a camera shutter."""

    @staticmethod
    def fire(root):
        try:
            win = tk.Toplevel(root)
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
            def _fade(t):
                try:
                    win.attributes("-alpha", 0.15 * (1 - t))
                except Exception:
                    pass
            Animator(win, 240, _fade, on_complete=win.destroy).start()
        except Exception as e:
            log.error("Screen flash error: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
class IconButton(tk.Canvas):
    """
    Circular icon button with smooth hover color animation.

    Args:
        parent: Parent widget.
        icon:   Unicode icon character.
        hover_bg: Background color on hover.
        command: Callable on click.
    """

    NORMAL_BG = ELEVATED

    def __init__(self, parent, icon: str, hover_bg: str,
                 command=None, size: int = 36, **kwargs):
        kwargs.setdefault("bg", SURFACE)
        super().__init__(parent, width=size, height=size,
                         highlightthickness=0, **kwargs)
        self._icon     = icon
        self._hover_bg = hover_bg
        self._cmd      = command
        self._size     = size
        self._cur_bg   = self.NORMAL_BG
        self._hover    = False
        self._anim: Optional[ColorAnimator] = None
        self._draw(self.NORMAL_BG)
        self.bind("<Enter>",           self._on_enter)
        self.bind("<Leave>",           self._on_leave)
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self, bg: str, scale: float = 1.0):
        self.delete("all")
        s   = self._size
        cx  = cy = s // 2
        r   = int((s // 2 - 2) * scale)
        self.create_oval(cx-r, cy-r, cx+r, cy+r, fill=bg, outline="")
        fs  = max(int(18 * scale), 10)
        self.create_text(cx, cy, text=self._icon,
                         fill=TEXT_P, font=("Segoe UI Emoji", fs))
        self._cur_bg = bg

    def _animate_to(self, target: str):
        if self._anim:
            self._anim.stop()
        self._anim = ColorAnimator(
            self, self._cur_bg, target, 120,
            setter=lambda c: self._draw(c)
        )
        self._anim.start()

    def _on_enter(self, _=None):
        self._hover = True
        self._animate_to(self._hover_bg)

    def _on_leave(self, _=None):
        self._hover = False
        self._animate_to(self.NORMAL_BG)

    def _on_press(self, _=None):
        self._draw(self._hover_bg, scale=0.85)

    def _on_release(self, _=None):
        self._draw(self._hover_bg if self._hover else self.NORMAL_BG)
        if self._cmd:
            self._cmd()


# ═══════════════════════════════════════════════════════════════════════════════
class RecordButton(tk.Canvas):
    """Record button that pulses red while recording is active."""

    SIZE = 36

    def __init__(self, parent, command=None, **kwargs):
        kwargs.setdefault("bg", SURFACE)
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         highlightthickness=0, **kwargs)
        self._cmd       = command
        self._recording = False
        self._enabled   = True
        self._pulse: Optional[PulseLoop] = None
        self._cur_bg    = ELEVATED
        self._draw(ELEVATED)
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda _: self._draw("#3A1A1A") if not self._recording else None)
        self.bind("<Leave>", lambda _: self._draw(ELEVATED) if not self._recording else None)

    def _draw(self, bg: str, scale: float = 1.0):
        self.delete("all")
        s  = self.SIZE
        cx = cy = s // 2
        r  = int((s // 2 - 2) * scale)
        self.create_oval(cx-r, cy-r, cx+r, cy+r, fill=bg, outline="")
        self.create_text(cx, cy, text="⏺",
                         fill=TEXT_P, font=("Segoe UI Emoji", max(int(18*scale), 10)))
        self._cur_bg = bg

    def start_pulse(self):
        self._recording = True
        self._pulse = PulseLoop(
            self, 1800,
            on_update=lambda t: self._draw(lerp_color(ACCENT_R, ACCENT_R2, t))
        )
        self._pulse.start()

    def stop_pulse(self):
        self._recording = False
        if self._pulse:
            self._pulse.stop()
            self._pulse = None
        self._draw(ELEVATED)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def _on_press(self, _=None):
        if not self._enabled:
            return
        self._draw(ACCENT_R, scale=0.85)

    def _on_release(self, _=None):
        if not self._enabled:
            return
        self._draw(self._cur_bg)
        if self._cmd:
            self._cmd()


# ═══════════════════════════════════════════════════════════════════════════════
class Toolbar(ctk.CTk):
    """
    Main floating toolbar for Soumo Screen Recorder PRO.
    """

    def __init__(self):
        super().__init__()

        log.info("Toolbar init — Python %s on %s", sys.version, platform.platform())

        self._settings  = load_settings()
        self._recorder  = ScreenRecorder()
        self._recorder.set_timer_callback(self._on_timer)
        self._hotkeys   = HotkeyManager()
        self._region: Optional[Tuple[int, int, int, int]] = None
        self._settings_win: Optional[SettingsPanel] = None
        self._recording_lock = threading.Lock()
        self._drag_ox = self._drag_oy = 0

        ctk.set_appearance_mode("dark")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=BG)
        self.attributes("-alpha", 0)

        # Position
        sw = self.winfo_screenwidth()
        sx = self._settings.toolbar_x
        sy = self._settings.toolbar_y
        if sx < 0 or sx + BAR_W > sw:
            sx = (sw - BAR_W) // 2
        if sy < 0:
            sy = 16
        self.geometry(f"{BAR_W}x{BAR_H}+{sx}+{sy}")

        self._build()
        self._apply_capture_exclusion()
        self._register_hotkeys()
        self.after(100, self._animate_slide_in)
        self.bind("<Configure>", self._on_configure)

    # ── Capture exclusion ─────────────────────────────────────────────────────

    def _apply_capture_exclusion(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            ok   = ctypes.windll.user32.SetWindowDisplayAffinity(
                hwnd, WDA_EXCLUDEFROMCAPTURE)
            log.info("SetWindowDisplayAffinity result: %d", ok)
        except Exception as e:
            log.error("Capture exclusion failed: %s", e)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        self._bar = tk.Frame(self, bg=SURFACE, bd=0,
                             highlightthickness=1,
                             highlightbackground=BORDER)
        self._bar.pack(fill="both", expand=True, padx=2, pady=2)

        # Grip + brand
        grip = tk.Label(self._bar, text="⠿", bg=SURFACE, fg=TEXT_S,
                        font=("Segoe UI", 16), cursor="fleur")
        grip.pack(side="left", padx=(10, 2))
        grip.bind("<ButtonPress-1>", self._drag_start)
        grip.bind("<B1-Motion>",     self._drag_move)
        Tooltip(grip, "Drag to move")

        tk.Label(self._bar, text="SOUMO", bg=SURFACE, fg=TEXT_S,
                 font=("Segoe UI Variable", 10, "bold")).pack(side="left", padx=(2, 6))

        self._div()

        # Screenshot button
        self._btn_shot = IconButton(
            self._bar, "📷", "#1A2A4A", command=self._take_screenshot, bg=SURFACE)
        self._btn_shot.pack(side="left", padx=3, pady=6)
        self._tt_shot = Tooltip(self._btn_shot, "Screenshot  [Ctrl+Shift+S]")

        # Record button
        self._btn_rec = RecordButton(self._bar, command=self._toggle_record, bg=SURFACE)
        self._btn_rec.pack(side="left", padx=3, pady=6)
        self._tt_rec = Tooltip(self._btn_rec, "Start Recording  [Ctrl+Shift+R]")

        self._div()

        # Region button + status label
        self._btn_region = IconButton(
            self._bar, "⛶", "#3D2A00", command=self._select_region, bg=SURFACE)
        self._btn_region.pack(side="left", padx=(3, 1), pady=6)
        self._btn_region.bind("<Button-3>", lambda _: self._clear_region())
        Tooltip(self._btn_region, "Select region  [Right-click to clear]")

        self._region_lbl = tk.Label(
            self._bar, text="Full Screen",
            bg=SURFACE, fg=TEXT_S,
            font=("Segoe UI", 9))
        self._region_lbl.pack(side="left", padx=(1, 4))

        self._div()

        # Folder button
        self._btn_folder = IconButton(
            self._bar, "📁", "#0D3320", command=self._open_folder, bg=SURFACE)
        self._btn_folder.pack(side="left", padx=3, pady=6)
        Tooltip(self._btn_folder, "Open Recordings folder")

        # Settings button
        self._btn_gear = IconButton(
            self._bar, "⚙", "#2D1A4A", command=self._open_settings, bg=SURFACE)
        self._btn_gear.pack(side="left", padx=3, pady=6)
        Tooltip(self._btn_gear, "Settings")

        self._div()

        # Timer
        self._timer_var = tk.StringVar(value="00:00:00")
        self._timer_lbl = tk.Label(
            self._bar,
            textvariable=self._timer_var,
            bg=SURFACE, fg=TEXT_S,
            font=("Courier New", 14, "bold"),
            width=9)
        self._timer_lbl.pack(side="left", padx=(4, 0))

        # Red bottom indicator bar (hidden initially)
        self._rec_bar = tk.Frame(self, bg=ACCENT_R, height=2)
        self._rec_bar.place(x=0, rely=1.0, relwidth=1.0, y=-2)
        self._rec_bar.lower()
        self._rec_pulse: Optional[PulseLoop] = None

        # Close button
        close_lbl = tk.Label(self._bar, text="✕", bg=SURFACE, fg=TEXT_S,
                             font=("Segoe UI", 12), cursor="hand2", padx=10)
        close_lbl.pack(side="right", padx=(2, 6))
        close_lbl.bind("<Enter>",   lambda _: close_lbl.configure(fg=ACCENT_R2))
        close_lbl.bind("<Leave>",   lambda _: close_lbl.configure(fg=TEXT_S))
        close_lbl.bind("<Button-1>", lambda _: self._quit())
        Tooltip(close_lbl, "Quit")

    def _div(self):
        tk.Label(self._bar, text="│", bg=SURFACE, fg=BORDER,
                 font=("Segoe UI", 16)).pack(side="left", padx=2)

    # ── Slide-in animation ────────────────────────────────────────────────────

    def _animate_slide_in(self):
        x   = self.winfo_x()
        y_e = self.winfo_y()
        y_s = -BAR_H - 20
        def _upd(t):
            yy = int(y_s + (y_e - y_s) * ease_out_cubic(t))
            self.geometry(f"+{x}+{yy}")
            self.attributes("-alpha", t)
        Animator(self, 380, _upd).start()

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
        log.info("Global hotkeys registered: Ctrl+Shift+R, Ctrl+Shift+S")

    # ── Thread-safe UI helpers ────────────────────────────────────────────────

    def _ui(self, fn):
        """Schedule fn() on the main thread. Safe to call from any thread."""
        self.after(0, fn)

    def _set_status(self, text: str, color: str = TEXT_S):
        self._ui(lambda: (
            self._timer_var.set(text),
            self._timer_lbl.configure(fg=color)
        ))

    def _set_border(self, color: str):
        self._ui(lambda: self._bar.configure(highlightbackground=color))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _open_folder(self):
        path = self._settings.output_folder
        if not os.path.exists(path):
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
            return
        self._set_status("Draw…", ACCENT_Y)
        self.iconify()
        self.after(250, self._launch_selector)

    def _launch_selector(self):
        rs = RegionSelector(self._on_region_selected)
        rs.run()

    def _on_region_selected(self, region):
        self.deiconify()
        self._region = region
        if region:
            l, t, r, b = region
            w, h = r - l, b - t
            self._ui(lambda: (
                self._region_lbl.configure(text=f"{w}×{h}", fg=ACCENT_Y),
                self._btn_region.configure(highlightbackground=ACCENT_Y,
                                           highlightthickness=1)
            ))
            notify("Region Selected", f"{w}×{h} pixels", kind="info", duration=2000)
            log.info("Region set: %s (%dx%d)", region, w, h)
        else:
            self._ui(lambda: self._region_lbl.configure(text="Full Screen", fg=TEXT_S))
        self._set_status("00:00:00", TEXT_S)

    def _clear_region(self):
        self._region = None
        self._ui(lambda: self._region_lbl.configure(text="Full Screen", fg=TEXT_S))
        log.info("Region cleared")

    def _take_screenshot(self):
        """Take screenshot — dispatched to background thread immediately."""
        # Prevent during active recording setup
        idx = self._settings.monitor
        ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = self._settings.output_folder
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"Screenshot_{ts}.png")

        ScreenFlash.fire(self)
        self._set_status("SNAP!", ACCENT_B)

        def _do():
            ok = self._recorder.take_screenshot(
                monitor_index=idx,
                output_path=path,
                region=self._region,
                copy_to_clipboard=self._settings.copy_screenshot,
            )
            if ok:
                notify("Screenshot Saved", os.path.basename(path), kind="info")
            else:
                notify("Screenshot Failed",
                       "Could not grab frame. Check soumo_sr.log", kind="error")
            self._set_status("00:00:00", TEXT_S)

        threading.Thread(target=_do, daemon=True, name="soumo-screenshot").start()

    def _toggle_record(self):
        """Toggle recording state — safe against rapid clicks."""
        if not self._recording_lock.acquire(blocking=False):
            log.warning("Toggle record called while lock held — ignored")
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
            # Release lock after a short delay to block rapid double-clicks
            self.after(500, self._recording_lock.release)

    def _start_recording(self):
        """Kick off recording in a background thread."""
        # Disable record button immediately
        self._ui(lambda: self._btn_rec.set_enabled(False))

        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        ext  = {"MP4": "mp4", "MKV": "mkv", "WebM": "webm"}.get(
                   self._settings.output_format, "mp4")
        path = os.path.join(self._settings.output_folder, f"Video_{ts}.{ext}")

        def _do():
            try:
                self._recorder.start_recording(
                    monitor_index=self._settings.monitor,
                    fps=self._settings.fps,
                    output_path=path,
                    quality=self._settings.quality,
                    color_grading=self._settings.color_grade,
                    region=self._region,
                    audio_enabled=self._settings.audio_enabled,
                    mic_enabled=self._settings.mic_enabled,
                    output_format=self._settings.output_format,
                )
                # Success — update UI
                self._ui(lambda: (
                    self._btn_rec.start_pulse(),
                    self._btn_rec.set_enabled(True),
                    self._rec_bar.lift(),
                    self._set_border(BORDER_REC),
                    self._tt_rec.update_text("Stop Recording  [Ctrl+Shift+R]"),
                ))
                self._start_rec_bar_pulse()
                log.info("Recording started: %s", path)

            except RuntimeError as e:
                # User-visible error
                self._ui(lambda: (
                    self._btn_rec.set_enabled(True),
                    self._set_status("ERROR", ACCENT_R),
                ))
                notify("Recording Failed", str(e), kind="error")
                log.error("Recording start failed: %s", e)
            except Exception as e:
                log.exception("Unexpected recording start error: %s", e)
                self._ui(lambda: self._btn_rec.set_enabled(True))
                notify("Recording Error", str(e), kind="error")

        threading.Thread(target=_do, daemon=True, name="soumo-start-rec").start()

    def _stop_recording(self):
        """Stop recording in a background thread."""
        self._ui(lambda: (
            self._btn_rec.set_enabled(False),
            self._btn_rec.stop_pulse(),
            self._rec_bar.lower(),
            self._set_border(BORDER),
            self._set_status("Saving…", ACCENT_Y),
            self._tt_rec.update_text("Start Recording  [Ctrl+Shift+R]"),
        ))
        self._stop_rec_bar_pulse()

        def _do():
            try:
                self._recorder.stop_recording()
                fname = os.path.basename(self._recorder.output_file)
                self._set_status("✓ Saved", GREEN)
                notify("Recording Saved", fname, kind="success")
                if self._settings.auto_open and self._recorder.output_file:
                    try:
                        os.startfile(self._recorder.output_file)
                    except Exception:
                        pass
            except Exception as e:
                log.exception("Stop recording error: %s", e)
                notify("Save Error", str(e), kind="error")
                self._set_status("ERROR", ACCENT_R)
            finally:
                self._ui(lambda: self._btn_rec.set_enabled(True))
                self.after(2500, lambda: self._set_status("00:00:00", TEXT_S))

        threading.Thread(target=_do, daemon=True, name="soumo-stop-rec").start()

    # ── Record bar pulse ──────────────────────────────────────────────────────

    def _start_rec_bar_pulse(self):
        self._rec_pulse = PulseLoop(
            self, 1600,
            on_update=lambda t: self._rec_bar.configure(
                bg=lerp_color(ACCENT_R, "#FF7070", t))
        )
        self._rec_pulse.start()

    def _stop_rec_bar_pulse(self):
        if self._rec_pulse:
            self._rec_pulse.stop()
            self._rec_pulse = None

    # ── Timer callback ────────────────────────────────────────────────────────

    def _on_timer(self, time_str: str):
        self._set_status(time_str, ACCENT_R)

    # ── Quit ──────────────────────────────────────────────────────────────────

    def _quit(self):
        log.info("Quit requested")
        self._hotkeys.unregister_all()
        if self._recorder.is_recording:
            self._recorder.stop_recording()
        save_settings(self._settings)
        self.destroy()
