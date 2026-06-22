# Modules & Dependencies — Fun Time Wonder Connect

## pip Packages

```
pip install opencv-python numpy imagehash Pillow mss pywin32 pygetwindow
```

| Package | pip name | Import | Purpose |
|---|---|---|---|
| OpenCV | `opencv-python` | `cv2` | Screen capture processing, card crop, empty cell detection |
| NumPy | `numpy` | `numpy` | Image array operations |
| ImageHash | `imagehash` | `imagehash` | Perceptual hashing for card pattern matching |
| Pillow | `Pillow` | `PIL` | Required by imagehash; also used by RegionSetupTool |
| mss | `mss` | `mss` | Fast scrcpy window capture via `WindowManager.capture_window()` |
| pywin32 | `pywin32` | `win32gui` | `GetClientRect` + `ClientToScreen` for title-bar-excluded capture |
| pygetwindow | `pygetwindow` | `pygetwindow` | Window lookup by title for scrcpy capture |

## Shared lib-utils Modules

| Module | Path | Used for |
|---|---|---|
| `AdbUtils` | `utils/standalone/adb_utils.py` | Screenshot, touch events |
| `WindowManager` | `utils/standalone/win_automation_utils.py` | scrcpy window capture (client area, DPI-safe) |
| `RegionSetupTool` | `utils/standalone/region_setup.py` | Grid + reshuffle button region setup |

## ADB

See `common/lm_adb.py` — handles device connection shared across all tools.
