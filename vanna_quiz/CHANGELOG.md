# Changelog

## [0.6.3] — 2026-11-18

### Fixed
- **A question could be read off the previous question's screen** — after the tap, any change in the OCR'd question text counted as "new", but OCR of one question varies by a letter between frames ("ihere" / "there"), so Q4 was read and answered from Q3's still-visible screen. Now:
  - wait 1.0 s after the tap (was 0.5 s): the question changes some time after the answer is chosen;
  - a read below 0.8 similarity to the previous question is new;
  - a read at 0.8 or above may be the old question or a similar new one (some bank questions score up to 0.94 against each other), so wait another 1.0 s and take the next frame as the new question;
  - when no answer is found, one fresh frame is read before falling back to manual (a frame caught mid-animation).

---

## [0.6.2] — 2026-11-17

### Fixed
- **Two-line answers were garbled by OCR** and could pick the wrong box: answer regions were read in Tesseract single-line mode (`--psm 7`), but answers wrap onto two lines. On a real Q1 frame, "Redeem with Basic Color Chart" read as "ee chor", so had it been the correct answer, the fuzzy match would have chosen D ("Redeem with Basic …") instead of C. All regions now use block mode (`--psm 6`) with line breaks joined into single spaces. Measured on the same frame at scrcpy (810×1296) and adb (1800×2880) resolution: answer-text similarity 0.71 / 0.74 → 1.00, right box for every possible answer 3/4 → 4/4; OCR total 1.32 s → 1.18 s live.

### Changed
- `QuizScreenReader._ocr()` — `single_line` parameter removed; the question text is also line-joined, so wrapped questions compare cleanly with the one-line answer bank

---

## [0.6.1] — 2026-11-17

### Fixed
- **Taps missed the answer under scrcpy capture** — the tap box was computed in screenshot pixels, but the scrcpy mirror window is usually smaller than the device resolution, so taps landed up and to the left of the chosen answer. Taps now scale the stored region fractions by the device screen size (`QuizAssistant._tap_region`), correct for both scrcpy and adb screencap.

### Removed
- `QuizScreenReader.get_region_px` — no longer used

---

## [0.6.0] — 2026-06-23

### Added
- **scrcpy window capture** — faster alternative to `adb screencap`
  - `--adb` flag forces adb screencap fallback
  - scrcpy exe/bitrate configured once via `setup.py` → stored in `common/config.json`
  - `SCRCPY_WINDOW_TITLE = 'vanna_quiz'` used as fixed window title on launch
- **`--fetch-answers`** CLI flag — fetches latest answers from wiki and updates `config.json` cache, then exits (no device needed)
- **Transition detection** replaces fixed `DELAY_BETWEEN_QUESTIONS` sleep
  - After each tap, polls screenshots until the question OCR text changes
  - Constants: `TRANSITION_MIN_WAIT=0.5s`, `TRANSITION_POLL=0.3s`, `TRANSITION_TIMEOUT=10.0s`
  - Next-question screenshot is reused as the first read of the following loop iteration — no redundant capture
  - Falls back on timeout with a warning; manual-answer path forces a fresh capture

### Changed
- `setup.py` — calls `setup_scrcpy()` from `common.lm_adb` on first run (skipped if already configured in `common/config.json`); `--redo` re-prompts
- `QuizAssistant` — accepts `capture=` param; `_take_screenshot()` routes to scrcpy or adb transparently

---

## [0.4.0] — 2026-06-21

### Added
- `main.py` accepts CLI arguments via `argparse` — no more editing constants to switch modes:
  - `--debug` / `-d` — enable debug mode (live ADB screenshot, no taps)
  - `--screenshot PATH` / `-s PATH` — debug with a screenshot file (implies `--debug`, no device needed)
  - `--adb-path PATH` — override adb executable location
- `AdbUtils.tap_in_region` now accepts `margin=0.25` (default 25%) — tap is restricted to the inner zone of the region; callers pass the full bbox

### Changed
- Debug mode always stops after 1 question
- When no answer is found: script pauses and prompts user to answer manually on the phone, then waits for Enter to continue (Ctrl+C to exit)
- Debug image crosshair now shows a randomised point within the `margin=0.25` inner zone, matching the real tap behaviour
- Quiz script passes full region bbox to `tap_in_region`; margin logic lives entirely in `AdbUtils`

---

## [0.3.0] — 2026-06-20

### Added
- **Debug mode** in `main.py`
  - Set `DEBUG_MODE = True` and `DEBUG_SCREENSHOT = 'path/to/ref.png'`
  - Runs full OCR + answer lookup pipeline with no ADB tap sent to device
  - Saves annotated PNG (`*_debug_q1.png`) showing: all region boxes outlined, chosen region highlighted in red, circle + crosshair at tap center, info overlay (matched question, correct answer, chosen label)
- **Multi-device config** — `config.json` now keyed by ADB device serial
  - `setup.py`: detects if current device is already registered and skips setup; `--redo` flag to force redo; prompts for optional friendly device name
  - `main.py`: reads regions by device serial on startup; prints recognized device name
- **Local answer cache** in `config.json` under `"answers"` key
  - `QuizAnswerLoader` loads from local cache first; only fetches the wiki page on first cache miss
  - New answers merged into cache and saved immediately after each web fetch
  - Subsequent runs with known questions need no network request

### Changed
- `vanna_quiz/setup.py` — device-keyed save; checks for existing registration; `--redo` flag
- `main.py` — `_find_correct_choice` now returns `(label, matched_q, answer)` tuple instead of just label; answer lookup delegated to `QuizAnswerLoader.lookup()`

---

## [0.2.0] — 2026-06-20

### Added
- `setup.py` — guided region setup launcher for Life Makeover quiz
  - Connects to device via ADB, waits for user to navigate to quiz screen
  - Launches `RegionSetupTool` GUI and saves result to `config.json`
- `RegionSetupTool` added to shared `lib-utils` (`utils/standalone/region_setup.py`)
  - Generic, reusable across any future game — accepts a list of region names
  - Displays ADB screenshot (or a file) in a scaled tkinter canvas
  - Two-click per region: top-left then bottom-right; draws labeled rectangles in distinct colors
  - Right-click or Backspace to redo the last region
  - Saves normalized (0.0–1.0) coords + original screen size to JSON

### Changed
- `main.py` — removed hardcoded `REGIONS` dict; now loads from `config.json` at startup
  - Exits with a clear message if `config.json` is missing (prompts to run `setup.py`)

---

## [0.1.0] — 2026-06-20

### Added
- `main.py` — initial implementation of Vvanna Quiz automation
  - `QuizAnswerLoader`: fetches question→answer table from Life Makeover fandom wiki using `requests` + `beautifulsoup4`; results cached in memory for the session
  - `QuizScreenReader`: captures on-screen question and four answer choices (A/B/C/D) via OpenCV preprocessing + Tesseract OCR; regions configured as normalized screen fractions
  - `QuizAssistant`: main loop — screenshot → OCR → fuzzy match question to wiki answers → fuzzy match answer text to on-screen choice → ADB tap
  - Humanized touch: `tap_in_region` picks a uniformly random pixel within the choice bounding box
  - `difflib.get_close_matches` fuzzy matching tolerates OCR noise (cutoff configurable via `FUZZY_CUTOFF`)
- `AdbUtils` class added to shared `lib-utils` (`utils/standalone/adb_utils.py`)
  - `take_screenshot()` via `adb exec-out screencap -p` → numpy array
  - `tap(x, y, jitter_px)` with random pixel jitter + screen-edge clamping
  - `tap_in_region(x1, y1, x2, y2)` uniform random tap within bbox
  - `swipe()`, `get_devices()`, `get_screen_size()`
  - Follows lib-utils standalone class pattern with `lib_demo_params` + interactive demo
