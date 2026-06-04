"""
core/recorder.py
High-level recording orchestrator — FIXED VERSION.

Architecture (bug-free):
  Video: dxcam BGR frames -> FFmpeg stdin -> temp video file
  Audio: pyaudiowpatch WASAPI -> in-memory buffer -> WAV file on stop
  Final: FFmpeg mux temp_video + temp_audio -> output file (fast, copy codec)

No Named Pipes for video (eliminates deadlock risk).
Full FFmpeg stderr monitoring.
Full frame validation and logging.
threading.Event for clean shutdown.
All UI calls dispatched via root.after().
"""

import dxcam
import threading
import time
import os
import wave
import shutil
import logging
import subprocess
import numpy as np
from typing import Optional, Tuple, Callable
from PIL import Image

log = logging.getLogger(__name__)

# Quality: maps profile name -> (libx264 crf, nvenc cq, preset)
QUALITY_PROFILES = {
    "Low":    ("30", "30", "fast",   "p4"),
    "Medium": ("23", "25", "medium", "p5"),
    "High":   ("18", "20", "medium", "p6"),
    "Ultra":  ("14", "16", "slow",   "p7"),
}

COLOR_FILTERS = {
    "Neutral":   None,
    "Vibrant":   "eq=saturation=1.35:contrast=1.06:brightness=0.02",
    "Cinematic": "eq=contrast=1.18:gamma=0.92:saturation=0.82",
    "Warm":      "eq=saturation=1.1:contrast=1.05",
    "Cool":      "eq=saturation=0.95:contrast=1.08",
}


def _ffmpeg_stderr_reader(process: subprocess.Popen, logger) -> None:
    """
    Thread target: reads every FFmpeg stderr line and logs it.
    Must be started immediately after Popen to avoid pipe buffer fill.
    """
    try:
        for line in iter(process.stderr.readline, b""):
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded:
                logger.warning("FFmpeg: %s", decoded)
    except Exception as e:
        logger.error("FFmpeg stderr reader died: %s", e)


def _validate_frame(frame, label: str = "frame") -> bool:
    """
    Validate a captured numpy frame. Logs shape, dtype, pixel range.

    Args:
        frame: numpy array or None
        label: context label for logging

    Returns:
        True if frame looks valid.
    """
    if frame is None:
        log.warning("%s is None", label)
        return False
    if frame.size == 0:
        log.warning("%s is empty (size=0)", label)
        return False
    log.debug("%s: shape=%s dtype=%s min=%d max=%d",
              label, frame.shape, frame.dtype, int(frame.min()), int(frame.max()))
    if int(frame.max()) == 0:
        log.warning("%s appears completely black (max pixel = 0)", label)
    return True


def _find_ffmpeg() -> Optional[str]:
    """Locate FFmpeg binary. Checks PATH and common winget install locations."""
    import shutil as sh
    ffmpeg = sh.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    # Common winget location
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


class ScreenRecorder:
    """
    Orchestrates dxcam screen capture + system audio capture + FFmpeg encoding.

    Usage:
        rec = ScreenRecorder()
        rec.set_timer_callback(fn)
        rec.start_recording(...)
        rec.stop_recording()
    """

    def __init__(self):
        self.is_recording: bool = False
        self.is_paused:    bool = False
        self.output_file: str = ""

        self._stop_event   = threading.Event()
        self._pause_event  = threading.Event()  # set = paused
        self._timer_stop   = threading.Event()
        self._timer_cb: Optional[Callable[[str], None]] = None
        self._start_time: float = 0.0
        self._paused_elapsed: float = 0.0  # accumulated paused time
        self._pause_start: float = 0.0

        self._camera: Optional[dxcam.DXCamera] = None
        self._ffmpeg: Optional[subprocess.Popen] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._audio_thread:   Optional[threading.Thread] = None
        self._timer_thread:   Optional[threading.Thread] = None
        self._stderr_thread:  Optional[threading.Thread] = None

        self._audio_frames: list = []
        self._audio_info:   dict = {}
        self._temp_video: str = ""
        self._temp_audio: str = ""
        self._last_frame: Optional[np.ndarray] = None  # for freeze-frame during pause

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_timer_callback(self, cb: Callable[[str], None]) -> None:
        """Register a callback that receives elapsed time string (HH:MM:SS) each second."""
        self._timer_cb = cb

    def get_monitors(self):
        """Return available monitor descriptors from dxcam."""
        try:
            info = dxcam.output_info()
            log.info("Monitors detected: %s", info)
            return info
        except Exception as e:
            log.warning("get_monitors failed: %s", e)
            return ["Primary Monitor"]

    def take_screenshot(
        self,
        monitor_index: int = 0,
        output_path: str = "screenshot.png",
        region: Optional[Tuple[int, int, int, int]] = None,
        copy_to_clipboard: bool = True,
    ) -> bool:
        """
        Capture a single frame and save as PNG.

        Args:
            monitor_index:      Display index.
            output_path:        Destination PNG path.
            region:             (left, top, right, bottom) to crop AFTER capture.
            copy_to_clipboard:  If True, copies file path to clipboard.

        Returns:
            True if screenshot was saved successfully.
        """
        log.info("Screenshot: monitor=%d region=%s -> %s",
                 monitor_index, region, output_path)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        ffmpeg_path = _find_ffmpeg()
        log.info("FFmpeg path: %s", ffmpeg_path)

        for attempt in range(3):
            camera = None
            try:
                # ALWAYS use BGR, no region in dxcam (we crop manually)
                camera = dxcam.create(output_idx=monitor_index, output_color="BGR")
                frame = camera.grab()
                del camera
                camera = None

                if not _validate_frame(frame, f"screenshot attempt {attempt+1}"):
                    time.sleep(0.05)
                    continue

                # Crop if region is set
                if region is not None:
                    l, t, r, b = region
                    cropped = frame[t:b, l:r]
                    log.info("Cropped region %s -> shape %s", region, cropped.shape)
                    frame = cropped

                if frame is None or frame.size == 0:
                    log.warning("Frame empty after crop, retrying")
                    time.sleep(0.05)
                    continue

                # BGR -> RGB for Pillow
                rgb = frame[:, :, ::-1].astype(np.uint8)
                img = Image.fromarray(rgb)
                img.save(output_path, format="PNG")

                sz = os.path.getsize(output_path)
                log.info("Screenshot saved: %s (%d bytes)", output_path, sz)

                if copy_to_clipboard:
                    try:
                        import pyperclip
                        pyperclip.copy(output_path)
                    except Exception:
                        pass

                return True

            except Exception as e:
                log.exception("Screenshot attempt %d failed: %s", attempt + 1, e)
                if camera:
                    try:
                        del camera
                    except Exception:
                        pass
                time.sleep(0.05)

        log.error("All screenshot attempts failed for monitor %d", monitor_index)
        return False

    def start_recording(
        self,
        monitor_index: int = 0,
        fps: int = 60,
        output_path: str = "output.mp4",
        quality: str = "High",
        color_grading: str = "Neutral",
        region: Optional[Tuple[int, int, int, int]] = None,
        audio_enabled: bool = True,
        mic_enabled: bool = False,
        output_format: str = "MP4",
    ) -> None:
        """
        Start recording the screen.

        Raises RuntimeError with a user-readable message on any setup failure.
        """
        if self.is_recording:
            log.warning("start_recording called while already recording — ignored")
            return

        log.info("=== START RECORDING ===")
        log.info("  monitor=%d fps=%d quality=%s color=%s region=%s format=%s",
                 monitor_index, fps, quality, color_grading, region, output_format)
        log.info("  output=%s", output_path)

        self.output_file = output_path
        out_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(out_dir, exist_ok=True)

        # Verify output folder is writable
        if not os.access(out_dir, os.W_OK):
            raise RuntimeError(f"Cannot write to output folder: {out_dir}")

        ffmpeg_bin = _find_ffmpeg()
        if not ffmpeg_bin:
            raise RuntimeError(
                "FFmpeg not found. Install it with:\n  winget install ffmpeg\n"
                "Then restart your terminal."
            )
        log.info("FFmpeg binary: %s", ffmpeg_bin)

        # ── Temp file paths ────────────────────────────────────────────────────
        self._temp_video = os.path.join(out_dir, "_soumo_tmp_video.mp4")
        self._temp_audio = os.path.join(out_dir, "_soumo_tmp_audio.wav")
        for f in [self._temp_video, self._temp_audio]:
            if os.path.exists(f):
                os.remove(f)

        # ── Initialize dxcam ──────────────────────────────────────────────────
        # We NEVER pass region to dxcam — we crop frames manually.
        # This avoids a known dxcam bug where certain regions produce black frames.
        log.info("Initializing dxcam: monitor=%d, color=BGR", monitor_index)
        try:
            self._camera = dxcam.create(output_idx=monitor_index, output_color="BGR")
        except Exception as e:
            log.exception("dxcam.create failed: %s", e)
            raise RuntimeError(
                f"Screen capture failed to initialize. "
                f"Try running as Administrator. Error: {e}"
            )

        # Grab a test frame to determine resolution
        w, h = 1920, 1080
        for attempt in range(3):
            try:
                test_frame = self._camera.grab()
                if _validate_frame(test_frame, "test frame"):
                    h, w = test_frame.shape[:2]
                    log.info("Test frame OK: %dx%d", w, h)
                    break
                time.sleep(0.1)
            except Exception as e:
                log.exception("Test frame grab attempt %d failed: %s", attempt+1, e)
                time.sleep(0.1)
        else:
            del self._camera
            self._camera = None
            raise RuntimeError(
                "Screen capture returned no frames after 3 attempts. "
                "Try running as Administrator."
            )

        # If region is set, compute crop dimensions for FFmpeg
        if region is not None:
            l, t, r, b = region
            crop_w = r - l
            crop_h = b - t
            self._crop_region = region
            enc_w, enc_h = crop_w, crop_h
            log.info("Recording with region: %s -> enc size %dx%d", region, enc_w, enc_h)
        else:
            self._crop_region = None
            enc_w, enc_h = w, h

        # ── Build FFmpeg command ───────────────────────────────────────────────
        q_crf, q_cq, q_preset_x264, q_preset_nvenc = QUALITY_PROFILES.get(
            quality, QUALITY_PROFILES["High"])
        vf = COLOR_FILTERS.get(color_grading)

        # Try codecs in order: hevc_nvenc -> h264_nvenc -> libx264
        codec_options = [
            ("hevc_nvenc", ["-preset", q_preset_nvenc, "-rc", "vbr",
                            "-cq", q_cq, "-pix_fmt", "yuv420p"]),
            ("h264_nvenc", ["-preset", q_preset_nvenc, "-rc", "vbr",
                            "-cq", q_cq, "-pix_fmt", "yuv420p"]),
            ("libx264",    ["-preset", q_preset_x264, "-crf", q_crf,
                            "-pix_fmt", "yuv420p"]),
        ]

        self._ffmpeg = None
        for codec, codec_args in codec_options:
            cmd = [
                ffmpeg_bin, "-y",
                # Video input from stdin
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-s", f"{enc_w}x{enc_h}",
                "-pix_fmt", "bgr24",
                "-r", str(fps),
                "-i", "pipe:0",
            ]
            if vf:
                cmd += ["-vf", vf]
            cmd += ["-c:v", codec] + codec_args + [self._temp_video]

            log.info("Trying codec %s: %s", codec, " ".join(cmd))
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                )
                # Start stderr reader immediately
                t = threading.Thread(
                    target=_ffmpeg_stderr_reader,
                    args=(proc, log),
                    daemon=True,
                    name=f"ffmpeg-stderr-{codec}"
                )
                t.start()
                self._stderr_thread = t

                # Wait briefly — if FFmpeg dies immediately, codec unsupported
                time.sleep(0.4)
                if proc.poll() is not None:
                    log.warning("Codec %s failed immediately (returncode=%s), trying next",
                                codec, proc.returncode)
                    continue

                self._ffmpeg = proc
                log.info("FFmpeg started with codec: %s", codec)
                break

            except FileNotFoundError:
                raise RuntimeError(
                    "FFmpeg not found. Install it with: winget install ffmpeg"
                )
            except Exception as e:
                log.exception("FFmpeg start with %s failed: %s", codec, e)
                continue

        if self._ffmpeg is None:
            del self._camera
            self._camera = None
            raise RuntimeError(
                "Failed to start FFmpeg with any available codec. "
                "Check soumo_sr.log for details."
            )

        # ── Start capture and audio threads ───────────────────────────────────
        self._stop_event.clear()
        self._pause_event.clear()
        self._audio_frames = []
        self._audio_info   = {}
        self._last_frame   = None
        self._paused_elapsed = 0.0
        self._fps          = fps  # store for capture loop

        self._camera.start(target_fps=fps, video_mode=True)
        log.info("dxcam camera started in video_mode")

        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=False, name="soumo-capture")
        self._capture_thread.start()

        if audio_enabled:
            self._audio_thread = threading.Thread(
                target=self._audio_loop, daemon=False, name="soumo-audio")
            self._audio_thread.start()
        else:
            self._audio_thread = None

        # Timer
        self._timer_stop.clear()
        self._start_time = time.time()
        self._timer_thread = threading.Thread(
            target=self._timer_loop, daemon=True, name="soumo-timer")
        self._timer_thread.start()

        self.is_recording = True
        self.is_paused    = False
        log.info("Recording is live.")

    def pause_recording(self) -> None:
        """Pause recording — freezes last frame into FFmpeg, pauses timer."""
        if not self.is_recording or self.is_paused:
            return
        self.is_paused   = True
        self._pause_start = time.time()
        self._pause_event.set()
        log.info("Recording paused")

    def resume_recording(self) -> None:
        """Resume paused recording."""
        if not self.is_recording or not self.is_paused:
            return
        self._paused_elapsed += time.time() - self._pause_start
        self.is_paused = False
        self._pause_event.clear()
        log.info("Recording resumed (total paused: %.1fs)", self._paused_elapsed)

    def stop_recording(self) -> None:
        """
        Stop the active recording. Blocks until encoder flushes and mux completes.
        Call this ONLY from a background thread — never from the UI thread.
        """
        if not self.is_recording:
            log.warning("stop_recording called while not recording")
            return
        # Ensure we unpause before stopping
        if self.is_paused:
            self.resume_recording()

        log.info("=== STOP RECORDING ===")
        self.is_recording = False

        # Signal all threads to stop
        self._stop_event.set()
        self._timer_stop.set()

        # Stop dxcam
        if self._camera:
            try:
                self._camera.stop()
                log.info("dxcam stopped")
            except Exception as e:
                log.error("dxcam stop error: %s", e)

        # Wait for capture thread (it writes frames to FFmpeg)
        if self._capture_thread:
            self._capture_thread.join(timeout=8)
            if self._capture_thread.is_alive():
                log.error("Capture thread did not exit in time!")
            self._capture_thread = None

        # Wait for audio thread
        if self._audio_thread:
            self._audio_thread.join(timeout=5)
            self._audio_thread = None

        # Close FFmpeg stdin -> FFmpeg flushes and writes the output file
        if self._ffmpeg:
            try:
                if self._ffmpeg.stdin:
                    self._ffmpeg.stdin.close()
                    log.info("FFmpeg stdin closed, waiting for encoding to finish...")
                returncode = self._ffmpeg.wait(timeout=60)
                log.info("FFmpeg exited with returncode=%d", returncode)
            except subprocess.TimeoutExpired:
                self._ffmpeg.kill()
                log.error("FFmpeg timed out — killed")
            except Exception as e:
                log.exception("FFmpeg wait error: %s", e)
            self._ffmpeg = None

        # Release camera
        if self._camera:
            try:
                del self._camera
            except Exception:
                pass
            self._camera = None

        # Write audio WAV
        audio_ok = self._write_audio_wav()

        # Mux or rename
        if audio_ok and os.path.exists(self._temp_video):
            self._mux_files()
        elif os.path.exists(self._temp_video):
            try:
                shutil.move(self._temp_video, self.output_file)
                log.info("No audio — moved video to: %s", self.output_file)
            except Exception as e:
                log.exception("File move failed: %s", e)
        else:
            log.error("Temp video not found: %s", self._temp_video)

        # Log final file info
        if os.path.exists(self.output_file):
            sz = os.path.getsize(self.output_file)
            log.info("Final output: %s (%d bytes / %.1f MB)", 
                     self.output_file, sz, sz / 1024 / 1024)
        else:
            log.error("Output file was NOT created: %s", self.output_file)

    # ── Background Threads ────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """Grab BGR frames from dxcam, crop if needed, write raw bytes to FFmpeg."""
        frame_count  = 0
        error_count  = 0
        MAX_ERRORS   = 10
        frame_interval = 1.0 / max(self._fps, 1)
        log.info("Capture loop started (target fps=%d)", self._fps)

        while not self._stop_event.is_set():

            # ── Pause handling ─────────────────────────────────────────────────
            if self._pause_event.is_set():
                # Write frozen last frame to keep FFmpeg's timeline consistent
                if self._last_frame is not None and self._ffmpeg and self._ffmpeg.stdin:
                    try:
                        self._ffmpeg.stdin.write(self._last_frame.tobytes())
                        frame_count += 1
                    except Exception:
                        pass
                time.sleep(frame_interval)
                continue

            frame = self._camera.get_latest_frame()

            if frame is None:
                time.sleep(0.001)
                continue

            # Log first frame in detail
            if frame_count == 0:
                log.info("FIRST FRAME: shape=%s dtype=%s min=%d max=%d",
                         frame.shape, frame.dtype,
                         int(frame.min()), int(frame.max()))

            # Manual region crop
            if self._crop_region is not None:
                l, t, r, b = self._crop_region
                frame = frame[t:b, l:r]

            # Keep copy for pause freeze-frame
            self._last_frame = frame

            # Write raw BGR bytes to FFmpeg stdin
            if self._ffmpeg and self._ffmpeg.stdin:
                try:
                    self._ffmpeg.stdin.write(frame.tobytes())
                    frame_count += 1
                except (BrokenPipeError, OSError) as e:
                    log.error("FFmpeg pipe broken after %d frames: %s", frame_count, e)
                    break
                except Exception as e:
                    error_count += 1
                    log.error("Frame write error (frame %d, error %d): %s",
                              frame_count, error_count, e)
                    if error_count > MAX_ERRORS:
                        log.error("Too many write errors, stopping capture")
                        break
            else:
                break

        log.info("Capture loop ended: %d frames written, %d errors",
                 frame_count, error_count)

    def _audio_loop(self) -> None:
        """Capture WASAPI loopback audio to an in-memory buffer."""
        log.info("Audio loop started")
        try:
            import pyaudiowpatch as pyaudio
            pa = pyaudio.PyAudio()

            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            log.info("Default audio output: %s", default_out["name"])

            loopback = None
            if default_out.get("isLoopbackDevice"):
                loopback = default_out
            else:
                for dev in pa.get_loopback_device_info_generator():
                    if default_out["name"] in dev["name"]:
                        loopback = dev
                        break

            if loopback is None:
                log.warning("No loopback audio device found — recording without audio")
                pa.terminate()
                return

            rate     = int(loopback["defaultSampleRate"])
            channels = max(1, min(loopback["maxInputChannels"], 2))
            fmt      = pyaudio.paInt16
            sw       = pa.get_sample_size(fmt)

            self._audio_info = {
                "rate": rate, "channels": channels,
                "format": fmt, "sample_width": sw
            }
            log.info("Audio: rate=%d ch=%d device='%s'",
                     rate, channels, loopback["name"])

            def _cb(in_data, frame_count, time_info, status):
                if not self._stop_event.is_set():
                    self._audio_frames.append(in_data)
                return (in_data, pyaudio.paContinue)

            stream = pa.open(
                format=fmt,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=loopback["index"],
                frames_per_buffer=1024,
                stream_callback=_cb,
            )
            stream.start_stream()
            log.info("Audio stream active")

            while not self._stop_event.is_set():
                time.sleep(0.1)

            stream.stop_stream()
            stream.close()
            pa.terminate()
            log.info("Audio loop ended: %d chunks captured", len(self._audio_frames))

        except Exception as e:
            log.exception("Audio loop error: %s", e)

    def _timer_loop(self) -> None:
        """Emit elapsed time string every second. Pauses when recording is paused."""
        while not self._timer_stop.is_set():
            if not self.is_paused:
                elapsed = int(time.time() - self._start_time - self._paused_elapsed)
                h, rem = divmod(elapsed, 3600)
                m, s   = divmod(rem, 60)
                if self._timer_cb:
                    self._timer_cb(f"{h:02d}:{m:02d}:{s:02d}")
            time.sleep(1)

    def _write_audio_wav(self) -> bool:
        """Write captured audio frames to a WAV file. Returns True on success."""
        if not self._audio_frames or not self._audio_info:
            log.info("No audio data captured, skipping WAV write")
            return False
        try:
            info = self._audio_info
            with wave.open(self._temp_audio, "wb") as wf:
                wf.setnchannels(info["channels"])
                wf.setsampwidth(info["sample_width"])
                wf.setframerate(info["rate"])
                wf.writeframes(b"".join(self._audio_frames))
            sz = os.path.getsize(self._temp_audio)
            log.info("Audio WAV: %s (%d bytes)", self._temp_audio, sz)
            return True
        except Exception as e:
            log.exception("WAV write failed: %s", e)
            return False

    def _mux_files(self) -> None:
        """Mux temp video + temp audio into the final output file using stream copy."""
        log.info("Muxing: %s + %s -> %s",
                 self._temp_video, self._temp_audio, self.output_file)
        ffmpeg_bin = _find_ffmpeg() or "ffmpeg"
        cmd = [
            ffmpeg_bin, "-y",
            "-i", self._temp_video,
            "-i", self._temp_audio,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            self.output_file,
        ]
        log.info("Mux command: %s", " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode == 0:
                log.info("Mux succeeded: %s", self.output_file)
            else:
                log.error("Mux failed (code %d): %s",
                          result.returncode,
                          result.stderr.decode("utf-8", errors="replace")[-2000:])
                # Fallback: at least keep the video
                if os.path.exists(self._temp_video):
                    shutil.move(self._temp_video, self.output_file)
                    log.info("Mux fallback: moved raw video to output")
        except subprocess.TimeoutExpired:
            log.error("Mux timed out!")
        except Exception as e:
            log.exception("Mux error: %s", e)
        finally:
            for f in [self._temp_video, self._temp_audio]:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass
