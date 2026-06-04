"""
main.py
Soumo Screen Recorder PRO — Entry point.
Configures logging, ensures output folder and icon asset exist, launches toolbar.
"""
import sys
import os
import logging

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soumo_sr.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("main")

import platform
log.info("=== SOUMO SCREEN RECORDER PRO ===")
log.info("Python  : %s", sys.version)
log.info("Platform: %s", platform.platform())
log.info("CWD     : %s", os.getcwd())


def ensure_assets():
    """Generate the app icon if it doesn't exist yet."""
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    os.makedirs(assets_dir, exist_ok=True)
    icon_path = os.path.join(assets_dir, "icon.ico")
    if not os.path.exists(icon_path):
        try:
            from PIL import Image, ImageDraw
            img  = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle((8, 8, 248, 248), radius=48, fill=(13, 13, 20, 255))
            draw.ellipse((72, 72, 184, 184), fill=(192, 57, 43, 255))
            img.save(icon_path, format="ICO",
                     sizes=[(256, 256), (128, 128), (64, 64), (32, 32)])
            log.info("Generated icon.ico")
        except Exception as e:
            log.warning("Icon generation failed: %s", e)
    return icon_path


def ensure_output_folder():
    """Create the default recordings folder."""
    from utils.settings import SAVE_FOLDER_DEFAULT
    os.makedirs(SAVE_FOLDER_DEFAULT, exist_ok=True)
    log.info("Output folder: %s", SAVE_FOLDER_DEFAULT)


if __name__ == "__main__":
    ensure_assets()
    ensure_output_folder()

    from ui.toolbar import Toolbar

    app = Toolbar()

    # Set taskbar icon
    try:
        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico"
        )
        if os.path.exists(icon_path):
            app.iconbitmap(icon_path)
    except Exception:
        pass

    log.info("Entering mainloop")
    app.mainloop()
    log.info("Soumo Screen Recorder PRO exited cleanly.")
