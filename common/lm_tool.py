"""
Shared scaffolding for the Life Makeover tools: each tool's config.json and its device profiles.

A tool's config.json holds "devices": {serial: profile}, keyed by the hardware serial
(common.lm_adb.device_id). A profile is {"name", "screen_size", "regions", ...tool keys}, with
regions as screen fractions (x1, y1, x2, y2). A "default" profile is used for unregistered devices.

Usage:
    from common.lm_tool import add_common_args, select_device, profile_regions
    args = add_common_args(argparse.ArgumentParser()).parse_args()
    cfg, adb, profile = select_device(args, CONFIG_PATH)   # --debug -s: adb None, first profile
    regions = profile_regions(profile)
"""

import sys as _sys

from utils import UtilityFunctions

from common.lm_adb import device_id, get_adb

_utils = UtilityFunctions()


def add_common_args(parser):
    """Add the options every tool's main.py takes: --debug/-d, --screenshot/-s, --adb, --connect,
    --adb-path. Returns the parser."""
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Debug: no taps; save an annotated screenshot')
    parser.add_argument('--screenshot', '-s', metavar='PATH',
                        help='Debug on a saved screenshot (implies --debug; no device needed; '
                             'uses the first profile in config.json)')
    parser.add_argument('--adb', action='store_true',
                        help='Take frames with adb screencap instead of scrcpy capture (much slower). '
                             'Default: scrcpy when found (config exe or PATH)')
    parser.add_argument('--connect', metavar='HOST[:PORT]',
                        help='Use this device over Wi-Fi (saved; see ../adb_wireless.py). '
                             'Default: attached device, else the saved Wi-Fi address')
    parser.add_argument('--adb-path', metavar='PATH',
                        help='adb to use (default: the adb bundled with scrcpy, else adb on PATH)')
    return parser


def read_config(path) -> dict:
    """A tool's config.json as a dict ({} when the file doesn't exist yet)."""
    return _utils.read_json_file(path, default={})


def write_config(path, cfg) -> None:
    _utils.write_json_file(path, cfg)


def profile_regions(profile) -> dict:
    """A profile's regions as {name: (x1, y1, x2, y2)} screen fractions."""
    return {k: tuple(v) for k, v in profile['regions'].items()}


def load_profile(cfg, serial):
    """The device profile for `serial`, else the "default" profile with a warning; None if neither.
    Prints which profile is used."""
    devices = cfg.get('devices', {})
    profile = devices.get(serial)
    using_default = False
    if profile is None and serial != 'default':
        profile = devices.get('default')
        using_default = profile is not None
    if profile is None:
        return None
    size = profile.get('screen_size') or ['?', '?']
    name = profile.get('name', serial)
    if using_default:
        print(f'  [WARN] Device "{serial}" not in config — using "default" profile '
              f'({name}, {size[0]}×{size[1]}). Regions may not match your screen exactly.')
        print('         Run setup.py to register your device for accurate results.')
    else:
        print(f'Recognized device "{name}" ({serial}) — {size[0]}×{size[1]}')
    return profile


def first_profile(cfg):
    """(serial, profile) of the first profile in the config, or (None, None)."""
    devices = cfg.get('devices', {})
    if not devices:
        return None, None
    serial = next(iter(devices))
    return serial, devices[serial]


def register_device(config_path, region_names, screen_name, redo=False):
    """setup.py's device registration, shared by the tools.

    Asks for the shared scrcpy settings (first time, or redo), connects, and when this device has
    no profile yet (or redo): asks for a friendly name, waits until `screen_name` is on screen,
    lets the user mark `region_names` (RegionSetupTool) and saves the new profile.

    Returns (cfg, adb, profile, is_new): profile is this device's saved entry in cfg['devices'],
    is_new is True when its regions were just marked. Returns None if region marking was left
    incomplete (nothing saved). Tool-specific keys: add them to profile, then write_config()."""
    from common.lm_adb import read_common_config, setup_scrcpy
    from utils.tools.region_setup import RegionSetupTool   # tkinter GUI: only needed here

    if not read_common_config().get('scrcpy') or redo:
        setup_scrcpy()

    adb = get_adb()
    serial = device_id(adb)  # profile key: hardware serial, same over USB and Wi-Fi
    screen_size = adb.get_screen_size()

    cfg = read_config(config_path)
    devices = cfg.setdefault('devices', {})

    if serial in devices and not redo:
        profile = devices[serial]
        size = profile.get('screen_size') or ['?', '?']
        print(f'Device "{profile.get("name", serial)}" ({serial}) already configured '
              f'(screen {size[0]}×{size[1]}). Run with --redo to reconfigure.')
        return cfg, adb, profile, False

    print(f'\nDevice: {serial}  |  Screen: {screen_size[0]}×{screen_size[1]}')
    name = input('Optional friendly name for this device (Enter to skip): ').strip() or serial

    print(f'\nOpen {screen_name} on the device, then press Enter here.')
    input('Press Enter when ready...')

    regions = RegionSetupTool(region_names, adb=adb).run()
    if len(regions) < len(region_names):
        print(f'Setup incomplete — only {len(regions)}/{len(region_names)} regions defined. Not saved.')
        return None

    profile = devices[serial] = {
        'name': name,
        'screen_size': list(screen_size) if screen_size else [],
        'regions': {k: list(v) for k, v in regions.items()},
    }
    write_config(config_path, cfg)
    print(f'Config saved → {config_path}')
    return cfg, adb, profile, True


def select_device(args, config_path):
    """The device and profile for a tool's main.py: (cfg, adb, profile).

    With --debug -s PATH (args.screenshot): no device (adb is None) and the config's first profile.
    Otherwise: connect (args.adb_path, args.connect) and use this device's profile, or "default".
    Exits with a message when there is no profile to use."""
    cfg = read_config(config_path)
    if getattr(args, 'screenshot', None):
        serial, profile = first_profile(cfg)
        if profile is None:
            print('No device config found. Run setup.py first.')
            _sys.exit(1)
        print(f'Debug mode — regions from device "{serial}"')
        return cfg, None, profile

    adb = get_adb(adb_path=args.adb_path, address=args.connect)
    serial = device_id(adb)
    profile = load_profile(cfg, serial)
    if profile is None:
        print(f'Device "{serial}" not in config. Run setup.py to register this device.')
        _sys.exit(1)
    return cfg, adb, profile
