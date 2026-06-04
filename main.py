"""
main.py
Entry point for Soumo Screen Recorder PRO.
Configures logging, generates assets, and launches the toolbar.
"""

import sys
import os
import logging

# ── Logging setup ──────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soumo_sr.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("main")

# ── Ensure assets exist ────────────────────────────────────────────────────────
def ensure_assets():
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    os.makedirs(assets_dir, exist_ok=True)
    icon_path = os.path.join(assets_dir, "icon.ico")
    if not os.path.exists(icon_path):
        try:
            from PIL import Image, ImageDraw
            img  = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle((8, 8, 248, 248), radius=48, fill=(13, 13, 26, 255))
            draw.ellipse((64, 64, 192, 192), fill=(192, 57, 43, 255))
            img.save(icon_path, format="ICO", sizes=[(256,256),(128,128),(64,64),(32,32)])
            log.info("Generated icon.ico")
        except Exception as e:
            log.warning("Icon generation failed: %s", e)
    return icon_path


if __name__ == "__main__":
    log.info("Starting Soumo Screen Recorder PRO")
    ensure_assets()

    from ui.toolbar import Toolbar
    app = Toolbar()

    # Set window icon if available
    try:
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
        if os.path.exists(icon_path):
            app.iconbitmap(icon_path)
    except Exception:
        pass

    app.mainloop()
    log.info("Soumo Screen Recorder PRO exited.")
