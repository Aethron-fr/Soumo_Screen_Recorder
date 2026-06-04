"""
utils/settings.py
Settings persistence — loads/saves user preferences to settings.json.
"""

import json
import os
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple

log = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "settings.json")

SAVE_FOLDER_DEFAULT = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "Soumo Recordings")
if not os.path.exists(os.path.join(os.path.expanduser("~"), "OneDrive")):
    SAVE_FOLDER_DEFAULT = os.path.join(os.path.expanduser("~"), "Desktop", "Soumo Recordings")
os.makedirs(SAVE_FOLDER_DEFAULT, exist_ok=True)


@dataclass
class Settings:
    """All user-configurable preferences for the recorder."""
    monitor: int = 0
    fps: int = 120
    quality: str = "High"
    color_grade: str = "Neutral"
    output_folder: str = SAVE_FOLDER_DEFAULT
    audio_enabled: bool = True
    mic_enabled: bool = False
    toolbar_x: int = -1  # -1 = auto-center
    toolbar_y: int = 16
    output_format: str = "MP4"
    auto_open: bool = False
    countdown_enabled: bool = False
    copy_screenshot: bool = True


def load_settings() -> Settings:
    """Load settings from disk. Returns defaults if file missing or corrupt."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            s = Settings()
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
            return s
    except Exception as e:
        log.warning("Failed to load settings, using defaults: %s", e)
    return Settings()


def save_settings(settings: Settings) -> None:
    """Persist settings to disk."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, indent=2)
    except Exception as e:
        log.error("Failed to save settings: %s", e)
