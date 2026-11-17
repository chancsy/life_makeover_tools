"""
Shared ADB + scrcpy helpers for all Life Makeover tools.

lib-utils must be installed (pip install -e ../lib-utils, see README); this module
doesn't touch sys.path. The scrcpy plumbing lives in lib-utils
utils/standalone/scrcpy_utils.py; this module adds the shared common/config.json.

Usage:
    from common.lm_adb import get_adb, get_scrcpy
    adb     = get_adb()                          # --adb-path > adb bundled with scrcpy > adb on PATH
    capture = get_scrcpy(cfg, adb.device, adb)   # optional fast frame capture
"""

import json as _json
import os as _os

from utils.standalone.adb_utils import AdbUtils
from utils.standalone.scrcpy_utils import ScrcpyCapture, find_scrcpy, launch_scrcpy, resolve_adb  # noqa: F401 (ScrcpyCapture re-exported)

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


def _configured_scrcpy_exe(cfg=None) -> str | None:
    """scrcpy exe from common config, overridden per-key by a plugin cfg; None/'' = find on PATH."""
    scrcpy_cfg = {**read_common_config().get('scrcpy', {}), **(cfg or {}).get('scrcpy', {})}
    return scrcpy_cfg.get('exe') or None


def setup_scrcpy() -> dict:
    """
    Interactive prompt to configure scrcpy exe/bitrate in common/config.json.
    Call from any plugin's setup.py.  Returns the saved scrcpy config dict.
    The exe is optional: leave it blank to find scrcpy on PATH.
    """
    cfg = read_common_config()
    existing = cfg.get('scrcpy', {})
    cur_exe     = existing.get('exe', '')
    cur_bitrate = existing.get('video_bitrate', '16M')
    on_path     = find_scrcpy()

    print('\n-- scrcpy configuration (shared across all tools) --')
    print('  Press Enter to keep the value in [brackets].')
    print(f'  scrcpy on PATH: {on_path or "not found"}')
    exe = input(f'  Path to scrcpy executable, "-" = use PATH [{cur_exe or "PATH"}]: ').strip() or cur_exe
    if exe == '-':
        exe = ''
    bitrate = input(f'  Video bitrate [{cur_bitrate}]: ').strip() or cur_bitrate
    cfg['scrcpy'] = {'video_bitrate': bitrate}
    if exe:
        cfg['scrcpy']['exe'] = exe
    _write_common_config(cfg)
    print(f'  Saved to common/config.json: exe="{exe or "(PATH)"}"  video_bitrate="{bitrate}"')
    return cfg['scrcpy']


def get_adb(adb_path=None):
    """
    Return an AdbUtils instance connected to the first available device.

    adb_path: explicit adb (e.g. --adb-path) always wins; otherwise the adb bundled
              with scrcpy, so the tool and scrcpy share one adb client; else adb on PATH.
    Raises RuntimeError if no device is found.
    """
    adb = AdbUtils(adb_path=resolve_adb(adb_path, _configured_scrcpy_exe()))
    devices = adb.get_devices()
    if not devices:
        raise RuntimeError('No ADB devices found. Connect your device and enable USB debugging.')
    adb.set_device(devices[0])
    print(f'ADB connected: {devices[0]}  (adb: {adb.adb_path})')
    return adb


def device_id(adb) -> str:
    """
    Key for per-device profiles in each tool's config.json: the device's hardware
    serial (ro.serialno), which stays the same over USB and Wi-Fi — the adb serial
    becomes 'host:port' over Wi-Fi. Over USB the two are normally equal, so
    profiles saved under the USB serial still match. Cached on the adb object.
    """
    if getattr(adb, '_lm_device_id', None) is None:
        adb._lm_device_id = adb.get_hardware_serial()
    return adb._lm_device_id


# ---------------------------------------------------------------------------
# Scrcpy window capture
# ---------------------------------------------------------------------------

def get_scrcpy(cfg, serial=None, adb=None, window_title=None, launch_timeout=10.0):
    """
    Return a ScrcpyCapture ready to grab frames from the scrcpy window,
    launching scrcpy if the window isn't open yet.

    cfg:            plugin config dict — optional 'scrcpy' key overrides common/config.json per key
                    ({"exe": ..., "video_bitrate": ..., "window_title": ...})
    serial:         ADB device serial passed to scrcpy -s (optional)
    adb:            AdbUtils instance — scrcpy is launched with the same adb (optional)
    window_title:   title to set on the scrcpy window; overrides cfg if provided
    launch_timeout: seconds to wait for the window to appear after launch
    """
    scrcpy_cfg = {**read_common_config().get('scrcpy', {}), **cfg.get('scrcpy', {})}
    return launch_scrcpy(
        window_title=window_title or scrcpy_cfg.get('window_title', 'scrcpy'),
        exe=scrcpy_cfg.get('exe') or None,
        serial=serial,
        adb_path=adb.adb_path if adb is not None else None,
        video_bitrate=scrcpy_cfg.get('video_bitrate', '16M'),
        launch_timeout=launch_timeout,
    )
