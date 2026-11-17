# Vvanna Quiz

Answers the 8-question **Vvanna Quiz** (Shining Journey) automatically. Each question:
OCR reads the question and the four answers, the question is looked up in an answer bank
from the [Life Makeover Wiki](https://life-makeover.fandom.com/wiki/Shining_Journey/Vvanna_Quiz),
and the matching answer is tapped. It then waits for the next question to appear.

> The quiz can only be played once per round. Use `--debug` (below) to check a setup
> without answering.

## Setup (once per device)

```
python setup.py          # register this device and mark the screen regions
python setup.py --redo   # redo it (also re-asks the shared scrcpy settings)
```

1. On first use it asks for the shared scrcpy settings (`common/config.json`): the
   scrcpy executable (Enter or `-` = find it on PATH) and the video bitrate.
2. Open a quiz question on the device, then press Enter.
3. A window shows a screenshot: click the top-left, then the bottom-right corner of
   each region in turn — `question`, `A`, `B`, `C`, `D`. Right-click or Backspace undoes the last click.
   Close the window when all five are done.

Regions are saved in `config.json` under the device's hardware serial, as fractions of
the screen, so they work at any capture size and over USB or Wi-Fi. A device that isn't
registered falls back to the `default` profile, with a warning.

## Running

```
python main.py                     # answer a quiz (scrcpy capture if available)
python main.py --debug             # read one question live and save an annotated image; no tap
python main.py --debug -s shot.png # same, on a saved screenshot (no device needed)
python main.py --fetch-answers     # refresh the answer bank from the wiki, then exit
```

| Option | Meaning |
|---|---|
| `--debug`, `-d` | Stop after one question and save `screenshot_debug_q1.png` (regions, chosen answer, tap point) instead of tapping |
| `--screenshot PATH`, `-s PATH` | Debug with a saved screenshot (implies `--debug`). Uses the **first** profile in `config.json`, which may not fit your device |
| `--adb` | Use `adb screencap` instead of scrcpy capture (much slower over Wi-Fi: ~2.8 s vs ~0.1 s per frame, same OCR result) |
| `--connect HOST[:PORT]` | Use this device over Wi-Fi (see [Wireless ADB](../README.md#wireless-adb)) |
| `--adb-path PATH` | Use this adb (default: the adb bundled with scrcpy, else `adb` on PATH) |
| `--fetch-answers` | Download the latest answer bank and exit |

### How it answers

- **Answer bank** — cached in `config.json` under `"answers"`. The first time a question
  isn't found, the wiki is fetched (MediaWiki API) and the cache updated.
- **Matching** — the OCR'd question is fuzzy-matched to the bank, then the bank's answer is
  fuzzy-matched to the four OCR'd choices (`FUZZY_CUTOFF = 0.4`).
- **OCR** — each region is grayscale + Otsu threshold, read as a text block with line breaks
  joined, so two-line answers are read whole.
- **Tap** — inside the chosen answer's region, scaled to the device's own resolution
  (the scrcpy frame is smaller than the device screen).
- **Next question** — after a tap it polls until the question text changes
  (`TRANSITION_MIN_WAIT` 0.5 s, `TRANSITION_POLL` 0.3 s, `TRANSITION_TIMEOUT` 10 s).
- **Not found** — if no answer matches, it asks you to answer on the device and press Enter.

## Troubleshooting

| Symptom | Check |
|---|---|
| OCR text is garbage | Is a quiz question on screen? Run `--debug` and look at the region boxes in the saved image; re-run `setup.py --redo` if they're off |
| `Device "…" not in config` / `using "default" profile` | Run `setup.py` for this device |
| `No answer found` for a readable question | New question not on the wiki yet — `--fetch-answers`, or answer by hand |
| Wrong answer box chosen | Run `--debug`: compare the OCR'd choices with the screen |
| `TesseractNotFoundError` | Install Tesseract (below) or set its path |

## Requirements

Install with the project's [requirements.txt](../requirements.txt) and lib-utils (see the [root README](../README.md#dependencies)). Python 3.11+.

| Package | Used for |
|---|---|
| `opencv-python`, `numpy` | Cropping and thresholding regions before OCR |
| `pytesseract` | OCR of the question and answers |
| `requests`, `beautifulsoup4` | Fetching and parsing the wiki answer table |
| `Pillow` | Screenshot display in the region setup window |
| `mss`, `pywin32`, `pygetwindow`, `pyautogui`, `pycaw` | scrcpy window capture (Windows) |

From lib-utils: `AdbUtils` (`utils/standalone/adb_utils.py` — device, screenshots, taps, Wi-Fi),
`scrcpy_utils` (`utils/standalone/scrcpy_utils.py` — find / launch scrcpy, grab frames),
`RegionSetupTool` (`utils/tools/region_setup.py` — the region setup window).

**External programs**

- **Tesseract OCR** — [Windows installer](https://github.com/UB-Mannheim/tesseract/wiki).
  Put it on PATH, or add `pytesseract.pytesseract.tesseract_cmd = r'C:\path\to\tesseract.exe'` to `main.py`.
- **scrcpy** (recommended, ships its own adb) — [releases](https://github.com/Genymobile/scrcpy/releases); found on PATH.
- **adb** — only needed separately without scrcpy: [platform-tools](https://developer.android.com/tools/releases/platform-tools).
  On the device: Developer options → USB debugging (or Wireless debugging).

See [CHANGELOG.md](CHANGELOG.md) for history.
