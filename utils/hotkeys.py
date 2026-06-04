"""
utils/hotkeys.py
Global hotkey management using the keyboard library.
"""

import logging
from typing import Callable, Dict
import keyboard

log = logging.getLogger(__name__)


class HotkeyManager:
    """
    Manages registration and cleanup of global hotkeys.

    All hotkeys are registered here and can be cleanly unregistered
    on app exit to avoid lingering hooks.
    """

    def __init__(self):
        self._hooks: Dict[str, object] = {}

    def register(self, combo: str, callback: Callable) -> bool:
        """
        Register a global hotkey.

        Args:
            combo: Key combination string, e.g. 'ctrl+shift+r'
            callback: Callable to invoke when hotkey is pressed.

        Returns:
            True if registration succeeded, False otherwise.
        """
        try:
            if combo in self._hooks:
                self.unregister(combo)
            self._hooks[combo] = keyboard.add_hotkey(combo, callback)
            log.info("Registered hotkey: %s", combo)
            return True
        except Exception as e:
            log.error("Failed to register hotkey %s: %s", combo, e)
            return False

    def unregister(self, combo: str) -> None:
        """
        Unregister a previously registered hotkey.

        Args:
            combo: Key combination string to remove.
        """
        try:
            keyboard.remove_hotkey(combo)
            self._hooks.pop(combo, None)
        except Exception as e:
            log.warning("Failed to unregister hotkey %s: %s", combo, e)

    def unregister_all(self) -> None:
        """Unregister all managed hotkeys."""
        for combo in list(self._hooks.keys()):
            self.unregister(combo)
        log.info("All hotkeys unregistered.")
