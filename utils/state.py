"""
utils/state.py
Shared application state dataclass.
Single source of truth passed by reference between all components.
No global variables. No circular imports.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Optional, Tuple, Callable


@dataclass
class AppState:
    """
    Single source of truth for all mutable runtime state.

    Passed by reference to every component so all parts of the app
    share the same live state without event buses or globals.
    """

    # ── Recording state ──
    is_recording:    bool = False
    is_paused:       bool = False
    current_region:  Optional[Tuple[int, int, int, int]] = None
    last_output_file: str = ""

    # ── Live settings (kept in sync with Settings dataclass) ──
    fps:           int  = 60
    quality:       str  = "High"
    color_grade:   str  = "Neutral"
    output_format: str  = "MP4"
    audio_enabled: bool = True
    mic_enabled:   bool = False

    # ── Threading primitives ──
    stop_event:    threading.Event = field(default_factory=threading.Event)
    pause_event:   threading.Event = field(default_factory=threading.Event)

    # ── UI callbacks (set by toolbar, called from background threads) ──
    # Always call via root.after(0, ...) when on a background thread.
    on_timer:      Optional[Callable[[str], None]] = None
    on_error:      Optional[Callable[[str, str], None]] = None
    on_saved:      Optional[Callable[[str], None]] = None
