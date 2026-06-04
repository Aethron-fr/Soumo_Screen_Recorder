# 🎬 Soumo Screen Recorder PRO

A professional-grade, 4K/120FPS screen recorder built in Python for Windows.
Features a premium floating toolbar, GPU hardware encoding, and zero-delay output.

---

## ✨ Features

| Feature | Details |
|---|---|
| **Screen Capture** | `dxcam` — Windows Desktop Duplication API (fastest possible) |
| **GPU Encoding** | `hevc_nvenc` → `h264_nvenc` → `libx264` fallback chain |
| **Zero-delay Stop** | Video encodes in real-time; stop = file instantly ready |
| **System Audio** | WASAPI loopback via `pyaudiowpatch` |
| **Region Selection** | Click-drag overlay with marching-ant border |
| **Screenshots** | Lossless PNG, auto-copied to clipboard |
| **Global Hotkeys** | `Ctrl+Shift+R` record · `Ctrl+Shift+S` screenshot |
| **Invisible Toolbar** | `WDA_EXCLUDEFROMCAPTURE` — toolbar never appears in recordings |
| **Quality Profiles** | Low / Medium / High / Ultra |
| **Color Grading** | Neutral / Vibrant / Cinematic |
| **FPS Options** | 30 / 60 / 120 / 144 |
| **Output Formats** | MP4 / MKV / WebM |
| **Toast Notifications** | Bottom-right slide-up confirmations |
| **Settings Persistence** | `settings.json` — all prefs + toolbar position remembered |

---

## 🚀 Quick Start

### 1. Prerequisites
- **Python 3.10+** — [python.org](https://python.org)
- **FFmpeg** — install via winget:
  ```powershell
  winget install ffmpeg
  ```
- **NVIDIA GPU** recommended (falls back to CPU encoding automatically)

### 2. Install dependencies
```powershell
cd soumo_sr
pip install -r requirements.txt
```

### 3. Run
```powershell
python main.py
```
Or double-click `run.bat`.

---

## 📁 Project Structure

```
soumo_sr/
├── main.py                    # Entry point + logging + asset generation
├── run.bat                    # Double-click launcher
├── requirements.txt           # Python dependencies
├── assets/
│   └── icon.ico               # Auto-generated app icon
├── core/
│   ├── recorder.py            # High-level orchestrator (dxcam + FFmpeg + audio)
│   ├── audio.py               # WASAPI audio capture
│   └── encoder.py             # FFmpeg subprocess manager
├── ui/
│   ├── toolbar.py             # Main floating toolbar
│   ├── settings_panel.py      # Settings popup with sections
│   ├── region_selector.py     # Click-drag region overlay
│   └── toast.py               # Stacking toast notifications
└── utils/
    ├── animations.py          # 60fps animation engine (Animator, PulseLoop)
    ├── settings.py            # settings.json persistence
    └── hotkeys.py             # Global hotkey manager
```

---

## ⌨️ Hotkeys

| Action | Shortcut |
|---|---|
| Start / Stop Recording | `Ctrl + Shift + R` |
| Take Screenshot | `Ctrl + Shift + S` |
| Cancel Region | `Escape` |

---

## 🎨 UI Controls

| Button | Action |
|---|---|
| `📷` | Screenshot |
| `⏺` | Start / Stop Recording |
| `⛶` | Select capture region (right-click to clear) |
| `📁` | Open Recordings folder |
| `⚙` | Settings |
| `✕` | Quit |

All recordings saved to: `Desktop\Soumo Recordings\`

---

## 🔧 Requirements

```
customtkinter==5.2.2
dxcam==0.0.5
numpy
pyaudiowpatch
ffmpeg-python
pillow
keyboard
pywin32
pyperclip
```

---

## 📝 License

MIT License — free to use, modify, and distribute.
