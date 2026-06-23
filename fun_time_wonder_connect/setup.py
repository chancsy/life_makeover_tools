"""
Region Setup — Fun Time Wonder Connect
Run once per device. Saves grid region and reshuffle button to config.json.

Usage:
    python setup.py
    python setup.py --redo          # redo everything (regions, scrcpy config, histogram)
    python setup.py --redo-hist     # recalibrate empty-cell histogram only
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.lm_adb import get_adb, get_scrcpy, setup_scrcpy, read_common_config

SCRCPY_WINDOW_TITLE = 'fun_time_wonder_connect'  # must match main.py

import json
import numpy as np
import cv2

# Shared histogram helpers (mirrors GridParser._empty_hist_compute in main.py)
def _color_hist(crop_bgr):
    """Full crop — used for empty-cell histogram (uniform cells, full area is most distinctive)."""
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    hists = []
    for ch, bins in enumerate([180, 256, 256]):
        h = cv2.calcHist([hsv], [ch], None, [bins], [0, bins])
        cv2.normalize(h, h)
        hists.append(h)
    return hists

from utils.tools.region_setup import RegionSetupTool

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

GRID_ROWS = 8
GRID_COLS = 6

# Single region covering the entire card grid (top-left → bottom-right)
# Plus the reshuffle button as a tappable region
REGIONS = ['grid', 'reshuffle_btn']


def load_config(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'devices': {}}


def save_config(path, cfg):
    with open(path, 'w') as f:
        json.dump(cfg, f, indent=2)
    print(f'Config saved → {path}')


def _crop_cell(img, grid_region, row, col):
    h, w = img.shape[:2]
    x1p, y1p, x2p, y2p = grid_region
    gx1, gy1 = int(x1p * w), int(y1p * h)
    gx2, gy2 = int(x2p * w), int(y2p * h)
    cell_w = (gx2 - gx1) / GRID_COLS
    cell_h = (gy2 - gy1) / GRID_ROWS
    pad_x = max(2, int(cell_w * 0.08))
    pad_y = max(2, int(cell_h * 0.08))
    cx1 = int(gx1 + col * cell_w) + pad_x
    cy1 = int(gy1 + row * cell_h) + pad_y
    cx2 = int(cx1 + cell_w) - 2 * pad_x
    cy2 = int(cy1 + cell_h) - 2 * pad_y
    return img[cy1:cy2, cx1:cx2]


def _sample_empty_hist(capture, grid_region):
    """
    Learn the empty-cell color histogram from cleared cells.
    capture: any object with take_screenshot() — AdbUtils or ScrcpyCapture.
             Must match the runtime capture source so histogram values are consistent.
    Returns serializable [[float,...], [float,...], [float,...]] or None if skipped.
    """
    print('\nEmpty-cell calibration (recommended — prevents ghost taps after reshuffle).')
    print(f'  Grid layout: {GRID_ROWS} rows x {GRID_COLS} cols, 0-indexed.')
    print('  Manually link 2-4 pairs in the game to create empty cells.')
    print('  Then enter their coordinates below, one per line.')
    print('  Press Enter on an empty line when done (or right away to skip).')

    coords = []
    while True:
        cell_input = input(f'  Empty cell {len(coords)+1} (row,col): ').strip()
        if not cell_input:
            break
        try:
            row, col = [int(x.strip()) for x in cell_input.split(',')]
        except ValueError:
            print('  Invalid — use format row,col (e.g. 0,2)')
            continue
        if not (0 <= row < GRID_ROWS and 0 <= col < GRID_COLS):
            print(f'  ({row},{col}) is outside the grid — skipping.')
            continue
        coords.append((row, col))

    if not coords:
        print('  Skipped — empty-cell detection disabled (re-run setup.py --redo-hist to calibrate).')
        return None

    print(f'  Taking screenshot to sample {len(coords)} cell(s)...')
    screenshot = capture.take_screenshot()
    if screenshot is None:
        print('  Screenshot failed — skipping.')
        return None

    all_hists = []
    for row, col in coords:
        crop = _crop_cell(screenshot, grid_region, row, col)
        if crop.size == 0:
            print(f'  ({row},{col}) crop empty — skipping this cell.')
            continue
        all_hists.append(_color_hist(crop))
        print(f'  Sampled ({row},{col})')

    if not all_hists:
        print('  No valid cells — skipping.')
        return None

    n = len(all_hists)
    avg = [
        (sum(h[ch] for h in all_hists) / n).flatten().tolist()
        for ch in range(3)
    ]
    print(f'  Empty-cell histogram learned from {n} cell(s).')
    return avg


def _make_capture(cfg, adb):
    """
    Return the appropriate capture object for histogram calibration.
    Uses ScrcpyCapture if scrcpy is configured (matches runtime source),
    otherwise falls back to adb so histogram pixels are consistent.
    """
    if read_common_config().get('scrcpy'):
        print('  Using scrcpy for calibration (matches runtime capture source).')
        return get_scrcpy(cfg, serial=adb.device, adb=adb,
                          window_title=SCRCPY_WINDOW_TITLE)
    return adb


def main():
    force_redo      = '--redo' in sys.argv
    force_redo_hist = '--redo-hist' in sys.argv

    adb = get_adb()
    serial = adb.device
    screen_size = adb.get_screen_size()

    common = read_common_config()
    if not common.get('scrcpy') or force_redo:
        setup_scrcpy()

    cfg = load_config(CONFIG_PATH)
    devices = cfg.setdefault('devices', {})

    if serial in devices and not force_redo:
        entry = devices[serial]
        name = entry.get('name', serial)
        print(f'Device "{name}" ({serial}) already configured. Run with --redo to reconfigure.')

        if force_redo_hist or 'empty_hist' not in entry:
            if force_redo_hist:
                print('Recalibrating empty-cell histogram (--redo-hist)...')
            capture = _make_capture(cfg, adb)
            hist = _sample_empty_hist(capture, tuple(entry['regions']['grid']))
            if hist:
                entry['empty_hist'] = hist
                save_config(CONFIG_PATH, cfg)
        return

    print(f'\nDevice: {serial}  |  Screen: {screen_size[0]}×{screen_size[1]}')
    name = input('Optional friendly name for this device (Enter to skip): ').strip() or serial

    print('\nNavigate to the Wonder Connect game screen, then press Enter.')
    input('Press Enter when ready...')

    tool = RegionSetupTool(REGIONS, adb=adb)
    regions = tool.run()

    if len(regions) < len(REGIONS):
        print(f'Setup incomplete — only {len(regions)}/{len(REGIONS)} regions defined. Not saved.')
        return

    entry = {
        'name': name,
        'screen_size': list(screen_size) if screen_size else [],
        'regions': {k: list(v) for k, v in regions.items()},
    }

    capture = _make_capture(cfg, adb)
    hist = _sample_empty_hist(capture, tuple(regions['grid']))
    if hist:
        entry['empty_hist'] = hist

    devices[serial] = entry
    save_config(CONFIG_PATH, cfg)
    print('Setup complete. Run main.py to start the assistant.')


if __name__ == '__main__':
    main()
