# Fun Time Wonder Connect

Plays **Wonder Connect** (Fun Time) automatically: reads the 8×6 card board, finds pairs of
identical cards that can be linked with at most 2 bends, and taps them until the board is clear,
with human-like pacing (default target ~14 s per board). Handles the game's reshuffles.

Game rules and how the tool handles them in detail: [RULES.md](RULES.md).

## Setup (once per device)

```
python setup.py              # register this device: regions + empty-cell calibration
python setup.py --redo       # redo everything (regions, shared scrcpy settings, calibration)
python setup.py --redo-hist  # redo only the empty-cell calibration
```

1. On first use it asks for the shared scrcpy settings (`common/config.json`): the scrcpy
   executable (Enter or `-` = find it on PATH) and the video bitrate.
2. Open a Wonder Connect board on the device, then press Enter.
3. A window shows a screenshot: click the top-left, then the bottom-right corner of
   - `grid` — the whole card grid, outer edge of the top-left card to outer edge of the bottom-right card;
   - `reshuffle_btn` — the Refresh button.

   Right-click or Backspace undoes the last click. Close the window when both are done.
4. **Empty-cell calibration** (recommended): clear 2–4 pairs by hand in the game, then enter
   their cells as `row,col` (0-based, rows 0–7 top to bottom, columns 0–5 left to right), one per line;
   Enter on an empty line to finish.

### What the empty-cell calibration is for

It saves a colour histogram of an empty cell (`empty_hist` in `config.json`). The tool knows
the cells it cleared itself; this lets it also recognise cells that were **already empty** —
when you start it on a partly played board ("Found N pre-cleared cell(s)"), or cells it didn't
clear. Without it, such cells are read as cards, which corrupts the pairing and can waste taps.

Calibrate with the same capture you play with (scrcpy or adb): scrcpy's video compression shifts
colours slightly. `setup.py` uses scrcpy automatically when it's found (config or PATH), like `main.py`.

Regions and calibration are saved in `config.json` under the device's hardware serial, as
fractions of the screen, so they work at any capture size and over USB or Wi-Fi. A device that
isn't registered falls back to the `default` profile, with a warning.

## Running

```
python main.py                       # menu, then play (scrcpy capture if available)
python main.py --debug               # menu "Start game" reads the live board, saves an image; no tap
python main.py --debug -s shot.png   # same on a saved screenshot (no device, no menu)
python main.py --parse-debug         # raw matching metrics + interactive threshold check
```

### Menu

| Key | Action |
|---|---|
| `n` | Start game — scans for pre-cleared cells, then plays the board |
| `d` | Parse debug — saves `grid_check_<time>.png` (cell grid overlay), prints raw matching per cell, then asks for known pairs to show their scores against the thresholds |
| `t` | Target time — total seconds a full board should take; shows the finish window it gives. Saved in `config.json` (`"pacing": {"target": …}`), default 14 s |
| `s` | Launch scrcpy (shown when it isn't running) |
| `q` | Exit (scrcpy keeps running, so the next start is faster) |
| `x` | Exit and close scrcpy (shown only if this tool launched it) |

### Options

| Option | Meaning |
|---|---|
| `--debug`, `-d` | Stop at the first chosen pair: save an annotated image (cards' type numbers, valid pairs, chosen path) instead of tapping |
| `--screenshot PATH`, `-s PATH` | Debug with a saved screenshot (implies `--debug`, skips the menu). Uses the **first** profile in `config.json`, which may not fit your device |
| `--parse-debug` | Run the parse-debug mode once and exit (see menu `d`) |
| `--adb` | Use `adb screencap` instead of scrcpy capture (much slower; reshuffle polling slows down to match) |
| `--no-pacing` | No pauses between pairs — for measuring raw processing speed |
| `--connect HOST[:PORT]` | Use this device over Wi-Fi (see [Wireless ADB](../README.md#wireless-adb)) |
| `--adb-path PATH` | Use this adb (default: the adb bundled with scrcpy, else `adb` on PATH) |

### Pacing (target time)

Processing takes about 0.26 s per pair (~6.2 s for a full board of 24 pairs). The rest of the
target becomes pauses, shared out fast–slow–fast (first 5 pairs quick, middle slow, last 6 quick),
times one random speed factor per game (0.857–1.071) and ±3% per pair. A target of 14 s finishes
in about 12.9–14.6 s; time lost to a reshuffle is taken off the remaining pauses. Below ~6.2 s
there are no pauses.

### Output files

Written to the folder you run from: `screenshot_debug_connect.png` / `<shot>_debug_connect.png`
(`--debug`), `grid_check_<time>.png` (parse debug), `debug_timeout_<time>.png` + a per-cell dump
in the console when a reshuffle times out.

## Troubleshooting

| Symptom | Check |
|---|---|
| Odd card counts / `singles=` in the grid printout, or taps on wrong cards | Menu `d`: does `grid_check_*.png` line up with the cards? If not, `setup.py --redo`. If it does, enter a known pair to see which threshold blocks it |
| Taps on empty cells, or pre-cleared cells not found | `setup.py --redo-hist` with the capture you play with |
| `Reshuffle timeout -- tapping button` often | Normal late in a game (little changes on screen); check the `reshuffle_btn` region if the tap misses |
| `Device "…" not in config` / `using "default" profile` | Run `setup.py` for this device |
| scrcpy capture fails | Keep the scrcpy window visible (not minimised); it's launched always-on-top |

## Requirements

Install with the project's [requirements.txt](../requirements.txt) and lib-utils (see the [root README](../README.md#dependencies)). Python 3.11+.

| Package | Used for |
|---|---|
| `opencv-python`, `numpy` | Cell crops, colour histograms, empty-cell detection, debug images |
| `imagehash`, `Pillow` | Perceptual hash (pHash) of each card for matching; `Pillow` also shows the region setup screenshot |
| `mss`, `pywin32`, `pygetwindow`, `pyautogui`, `pycaw` | scrcpy window capture (Windows) |

From lib-utils: `AdbUtils` (`utils/standalone/adb_utils.py` — device, screenshots, taps, Wi-Fi),
`scrcpy_utils` (`utils/standalone/scrcpy_utils.py` — find / launch scrcpy, grab frames),
`WindowManager` (`utils/standalone/win_automation_utils.py` — window client-area capture),
`RegionSetupTool` (`utils/tools/region_setup.py` — the region setup window).

**External programs**

- **scrcpy** (recommended, ships its own adb) — [releases](https://github.com/Genymobile/scrcpy/releases); found on PATH.
- **adb** — only needed separately without scrcpy: [platform-tools](https://developer.android.com/tools/releases/platform-tools).
  On the device: Developer options → USB debugging (or Wireless debugging).

See [CHANGELOG.md](CHANGELOG.md) for history.
