# Wonder Connect — Game Rules & Tool Behavior

## Game Rules

### Board
- 8 rows × 6 columns = 48 cells total
- Cards appear in identical groups of exactly **2, 4, or 6** — never an odd count

### Linking
- Select two identical cards to link and clear them from the board
- A valid link requires a path with **at most 2 direction changes** (bends)
- Paths may extend **1 cell outside the board boundary**

### Cleared Cells
- Cleared cells stay at their exact positions permanently — they do not move
- **After reshuffle: cleared cell positions are unchanged**
- Only the remaining (uncleared) cards are reshuffled into new positions

### Reshuffle
- Game auto-reshuffles when no valid pair can be linked
- Shuffle animation takes ~3 seconds
- When the board is mostly empty, the per-pixel visual change is small — diff-based
  detection becomes unreliable because empty space dominates the grid area
- After reshuffle: same remaining cards, new positions; cleared cells stay in place

---

## Tool Behavior

Values below are the constants at the top of `main.py` (as of 2026-11-17); the code is the reference.

### Card Identification (per parse)
1. **Perceptual hash (pHash)** of each cell (8% border trimmed): cells within hash distance ≤ `HASH_THRESHOLD=12` are candidates
2. **HSV colour histogram** (centre 50% of the cell, correlation ≥ `COLOR_SIM_THRESHOLD=0.74`):
   second filter — rejects same-pattern, different-colour cards. Kept low for scrcpy: its H.264/H.265
   compression shifts histograms; true pairs were observed at 0.83–0.97
3. Both conditions must pass to merge two cells into the same type ID

### Mismatch Correction (post-parse passes)
- **Orphan merge** (singleton + singleton): two count-1 types paired by best colour similarity,
  floor `ORPHAN_COLOR_MIN=0.70` — skipped if below the floor
- **Triplet fix** (singleton + triplet): one misclassified cell from a count-3 type is
  reassigned to the singleton type using best colour similarity, same floor

### Empty Cell Tracking
- `_cleared` set: cells the tool has successfully linked — always skipped in parse
- **`_cleared` is never reset on reshuffle** — cleared positions are stable
- `_empty_hist` (full-cell HSV histogram from the setup calibration, `empty_hist` in `config.json`):
  a cell with similarity ≥ `EMPTY_CELL_SIM_THRESHOLD=0.97` is treated as empty. Covers cells not in
  `_cleared`: cleared before the tool started (scanned once at game start) or not cleared by the tool

### Reshuffle Flow
1. No pairs found → start polling for reshuffle immediately
   (every `RESHUFFLE_POLL=0.5s` with scrcpy, `RESHUFFLE_POLL_ADB=3.0s` with adb screencap)
2. If the grid's mean pixel difference > `RESHUFFLE_DIFF_THRESHOLD=8.0` → reshuffle detected, re-parse
3. If `RESHUFFLE_TIMEOUT=4.0s` (adb: `RESHUFFLE_TIMEOUT_ADB=8.0s`) passes without a large diff
   (board mostly empty) → tap the reshuffle button, wait 1 s for the animation, re-parse, and save a
   `debug_timeout_<time>.png` with a per-cell dump
4. `_cleared` is kept unchanged through all of the above
5. Time spent waiting is taken off the remaining pacing pauses

### Path Finding
- Tries, in order: a straight line, the two 1-bend (L) routes, then every 2-bend route through a
  middle row, then through a middle column (Z / S / U shapes)
- Virtual border cells (row -1, row 8, col -1, col 6) are always passable
- Pairs are taken in board order (first valid pair found)

### Force-Link (last 2 cells)
- If exactly 2 occupied cells remain and no valid path exists:
  force-link them unconditionally — the game guarantees they are the last matching pair

### Tap Timing
- `TAP_DELAY=0.03s` between tapping card 1 and card 2; each tap lands at a random point within
  ~5 px of the cell centre
- After each pair, a pause from `PacingController` (target game time, menu `t`; see the README's
  *Pacing* section). `--no-pacing` removes the pauses
