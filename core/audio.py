"""
core/audio.py
System audio capture via WASAPI Loopback using pyaudiowpatch.
Streams captured audio directly into a Windows Named Pipe.
"""

import threading
import logging
import win32pipe
import win32file
import pyaudiowpatch as pyaudio

log = logging.getLogger(__name__)

AUDIO_PIPE_NAME = r'\\.\pipe\soumo_audio_pipe'


class AudioCapture:
    """
    Captures system audio (WASAPI loopback) and writes raw PCM frames
    to a Windows Named Pipe so FFmpeg can consume them in real-time.

    Args:
        pipe_name: Name of the Windows Named Pipe to write audio into.
    """

    def __init__(self, pipe_name: str = AUDIO_PIPE_NAME):
        self._pipe_name   = pipe_name
        self._pipe_handle = None
        self._pa          = None
        self._stream      = None
        self._stop_event  = threading.Event()

        # Audio properties — set when stream opens
        self.sample_rate: int = 48000
        self.channels: int    = 2
        self.format               = pyaudio.paInt16
        self._chunk: int      = 1024

    def create_pipe(self) -> None:
        """
        Create the Windows Named Pipe server handle.
        Must be called before starting FFmpeg so it can connect.
        """
        self._pipe_handle = win32pipe.CreateNamedPipe(
            self._pipe_name,
            win32pipe.PIPE_ACCESS_OUTBOUND,
            win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT,
            1, 65536, 65536, 0, None
        )
        log.info("Audio pipe created: %s", self._pipe_name)

    def wait_for_client(self) -> None:
        """
        Block until FFmpeg connects to the audio pipe.
        Should be called in a background thread.
        """
        try:
            win32pipe.ConnectNamedPipe(self._pipe_handle, None)
            log.info("FFmpeg connected to audio pipe.")
        except Exception as e:
            log.error("Pipe connect error: %s", e)

    def start(self, stop_event: threading.Event) -> None:
        """
        Open the WASAPI loopback stream and begin capturing.

        Args:
            stop_event: Threading event; when set, capture stops cleanly.
        """
        self._stop_event = stop_event
        self._pa = pyaudio.PyAudio()
        device = self._find_loopback_device()

        if device:
            self.sample_rate = int(device["defaultSampleRate"])
            self.channels    = device["maxInputChannels"]
            idx              = device["index"]
        else:
            log.warning("No loopback device found, using defaults.")
            idx = None

        open_kwargs = dict(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            frames_per_buffer=self._chunk,
            input=True,
            stream_callback=self._callback
        )
        if idx is not None:
            open_kwargs["input_device_index"] = idx

        self._stream = self._pa.open(**open_kwargs)
        self._stream.start_stream()
        log.info("Audio capture started (rate=%d, ch=%d)", self.sample_rate, self.channels)

    def _find_loopback_device(self):
        """Locate the default speakers' loopback device."""
        try:
            wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default = self._pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            if default.get("isLoopbackDevice"):
                return default
            for dev in self._pa.get_loopback_device_info_generator():
                if default["name"] in dev["name"]:
                    return dev
        except Exception as e:
            log.error("Error finding loopback device: %s", e)
        return None

    def _callback(self, in_data, frame_count, time_info, status):
        """PyAudio callback — writes audio frames to the Named Pipe."""
        if not self._stop_event.is_set() and self._pipe_handle:
            try:
                win32file.WriteFile(self._pipe_handle, in_data)
            except Exception as e:
                log.error("Audio pipe write error: %s", e)
        return (in_data, pyaudio.paContinue)

    def stop(self) -> None:
        """Stop audio capture and clean up all resources."""
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                log.error("Error stopping audio stream: %s", e)
            self._stream = None

        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

        if self._pipe_handle:
            try:
                win32file.CloseHandle(self._pipe_handle)
            except Exception:
                pass
            self._pipe_handle = None

        log.info("Audio capture stopped.")
