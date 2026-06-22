"""
Region Setup — Life Makeover Vvanna Quiz
Run this once per device. Regions are saved to config.json keyed by device serial,
so subsequent runs on the same device skip setup automatically.

Usage:
    python setup.py
    python setup.py --redo    ← force redo even if device is already configured
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.lm_adb import get_adb, setup_scrcpy, read_common_config

import json

from utils.standalone.region_setup import RegionSetupTool

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

QUIZ_REGIONS = ['question', 'A', 'B', 'C', 'D']


def load_config(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'devices': {}}


def save_config(path, cfg):
    with open(path, 'w') as f:
        json.dump(cfg, f, indent=2)
    print(f'Config saved → {path}')


def main():
    force_redo = '--redo' in sys.argv

    common = read_common_config()
    if not common.get('scrcpy') or force_redo:
        setup_scrcpy()

    adb = get_adb()
    serial = adb.device
    screen_size = adb.get_screen_size()

    cfg = load_config(CONFIG_PATH)
    devices = cfg.setdefault('devices', {})

    if serial in devices and not force_redo:
        entry = devices[serial]
        name = entry.get('name', serial)
        size = entry.get('screen_size', ['?', '?'])
        print(f'Device "{name}" ({serial}) already configured (screen {size[0]}×{size[1]}).')
        print('Run with --redo to reconfigure.')
        return

    # Prompt for an optional friendly name
    print(f'\nDevice: {serial}  |  Screen: {screen_size[0]}×{screen_size[1]}')
    name = input('Optional friendly name for this device (Enter to skip): ').strip()
    if not name:
        name = serial

    print('\nNavigate to the quiz screen on your phone, then press Enter here.')
    input('Press Enter when ready...')

    tool = RegionSetupTool(QUIZ_REGIONS, adb=adb)
    regions = tool.run()  # no config_path — we handle saving below

    if len(regions) < len(QUIZ_REGIONS):
        print(f'Setup incomplete — only {len(regions)}/{len(QUIZ_REGIONS)} regions defined. Not saved.')
        return

    devices[serial] = {
        'name': name,
        'screen_size': list(screen_size) if screen_size else [],
        'regions': {k: list(v) for k, v in regions.items()},
    }
    save_config(CONFIG_PATH, cfg)
    print('Setup complete. Run main.py to start the quiz.')


if __name__ == '__main__':
    main()
