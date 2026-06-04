"""
utils/animations.py
Animation engine for Soumo Screen Recorder.
Provides smooth property animations via Tkinter's .after() loop.
"""

import math
import logging
from typing import Callable, Optional, Any

log = logging.getLogger(__name__)


# ── Easing Functions ───────────────────────────────────────────────────────────

def ease_out_cubic(t: float) -> float:
    """Decelerating cubic ease. t in [0,1]."""
    return 1 - (1 - t) ** 3


def ease_in_out_sine(t: float) -> float:
    """Smooth sine-wave easing. t in [0,1]."""
    return -(math.cos(math.pi * t) - 1) / 2


def ease_out_back(t: float, s: float = 1.70158) -> float:
    """Overshoot spring effect. t in [0,1]."""
    c1 = s
    c3 = c1 + 1
    return 1 + c3 * math.pow(t - 1, 3) + c1 * math.pow(t - 1, 2)


def ease_out_elastic(t: float) -> float:
    """Elastic bounce-back easing. t in [0,1]."""
    if t == 0:
        return 0
    if t == 1:
        return 1
    return math.pow(2, -10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1


# ── Color Helpers ──────────────────────────────────────────────────────────────

def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color string to (r, g, b) tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert (r, g, b) to hex color string."""
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def lerp_color(color_a: str, color_b: str, t: float) -> str:
    """
    Linearly interpolate between two hex colors.

    Args:
        color_a: Starting hex color.
        color_b: Ending hex color.
        t: Interpolation factor in [0, 1].

    Returns:
        Interpolated hex color string.
    """
    ra, ga, ba = hex_to_rgb(color_a)
    rb, gb, bb = hex_to_rgb(color_b)
    return rgb_to_hex(
        ra + (rb - ra) * t,
        ga + (gb - ga) * t,
        ba + (bb - ba) * t
    )


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b."""
    return a + (b - a) * t


# ── Animator Class ─────────────────────────────────────────────────────────────

class Animator:
    """
    Generic property animator using Tkinter's .after() scheduling.

    Drives smooth transitions from a start value to an end value
    over a given duration, calling an update function each frame.

    Args:
        root: Tkinter root or any widget with .after() method.
        duration_ms: Total animation duration in milliseconds.
        on_update: Callback receiving interpolated value (0.0 to 1.0).
        on_complete: Optional callback invoked when animation ends.
        easing: Easing function. Defaults to ease_out_cubic.
        fps: Frames per second target. Defaults to 60.
    """

    FPS = 60
    FRAME_MS = 1000 // FPS  # ~16ms

    def __init__(
        self,
        root,
        duration_ms: int,
        on_update: Callable[[float], None],
        on_complete: Optional[Callable] = None,
        easing: Callable[[float], float] = None,
    ):
        self._root       = root
        self._duration   = max(duration_ms, 1)
        self._on_update  = on_update
        self._on_complete = on_complete
        self._easing     = easing or ease_out_cubic
        self._elapsed    = 0
        self._after_id   = None
        self._running    = False

    def start(self) -> None:
        """Start the animation from the beginning."""
        self.stop()
        self._elapsed = 0
        self._running = True
        self._tick()

    def stop(self) -> None:
        """Cancel a running animation immediately."""
        self._running = False
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _tick(self) -> None:
        if not self._running:
            return
        t = min(self._elapsed / self._duration, 1.0)
        value = self._easing(t)
        try:
            self._on_update(value)
        except Exception as e:
            log.error("Animation update error: %s", e)
            self.stop()
            return

        if t >= 1.0:
            self._running = False
            if self._on_complete:
                try:
                    self._on_complete()
                except Exception as e:
                    log.error("Animation complete callback error: %s", e)
            return

        self._elapsed += self.FRAME_MS
        self._after_id = self._root.after(self.FRAME_MS, self._tick)


# ── Color Animator ─────────────────────────────────────────────────────────────

class ColorAnimator:
    """
    Animates smoothly between two hex colors, calling a setter each frame.

    Args:
        root: Tkinter root/widget.
        from_color: Starting hex color.
        to_color:   Ending hex color.
        duration_ms: Duration in milliseconds.
        setter: Callable that receives the current hex color string.
        easing: Easing function.
        on_complete: Optional completion callback.
    """

    def __init__(self, root, from_color: str, to_color: str, duration_ms: int,
                 setter: Callable[[str], None], easing=None, on_complete=None):
        self._from   = from_color
        self._to     = to_color
        self._setter = setter
        self._anim   = Animator(
            root, duration_ms,
            on_update=self._update,
            on_complete=on_complete,
            easing=easing
        )

    def _update(self, t: float) -> None:
        self._setter(lerp_color(self._from, self._to, t))

    def start(self) -> None:
        """Start the color animation."""
        self._anim.start()

    def stop(self) -> None:
        """Stop the color animation."""
        self._anim.stop()


# ── Pulse Loop ─────────────────────────────────────────────────────────────────

class PulseLoop:
    """
    Drives a continuous breathing/pulsing animation between two values.
    Uses a sine wave for smooth back-and-forth oscillation.

    Args:
        root: Tkinter root/widget.
        period_ms: Total cycle duration (full period) in milliseconds.
        on_update: Callback receiving current value in [0.0, 1.0].
    """

    def __init__(self, root, period_ms: int, on_update: Callable[[float], None]):
        self._root      = root
        self._period    = period_ms
        self._on_update = on_update
        self._elapsed   = 0
        self._running   = False
        self._after_id  = None
        self._frame_ms  = 16

    def start(self) -> None:
        """Start the pulse loop."""
        self.stop()
        self._elapsed = 0
        self._running = True
        self._tick()

    def stop(self) -> None:
        """Stop the pulse loop."""
        self._running = False
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _tick(self) -> None:
        if not self._running:
            return
        phase = (self._elapsed % self._period) / self._period  # 0..1
        value = (math.sin(2 * math.pi * phase - math.pi / 2) + 1) / 2  # 0..1
        try:
            self._on_update(value)
        except Exception:
            self.stop()
            return
        self._elapsed += self._frame_ms
        self._after_id = self._root.after(self._frame_ms, self._tick)
