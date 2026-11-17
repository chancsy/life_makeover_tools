"""
Shared ADB + scrcpy helpers for all Life Makeover tools.

lib-utils must be installed (pip install -e ../lib-utils, see README); this module
doesn't touch sys.path. The scrcpy plumbing lives in lib-utils
utils/standalone/scrcpy_utils.py; this module adds the shared common/config.json.

Usage:
    from common.lm_adb import get_adb, get_scrcpy
    adb     = get_adb()                          # --adb-path > adb bundled with scrcpy > adb on PATH
    adb     = get_adb(address='192.168.1.5:5555')  # Wi-Fi (see adb_wireless.py)
    capture = open_capture(cfg, adb, 'my_tool')  # scrcpy if found, else None = adb screencap
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


def scrcpy_found(cfg=None) -> str | None:
    """Path of the scrcpy the tools would use (configured exe, else PATH), or None.

    The tools capture with scrcpy whenever this finds it (unless --adb); the "scrcpy"
    config section is optional settings, not an on/off switch."""
    return find_scrcpy(_configured_scrcpy_exe(cfg))


def open_capture(cfg, adb, window_title, force_adb=False):
    """The tools' frame source: a ScrcpyCapture when scrcpy is found (attaching to or launching
    the window), else None = take frames with adb screencap. Prints why adb is used.

    force_adb: the --adb option."""
    if not force_adb and scrcpy_found(cfg):
        return get_scrcpy(cfg, serial=adb.device, adb=adb, window_title=window_title)
    print('Screenshot: adb screencap' + (' (--adb flag)' if force_adb else ' (scrcpy not found)'))
    return None


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


def new_adb(adb_path=None) -> AdbUtils:
    """AdbUtils with no device selected: adb_path if given > adb bundled with scrcpy > adb on PATH."""
    return AdbUtils(adb_path=resolve_adb(adb_path, _configured_scrcpy_exe()))


def save_wireless_address(address: str | None) -> None:
    """Remember the Wi-Fi 'host:port' in common/config.json so get_adb() reconnects to it (None = forget)."""
    cfg = read_common_config()
    adb_cfg = cfg.setdefault('adb', {})
    if address:
        adb_cfg['wireless'] = address
    else:
        adb_cfg.pop('wireless', None)
    _write_common_config(cfg)


def get_adb(adb_path=None, address=None):
    """
    Return an AdbUtils instance connected to a device.

    adb_path: explicit adb (e.g. --adb-path) always wins; otherwise the adb bundled
              with scrcpy, so the tool and scrcpy share one adb client; else adb on PATH.
    address:  Wi-Fi 'host[:port]' (e.g. --connect) to connect to and use; saved for next time.
    Without address: the first attached device (USB or already-connected Wi-Fi); if none,
    reconnects over Wi-Fi (saved address, then mDNS). See adb_wireless.py to set Wi-Fi up.
    Raises RuntimeError if no device is found.
    """
    adb = new_adb(adb_path)
    if address:
        serial = adb.connect(address)
        if not serial:
            raise RuntimeError(f'Could not connect to {address} over Wi-Fi. '
                               'Run adb_wireless.py (pair / usb) to set it up.')
        save_wireless_address(serial)
    else:
        # lib-utils AdbUtils: USB first, one tablet listed twice counts once
        serial = adb.pick_device()
        if not serial:
            saved = read_common_config().get('adb', {}).get('wireless')
            serial = adb.reconnect_wireless(saved)       # saved address, then mDNS
            if serial and serial != saved:
                save_wireless_address(serial)            # new port found over mDNS
        if not serial:
            raise RuntimeError('No ADB devices found. Connect the device by USB with USB debugging on, '
                               'or set up Wi-Fi with adb_wireless.py.')
    adb.set_device(serial)
    print(f'ADB connected: {serial}{"  (Wi-Fi)" if adb.is_wireless(serial) else ""}  (adb: {adb.adb_path})')
    return adb


def device_id(adb) -> str:
    """
    Key for per-device profiles in each tool's config.json: the device's hardware
    serial (ro.serialno), which stays the same over USB and Wi-Fi — the adb serial
    becomes 'host:port' over Wi-Fi. Over USB the two are normally equal, so
    profiles saved under the USB serial still match. (AdbUtils caches it.)
    """
    return adb.get_hardware_serial()


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
