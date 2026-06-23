# Fun Time Wonder Connect — Link Card Game Assistant
#
# Dependencies:
#   pip install opencv-python numpy imagehash Pillow mss
#
# First-time setup:
#   python setup.py
#
# Usage:
#   python main.py                       # scrcpy capture if configured, else adb screencap
#   python main.py --adb                 # force adb screencap (low-speed fallback)
#   python main.py --debug -s screenshot.png
#
# Note: scrcpy uses H.264/H.265 video compression. If matching accuracy degrades
# vs adb screencap, tune HASH_THRESHOLD up and COLOR_SIM_THRESHOLD down slightly.

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.lm_adb import get_adb, get_scrcpy, read_common_config

import argparse
import json
import random
import time

import cv2
import numpy as np
import imagehash
from PIL import Image

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

ADB_PATH = None

SCRCPY_WINDOW_TITLE = 'fun_time_wonder_connect'  # fixed title passed to scrcpy --window-title on launch

GRID_ROWS = 8
GRID_COLS = 6

TAP_DELAY                = 0.03  # seconds between tapping card 1 and card 2
LOOP_DELAY               = 0.03   # seconds after a successful link (game input processing time)
RESHUFFLE_POLL           = 0.5   # scrcpy: seconds between reshuffle polls
RESHUFFLE_TIMEOUT        = 4.0   # scrcpy: tap reshuffle button after this many seconds
RESHUFFLE_POLL_ADB       = 3.0   # adb screencap: slower poll (screencap takes ~150ms)
RESHUFFLE_TIMEOUT_ADB    = 8.0   # adb screencap: longer timeout to compensate
HASH_THRESHOLD           = 12    # max perceptual hash distance to consider cards identical
COLOR_SIM_THRESHOLD      = 0.74  # min HSV histogram correlation (0-1) to confirm same card type
                                  # scrcpy H.264 compression shifts HSV histograms; true pairs
                                  # observed in 0.83–0.97 range — keep margin below lowest seen
ORPHAN_COLOR_MIN         = 0.70  # min color_sim to accept an orphan merge; skip if below
EMPTY_CELL_SIM_THRESHOLD = 0.97  # min color_sim to classify a cell as empty (vs a card)
RESHUFFLE_DIFF_THRESHOLD = 8.0   # min grid mean-pixel-diff to declare board changed

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _read_config(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def load_device_config(config_path, serial):
    devices = _read_config(config_path).get('devices', {})
    entry = devices.get(serial)
    using_default = False
    if entry is None and serial != 'default':
        entry = devices.get('default')
        using_default = entry is not None
    if entry is None:
        return None, None, None
    regions = {k: tuple(v) for k, v in entry['regions'].items()}
    name = entry.get('name', serial)
    size = entry.get('screen_size', ['?', '?'])
    if using_default:
        print(f'  [WARN] Device "{serial}" not in config — using "default" profile '
              f'({name}, {size[0]}×{size[1]}). Regions may not match your screen exactly.')
        print('         Run setup.py to register your device for accurate results.')
    else:
        print(f'Recognized device "{name}" ({serial}) -- {size[0]}x{size[1]}')
    empty_hist = entry.get('empty_hist')
    if empty_hist is not None:
        empty_hist = [np.array(ch, dtype=np.float32).reshape(-1, 1) for ch in empty_hist]
        print('  Loaded empty-cell histogram from config.')
    return regions, entry.get('screen_size'), empty_hist

# ---------------------------------------------------------------------------
# Grid Parser
# ---------------------------------------------------------------------------

class GridParser:
    """
    Divides the card grid into cells and computes perceptual hashes to group
    matching cards into type IDs.

    Empty cells are tracked explicitly via mark_cleared() — no colour-based
    detection.  Only cells the tool has cleared are ever treated as empty,
    so parse() is never confused by card colours that look like empty tiles.
    """

    def __init__(self, grid_region, rows, cols):
        self.grid_region = grid_region
        self.rows = rows
        self.cols = cols
        self._cleared = set()   # (r, c) cells we have successfully linked & removed
        self._empty_hist = None  # color histogram of an empty cell (learned at runtime)

    def mark_cleared(self, r1, c1, r2, c2):
        """Mark two cells as permanently empty (we just linked them)."""
        self._cleared.add((r1, c1))
        self._cleared.add((r2, c2))

    def scan_empty_cells(self, screenshot):
        """
        Scan the board once and add empty-looking cells to _cleared.
        Used when resuming a partially completed game so the tool is immediately
        aware of cells the user already linked before starting the tool.
        Requires _empty_hist to be calibrated; returns number of cells added.
        """
        if self._empty_hist is None:
            return 0
        added = 0
        for r in range(self.rows):
            for c in range(self.cols):
                if (r, c) in self._cleared:
                    continue
                crop, _ = self._cell_crop(screenshot, r, c)
                if crop.size == 0:
                    continue
                sim = self._hist_sim(self._empty_hist_compute(crop), self._empty_hist)
                if sim >= EMPTY_CELL_SIM_THRESHOLD:
                    self._cleared.add((r, c))
                    added += 1
        return added

    def _grid_px(self, img):
        h, w = img.shape[:2]
        x1p, y1p, x2p, y2p = self.grid_region
        return int(x1p * w), int(y1p * h), int(x2p * w), int(y2p * h)

    def _cell_crop(self, img, row, col):
        gx1, gy1, gx2, gy2 = self._grid_px(img)
        cell_w = (gx2 - gx1) / self.cols
        cell_h = (gy2 - gy1) / self.rows
        x1 = int(gx1 + col * cell_w)
        y1 = int(gy1 + row * cell_h)
        x2 = int(x1 + cell_w)
        y2 = int(y1 + cell_h)
        pad_x, pad_y = max(2, int(cell_w * 0.08)), max(2, int(cell_h * 0.08))
        return img[y1 + pad_y:y2 - pad_y, x1 + pad_x:x2 - pad_x], (x1, y1, x2, y2)

    def _cell_center_px(self, img, row, col):
        gx1, gy1, gx2, gy2 = self._grid_px(img)
        cell_w = (gx2 - gx1) / self.cols
        cell_h = (gy2 - gy1) / self.rows
        cx = int(gx1 + (col + 0.5) * cell_w)
        cy = int(gy1 + (row + 0.5) * cell_h)
        return cx, cy

    def _phash(self, crop_bgr):
        pil = Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB))
        return imagehash.phash(pil)

    def _center_crop(self, crop_bgr, keep=0.5):
        """Return the central keep×keep fraction of a crop (focuses on symbol, not border)."""
        h, w = crop_bgr.shape[:2]
        margin_y = int(h * (1 - keep) / 2)
        margin_x = int(w * (1 - keep) / 2)
        return crop_bgr[margin_y:h - margin_y, margin_x:w - margin_x]

    def _color_hist(self, crop_bgr):
        """Card-type matching: center crop to focus on symbol color, not border."""
        inner = self._center_crop(crop_bgr)
        hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
        hists = []
        for ch, bins in enumerate([180, 256, 256]):
            h = cv2.calcHist([hsv], [ch], None, [bins], [0, bins])
            cv2.normalize(h, h)
            hists.append(h)
        return hists

    def _empty_hist_compute(self, crop_bgr):
        """Empty-cell detection: full crop — empty cells are uniform, full crop is most distinctive."""
        hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
        hists = []
        for ch, bins in enumerate([180, 256, 256]):
            h = cv2.calcHist([hsv], [ch], None, [bins], [0, bins])
            cv2.normalize(h, h)
            hists.append(h)
        return hists

    def _hist_sim(self, h1, h2):
        return sum(cv2.compareHist(a, b, cv2.HISTCMP_CORREL) for a, b in zip(h1, h2)) / 3

    def _board_diff(self, img1, img2):
        """Mean pixel diff of the grid area — used for reshuffle change detection."""
        gx1, gy1, gx2, gy2 = self._grid_px(img1)
        p1 = cv2.resize(img1[gy1:gy2, gx1:gx2], (64, 64)).astype(float)
        p2 = cv2.resize(img2[gy1:gy2, gx1:gx2], (64, 64)).astype(float)
        return float(np.abs(p1 - p2).mean())

    def _parse_cells(self, screenshot):
        """
        Core cell scan: hash every non-cleared, non-empty cell.
        Returns (grid, centers, hashes, colors, cell_hashes, cell_colors) without
        any merge or correction passes.  cell_hashes/cell_colors are keyed by (r,c).
        """
        centers = [[None] * self.cols for _ in range(self.rows)]
        for r in range(self.rows):
            for c in range(self.cols):
                centers[r][c] = self._cell_center_px(screenshot, r, c)

        hashes      = {}   # tid -> phash
        colors      = {}   # tid -> color_hist
        cell_hashes = {}   # (r,c) -> phash
        cell_colors = {}   # (r,c) -> color_hist
        grid        = [[0] * self.cols for _ in range(self.rows)]
        next_id     = 1
        phash_count = 0
        t_phash     = 0.0

        for r in range(self.rows):
            for c in range(self.cols):
                if (r, c) in self._cleared:
                    continue
                crop, _ = self._cell_crop(screenshot, r, c)
                if self._empty_hist is not None:
                    if self._hist_sim(self._empty_hist_compute(crop), self._empty_hist) >= EMPTY_CELL_SIM_THRESHOLD:
                        continue  # visually empty — skip before any further processing
                t0 = time.perf_counter()
                h = self._phash(crop)
                t_phash += time.perf_counter() - t0
                phash_count += 1
                chist = self._color_hist(crop)
                cell_hashes[(r, c)] = h
                cell_colors[(r, c)] = chist
                matched_id = None
                for tid, th in hashes.items():
                    if (h - th) <= HASH_THRESHOLD and self._hist_sim(chist, colors[tid]) >= COLOR_SIM_THRESHOLD:
                        matched_id = tid
                        break
                if matched_id is None:
                    matched_id = next_id
                    hashes[matched_id] = h
                    colors[matched_id] = chist
                    next_id += 1
                grid[r][c] = matched_id

        if phash_count:
            avg_ms = t_phash / phash_count * 1000
            print(f'  [time] phash x{phash_count}: {t_phash*1000:5.0f} ms  ({avg_ms:.1f} ms/cell)')

        return grid, centers, hashes, colors, cell_hashes, cell_colors

    def parse(self, screenshot):
        """
        Returns:
            grid:    2D list[rows][cols] — 0 = empty/cleared, 1+ = card type ID
            centers: 2D list[rows][cols] of (cx, cy) pixel coords
            hashes:  dict {type_id: phash}

        Cleared cells (from mark_cleared) are always 0.
        All other cells are hashed; identical cards share a type ID.
        """
        grid, centers, hashes, colors, cell_hashes, cell_colors = self._parse_cells(screenshot)

        # Second pass: merge orphan singletons by best color similarity.
        # Game guarantees groups of 2 or 4, so any singleton must match another singleton.
        from collections import Counter
        counts = Counter(grid[r][c] for r in range(self.rows) for c in range(self.cols) if grid[r][c] != 0)
        singleton_ids = {tid for tid, n in counts.items() if n == 1}
        if singleton_ids:
            singleton_cells = [(r, c) for r in range(self.rows) for c in range(self.cols)
                               if grid[r][c] in singleton_ids]
            merged = set()
            for i, (r1, c1) in enumerate(singleton_cells):
                if (r1, c1) in merged:
                    continue
                best_sim, best_rc = -1, None
                for r2, c2 in singleton_cells[i+1:]:
                    if (r2, c2) in merged:
                        continue
                    sim = self._hist_sim(cell_colors[(r1, c1)], cell_colors[(r2, c2)])
                    if sim > best_sim:
                        best_sim, best_rc = sim, (r2, c2)
                if best_rc and best_sim >= ORPHAN_COLOR_MIN:
                    r2, c2 = best_rc
                    new_id = grid[r1][c1]
                    grid[r2][c2] = new_id
                    hashes[new_id] = hashes[grid[r1][c1]]
                    colors[new_id] = cell_colors[(r1, c1)]
                    print(f'  [orphan] ({r1},{c1}) <-> ({r2},{c2}) merged (color_sim={best_sim:.3f})')
                    merged.add((r1, c1))
                    merged.add(best_rc)
                elif best_rc:
                    print(f'  [orphan] ({r1},{c1}) skipped — best color_sim={best_sim:.3f} below {ORPHAN_COLOR_MIN}')
            print(f'  [orphan] total merged: {len(merged) // 2} pair(s)')

        # Third pass: singleton + triplet correction.
        # If a type has count=1 and another has count=3, one triplet cell was
        # misclassified — reassign the best-matching triplet cell to the singleton's type.
        counts = Counter(grid[r][c] for r in range(self.rows) for c in range(self.cols) if grid[r][c] != 0)
        singleton_ids = {tid for tid, n in counts.items() if n == 1}
        triplet_ids   = {tid for tid, n in counts.items() if n == 3}
        if singleton_ids and triplet_ids:
            for s_id in singleton_ids:
                s_cells = [(r, c) for r in range(self.rows) for c in range(self.cols) if grid[r][c] == s_id]
                sr, sc = s_cells[0]
                best_sim, best_rc, best_old_id = -1, None, None
                for t_id in triplet_ids:
                    for tr, tc in [(r, c) for r in range(self.rows) for c in range(self.cols) if grid[r][c] == t_id]:
                        sim = self._hist_sim(cell_colors[(sr, sc)], cell_colors[(tr, tc)])
                        if sim > best_sim:
                            best_sim, best_rc, best_old_id = sim, (tr, tc), t_id
                if best_rc and best_sim >= ORPHAN_COLOR_MIN:
                    tr, tc = best_rc
                    grid[tr][tc] = s_id
                    print(f'  [triplet-fix] ({sr},{sc}) type {s_id} <-> ({tr},{tc}) type {best_old_id} reassigned (color_sim={best_sim:.3f})')
                elif best_rc:
                    print(f'  [triplet-fix] ({sr},{sc}) singleton — best color_sim={best_sim:.3f} below {ORPHAN_COLOR_MIN}, skipped')

        return grid, centers, hashes

    def parse_verbose(self, screenshot):
        """
        Parse without any merge/correction passes.
        For each cell that couldn't match an existing type, logs what it was
        compared against (phash distance + color_sim) so thresholds can be tuned.

        Returns (grid, centers, cell_hashes, cell_colors) — raw per-cell data
        so callers can query any pair of cells directly.
        """
        from collections import Counter

        grid, centers, hashes, colors, cell_hashes, cell_colors = self._parse_cells(screenshot)

        # Report every new-type cell with its closest candidate and why it didn't match
        print('\n  [verbose] Per-cell match details (cells that became new types):')
        for r in range(self.rows):
            for c in range(self.cols):
                if grid[r][c] == 0 or (r, c) not in cell_hashes:
                    continue
                h = cell_hashes[(r, c)]
                tid = grid[r][c]
                # A cell is a "new type" if no earlier type has the same ID
                # (i.e., it was the first cell to get this ID).
                # We detect this by checking if any other cell shares the same tid.
                same_type_cells = [(rr, cc) for rr in range(self.rows)
                                   for cc in range(self.cols)
                                   if grid[rr][cc] == tid and (rr, cc) != (r, c)]
                if same_type_cells:
                    continue   # matched something — not interesting
                # Singleton: show closest candidate from all other cells
                candidates = []
                for r2 in range(self.rows):
                    for c2 in range(self.cols):
                        if (r2, c2) == (r, c) or (r2, c2) not in cell_hashes:
                            continue
                        dist = h - cell_hashes[(r2, c2)]
                        sim  = self._hist_sim(cell_colors[(r, c)], cell_colors[(r2, c2)])
                        candidates.append((dist, sim, r2, c2, grid[r2][c2]))
                candidates.sort()
                print(f'    ({r},{c}) type={tid}  — no match found, top candidates:')
                for dist, sim, r2, c2, t2 in candidates[:5]:
                    flag = ''
                    if dist <= HASH_THRESHOLD and sim < COLOR_SIM_THRESHOLD:
                        flag = '  <-- hash OK, color blocked'
                    elif dist > HASH_THRESHOLD and sim >= COLOR_SIM_THRESHOLD:
                        flag = '  <-- color OK, hash blocked'
                    elif dist <= HASH_THRESHOLD and sim >= COLOR_SIM_THRESHOLD:
                        flag = '  <-- WOULD MATCH (should not appear here)'
                    print(f'      vs ({r2},{c2}) type={t2}:  phash_dist={dist}  color_sim={sim:.3f}{flag}')

        counts = Counter(grid[r][c] for r in range(self.rows) for c in range(self.cols) if grid[r][c] != 0)
        singles = sum(1 for n in counts.values() if n == 1)
        pairs   = sum(1 for n in counts.values() if n == 2)
        quads   = sum(1 for n in counts.values() if n == 4)
        sixes   = sum(1 for n in counts.values() if n == 6)
        odd     = [(tid, n) for tid, n in counts.items() if n % 2 != 0]
        print(f'\n  [verbose] counts: singles={singles}  pairs={pairs}  quads={quads}  sixes={sixes}')
        if odd:
            print(f'  [verbose] odd-count types (impossible in game): {odd}')

        return grid, centers, cell_hashes, cell_colors

# ---------------------------------------------------------------------------
# Link Checker
# ---------------------------------------------------------------------------

class LinkChecker:
    """
    Checks whether two cards can be linked with <= 2 bends through empty cells.
    The virtual grid is extended by 1 cell on all sides so paths can go outside.
    """

    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols

    def _is_passable(self, grid, r, c, endpoint_a, endpoint_b):
        if (r, c) == endpoint_a or (r, c) == endpoint_b:
            return True
        if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
            return True
        return grid[r][c] == 0

    def _line_clear(self, grid, r1, c1, r2, c2, ep_a, ep_b):
        if r1 != r2 and c1 != c2:
            return False
        if r1 == r2:
            for c in range(min(c1, c2), max(c1, c2) + 1):
                if not self._is_passable(grid, r1, c, ep_a, ep_b):
                    return False
        else:
            for r in range(min(r1, r2), max(r1, r2) + 1):
                if not self._is_passable(grid, r, c1, ep_a, ep_b):
                    return False
        return True

    def can_connect(self, grid, r1, c1, r2, c2):
        """Return True if (r1,c1) and (r2,c2) can be linked with <= 2 bends."""
        ep_a, ep_b = (r1, c1), (r2, c2)

        if self._line_clear(grid, r1, c1, r2, c2, ep_a, ep_b):
            return True

        for cr, cc in [(r1, c2), (r2, c1)]:
            if self._is_passable(grid, cr, cc, ep_a, ep_b):
                if (self._line_clear(grid, r1, c1, cr, cc, ep_a, ep_b) and
                        self._line_clear(grid, cr, cc, r2, c2, ep_a, ep_b)):
                    return True

        # Form 1: vert -> horiz -> vert
        for rmid in range(-1, self.rows + 1):
            via1, via2 = (rmid, c1), (rmid, c2)
            if (self._line_clear(grid, r1, c1, *via1, ep_a, ep_b) and
                    self._line_clear(grid, *via1, *via2, ep_a, ep_b) and
                    self._line_clear(grid, *via2, r2, c2, ep_a, ep_b)):
                return True

        # Form 2: horiz -> vert -> horiz
        for cmid in range(-1, self.cols + 1):
            via1, via2 = (r1, cmid), (r2, cmid)
            if (self._line_clear(grid, r1, c1, *via1, ep_a, ep_b) and
                    self._line_clear(grid, *via1, *via2, ep_a, ep_b) and
                    self._line_clear(grid, *via2, r2, c2, ep_a, ep_b)):
                return True

        return False

    def find_path(self, grid, r1, c1, r2, c2):
        """Return list of (r,c) waypoints for the path, or [] if none."""
        ep_a, ep_b = (r1, c1), (r2, c2)
        if self._line_clear(grid, r1, c1, r2, c2, ep_a, ep_b):
            return [(r1, c1), (r2, c2)]
        for cr, cc in [(r1, c2), (r2, c1)]:
            if self._is_passable(grid, cr, cc, ep_a, ep_b):
                if (self._line_clear(grid, r1, c1, cr, cc, ep_a, ep_b) and
                        self._line_clear(grid, cr, cc, r2, c2, ep_a, ep_b)):
                    return [(r1, c1), (cr, cc), (r2, c2)]
        for rmid in range(-1, self.rows + 1):
            via1, via2 = (rmid, c1), (rmid, c2)
            if (self._line_clear(grid, r1, c1, *via1, ep_a, ep_b) and
                    self._line_clear(grid, *via1, *via2, ep_a, ep_b) and
                    self._line_clear(grid, *via2, r2, c2, ep_a, ep_b)):
                return [(r1, c1), via1, via2, (r2, c2)]
        for cmid in range(-1, self.cols + 1):
            via1, via2 = (r1, cmid), (r2, cmid)
            if (self._line_clear(grid, r1, c1, *via1, ep_a, ep_b) and
                    self._line_clear(grid, *via1, *via2, ep_a, ep_b) and
                    self._line_clear(grid, *via2, r2, c2, ep_a, ep_b)):
                return [(r1, c1), via1, via2, (r2, c2)]
        return []

    def find_all_pairs(self, grid):
        """Return list of ((r1,c1),(r2,c2)) for all valid linkable pairs."""
        pairs = []
        cells = [(r, c) for r in range(self.rows) for c in range(self.cols)
                 if grid[r][c] != 0]
        for i, (r1, c1) in enumerate(cells):
            for r2, c2 in cells[i + 1:]:
                if grid[r1][c1] == grid[r2][c2]:
                    if self.can_connect(grid, r1, c1, r2, c2):
                        pairs.append(((r1, c1), (r2, c2)))
        return pairs

# ---------------------------------------------------------------------------
# Pacing Controller
# ---------------------------------------------------------------------------

class PacingController:
    """
    Human-like inter-pair timing to avoid bot detection.

    Strategy:
      - Pairs 1-5   : fast (getting started)
      - Pairs 6-N-6 : slow (working through the board)
      - Last 6 pairs: fast (finishing up)

    Target total game time: 10-18s. Delays are pre-distributed across pairs
    by weight, with ±25% random jitter per pair. When a reshuffle consumes
    wall time, remaining delays are scaled down proportionally.
    """

    FAST_START = 5
    FAST_END   = 6

    def __init__(self, total_pairs, target=14.0, processing_per_pair=0.26):
        self._total = max(1, total_pairs)
        self._pair  = 0
        budget = max(0.0, target - self._total * processing_per_pair)

        weights = []
        for i in range(self._total):
            n = i + 1
            if n <= self.FAST_START:
                w = 0.4
            elif n > self._total - self.FAST_END:
                w = 0.6
            else:
                w = 3.0
            weights.append(w)

        total_w = sum(weights) or 1.0
        self._delays = [budget * w / total_w for w in weights]
        # Global speed factor chosen once per game — drives total-time variance.
        # Per-pair jitter alone averages out over 24 pairs; this does not.
        self._speed = random.uniform(0.857, 1.071)  # maps total to ~12s–15s

    def record_reshuffle(self, seconds_lost):
        """Scale down remaining delays to compensate for time lost to reshuffle."""
        remaining_total = sum(self._delays[self._pair:])
        if remaining_total <= 0:
            return
        reduction = min(seconds_lost, remaining_total)
        factor = max(0.0, 1.0 - reduction / remaining_total)
        for i in range(self._pair, len(self._delays)):
            self._delays[i] *= factor
        print(f'  [pacing] reshuffle -{seconds_lost:.1f}s → remaining delays ×{factor:.0%}')

    def next_delay(self):
        if self._pair >= len(self._delays):
            return 0.02
        base  = self._delays[self._pair]
        self._pair += 1
        d = base * self._speed * random.uniform(0.97, 1.03)
        return max(0.01, d)

    @property
    def pair_num(self):
        return self._pair


# ---------------------------------------------------------------------------
# Game Assistant
# ---------------------------------------------------------------------------

class GameAssistant:
    def __init__(self, adb, parser, checker, reshuffle_btn=None, capture=None, device_size=None):
        self.adb = adb
        self.parser = parser
        self.checker = checker
        self.reshuffle_btn = reshuffle_btn  # normalized (x1p,y1p,x2p,y2p) or None
        self._capture = capture or adb     # ScrcpyCapture or fallback to adb
        self._device_size = device_size    # (w, h) in device pixels — for tap coordinate mapping
        self._capture_size = None          # (w, h) of last screenshot — set by _take_screenshot
        # Use slower poll/timeout when falling back to adb screencap (capture param is None)
        self._reshuffle_poll    = RESHUFFLE_POLL    if capture else RESHUFFLE_POLL_ADB
        self._reshuffle_timeout = RESHUFFLE_TIMEOUT if capture else RESHUFFLE_TIMEOUT_ADB

    def _to_device(self, cx, cy):
        """Convert screenshot pixel coords to device pixel coords for ADB tap."""
        if self._device_size is None or self._capture_size is None:
            return cx, cy  # fallback: adb screencap is already in device pixels
        sw, sh = self._capture_size
        dw, dh = self._device_size
        return int(cx / sw * dw), int(cy / sh * dh)

    def _tap_reshuffle_btn(self):
        if self.reshuffle_btn is None:
            print('  [reshuffle] no button region configured, skipping tap.')
            return
        if self._device_size:
            dw, dh = self._device_size
        elif self._capture_size:
            dw, dh = self._capture_size
        else:
            print('  [reshuffle] no size info for tap, skipping.')
            return
        x1p, y1p, x2p, y2p = self.reshuffle_btn
        self.adb.tap_in_region(int(x1p*dw), int(y1p*dh), int(x2p*dw), int(y2p*dh))
        print('  [reshuffle] tapped reshuffle button.')

    def _tap_cell(self, centers, r, c):
        cx, cy = centers[r][c]
        cx, cy = self._to_device(cx, cy)
        self.adb.tap_in_region(cx - 10, cy - 10, cx + 10, cy + 10)

    def _cell_px(self, screenshot, r, c):
        """Pixel centre of a cell, extrapolating for virtual border positions."""
        gx1, gy1, gx2, gy2 = self.parser._grid_px(screenshot)
        cell_w = (gx2 - gx1) / self.parser.cols
        cell_h = (gy2 - gy1) / self.parser.rows
        return (int(gx1 + (c + 0.5) * cell_w),
                int(gy1 + (r + 0.5) * cell_h))

    def _save_debug_image(self, screenshot, grid, centers, pairs, chosen, screenshot_path):
        img = screenshot.copy()

        for r in range(self.parser.rows):
            for c in range(self.parser.cols):
                _, bbox = self.parser._cell_crop(screenshot, r, c)
                x1, y1, x2, y2 = bbox
                tid = grid[r][c]
                color = (60, 60, 60) if tid == 0 else (160, 160, 160)
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 1)
                if tid != 0:
                    cx2_, cy2_ = (x1 + x2) // 2, (y1 + y2) // 2
                    cv2.putText(img, str(tid), (cx2_ - 6, cy2_ + 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1)

        for (r1, c1), (r2, c2) in pairs:
            for r, c in [(r1, c1), (r2, c2)]:
                cx, cy = centers[r][c]
                cv2.circle(img, (cx, cy), 14, (60, 180, 60), 1)

        if chosen:
            (r1, c1), (r2, c2) = chosen
            path = self.checker.find_path(grid, r1, c1, r2, c2)
            if path:
                pts = [self._cell_px(screenshot, pr, pc) for pr, pc in path]
                for i in range(len(pts) - 1):
                    cv2.line(img, pts[i], pts[i + 1], (50, 200, 50), 2)
                for pt in pts[1:-1]:
                    cv2.circle(img, pt, 5, (50, 200, 50), -1)
            for r, c in [(r1, c1), (r2, c2)]:
                cx, cy = centers[r][c]
                cv2.circle(img, (cx, cy), 20, (50, 50, 230), 3)
                cv2.line(img, (cx - 14, cy), (cx + 14, cy), (50, 50, 230), 2)
                cv2.line(img, (cx, cy - 14), (cx, cy + 14), (50, 50, 230), 2)
            path_str = ' -> '.join(str(p) for p in path) if path else 'none'
            print(f'  Path: {path_str}')

        info = [
            '[DEBUG] Wonder Connect',
            f'Valid pairs: {len(pairs)}',
            f'Chosen: {chosen}',
        ]
        y = 36
        for line in info:
            cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4)
            cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
            y += 28

        src = screenshot_path or 'screenshot'
        out_path = f'{os.path.splitext(src)[0]}_debug_connect.png'
        cv2.imwrite(out_path, img)
        print(f'Debug image -> {out_path}')

    def _save_screenshot(self, screenshot, grid, label):
        """Save annotated screenshot with type IDs overlaid and a timestamped label."""
        img = screenshot.copy()
        for r in range(self.parser.rows):
            for c in range(self.parser.cols):
                _, bbox = self.parser._cell_crop(screenshot, r, c)
                x1, y1, x2, y2 = bbox
                tid = grid[r][c]
                if tid != 0:
                    cx_ = (x1 + x2) // 2
                    cy_ = (y1 + y2) // 2
                    cv2.putText(img, str(tid), (cx_ - 6, cy_ + 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1)
        ts = time.strftime('%Y%m%d_%H%M%S')
        path = f'game_{ts}_{label}.png'
        cv2.imwrite(path, img)
        print(f'  [saved] {path}')

    def _save_screenshot_debug(self, screenshot, grid):
        """Triggered only on reshuffle timeout. Saves screenshot and dumps per-cell diagnostics."""
        ts = time.strftime('%Y%m%d_%H%M%S')
        path = f'debug_timeout_{ts}.png'
        img = screenshot.copy()
        print(f'\n═══ RESHUFFLE TIMEOUT DEBUG  {ts} ═══')
        print(f'  HASH_THRESHOLD={HASH_THRESHOLD}  COLOR_SIM_THRESHOLD={COLOR_SIM_THRESHOLD}'
              f'  ORPHAN_COLOR_MIN={ORPHAN_COLOR_MIN}')

        # Collect per-cell data
        cell_data = {}  # (r,c) -> (tid, phash, hist)
        for r in range(self.parser.rows):
            for c in range(self.parser.cols):
                crop, bbox = self.parser._cell_crop(screenshot, r, c)
                x1, y1, x2, y2 = bbox
                tid = grid[r][c]
                if crop.size == 0:
                    continue
                ph = self.parser._phash(crop)
                hist = self.parser._color_hist(crop)
                cell_data[(r, c)] = (tid, ph, hist)
                cx_ = (x1 + x2) // 2
                cy_ = (y1 + y2) // 2
                cv2.putText(img, str(tid), (cx_ - 6, cy_ + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 80, 255), 1)

        # Per-cell summary
        print(f'\n  {"cell":>6}  {"type":>4}  {"hash"}')
        for (r, c), (tid, ph, _) in sorted(cell_data.items()):
            print(f'  ({r},{c}):  type={tid:>3}  hash={ph}')

        # Per-type-group: pairwise hash distance and color_sim between members
        from collections import defaultdict
        by_type = defaultdict(list)
        for (r, c), (tid, ph, hist) in cell_data.items():
            if tid != 0:
                by_type[tid].append(((r, c), ph, hist))
        print(f'\n  Per-type pairwise diagnostics:')
        for tid in sorted(by_type):
            members = by_type[tid]
            if len(members) < 2:
                print(f'  type {tid:>3}: SINGLETON  {members[0][0]}')
                continue
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    ca, pha, ha = members[i]
                    cb, phb, hb = members[j]
                    hdist = pha - phb
                    csim = self.parser._hist_sim(ha, hb)
                    ok = 'OK' if hdist <= HASH_THRESHOLD and csim >= COLOR_SIM_THRESHOLD else 'FAIL'
                    print(f'  type {tid:>3}: {ca}<->{cb}  hash_dist={hdist:>3}  color_sim={csim:.4f}  [{ok}]')

        cv2.imwrite(path, img)
        print(f'\n  [saved] {path}')
        print('═══════════════════════════════════════\n')

    def _print_grid(self, grid):
        from collections import Counter
        print('  Grid (type IDs, 0=empty):')
        for r in range(self.parser.rows):
            row_str = ' '.join(f'{grid[r][c]:3d}' for c in range(self.parser.cols))
            print(f'    row {r}: {row_str}')
        counts = Counter(grid[r][c] for r in range(self.parser.rows)
                         for c in range(self.parser.cols) if grid[r][c] != 0)
        singles = sum(1 for n in counts.values() if n == 1)
        pairs   = sum(1 for n in counts.values() if n == 2)
        quads   = sum(1 for n in counts.values() if n == 4)
        sixes   = sum(1 for n in counts.values() if n == 6)
        odd     = sum(1 for n in counts.values() if n % 2 != 0)
        over6   = sum(1 for n in counts.values() if n > 6)
        print(f'  singles={singles}  pairs={pairs}  quads={quads}  sixes={sixes}  odd={odd}  >6={over6}')

    def _take_screenshot(self):
        t0 = time.perf_counter()
        img = self._capture.take_screenshot()
        print(f'  [time] screenshot: {(time.perf_counter()-t0)*1000:5.0f} ms')
        if img is not None:
            self._capture_size = (img.shape[1], img.shape[0])  # (w, h)
        return img

    def _parse(self, screenshot):
        t0 = time.perf_counter()
        grid, centers, hashes = self.parser.parse(screenshot)
        print(f'  [time] parse total:{(time.perf_counter()-t0)*1000:5.0f} ms')
        return grid, centers, hashes

    def run(self, debug=False, screenshot_path=None, no_pacing=False):
        grid = None
        centers = None
        pacing = None
        game_started = False
        t_game_start = None
        timing_log = []   # list of (label, t_relative) for end-of-game summary

        while True:
            # ── Take a fresh screenshot only on first run or when requested ──
            need_fresh = grid is None

            if debug and screenshot_path:
                screenshot = cv2.imread(screenshot_path)
                if screenshot is None:
                    print(f'Cannot read {screenshot_path}')
                    break
                need_fresh = True
            elif need_fresh:
                screenshot = self._take_screenshot()
                if screenshot is None:
                    print('Screenshot failed, retrying...')
                    time.sleep(1)
                    continue

            if need_fresh:
                grid, centers, _ = self._parse(screenshot)
                if not game_started:
                    game_started = True
                    t_game_start = time.perf_counter()
                    timing_log.append(('START', 0.0))
                    occupied = sum(1 for r in range(self.parser.rows)
                                   for c in range(self.parser.cols) if grid[r][c] != 0)
                    pacing = PacingController(occupied // 2)
                    print(f'  [pacing] speed factor={pacing._speed:.3f}  (budget ×{pacing._speed:.0%})')
                    self._print_grid(grid)

            # ── Board clear? ──
            occupied = sum(1 for r in range(self.parser.rows)
                           for c in range(self.parser.cols) if grid[r][c] != 0)
            if occupied == 0:
                t_end = time.perf_counter() - t_game_start
                timing_log.append(('END', t_end))
                print('Board cleared!')
                break

            # ── Find valid pairs ──
            t0 = time.perf_counter()
            pairs = self.checker.find_all_pairs(grid)
            print(f'  [time] find_pairs: {(time.perf_counter()-t0)*1000:5.0f} ms  '
                  f'({len(pairs)} found, {occupied} occupied cells)')

            if not pairs:
                if debug:
                    print('No valid pairs found.')
                    self._save_debug_image(screenshot, grid, centers, [], None, screenshot_path)
                    break

                # If exactly 2 cells remain they must be the last pair — force link
                if occupied == 2:
                    remaining = [(r, c) for r in range(self.parser.rows)
                                 for c in range(self.parser.cols) if grid[r][c] != 0]
                    (r1, c1), (r2, c2) = remaining
                    print(f'Force-linking last 2 cells ({r1},{c1}) <-> ({r2},{c2})  [type ids: {grid[r1][c1]}, {grid[r2][c2]}]')
                    self._tap_cell(centers, r1, c1)
                    time.sleep(TAP_DELAY)
                    self._tap_cell(centers, r2, c2)
                    d = 0.0 if no_pacing else (pacing.next_delay() if pacing else LOOP_DELAY)
                    print(f'  [pacing] pair {pacing.pair_num}/{pacing._total}  delay={d*1000:.0f}ms')
                    time.sleep(d)
                    grid[r1][c1] = 0
                    grid[r2][c2] = 0
                    self.parser.mark_cleared(r1, c1, r2, c2)
                    continue

                self._print_grid(grid)
                print('No pairs -- waiting for reshuffle...')
                prev_board = screenshot
                t_wait_start = time.perf_counter()
                timing_log.append((f'RESHUFFLE WAIT (pair {pacing.pair_num if pacing else "?"})',
                                   t_wait_start - t_game_start))
                while True:
                    time.sleep(self._reshuffle_poll)
                    new_board = self._take_screenshot()
                    elapsed = time.perf_counter() - t_wait_start
                    diff = self.parser._board_diff(prev_board, new_board)
                    print(f'  [board_diff] {diff:.2f}  elapsed={elapsed:.1f}s')
                    if diff > RESHUFFLE_DIFF_THRESHOLD:
                        print('Reshuffle detected (large diff), resuming...')
                        if pacing:
                            pacing.record_reshuffle(elapsed)
                        timing_log.append((f'  RESUME (waited {elapsed:.1f}s)',
                                           time.perf_counter() - t_game_start))
                        screenshot = new_board
                        grid, centers, _ = self._parse(screenshot)
                        self._print_grid(grid)
                        break
                    if elapsed >= self._reshuffle_timeout:
                        print(f'Reshuffle timeout -- tapping button and waiting 1s (diff={diff:.2f}).')
                        if pacing:
                            pacing.record_reshuffle(elapsed + 1.0)
                        self._tap_reshuffle_btn()
                        time.sleep(1.0)
                        timing_log.append((f'  RESUME via button (waited {elapsed+1.0:.1f}s)',
                                           time.perf_counter() - t_game_start))
                        screenshot = self._take_screenshot()
                        grid, centers, _ = self._parse(screenshot)
                        self._print_grid(grid)
                        self._save_screenshot_debug(screenshot, grid)
                        break
                    prev_board = new_board
                continue

            chosen = pairs[0]
            (r1, c1), (r2, c2) = chosen
            path = self.checker.find_path(grid, r1, c1, r2, c2)
            path_str = ' -> '.join(str(p) for p in path)
            print(f'Linking ({r1},{c1}) <-> ({r2},{c2})  [type {grid[r1][c1]}]  {path_str}')

            if debug:
                self._save_debug_image(screenshot, grid, centers, pairs, chosen, screenshot_path)
                break

            self._tap_cell(centers, r1, c1)
            time.sleep(TAP_DELAY)
            self._tap_cell(centers, r2, c2)
            d = 0.0 if no_pacing else (pacing.next_delay() if pacing else LOOP_DELAY)
            print(f'  [pacing] pair {pacing.pair_num}/{pacing._total}  delay={d*1000:.0f}ms')
            time.sleep(d)

            # ── Update local grid — mark cells as cleared, skip screenshot ──
            grid[r1][c1] = 0
            grid[r2][c2] = 0
            self.parser.mark_cleared(r1, c1, r2, c2)

        if timing_log and not debug:
            print('\n─── Timing summary ───')
            for label, t in timing_log:
                print(f'  {t:6.1f}s  {label}')
            total = next((t for label, t in reversed(timing_log) if label == 'END'), None)
            if total is not None:
                print(f'  Total: {total:.1f}s')
            print('──────────────────────')

    def run_parse_debug(self):
        """
        Parse-debug mode: no merge/correction logic, full metric output.
        After showing raw results, prompts for known correct pairs so we can
        print the actual phash_dist and color_sim to help tune thresholds.
        Saves a grid overlay image for visual position verification.
        """
        print('Taking screenshot...')
        screenshot = self._take_screenshot()
        if screenshot is None:
            print('Screenshot failed.')
            return

        h, w = screenshot.shape[:2]
        print(f'  Screenshot size: {w}x{h}')

        # Save grid overlay immediately so cell positions can be verified visually
        ts = time.strftime('%Y%m%d_%H%M%S')
        grid_img = screenshot.copy()
        gx1, gy1, gx2, gy2 = self.parser._grid_px(screenshot)
        cv2.rectangle(grid_img, (gx1, gy1), (gx2, gy2), (0, 255, 0), 2)
        cell_w = (gx2 - gx1) / self.parser.cols
        cell_h = (gy2 - gy1) / self.parser.rows
        for r in range(self.parser.rows):
            for c in range(self.parser.cols):
                x1 = int(gx1 + c * cell_w)
                y1 = int(gy1 + r * cell_h)
                x2 = int(x1 + cell_w)
                y2 = int(y1 + cell_h)
                cv2.rectangle(grid_img, (x1, y1), (x2, y2), (160, 160, 160), 1)
                cv2.putText(grid_img, f'{r},{c}', (x1 + 4, y1 + 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 220, 255), 1)
        grid_path = f'grid_check_{ts}.png'
        cv2.imwrite(grid_path, grid_img)
        print(f'  Grid overlay saved -> {grid_path}  (verify cell borders align with cards)')

        print('\n--- Raw parse (no orphan/triplet correction) ---')
        grid, centers, cell_hashes, cell_colors = self.parser.parse_verbose(screenshot)

        print('\n  Grid (type IDs, 0=empty):')
        for r in range(self.parser.rows):
            row_str = ' '.join(f'{grid[r][c]:3d}' for c in range(self.parser.cols))
            print(f'    row {r}: {row_str}')

        # Report odd-count types and ask user to confirm correct pairings
        from collections import Counter
        counts = Counter(grid[r][c] for r in range(self.parser.rows)
                         for c in range(self.parser.cols) if grid[r][c] != 0)
        odd_types = {tid: n for tid, n in counts.items() if n % 2 != 0}
        if odd_types:
            print('\n--- Odd-count types (need user confirmation) ---')
            for tid, n in sorted(odd_types.items()):
                cells = [(r, c) for r in range(self.parser.rows)
                         for c in range(self.parser.cols) if grid[r][c] == tid]
                print(f'  type {tid:3d}  count={n}  cells: {cells}')
        else:
            print('\n  All type counts are even — no obvious mismatches.')

        print('\n--- Manual pair verification ---')
        print('For each pair you know is correct, enter both cells (e.g.  5,0 6,1).')
        print('Press Enter with no input to finish.\n')
        while True:
            raw = input('  Pair: ').strip()
            if not raw:
                break
            parts = raw.replace(',', ' ').split()
            if len(parts) != 4:
                print('  Need exactly two cells: row1,col1 row2,col2')
                continue
            try:
                r1, c1, r2, c2 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            except ValueError:
                print('  Invalid numbers.')
                continue
            if (r1, c1) not in cell_hashes or (r2, c2) not in cell_hashes:
                print(f'  ({r1},{c1}) or ({r2},{c2}) not found in parsed cells (empty/cleared?).')
                continue
            dist = cell_hashes[(r1, c1)] - cell_hashes[(r2, c2)]
            sim  = self.parser._hist_sim(cell_colors[(r1, c1)], cell_colors[(r2, c2)])
            tid1, tid2 = grid[r1][c1], grid[r2][c2]
            matched = dist <= HASH_THRESHOLD and sim >= COLOR_SIM_THRESHOLD
            print(f'  ({r1},{c1}) type={tid1}  vs  ({r2},{c2}) type={tid2}')
            print(f'    phash_dist={dist}  color_sim={sim:.4f}')
            print(f'    thresholds: HASH_THRESHOLD={HASH_THRESHOLD}  COLOR_SIM_THRESHOLD={COLOR_SIM_THRESHOLD}')
            if matched:
                print(f'    -> WOULD match with current thresholds (same type expected: {tid1 == tid2})')
            else:
                reasons = []
                if dist > HASH_THRESHOLD:
                    reasons.append(f'phash_dist {dist} > {HASH_THRESHOLD} (need HASH_THRESHOLD >= {dist})')
                if sim < COLOR_SIM_THRESHOLD:
                    reasons.append(f'color_sim {sim:.4f} < {COLOR_SIM_THRESHOLD} (need COLOR_SIM_THRESHOLD <= {sim:.4f})')
                print(f'    -> blocked by: {"; ".join(reasons)}')
            print()

# ---------------------------------------------------------------------------

def _menu(use_scrcpy, capture):
    """
    Interactive startup menu. Returns one of:
      'launch'          — (re)launch scrcpy
      'start'           — start game (scans board for empty cells, then plays)
      'parse_debug'     — enter parse-debug mode
      ('exit', 'keep')  — exit, leave scrcpy running
      ('exit', 'stop')  — exit, stop scrcpy (only if we launched it)
    """
    while True:
        if use_scrcpy:
            up = capture is not None and capture.is_running()
            owned = capture is not None and capture.launched_by_us
            status = ('running (this tool)' if owned else 'running (external)') if up else 'not running'
            print(f'\n=== Wonder Connect ===  scrcpy: {status}\n')
        else:
            print('\n=== Wonder Connect ===  (adb screencap mode)\n')
            up = True

        opts = {}
        if use_scrcpy and not up:
            print('  s  Launch scrcpy')
            opts['s'] = 'launch'

        if up:
            print('  n  Start game')
            print('  d  Parse debug')
            opts['n'] = 'start'
            opts['d'] = 'parse_debug'

        if use_scrcpy and up and owned:
            print('  q  Exit  (keep scrcpy)')
            print('  x  Exit  (stop scrcpy)')
            opts['q'] = ('exit', 'keep')
            opts['x'] = ('exit', 'stop')
        else:
            print('  q  Exit')
            opts['q'] = ('exit', 'keep')

        choice = input('\n  Choice: ').strip().lower()
        if choice in opts:
            return opts[choice]
        print('  Invalid choice.')


def main():
    parser = argparse.ArgumentParser(description='Life Makeover -- Wonder Connect assistant')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Debug mode: annotate screenshot, no taps')
    parser.add_argument('--parse-debug', action='store_true',
                        help='Parse-debug mode: raw metrics, no merge logic, interactive pair verification')
    parser.add_argument('--screenshot', '-s', metavar='PATH',
                        help='Screenshot file for debug (implies --debug)')
    parser.add_argument('--adb-path', metavar='PATH', default=ADB_PATH)
    parser.add_argument('--adb', action='store_true',
                        help='Force adb screencap for screenshots (low-speed fallback). '
                             'Default: scrcpy window capture when configured in config.json.')
    parser.add_argument('--no-pacing', action='store_true',
                        help='Disable inter-pair delays (baseline timing run to measure raw processing speed).')
    args = parser.parse_args()

    debug = args.debug or bool(args.screenshot)
    screenshot_path = args.screenshot

    cfg = _read_config(CONFIG_PATH)
    empty_hist = None

    if debug and screenshot_path:
        devices_cfg = cfg.get('devices', {})
        if not devices_cfg:
            print('No device config. Run setup.py first.')
            sys.exit(1)
        first_serial = next(iter(devices_cfg))
        entry = devices_cfg[first_serial]
        regions = {k: tuple(v) for k, v in entry['regions'].items()}
        print(f'Debug mode -- regions from device "{first_serial}"')
        adb = None
    else:
        adb = get_adb(adb_path=args.adb_path)
        regions, _, empty_hist = load_device_config(CONFIG_PATH, adb.device)
        if regions is None:
            print(f'Device "{adb.device}" not in config. Run setup.py first.')
            sys.exit(1)

    grid_region = regions['grid']
    grid_parser = GridParser(grid_region, GRID_ROWS, GRID_COLS)
    if not debug and empty_hist is not None:
        grid_parser._empty_hist = empty_hist
    link_checker = LinkChecker(GRID_ROWS, GRID_COLS)
    device_size = adb.get_screen_size() if adb is not None else None

    _scrcpy_cfg = {**read_common_config().get('scrcpy', {}), **cfg.get('scrcpy', {})}
    use_scrcpy = not args.adb and bool(_scrcpy_cfg) and not (debug and screenshot_path)
    capture = None
    if use_scrcpy:
        capture = get_scrcpy(cfg, serial=adb.device, adb=adb, window_title=SCRCPY_WINDOW_TITLE)
    else:
        print('Screenshot: adb screencap' + (' (--adb flag)' if args.adb else ' (no scrcpy config)'))

    # Debug/parse-debug bypass the menu — run once and exit
    if args.parse_debug or (debug and screenshot_path):
        assistant = GameAssistant(adb, grid_parser, link_checker,
                                  reshuffle_btn=regions.get('reshuffle_btn'),
                                  capture=capture, device_size=device_size)
        if args.parse_debug:
            assistant.run_parse_debug()
        else:
            assistant.run(debug=True, screenshot_path=screenshot_path)
        return

    while True:
        action = _menu(use_scrcpy, capture)

        if action == 'launch':
            capture = get_scrcpy(cfg, serial=adb.device, adb=adb, window_title=SCRCPY_WINDOW_TITLE)

        elif action == 'start':
            grid_parser._cleared.clear()
            assistant = GameAssistant(adb, grid_parser, link_checker,
                                      reshuffle_btn=regions.get('reshuffle_btn'),
                                      capture=capture, device_size=device_size)
            if grid_parser._empty_hist is not None:
                print('  Scanning board for pre-cleared cells...')
                screenshot = assistant._take_screenshot()
                if screenshot is not None:
                    n = grid_parser.scan_empty_cells(screenshot)
                    print(f'  Found {n} pre-cleared cell(s).')
            assistant.run(no_pacing=args.no_pacing)

        elif action == 'parse_debug':
            assistant = GameAssistant(adb, grid_parser, link_checker,
                                      reshuffle_btn=regions.get('reshuffle_btn'),
                                      capture=capture, device_size=device_size)
            assistant.run_parse_debug()

        elif isinstance(action, tuple) and action[0] == 'exit':
            if action[1] == 'stop' and capture is not None:
                capture.stop()
                print('scrcpy stopped.')
            break


if __name__ == '__main__':
    main()
