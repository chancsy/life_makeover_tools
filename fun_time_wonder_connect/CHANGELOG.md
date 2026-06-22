# Changelog — Fun Time Wonder Connect

## [0.5.0] — 2026-06-23

### Added
- **Common scrcpy config** — exe/bitrate now stored in `common/config.json` via `setup_scrcpy()` from `common.lm_adb`; no longer duplicated per plugin
- `setup.py` calls `setup_scrcpy()` on first run, skipped if already in common config; `--redo` re-prompts

### Changed
- `main.py` reads scrcpy availability from `read_common_config()` merged with plugin cfg

---

## [0.4.0] — 2026-06-22

### Added
- **`PacingController`** — human-like timing to avoid bot detection
  - Targets 14s completion (±1s/−2s tolerance) via a per-game global speed factor `random.uniform(0.857, 1.071)` drawn once at start — avoids law-of-large-numbers averaging that made per-pair jitter too consistent
  - Small per-pair jitter (`±3%`) on top for natural tap rhythm variation
  - Fast first 5 pairs (weight 0.4×), slow middle, fast last 6 (weight 0.6×), slow middle weight 3.0×
  - `record_reshuffle(seconds_lost)` scales down remaining delays proportionally when reshuffle eats time
  - `processing_per_pair=0.26s` calibrated from `--no-pacing` baseline run (6.2s / 24 pairs)
- **`--no-pacing`** flag — bypasses all inter-pair delays for baseline timing measurement
- **Timing summary** printed at end of each run: START, RESHUFFLE WAIT, RESUME, END timestamps
- **Interactive startup menu** — terminal controls: launch scrcpy, start game, parse debug, exit keeping or stopping scrcpy
- **Reshuffle timeout debug dump** (`_save_screenshot_debug`) — triggered only on reshuffle timeout (not normal runs):
  - Saves `debug_timeout_<ts>.png`
  - Prints per-cell hash and type ID table
  - Prints pairwise `hash_dist` + `color_sim` for every type group with OK/FAIL verdict

### Changed
- Normal-run screenshot saving disabled (`_save_screenshot` no longer called on start or post-reshuffle)
- Speed factor printed at game start: `[pacing] speed factor=X.XXX`

---

## [0.3.0] — 2026-06-22

### Added
- **scrcpy window capture** — `ScrcpyCapture` class replaces slow `adb screencap`
  - `get_scrcpy()` launches scrcpy with `--always-on-top --no-audio --window-title <name>`; waits 2s after window appears for video stream to start
  - `ScrcpyCapture.is_running()`, `.stop()`, `.launched_by_us` for lifecycle management
  - `--adb` flag forces adb screencap fallback
- **Coordinate mapping** — `_to_device(cx, cy)` converts scrcpy window pixels to device pixels for ADB tap; capture size tracked per screenshot via `_capture_size`
- **Client-area capture** — `capture_window()` uses `GetClientRect + ClientToScreen` (no DPI mode change) to exclude title bar; avoids black-frame bug from `SetProcessDpiAwareness` mid-run

### Changed
- `COLOR_SIM_THRESHOLD` lowered to `0.74` (from 0.95) to accommodate H.264 histogram compression artifacts
- `ORPHAN_COLOR_MIN` lowered to `0.70`
- `ScrcpyCapture` no longer resizes to device resolution — normalized coords work at any capture size
- `_tap_reshuffle_btn` no longer takes `ref_img` argument

---

## [0.2.0] — 2026-06-21

### Added
- **Reshuffle detection** — polls board pixel-diff after no valid pairs found; auto-taps reshuffle button on timeout (`RESHUFFLE_TIMEOUT=4.0s`)
- **Empty-cell histogram** — learned from user-specified cleared cells during `setup.py`; `scan_empty_cells()` detects pre-cleared cells at game start so partially completed games resume correctly
- Multi-device config (`config.json` keyed by device serial)

---

## [0.1.0] — 2026-06-21

### Added
- `setup.py` — guided region setup; defines grid bounding box and reshuffle button; saved per device serial in `config.json`
- `main.py` — full game automation:
  - `GridParser`: divides grid into cells, crops each card, computes perceptual hash to identify matching pairs; detects empty cells by background similarity
  - `LinkChecker`: path-finding algorithm — checks connectivity between two cells with ≤2 bends through empty cells; virtual 1-cell border allows paths outside the grid
  - `GameAssistant`: game loop — screenshot → parse grid → find valid pairs → tap in sequence → wait for animation → repeat; pauses on reshuffle detection
  - CLI args: `--debug` / `-s PATH` for annotated PNG output without tapping; `--adb-path` to override ADB location
