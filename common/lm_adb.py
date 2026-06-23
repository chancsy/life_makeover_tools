"""
Shared ADB + scrcpy helpers for all Life Makeover tools.

Importing this module automatically adds lib-utils to sys.path, so tools
only need a single import to get ADB, scrcpy capture, and access to lib-utils.

Usage:
    from common.lm_adb import get_adb, get_scrcpy, ScrcpyCapture
    adb     = get_adb()
    capture = get_scrcpy(cfg, adb.device, adb)   # optional fast frame capture
"""

import json as _json
import subprocess
import time
import os as _os

from utils.standalone.adb_utils import AdbUtils

# ---------------------------------------------------------------------------
# Common config  (shared across all tools — scrcpy exe, bitrate, etc.)
# ---------------------------------------------------------------------------

_COMMON_CONFIG_PATH = _os.path.join(_os.path.dirname(__file__), 'config.json')


def read_common_config() -> dict:
    if _os.path.exists(_COMMON_CONFIG_PATH):
        with open(_COMMON_CONFIG_PATH) as f:
            return _json.load(f)
    return {}


def _write_common_config(cfg: dict) -> None:
    with open(_COMMON_CONFIG_PATH, 'w') as f:
        _json.dump(cfg, f, indent=2)


def setup_scrcpy() -> dict:
    """
    Interactive prompt to configure scrcpy exe/bitrate in common/config.json.
    Call from any plugin's setup.py.  Returns the saved scrcpy config dict.
    """
    cfg = read_common_config()
    existing = cfg.get('scrcpy', {})
    cur_exe     = existing.get('exe', 'scrcpy')
    cur_bitrate = existing.get('video_bitrate', '16M')

    print('\n-- scrcpy configuration (shared across all tools) --')
    print('  Press Enter to keep existing value.')
    exe     = input(f'  Path to scrcpy executable [{cur_exe}]: ').strip() or cur_exe
    bitrate = input(f'  Video bitrate [{cur_bitrate}]: ').strip() or cur_bitrate
    cfg['scrcpy'] = {'exe': exe, 'video_bitrate': bitrate}
    _write_common_config(cfg)
    print(f'  Saved to common/config.json: exe="{exe}"  video_bitrate="{bitrate}"')
    return cfg['scrcpy']


def get_adb(adb_path=None):
    """
    Return an AdbUtils instance connected to the first available device.
    Raises RuntimeError if no device is found.
    """
    adb = AdbUtils(adb_path=adb_path)
    devices = adb.get_devices()
    if not devices:
        raise RuntimeError('No ADB devices found. Connect your device and enable USB debugging.')
    adb.set_device(devices[0])
    print(f'ADB connected: {devices[0]}')
    return adb


# ---------------------------------------------------------------------------
# Scrcpy window capture
# ---------------------------------------------------------------------------

class ScrcpyCapture:
    """
    Captures the scrcpy mirror window via mss — fast alternative to adb screencap.
    Drop-in for adb.take_screenshot(): returns a BGR numpy array.

    The frame is returned at the window's native client-area size — no resize.
    Normalized grid coordinates (0.0–1.0 fractions) work correctly at any size
    as long as the scrcpy window has no letterboxing (device fills the client area).
    capture_window() handles DPI awareness and title-bar exclusion automatically.

    Requires: mss  (pip install mss)
    """

    def __init__(self, window_title='scrcpy', device_size=None, process=None):
        self._title = window_title
        self._device_size = device_size  # retained for API compatibility but not used
        self._process = process          # subprocess.Popen if we launched scrcpy, else None
        self._wm = None

    @property
    def launched_by_us(self):
        return self._process is not None

    def _get_wm(self):
        if self._wm is None:
            from utils.standalone.win_automation_utils import WindowManager
            self._wm = WindowManager()
        return self._wm

    def is_running(self):
        return self._get_wm().get_window_pos(self._title) is not None

    def stop(self):
        """Terminate scrcpy if we launched it; no-op if it was already running."""
        if self._process is not None:
            self._process.terminate()
            self._process = None

    def take_screenshot(self):
        img = self._get_wm().capture_window(self._title)
        if img is None:
            print(f'ScrcpyCapture: window "{self._title}" not found.')
            return None
        return img


def get_scrcpy(cfg, serial=None, adb=None, window_title=None, launch_timeout=10.0):
    """
    Return a ScrcpyCapture ready to grab frames from the scrcpy window.

    If the window is not already open, launches scrcpy automatically and waits
    for it to appear.  The window title is forced via --window-title on launch
    so it is always findable regardless of the device model name.

    cfg:            top-level config dict — expects optional 'scrcpy' key: {"exe": "scrcpy"}
    serial:         ADB device serial passed to scrcpy -s (optional)
    adb:            AdbUtils instance — used to read device screen size (optional)
    window_title:   title to set on the scrcpy window; overrides cfg if provided
    launch_timeout: seconds to wait for the window to appear after launch
    """
    # Common config provides defaults; plugin cfg can override per-key
    scrcpy_cfg    = {**read_common_config().get('scrcpy', {}), **cfg.get('scrcpy', {})}
    exe           = scrcpy_cfg.get('exe', 'scrcpy')
    title         = window_title or scrcpy_cfg.get('window_title', 'scrcpy')
    video_bitrate = scrcpy_cfg.get('video_bitrate', '16M')

    device_size = None
    if adb is not None:
        device_size = adb.get_screen_size()

    from utils.standalone.win_automation_utils import WindowManager
    wm = WindowManager()

    proc = None
    if wm.get_window_pos(title) is None:
        print(f'scrcpy window not found — launching "{exe}" (bitrate={video_bitrate})...')
        cmd = [exe,
               '--window-title', title,   # predictable title for window lookup
               '--always-on-top',         # keeps window visible above other apps for mss capture
               '--no-audio',              # no audio needed for screen capture
               '--video-bit-rate', video_bitrate]
        if serial:
            cmd += ['-s', serial]
        proc = subprocess.Popen(cmd)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < launch_timeout:
            time.sleep(0.5)
            if wm.get_window_pos(title) is not None:
                print(f'  scrcpy window appeared ({time.perf_counter()-t0:.1f}s) — waiting for video stream...')
                time.sleep(2.0)  # window title appears before video decoding starts
                print('  scrcpy ready.')
                break
        else:
            print(f'  Warning: scrcpy window did not appear within {launch_timeout}s — capture may fail.')
    else:
        print(f'  scrcpy window "{title}" already open.')

    return ScrcpyCapture(window_title=title, device_size=device_size, process=proc)
