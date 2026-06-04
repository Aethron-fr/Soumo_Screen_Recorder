"""
utils/animations.py
Complete animation engine for Soumo Screen Recorder PRO.
Provides smooth 60fps property animations via Tkinter .after() loops.
Includes spring physics, pulse loops, and color interpolation.
"""
from __future__ import annotations
import math
import logging
from typing import Callable, Optional

log = logging.getLogger(__name__)

FRAME_MS = 16  # ~60 FPS


# ────────────────────────────────────────────────────────────────
class EasingFunctions:
    """
    Collection of easing functions. All take t in [0.0, 1.0]
    and return an eased value, usually also in [0.0, 1.0].
    """

    @staticmethod
    def linear(t: float) -> float:
        return t

    @staticmethod
    def ease_out_cubic(t: float) -> float:
        """Decelerating. Starts fast, ends slow."""
        return 1 - (1 - t) ** 3

    @staticmethod
    def ease_in_cubic(t: float) -> float:
        """Accelerating. Starts slow, ends fast."""
        return t ** 3

    @staticmethod
    def ease_in_out_sine(t: float) -> float:
        """Smooth S-curve using sine wave."""
        return -(math.cos(math.pi * t) - 1) / 2

    @staticmethod
    def ease_out_back(t: float) -> float:
        """Slight overshoot and settle. Good for UI popins."""
        c1 = 1.70158
        c3 = c1 + 1
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

    @staticmethod
    def spring(t: float, stiffness: float = 200.0, damping: float = 20.0) -> float:
        """
        Physical spring simulation with overshoot.

        Args:
            t:          Time in [0.0, 1.0] (normalized to animation duration)
            stiffness:  Spring stiffness constant (higher = stiffer)
            damping:    Damping coefficient (higher = less oscillation)

        Returns:
            Displacement value (may exceed 1.0 on overshoot)
        """
        if t <= 0.0:
            return 0.0
        if t >= 1.0:
            return 1.0

        omega = math.sqrt(stiffness)
        zeta  = damping / (2.0 * omega)

        if zeta < 1.0:
            wd = omega * math.sqrt(1.0 - zeta ** 2)
            return 1.0 - math.exp(-zeta * omega * t) * (
                math.cos(wd * t) + (zeta * omega / wd) * math.sin(wd * t)
            )
        else:
            return 1.0 - math.exp(-omega * t) * (1.0 + omega * t)


# Convenient module-level aliases
ease_out_cubic   = EasingFunctions.ease_out_cubic
ease_in_out_sine = EasingFunctions.ease_in_out_sine
ease_out_back    = EasingFunctions.ease_out_back
spring           = EasingFunctions.spring


# ── Color helpers ─────────────────────────────────────────────────────────────
def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color string to (r, g, b) int tuple."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert (r, g, b) floats to hex color string."""
    return f"#{int(max(0,min(255,r))):02x}{int(max(0,min(255,g))):02x}{int(max(0,min(255,b))):02x}"


def lerp_color(a: str, b: str, t: float) -> str:
    """
    Linear interpolate between two hex colors.

    Args:
        a: Start hex color.
        b: End hex color.
        t: Factor in [0.0, 1.0].

    Returns:
        Interpolated hex color string.
    """
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    return rgb_to_hex(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation."""
    return a + (b - a) * t


# ── Animator ────────────────────────────────────────────────────────────────
class Animator:
    """
    Generic property animator using Tkinter's .after() scheduler.

    Drives a transition from 0.0 to 1.0 (normalized time) over
    `duration_ms` milliseconds, calling `on_update(t)` each frame
    where t is the eased value at that moment.

    Args:
        root:        Any Tkinter widget (used for .after() scheduling).
        duration_ms: Total animation length in milliseconds.
        on_update:   Called each frame with eased t in [0.0, ~1.05].
        on_complete: Optional callback when animation ends.
        easing:      Easing function. Defaults to ease_out_cubic.
    """

    def __init__(
        self,
        root,
        duration_ms: int,
        on_update:   Callable[[float], None],
        on_complete: Optional[Callable] = None,
        easing:      Callable[[float], float] = None,
    ):
        self._root       = root
        self._duration   = max(1, duration_ms)
        self._on_update  = on_update
        self._on_complete = on_complete
        self._easing     = easing or ease_out_cubic
        self._elapsed    = 0
        self._after_id   = None
        self._running    = False

    def start(self) -> "Animator":
        """Start the animation. Returns self for chaining."""
        self.stop()
        self._elapsed = 0
        self._running = True
        self._tick()
        return self

    def stop(self) -> None:
        """Cancel the animation immediately."""
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
        raw_t = min(self._elapsed / self._duration, 1.0)
        eased = self._easing(raw_t)
        try:
            self._on_update(eased)
        except Exception as e:
            log.debug("Animator update error: %s", e)
            self.stop()
            return

        if raw_t >= 1.0:
            self._running = False
            if self._on_complete:
                try:
                    self._on_complete()
                except Exception as e:
                    log.debug("Animator complete error: %s", e)
            return

        self._elapsed += FRAME_MS
        self._after_id = self._root.after(FRAME_MS, self._tick)


# ── ColorAnimator ───────────────────────────────────────────────────────────
class ColorAnimator:
    """
    Smoothly interpolates between two hex colors.

    Args:
        root:        Tkinter widget for scheduling.
        from_color:  Starting hex color.
        to_color:    Ending hex color.
        duration_ms: Duration in milliseconds.
        setter:      Callable receiving the current hex color string each frame.
        easing:      Optional easing function.
        on_complete: Optional completion callback.
    """

    def __init__(self, root, from_color: str, to_color: str,
                 duration_ms: int, setter: Callable[[str], None],
                 easing=None, on_complete=None):
        self._from  = from_color
        self._to    = to_color
        self._setter = setter
        self._anim   = Animator(
            root, duration_ms,
            on_update=self._update,
            on_complete=on_complete,
            easing=easing
        )

    def _update(self, t: float) -> None:
        self._setter(lerp_color(self._from, self._to, t))

    def start(self) -> "ColorAnimator":
        """Start the color animation."""
        self._anim.start()
        return self

    def stop(self) -> None:
        """Stop the color animation."""
        self._anim.stop()


# ── PulseLoop ────────────────────────────────────────────────────────────────
class PulseLoop:
    """
    Continuous sinusoidal breathing/pulsing animation.

    Calls on_update with a value in [0.0, 1.0] cycling on a sine wave.
    Runs indefinitely until stop() is called.

    Args:
        root:       Tkinter widget for scheduling.
        period_ms:  Full cycle duration (peak to peak) in milliseconds.
        on_update:  Callback receiving current value in [0.0, 1.0].
    """

    def __init__(self, root, period_ms: int, on_update: Callable[[float], None]):
        self._root      = root
        self._period    = period_ms
        self._on_update = on_update
        self._elapsed   = 0
        self._running   = False
        self._after_id  = None

    def start(self) -> "PulseLoop":
        """Start the pulse loop."""
        self.stop()
        self._elapsed = 0
        self._running = True
        self._tick()
        return self

    def stop(self) -> None:
        """Stop the pulse loop immediately."""
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
        phase = (self._elapsed % self._period) / self._period
        value = (math.sin(2 * math.pi * phase - math.pi / 2) + 1) / 2
        try:
            self._on_update(value)
        except Exception:
            self.stop()
            return
        self._elapsed += FRAME_MS
        self._after_id = self._root.after(FRAME_MS, self._tick)
