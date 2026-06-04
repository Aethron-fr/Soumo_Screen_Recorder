"""
core/screenshot.py
Screenshot capture module extracted from recorder.
Captures a single frame via dxcam and saves as PNG.
Applies region crop and clipboard copy.
"""
import os
import time
import logging
import numpy as np
from typing import Optional, Tuple
from PIL import Image
import dxcam

log = logging.getLogger(__name__)


def take_screenshot(
    monitor_index:      int = 0,
    output_path:        str = "screenshot.png",
    region:             Optional[Tuple[int, int, int, int]] = None,
    copy_to_clipboard:  bool = True,
    max_retries:        int = 3,
) -> bool:
    """
    Capture a single screen frame and save it as a lossless PNG.

    Uses dxcam with output_color="BGR", then converts BGR→RGB before
    saving with Pillow. Region is applied as a manual NumPy crop AFTER
    capture (avoids dxcam region bugs on some hardware).

    Args:
        monitor_index:      Index of the display to capture.
        output_path:        Full path to the destination PNG file.
        region:             Optional (left, top, right, bottom) crop.
        copy_to_clipboard:  Copy the file path to the system clipboard.
        max_retries:        Number of capture attempts before giving up.

    Returns:
        True if the screenshot was saved successfully, False otherwise.
    """
    log.info("Screenshot: monitor=%d region=%s -> %s", monitor_index, region, output_path)

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)

    camera = None
    for attempt in range(1, max_retries + 1):
        try:
            camera = dxcam.create(output_idx=monitor_index, output_color="BGR")
            frame  = camera.grab()
            del camera
            camera = None

            if frame is None:
                log.warning("Screenshot attempt %d: frame is None", attempt)
                time.sleep(0.05)
                continue

            log.info("Frame captured: shape=%s dtype=%s min=%d max=%d",
                     frame.shape, frame.dtype, int(frame.min()), int(frame.max()))

            if int(frame.max()) == 0:
                log.warning("Frame is all black — possible capture failure")

            # Manual region crop
            if region is not None:
                l, t, r, b = region
                frame = frame[t:b, l:r]
                log.info("Cropped to %s -> shape=%s", region, frame.shape)

            if frame is None or frame.size == 0:
                log.warning("Empty frame after crop on attempt %d", attempt)
                time.sleep(0.05)
                continue

            # BGR → RGB
            rgb = frame[:, :, ::-1].astype(np.uint8)
            img = Image.fromarray(rgb)
            img.save(output_path, format="PNG", compress_level=1)

            file_size = os.path.getsize(output_path)
            log.info("Screenshot saved: %s (%d bytes / %.1f KB)",
                     output_path, file_size, file_size / 1024)

            if copy_to_clipboard:
                try:
                    import pyperclip
                    pyperclip.copy(output_path)
                except Exception as clip_err:
                    log.debug("Clipboard copy failed: %s", clip_err)

            return True

        except Exception as e:
            log.exception("Screenshot attempt %d failed: %s", attempt, e)
            if camera:
                try:
                    del camera
                except Exception:
                    pass
                camera = None
            time.sleep(0.05)

    log.error("All %d screenshot attempts failed.", max_retries)
    return False
