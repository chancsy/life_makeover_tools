# Modules & Dependencies

## Python Version

Python 3.10+ recommended (matches the `lib-utils` package environment).

## pip Packages

Install all at once:

```
pip install opencv-python pytesseract requests beautifulsoup4 numpy Pillow mss
```

| Package | pip name | Import | Purpose |
|---|---|---|---|
| OpenCV | `opencv-python` | `cv2` | Screen image preprocessing (grayscale, threshold) before OCR |
| Tesseract wrapper | `pytesseract` | `pytesseract` | OCR — extracts question and answer text from cropped screen regions |
| Requests | `requests` | `requests` | Fetches the wiki answer page |
| BeautifulSoup | `beautifulsoup4` | `bs4` | Parses the wiki HTML table into a question→answer dict |
| NumPy | `numpy` | `numpy` | Buffer for raw ADB screenshot bytes → image array |
| Pillow | `Pillow` | `PIL` | Displays ADB screenshot in the region setup GUI (tkinter canvas) |
| mss | `mss` | `mss` | Fast scrcpy window capture (used by `ScrcpyCapture` in `common/lm_adb.py`) |

## External Binary

**Tesseract OCR** must be installed separately (not a pip package):

- Download: https://github.com/UB-Mannheim/tesseract/wiki (Windows installer)
- Default install path: `C:\Program Files\Tesseract-OCR\tesseract.exe`
- If installed to a non-default path, add to `main.py`:
  ```python
  pytesseract.pytesseract.tesseract_cmd = r'C:\path\to\tesseract.exe'
  ```

## Shared lib-utils Modules

These are sourced from `scripts_collection/lib-utils` (installed locally as `utils` package).

| Module | Path | Used for |
|---|---|---|
| `AdbUtils` | `utils/standalone/adb_utils.py` | ADB device communication, screenshot, touch events |
| `RegionSetupTool` | `utils/standalone/region_setup.py` | Interactive GUI for defining screen regions; reusable across all games |
| `UtilityFunctions` | `utils/utilities.py` | Module existence checks, demo runner |

## ADB (Android Debug Bridge)

Part of Android SDK Platform-Tools.

- Download: https://developer.android.com/tools/releases/platform-tools
- Add `platform-tools/` to system PATH, or set `ADB_PATH` constant in the script.
- Device setup: Settings → Developer Options → USB Debugging → Enable
