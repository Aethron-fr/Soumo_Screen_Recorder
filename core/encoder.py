"""
core/encoder.py
FFmpeg subprocess manager for hardware-accelerated video encoding.
Reads raw BGR frames from stdin and audio from a Named Pipe,
writing the final encoded output directly to the destination file.
"""

import subprocess
import logging
from typing import Optional, Tuple, List

log = logging.getLogger(__name__)

QUALITY_PROFILES = {
    "Low":    dict(cq="30", bv="20M", preset="p4"),
    "Medium": dict(cq="25", bv="35M", preset="p5"),
    "High":   dict(cq="20", bv="50M", preset="p6"),
    "Ultra":  dict(cq="16", bv="80M", preset="p7"),
}

COLOR_FILTERS = {
    "Neutral":   None,
    "Vibrant":   "eq=saturation=1.3:contrast=1.05",
    "Cinematic": "eq=contrast=1.15:gamma=0.95:saturation=0.9",
}

FORMAT_CONTAINERS = {
    "MP4": "mp4",
    "MKV": "matroska",
    "WebM": "webm",
}


class FFmpegEncoder:
    """
    Manages a single FFmpeg subprocess that encodes screen + audio in real time.

    Video comes in via stdin as raw BGR24 frames.
    Audio comes in via a Windows Named Pipe as raw PCM s16le.
    Both are muxed and encoded directly into the final output file.

    Args:
        width: Frame width in pixels.
        height: Frame height in pixels.
        fps: Target frames per second.
        output_path: Absolute path to the output video file.
        quality: Quality profile key (Low/Medium/High/Ultra).
        color_grade: Color grading preset key.
        audio_pipe: Windows Named Pipe path for audio input.
        sample_rate: Audio sample rate in Hz.
        channels: Number of audio channels.
        output_format: Output container format key (MP4/MKV/WebM).
    """

    def __init__(
        self,
        width: int,
        height: int,
        fps: int,
        output_path: str,
        quality: str = "High",
        color_grade: str = "Neutral",
        audio_pipe: str = r"\\.\pipe\soumo_audio_pipe",
        sample_rate: int = 48000,
        channels: int = 2,
        output_format: str = "MP4",
    ):
        self._width    = width
        self._height   = height
        self._fps      = fps
        self._out      = output_path
        self._quality  = QUALITY_PROFILES.get(quality, QUALITY_PROFILES["High"])
        self._color    = COLOR_FILTERS.get(color_grade)
        self._pipe     = audio_pipe
        self._rate     = sample_rate
        self._channels = channels
        self._fmt      = output_format
        self._process: Optional[subprocess.Popen] = None

    def _build_command(self) -> List[str]:
        """Construct the full FFmpeg command-line argument list."""
        q = self._quality
        cmd = [
            "ffmpeg", "-y",
            # — Video input (stdin)
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{self._width}x{self._height}",
            "-pix_fmt", "bgr24",
            "-r", str(self._fps),
            "-i", "-",
            # — Audio input (named pipe)
            "-f", "s16le",
            "-ar", str(self._rate),
            "-ac", str(self._channels),
            "-i", self._pipe,
        ]

        # Color grading filter
        if self._color:
            cmd += ["-vf", self._color]

        # Video codec — try NVENC first
        if self._fmt == "WebM":
            cmd += ["-c:v", "libvpx-vp9", "-crf", q["cq"], "-b:v", q["bv"]]
        else:
            cmd += [
                "-c:v", "hevc_nvenc",
                "-preset", q["preset"],
                "-tune", "hq",
                "-rc", "vbr",
                "-cq", q["cq"],
                "-b:v", q["bv"],
                "-pix_fmt", "yuv420p",
            ]

        # Audio codec
        if self._fmt == "WebM":
            cmd += ["-c:a", "libopus", "-b:a", "192k"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]

        cmd.append(self._out)
        return cmd

    def start(self) -> None:
        """
        Launch the FFmpeg subprocess.

        Raises:
            RuntimeError: If FFmpeg executable is not found.
        """
        cmd = self._build_command()
        log.info("Starting FFmpeg: %s", " ".join(cmd))
        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "FFmpeg not found. Please install FFmpeg and add it to your PATH."
            )

    def write_frame(self, frame_bytes: bytes) -> bool:
        """
        Write a raw video frame to FFmpeg's stdin.

        Args:
            frame_bytes: Raw BGR24 pixel data.

        Returns:
            True if write succeeded, False if process ended unexpectedly.
        """
        if self._process and self._process.stdin:
            try:
                self._process.stdin.write(frame_bytes)
                return True
            except Exception as e:
                log.error("Frame write error: %s", e)
        return False

    def stop(self) -> None:
        """Signal FFmpeg to finish encoding and wait for it to exit."""
        if self._process:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
                stderr_out = self._process.stderr.read().decode(errors="replace")
                self._process.wait(timeout=30)
                if self._process.returncode != 0:
                    log.error("FFmpeg exited with code %d\n%s",
                              self._process.returncode, stderr_out[-2000:])
                else:
                    log.info("FFmpeg finished successfully.")
            except subprocess.TimeoutExpired:
                self._process.kill()
                log.error("FFmpeg timed out — killed.")
            except Exception as e:
                log.error("FFmpeg stop error: %s", e)
            finally:
                self._process = None

    @property
    def is_running(self) -> bool:
        """True if the FFmpeg subprocess is still active."""
        return self._process is not None and self._process.poll() is None
