![Life Makeover Tools](https://raw.githubusercontent.com/chancsy/life_makeover_tools/assets/lifemakeover.png)

# Life Makeover Tools

ADB-based automation tools for the mobile game *Life Makeover*.

## Tools

| Folder | Description | Docs |
|---|---|---|
| [vanna_quiz/](vanna_quiz/) | Vvanna Quiz — answers the 8-question quiz (OCR + wiki answer bank) | [README](vanna_quiz/README.md) · [CHANGELOG](vanna_quiz/CHANGELOG.md) |
| [fun_time_wonder_connect/](fun_time_wonder_connect/) | Wonder Connect — links matching card pairs until the board is clear | [README](fun_time_wonder_connect/README.md) · [RULES](fun_time_wonder_connect/RULES.md) · [CHANGELOG](fun_time_wonder_connect/CHANGELOG.md) |

Each tool's README covers its setup, options and troubleshooting.

### Wonder Connect Demo
https://github.com/user-attachments/assets/2d5cc2c2-5b33-45ac-baad-e8f5210c2db0

## Quick Start

1. Install the [dependencies](#dependencies) and [scrcpy](https://github.com/Genymobile/scrcpy/releases) (on PATH).
2. Connect the device: USB with USB debugging on, or [over Wi-Fi](#wireless-adb).
3. In a tool's folder:
   ```
   python setup.py   # first time per device: shared scrcpy settings + screen regions
   python main.py    # run (scrcpy capture if available, else adb screencap)
   ```

Common options of every `main.py`: `--debug` (no taps; saves an annotated image), `--adb`
(adb screencap instead of scrcpy), `--connect HOST[:PORT]` (Wi-Fi), `--adb-path PATH`.

## Wireless ADB

Any tool works over Wi-Fi. Set it up once with `adb_wireless.py` (project root):

```
python adb_wireless.py pair                 # Android 11+: Developer options > Wireless debugging > "Pair device with pairing code"
python adb_wireless.py usb                  # any Android: device on USB now -> adb tcpip 5555 -> Wi-Fi (until reboot)
python adb_wireless.py connect HOST[:PORT]  # connect to a known address
python adb_wireless.py status               # attached, saved and mDNS-advertised devices
python adb_wireless.py disconnect           # disconnect and forget the saved address
```

The working address is saved in `common/config.json` (`"adb": {"wireless": ...}`). With no device
attached, every tool reconnects to it, or finds a paired Wireless debugging device again over mDNS
(its port changes each time Wireless debugging is turned on). `--connect HOST[:PORT]` picks one
explicitly. Device profiles are keyed by the hardware serial, so regions set up over USB also
apply over Wi-Fi. Over Wi-Fi, a lower scrcpy bitrate (e.g. `8M`, via `setup.py --redo`) may help.

## Shared Infrastructure

```
adb_wireless.py     — Wi-Fi setup (above)
common/
├── config.json     — shared settings: "scrcpy" (exe, video_bitrate), "adb" (wireless address)
└── lm_adb.py       — shared helpers (built on lib-utils AdbUtils + scrcpy_utils):
                        get_adb(adb_path, address)  connect: --adb-path > adb bundled with scrcpy > PATH;
                                                    attached device (USB first), else Wi-Fi reconnect
                        device_id(adb)              profile key: hardware serial (same over USB and Wi-Fi)
                        open_capture(cfg, adb, window_title, force_adb)  frame source: scrcpy when found,
                                                    else None = adb screencap (prints why)
                        get_scrcpy(cfg, serial, adb, window_title)  attach to / launch scrcpy, grab frames
                        scrcpy_found(cfg)           scrcpy path (config exe, else PATH) or None
                        setup_scrcpy()              interactive prompt -> common/config.json
                        read_common_config()        read common/config.json
                        new_adb(), save_wireless_address()
```

The tools capture with scrcpy whenever it's found (the config's `exe`, else PATH) unless `--adb` is
given; the `"scrcpy"` config section only holds settings, and blank `exe` means "find it on PATH".
The tools use the adb bundled with scrcpy, so both share one adb client.

## Adding a New Tool

1. Create `<tool_name>/` with `main.py`, `setup.py`, `README.md`, `CHANGELOG.md`
2. At the top of each script:
   ```python
   import sys, os
   sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
   from common.lm_adb import get_adb, open_capture, setup_scrcpy, read_common_config, device_id
   ```
3. In `setup.py`, call `setup_scrcpy()` once (skip it if `read_common_config()` already has `scrcpy`),
   then `RegionSetupTool` (lib-utils `utils.tools.region_setup`) to mark the regions; save them in
   `<tool>/config.json` under `device_id(adb)`
4. In `main.py`, `get_adb(adb_path=args.adb_path, address=args.connect)` and
   `open_capture(cfg, adb, '<tool_name>', force_adb=args.adb)`; store regions as screen
   fractions and scale taps by `adb.get_screen_size()` (the scrcpy frame is smaller than the device)
5. Add a row to the Tools table above

## Platform Support

**Windows only** (tested on Windows 11). Only the scrcpy *window capture* is Windows-specific;
the rest is cross-platform in principle but untested elsewhere:

| Part | Windows-specific? |
|---|---|
| scrcpy window capture — lib-utils `WindowManager.capture_window` (finds the window with `pygetwindow`, its client area with `win32gui`; `mss` grabs the pixels) | **Yes** — `WindowManager` refuses to start elsewhere |
| adb control, Wi-Fi (`AdbUtils`), `--adb` screenshots | No |
| OCR (Tesseract), card matching (OpenCV, imagehash) | No |
| Region setup window (tkinter) | No |
| `requirements.txt` | Windows-only packages are marked `sys_platform == "win32"`, so it installs elsewhere |

### Adding macOS / Linux support (notes, untested)

- **Today, elsewhere:** run every tool with `--adb`. The tools use scrcpy capture whenever scrcpy is
  found, which fails off Windows. First fix: make `common/lm_adb.py` `open_capture()` return None
  (adb screenshots) when not on Windows — both tools and Wonder Connect's `setup.py` go through it.
- **Window capture per OS** — `capture_window(title)` needs the window's client-area rectangle; `mss`
  already grabs pixels on all three systems:
  - macOS: Quartz `CGWindowListCopyWindowInfo` for the window bounds (needs the Screen Recording permission);
  - Linux X11: `xdotool search --name` / EWMH for the window geometry;
  - Linux Wayland: capturing another app's window isn't generally allowed — use the option below.
- **Linux alternative without window capture:** `scrcpy --v4l2-sink=/dev/videoN --no-video-playback`
  streams the device to a virtual camera (`v4l2loopback`), read with `cv2.VideoCapture` — full device
  resolution, no window needed.
- **scrcpy on macOS / Linux doesn't bundle adb:** the tools then use `adb` on PATH (already handled).
- Region coordinates are screen fractions and taps are scaled by the device size, so no change there.

## Dependencies

### lib-utils

The tools depend on [chancsy/lib-utils](https://github.com/chancsy/lib-utils), a shared utility library
that provides the ADB helpers (incl. Wi-Fi), scrcpy capture, window capture and the region setup GUI.

```
pip install -e ../lib-utils                              # local clone (editable)
pip install git+https://github.com/chancsy/lib-utils.git # or straight from GitHub
```

### Python packages

```
pip install -r requirements.txt
```

Python 3.11+. Each tool's README lists what its packages are used for.

### External programs

- **scrcpy** (recommended, ships its own adb) — [releases](https://github.com/Genymobile/scrcpy/releases)
- **adb** — only needed separately without scrcpy: [platform-tools](https://developer.android.com/tools/releases/platform-tools)
- **Tesseract OCR** — Vvanna Quiz only: [Windows installer](https://github.com/UB-Mannheim/tesseract/wiki)

---

## Credits

**Vvanna Quiz** — question/answer bank sourced from the [Life Makeover Wiki](https://life-makeover.fandom.com/wiki/Shining_Journey/Vvanna_Quiz).
Primary contributor: [Riblam](https://life-makeover.fandom.com/wiki/User:Riblam).
