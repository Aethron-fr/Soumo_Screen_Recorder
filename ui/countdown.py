"""
ui/countdown.py
3-2-1 countdown overlay before recording starts.
Full-screen dark overlay with animated scaling number.
"""
import tkinter as tk
import logging
from utils.animations import Animator, ease_out_cubic

log = logging.getLogger(__name__)


class CountdownOverlay:
    """
    Displays a full-screen 3-2-1 countdown before recording begins.

    Each number animates from scale 1.4 → 1.0 with ease_out_cubic,
    creating a punchy "snap" feel. The overlay is automatically
    destroyed when the countdown reaches 0.

    Args:
        on_done: Callback invoked when countdown finishes.
        start_from: Starting number (default 3).
    """

    def __init__(self, on_done, start_from: int = 3):
        self._on_done    = on_done
        self._count      = start_from
        self._start_from = start_from
        self._win        = None
        self._lbl        = None
        self._anim_id    = None

    def show(self) -> None:
        """Create and display the countdown overlay."""
        self._win = tk.Toplevel()
        self._win.overrideredirect(True)
        self._win.attributes("-fullscreen", True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", 0.0)
        self._win.configure(bg="#000000")

        # Fade in
        def _fade(t):
            try:
                self._win.attributes("-alpha", t * 0.80)
            except Exception:
                pass
        Animator(self._win, 200, _fade).start()

        self._lbl = tk.Label(
            self._win, text=str(self._count),
            bg="#000000", fg="#E74C3C",
            font=("Segoe UI Variable", 180, "bold")
        )
        self._lbl.place(relx=0.5, rely=0.5, anchor="center")
        self._tick()

    def _tick(self) -> None:
        if self._count <= 0:
            self._finish()
            return

        self._lbl.configure(
            text=str(self._count),
            font=("Segoe UI Variable", int(180 * 1.4), "bold")
        )
        # Scale 1.4 → 1.0 over 600ms
        def _scale(t):
            sz = int(180 * (1.4 - 0.4 * ease_out_cubic(t)))
            try:
                self._lbl.configure(font=("Segoe UI Variable", max(sz, 40), "bold"))
            except Exception:
                pass
        Animator(self._win, 600, _scale).start()

        self._count -= 1
        self._anim_id = self._win.after(1000, self._tick)

    def _finish(self) -> None:
        """Fade out and destroy overlay, then invoke on_done."""
        if not self._win:
            return

        def _fade_out(t):
            try:
                self._win.attributes("-alpha", 0.80 * (1 - t))
            except Exception:
                pass

        def _destroy():
            try:
                self._win.destroy()
            except Exception:
                pass
            self._on_done()

        Animator(self._win, 250, _fade_out, on_complete=_destroy).start()
