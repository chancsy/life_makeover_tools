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

from common.lm_adb import open_capture
from common.lm_tool import register_device, write_config

# Same grid geometry, cell crop and empty-cell histogram as the runtime (main.py)
from main import GridParser, GRID_ROWS, GRID_COLS, SCRCPY_WINDOW_TITLE

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

# Single region covering the entire card grid (top-left → bottom-right)
# Plus the reshuffle button as a tappable region
REGIONS = ['grid', 'reshuffle_btn']


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

    grid = GridParser(grid_region, GRID_ROWS, GRID_COLS)
    all_hists = []
    for row, col in coords:
        crop, _ = grid._cell_crop(screenshot, row, col)
        if crop.size == 0:
            print(f'  ({row},{col}) crop empty — skipping this cell.')
            continue
        all_hists.append(grid._empty_hist_compute(crop))
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
    Uses ScrcpyCapture if scrcpy is found (matches runtime source),
    otherwise falls back to adb so histogram pixels are consistent.
    """
    capture = open_capture(cfg, adb, SCRCPY_WINDOW_TITLE)
    if capture is not None:
        print('  Using scrcpy for calibration (matches runtime capture source).')
        return capture
    return adb


def main():
    force_redo      = '--redo' in sys.argv
    force_redo_hist = '--redo-hist' in sys.argv

    result = register_device(CONFIG_PATH, REGIONS, 'a Wonder Connect board', redo=force_redo)
    if result is None:
        return
    cfg, adb, profile, is_new = result

    if is_new or force_redo_hist or 'empty_hist' not in profile:
        if force_redo_hist:
            print('Recalibrating empty-cell histogram (--redo-hist)...')
        capture = _make_capture(cfg, adb)
        hist = _sample_empty_hist(capture, tuple(profile['regions']['grid']))
        if hist:
            profile['empty_hist'] = hist
            write_config(CONFIG_PATH, cfg)
            print(f'Config saved → {CONFIG_PATH}')

    if is_new:
        print('Setup complete. Run main.py to start the assistant.')


if __name__ == '__main__':
    main()
