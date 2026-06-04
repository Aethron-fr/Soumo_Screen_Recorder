"""
utils/animations.py
Key-based animation engine for Soumo Screen Recorder PRO.
Uses time.perf_counter for precise timing. Each animation is
identified by a unique string key so it can be cancelled by name.
"""
from __future__ import annotations
import math
import time
import logging
from typing import Callable, Dict, Optional

log = logging.getLogger(__name__)


# ── Color helpers ─────────────────────────────────────────────────────────────

def interpolate_color(hex1: str, hex2: str, t: float) -> str:
    """Interpolate between two hex colors. t in [0.0, 1.0]."""
    t = max(0.0, min(1.0, t))
    def _parse(h: str):
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r1, g1, b1 = _parse(hex1)
    r2, g2, b2 = _parse(hex2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# ── Easing functions ──────────────────────────────────────────────────────────

def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3

def _ease_in_out_sine(t: float) -> float:
    return -(math.cos(math.pi * t) - 1) / 2

def _spring(t: float) -> float:
    """Spring approximation with slight overshoot."""
    if t >= 1.0:
        return 1.0
    v = 1 - math.exp(-6 * t) * math.cos(12 * t)
    return min(v, 1.05)  # allow tiny overshoot


_EASINGS: Dict[str, Callable[[float], float]] = {
    "linear":           lambda t: t,
    "ease_out_cubic":   _ease_out_cubic,
    "ease_in_out_sine": _ease_in_out_sine,
    "spring":           _spring,
}

# Public aliases — imported by countdown.py and other modules
ease_out_cubic   = _ease_out_cubic
ease_in_out_sine = _ease_in_out_sine
spring_ease      = _spring


def lerp_color(a: str, b: str, t: float) -> str:
    """Alias for interpolate_color (backwards compatibility)."""
    return interpolate_color(a, b, t)


# ── Animator ──────────────────────────────────────────────────────────────────

class Animator:
    """
    Key-based animation manager for Tkinter.

    Each animation is keyed by a string. Starting a new animation
    with the same key automatically cancels the previous one.

    Uses time.perf_counter() for sub-millisecond precision.
    All callbacks are scheduled via root.after() so they execute
    safely on the main Tkinter thread.

    Usage:
        anim = Animator(root)
        anim.animate("btn_hover", 0, 1, 120, "ease_out_cubic",
                     on_update=lambda v: update_color(v))
        anim.pulse("rec_pulse", on_update=lambda v: set_glow(v),
                   min_val=0.3, max_val=1.0, period_ms=1800)
        anim.stop("rec_pulse")
        anim.stop_all()
    """

    def __init__(self, root):
        self.root = root
        self._active: Dict[str, str] = {}  # key -> after_id

    def animate(
        self,
        key:         str,
        start:       float,
        end:         float,
        duration_ms: int,
        easing:      str = "ease_out_cubic",
        on_update:   Optional[Callable[[float], None]] = None,
        on_done:     Optional[Callable] = None,
    ) -> None:
        """
        Animate a float value from start to end over duration_ms.

        Args:
            key:         Unique identifier. Cancels any existing animation with same key.
            start:       Starting value.
            end:         Target value.
            duration_ms: Duration in milliseconds.
            easing:      Easing function name (see _EASINGS).
            on_update:   Called each frame with current interpolated value.
            on_done:     Called once when animation completes.
        """
        self.stop(key)
        easing_fn = _EASINGS.get(easing, _ease_out_cubic)
        start_t   = time.perf_counter()
        dur_s     = max(duration_ms, 1) / 1000.0

        def _tick():
            if key not in self._active:
                return
            elapsed = time.perf_counter() - start_t
            raw_t   = min(elapsed / dur_s, 1.0)
            value   = start + (end - start) * easing_fn(raw_t)

            if on_update:
                try:
                    on_update(value)
                except Exception as e:
                    log.debug("Animator[%s] update error: %s", key, e)

            if raw_t >= 1.0:
                self._active.pop(key, None)
                if on_update:
                    try:
                        on_update(end)
                    except Exception:
                        pass
                if on_done:
                    try:
                        on_done()
                    except Exception as e:
                        log.debug("Animator[%s] done error: %s", key, e)
            else:
                self._active[key] = self.root.after(16, _tick)

        self._active[key] = self.root.after(0, _tick)

    def pulse(
        self,
        key:        str,
        on_update:  Callable[[float], None],
        min_val:    float = 0.0,
        max_val:    float = 1.0,
        period_ms:  int   = 1800,
    ) -> None:
        """
        Run a continuous sine-wave pulse between min_val and max_val.
        Runs until stop(key) is called.

        Args:
            key:        Unique animation key.
            on_update:  Called ~60fps with current value in [min_val, max_val].
            min_val:    Minimum oscillation value.
            max_val:    Maximum oscillation value.
            period_ms:  Full oscillation cycle duration in milliseconds.
        """
        self.stop(key)
        start_t = time.perf_counter()

        def _tick():
            if key not in self._active:
                return
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            phase = (elapsed_ms % period_ms) / period_ms
            sine  = math.sin(2 * math.pi * phase - math.pi / 2)
            val   = min_val + (max_val - min_val) * (sine * 0.5 + 0.5)
            try:
                on_update(val)
            except Exception:
                self.stop(key)
                return
            self._active[key] = self.root.after(16, _tick)

        self._active[key] = self.root.after(16, _tick)

    def stop(self, key: str) -> None:
        """Cancel animation by key."""
        after_id = self._active.pop(key, None)
        if after_id:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass

    def stop_all(self) -> None:
        """Cancel all active animations."""
        for key in list(self._active.keys()):
            self.stop(key)
