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

### Card Identification (per parse)
1. **Perceptual hash (pHash)**: cells within hash distance ≤ `HASH_THRESHOLD=12` are candidates
2. **HSV color histogram** (center 50% crop, correlation ≥ `COLOR_SIM_THRESHOLD=0.95`):
   second filter — rejects same-pattern, different-color cards
3. Both conditions must pass to merge two cells into the same type ID

### Mismatch Correction (post-parse passes)
- **Orphan merge** (singleton + singleton): two type-1 cells paired by best color similarity,
  floor `ORPHAN_COLOR_MIN=0.85` — skipped if below floor
- **Triplet fix** (singleton + triplet): one misclassified cell from a count-3 type is
  reassigned to the singleton type using best color similarity, same floor

### Empty Cell Tracking
- `_cleared` set: cells the tool has successfully linked — always skipped in parse
- **`_cleared` is never reset on reshuffle** — cleared positions are stable
- `_empty_hist` (full-crop HSV histogram, loaded from `config.json`): backup visual
  filter for cells not yet in `_cleared` (e.g. first parse after reshuffle in new positions)

### Reshuffle Flow
1. No pairs found → start polling for reshuffle immediately
2. If board diff > `RESHUFFLE_DIFF_THRESHOLD=8.0` → reshuffle detected early, re-parse
3. If `RESHUFFLE_TIMEOUT=5.0s` elapsed without large diff (board mostly empty) →
   tap the reshuffle button, wait 1s for animation, then re-parse
4. `_cleared` is kept unchanged through all of the above

### Path Finding
- BFS-style check: direct line, 1-bend (L-shape), 2-bend (Z/S/U-shape)
- Virtual border cells (row -1, row 8, col -1, col 6) are always passable

### Force-Link (last 2 cells)
- If exactly 2 occupied cells remain and no valid path exists:
  force-link them unconditionally — game guarantees they are the last matching pair

### Tap Timing
- `TAP_DELAY=0.03s` between tapping card 1 and card 2
- `LOOP_DELAY=0.03s` after each successful link
