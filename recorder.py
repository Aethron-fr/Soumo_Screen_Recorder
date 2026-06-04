import dxcam
import pyaudiowpatch as pyaudio
import subprocess
import threading
import time
import os
import win32pipe, win32file
from PIL import Image

class ScreenRecorder:
    def __init__(self):
        self.dxcam_camera = None
        self.audio = None
        self.audio_stream = None
        self.is_recording = False
        self.video_process = None
        
        self.target_fps = 120
        self.resolution = None
        self.output_file = "output.mp4"
        
        self.capture_thread = None
        
        self.audio_format = pyaudio.paInt16
        self.audio_channels = 2
        self.audio_rate = 48000
        self.audio_chunk = 1024
        
        self.start_time = 0
        self.duration_callback = None
        self._timer_thread = None
        
        self.audio_pipe_name = r'\\.\pipe\soumo_audio_pipe'
        self.audio_pipe_handle = None

    def get_monitors(self):
        try:
            return dxcam.output_info()
        except Exception:
            return ["Primary Monitor"]

    def set_duration_callback(self, callback):
        self.duration_callback = callback
        
    def _run_timer(self):
        while self.is_recording:
            if self.duration_callback:
                elapsed = int(time.time() - self.start_time)
                mins, secs = divmod(elapsed, 60)
                hours, mins = divmod(mins, 60)
                time_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
                self.duration_callback(time_str)
            time.sleep(1)

    def take_screenshot(self, monitor_index=0, output_path="screenshot.png", region=None):
        camera = dxcam.create(output_idx=monitor_index, output_color="RGB", region=region)
        frame = camera.grab()
        if frame is None:
            time.sleep(0.1)
            frame = camera.grab()
            
        if frame is not None:
            img = Image.fromarray(frame)
            img.save(output_path)
            del camera
            return True
        del camera
        return False

    def start_recording(self, monitor_index=0, fps=120, output_path="output.mp4", quality="High", color_grading="Neutral", region=None):
        if self.is_recording:
            return

        self.target_fps = fps
        self.output_file = output_path
        self.is_recording = True
        self.start_time = time.time()
        
        out_dir = os.path.dirname(os.path.abspath(output_path))
        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        self.dxcam_camera = dxcam.create(output_idx=monitor_index, output_color="BGR", region=region)
        
        frame = self.dxcam_camera.grab()
        if frame is None:
            time.sleep(0.1)
            frame = self.dxcam_camera.grab()
            
        if frame is not None:
            height, width, _ = frame.shape
            self.resolution = (width, height)
        else:
            self.resolution = (1920, 1080)
            
        width, height = self.resolution

        # Quality profiles
        if quality == "Low":
            cq = '30'; bv = '20M'; preset = 'p4'
        elif quality == "Medium":
            cq = '25'; bv = '35M'; preset = 'p5'
        elif quality == "High":
            cq = '20'; bv = '50M'; preset = 'p6'
        else: # Ultra
            cq = '16'; bv = '80M'; preset = 'p7'

        vf_args = []
        if color_grading == "Vibrant":
            vf_args = ['-vf', 'eq=saturation=1.3:contrast=1.05']
        elif color_grading == "Cinematic":
            vf_args = ['-vf', 'eq=contrast=1.15:gamma=0.95:saturation=0.9']
            
        # Create Audio Named Pipe
        self.audio_pipe_handle = win32pipe.CreateNamedPipe(
            self.audio_pipe_name,
            win32pipe.PIPE_ACCESS_OUTBOUND,
            win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT,
            1, 65536, 65536,
            0, None
        )

        ffmpeg_cmd = [
            'ffmpeg',
            '-y',
            # Video Input (stdin)
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{width}x{height}',
            '-pix_fmt', 'bgr24',
            '-r', str(self.target_fps),
            '-i', '-', 
            # Audio Input (Named Pipe)
            '-f', 's16le',
            '-ar', str(self.audio_rate),
            '-ac', str(self.audio_channels),
            '-i', self.audio_pipe_name,
        ]
        
        if vf_args:
            ffmpeg_cmd.extend(vf_args)
            
        ffmpeg_cmd.extend([
            '-c:v', 'hevc_nvenc',
            '-preset', preset,
            '-tune', 'hq',
            '-rc', 'vbr',
            '-cq', cq,
            '-b:v', bv,
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '192k',
            self.output_file
        ])

        try:
            self.video_process = subprocess.Popen(
                ffmpeg_cmd, 
                stdin=subprocess.PIPE, 
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL
            )
        except FileNotFoundError:
            win32file.CloseHandle(self.audio_pipe_handle)
            raise Exception("FFmpeg not found! Please ensure it's installed.")

        # Accept connection to the pipe (blocks until ffmpeg opens it)
        threading.Thread(target=self._connect_audio_pipe, daemon=True).start()

        # Init Audio Capture
        self.audio = pyaudio.PyAudio()
        wasapi_info = self.audio.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_speakers = self.audio.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        
        if not default_speakers["isLoopbackDevice"]:
            for loopback in self.audio.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    default_speakers = loopback
                    break
        
        self.audio_stream = self.audio.open(
            format=self.audio_format,
            channels=self.audio_channels,
            rate=self.audio_rate,
            frames_per_buffer=self.audio_chunk,
            input=True,
            input_device_index=default_speakers["index"],
            stream_callback=self._audio_callback
        )
        self.audio_stream.start_stream()

        # Start Capture Threads
        self.dxcam_camera.start(target_fps=self.target_fps, video_mode=True)
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()
        
        self._timer_thread = threading.Thread(target=self._run_timer, daemon=True)
        self._timer_thread.start()

    def _connect_audio_pipe(self):
        try:
            win32pipe.ConnectNamedPipe(self.audio_pipe_handle, None)
        except Exception:
            pass

    def _audio_callback(self, in_data, frame_count, time_info, status):
        if self.is_recording and self.audio_pipe_handle:
            try:
                win32file.WriteFile(self.audio_pipe_handle, in_data)
            except Exception:
                pass
        return (in_data, pyaudio.paContinue)

    def _capture_loop(self):
        while self.is_recording:
            frame = self.dxcam_camera.get_latest_frame()
            if frame is not None:
                try:
                    self.video_process.stdin.write(frame.tobytes())
                except Exception:
                    break
            else:
                time.sleep(0.001)

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        
        if self.dxcam_camera is not None:
            self.dxcam_camera.stop()
            del self.dxcam_camera
            self.dxcam_camera = None

        if self.capture_thread is not None:
            self.capture_thread.join()

        if self.audio_stream is not None:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
            self.audio_stream = None
            
        if self.audio is not None:
            self.audio.terminate()
            self.audio = None

        if self.video_process is not None:
            self.video_process.stdin.close()
            self.video_process.wait()
            self.video_process = None

        if self.audio_pipe_handle is not None:
            try:
                win32file.CloseHandle(self.audio_pipe_handle)
            except Exception:
                pass
            self.audio_pipe_handle = None
