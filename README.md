# MEOWBOARD 🐈
### High-Performance System-Wide Windows Keyboard Meow Sound Engine

> Every time you press a physical key on your keyboard, a cat meows.  
> System-wide. On the desktop, in Chrome, in VS Code, in games, everywhere.  
> Instantaneous. Zero backlog. Ridiculously good engineering.

---

## 🌟 Highlights

- **Universal Windows Key Detection**: Powered by a non-blocking `WH_KEYBOARD_LL` low-level Windows hook with a dedicated Win32 message pump thread. Detects all physical keystrokes and typematic key-repeat events across any application without modifying, swallowing, or injecting input.
- **Zero-Backlog Audio Engine**: Designed from the ground up to prevent sound lag during rapid typing.
  - All samples preloaded into memory — **zero disk I/O and zero audio decoding** during keypresses.
  - Dynamic channel pool with configurable concurrency:
    - **CHILL**: 4 channels (calm, cozy typing)
    - **NORMAL**: 12 channels (everyday typing)
    - **CHAOS**: 24 channels (maximum feline density)
  - **Oldest-Channel Stealing**: When channel capacity is saturated, the oldest playing sound is preempted immediately for the newest keystroke.
  - **Anti-Clipping Headroom**: Real-time gain scaling prevents audio clipping even during typing bursts.
  - **Audio Device Fault Recovery**: Automatically detects and gracefully recovers from audio device disconnections or suspensions.
- **Subtle Acoustic Key Pitch Mapping**:
  - Keys across rows and columns feature subtle musical gradations preserving natural cat character.
  - Function keys / Escape: Crisp, high chirps
  - Number row: Medium to slightly high
  - QWERTY row: Medium
  - ASDF row: Medium to slightly low
  - ZXCV row: Low to medium
  - Spacebar: Warm, extended meow
  - Enter: Distinct cheerful upbeat meow
  - Backspace: Inquisitive upward-inflected meow
  - Controlled ±1.8% pitch micro-jitter ensures repeated presses never sound mechanical.
- **4 Selectable Cat Personalities**:
  - **NORMAL CAT**: Natural, balanced feline vocalizations
  - **KITTEN**: High-pitched, soft and gentle chirps
  - **ANGRY CAT**: Raspy, disgruntled vocal-fry growls
  - **DEEP CAT**: Resonant, chesty low-pitch tones
- **Modern Dark-Mode Dashboard**:
  - Sleek, rounded cat-inspired UI built with PySide6 (Qt).
  - Live interactive keyboard visualizer that glows in real-time on physical keypresses.
  - Real-time typing speed (meows/second), total meow counter, and last key indicator.
  - Master active/muted toggle with instant response.
- **Quiet System Tray Background Operation**:
  - Minimizes cleanly to the notification area.
  - Closing the main window keeps MEOWBOARD running in the tray.
  - Tray context menu with quick volume control, personality switching, intensity modes, and exit.
  - Optional Windows startup registration (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).

---

## 📁 Project Architecture

```
MEOW/
├── main.py                     # Application entry point
├── run_meowboard.bat           # One-click Windows launch script (no terminal window)
├── build_executable.bat        # PyInstaller executable build script
├── meowboard.spec              # PyInstaller build specification
├── requirements.txt            # Python dependencies
├── README.md                   # Complete documentation
│
├── meowboard/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py         # Config dataclass, pitch maps, channel limits
│   ├── core/
│   │   ├── __init__.py
│   │   ├── audio_engine.py      # Low-latency channel pool & oldest-channel stealing
│   │   ├── keyboard_listener.py # Passive Raw Input listener (no hook)
│   │   ├── pitch_mapper.py      # Key-to-pitch & category mapping
│   │   ├── sound_generator.py   # Procedural acoustic formant feline synthesizer
│   │   └── sound_manager.py     # In-memory sample cache & pitch variation preloading
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py       # Primary PySide6 dark-mode dashboard
│   │   ├── tray_manager.py      # Windows notification area system tray integration
│   │   ├── widgets.py           # Real-time keyboard visualizer & status badges
│   │   ├── styles.py            # Modern dark QSS stylesheet
│   │   └── icon_generator.py    # High-DPI icon & tray pixmap generator
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── config_manager.py    # JSON persistence (~/.meowboard/settings.json)
│   │   ├── autostart.py         # Windows Run registry key integration
│   │   └── logger.py            # Structured logging
│   └── assets/
│       ├── icons/               # meowboard.ico, meowboard.png, tray icons
│       └── sounds/              # 20 preloaded WAV vocalizations across 4 profiles
│
├── scripts/
│   └── generate_assets.py      # Offline asset pre-generator
│
└── tests/
    ├── test_pitch_mapper.py           # Pitch mapping & category tests
    ├── test_sound_generator.py        # Audio waveform & asset tests
    ├── test_audio_engine.py           # Channel bounds & stealing tests
    ├── test_config.py                 # Persistence & fallback tests
    ├── test_keyboard_listener.py      # Hook lifecycle tests
    └── test_end_to_end_integration.py # Full E2E suite covering tests 1-12
```

---

## 🚀 Quick Start

### Option 1: One-Click Launch (Recommended)
Double-click `run_meowboard.bat`.  
This script automatically sets up the Python virtual environment, installs dependencies, and launches the application quietly in the background without keeping a console window open.

### Option 2: Manual Setup
```powershell
# 1. Navigate to project root
cd c:\Users\l\OneDrive\Documents\PROJECTS\MEOW

# 2. Create virtual environment
py -3.12 -m venv .venv

# 3. Activate and install requirements
.\.venv\Scripts\pip.exe install -r requirements.txt

# 4. Generate assets (if not already present)
.\.venv\Scripts\python.exe scripts\generate_assets.py

# 5. Launch MEOWBOARD
.\.venv\Scripts\pythonw.exe main.py
```

---

## 🧪 Testing

Run the automated test suite with pytest:

```powershell
.\.venv\Scripts\pytest.exe -v
```

All 23 unit and end-to-end integration tests execute in ~6.5 seconds, verifying:
- Rapid burst key typing without backlog accumulation
- Bounded channel limits (Chill = 4, Normal = 12, Chaos = 24)
- Oldest-channel stealing during saturation
- Master mute and instant resume
- Dynamic switching across all 4 personalities and 3 intensity levels
- Key-repeat events when holding keys down
- Special key mappings (Space, Enter, Backspace, Esc, Modifiers, Function keys)
- Clean release of Windows hooks and audio mixer upon shutdown

---

## 📦 Building Standalone Windows Executable

To build a standalone `.exe` that runs without Python:

```powershell
.\build_executable.bat
```
or:
```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm meowboard.spec
```

The resulting standalone executable will be located at:
`dist\MEOWBOARD\MEOWBOARD.exe`

The executable is windowed (`console=False`), so no terminal window appears when launched.

---

## ⚙️ Configuration & Persistence

Settings are automatically saved to:
`%USERPROFILE%\.meowboard\settings.json`

Remembered preferences include:
- `enabled`: Master toggle state
- `volume`: Master volume (0–100)
- `intensity`: CHILL, NORMAL, or CHAOS
- `personality`: NORMAL CAT, KITTEN, ANGRY CAT, or DEEP CAT
- `start_with_windows`: Automatic startup on Windows boot
- `minimize_to_tray_on_close`: Background tray behavior
