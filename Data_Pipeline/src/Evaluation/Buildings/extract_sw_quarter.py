#!/usr/bin/env python3
"""
extract_sw_quarter.py
---------------------
Copies the tiles that make up the south-western quarter of a tiled image
into an output folder.

Tile filename conventions supported (auto-detected):
  • row/col embedded in name:   tile_r3_c5.tif  /  tile_3_5.tif
  • x/y embedded in name:       tile_x512_y1024.tif
  • flat index (requires --cols):  tile_0007.tif

Usage
-----
  python extract_sw_quarter.py <input_folder> <output_folder> [--cols N]

Arguments
---------
  input_folder   Folder containing the .tif tiles.
  output_folder  Destination folder (created if it doesn't exist).
  --cols N       Number of tile columns in the grid. Only needed when tiles
                 are named with a flat index (e.g. tile_0007.tif).
  --dry-run      Print what would be copied without actually copying.
  --verbose      Print every tile decision.

The script figures out the full grid extent from the filenames, then copies
tiles whose column index is in the LEFT half and whose row index is in the
BOTTOM half (south = higher row numbers, west = lower column numbers).
"""

import argparse
import math
import re
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Filename parsers
# ---------------------------------------------------------------------------

def parse_row_col(name: str):
    """Match patterns like:  tile_r3_c5  /  tile_3_5  /  r03c05"""
    # Explicit r/c labels
    m = re.search(r'[_\-]?r(\d+)[_\-]?c(\d+)', name, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Two bare numbers separated by a non-digit
    m = re.search(r'[_\-](\d+)[_\-](\d+)', name)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def parse_xy(name: str):
    """Match patterns like:  tile_x512_y1024  (pixel offsets, not indices)."""
    m = re.search(r'[_\-]?x(\d+)[_\-]?y(\d+)', name, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def parse_flat_index(name: str):
    """Match a single trailing number:  tile_0007."""
    m = re.search(r'[_\-](\d+)(?:\.\w+)?$', name)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Grid detection
# ---------------------------------------------------------------------------

class TileGrid:
    def __init__(self, tiles: list[tuple[Path, int, int]]):
        """tiles: list of (path, row, col) – 0-based indices."""
        self.tiles = tiles
        rows = [r for _, r, _ in tiles]
        cols = [c for _, _, c in tiles]
        self.min_row, self.max_row = min(rows), max(rows)
        self.min_col, self.max_col = min(cols), max(cols)
        self.n_rows = self.max_row - self.min_row + 1
        self.n_cols = self.max_col - self.min_col + 1

    def sw_quarter(self):
        """
        South-western quarter:
          • West  → left half  (col < min_col + n_cols/2)
          • South → bottom half (row >= min_row + n_rows/2)
        """
        col_threshold = self.min_col + self.n_cols / 2   # exclusive upper bound for west
        row_threshold = self.min_row + self.n_rows / 2   # inclusive lower bound for south

        return [
            (path, r, c)
            for path, r, c in self.tiles
            if c < col_threshold and r >= row_threshold
        ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_grid(folder: Path, cols_hint: int | None) -> TileGrid:
    tif_files = sorted(folder.glob("*.tif")) + sorted(folder.glob("*.tiff"))
    if not tif_files:
        sys.exit(f"[ERROR] No .tif/.tiff files found in {folder}")

    tiles = []
    mode = None  # 'rowcol' | 'xy' | 'flat'

    for f in tif_files:
        stem = f.stem

        rc = parse_row_col(stem)
        if rc:
            tiles.append((f, rc[0], rc[1]))
            mode = 'rowcol'
            continue

        xy = parse_xy(stem)
        if xy:
            tiles.append((f, xy[1], xy[0]))   # treat y→row, x→col
            mode = 'xy'
            continue

        idx = parse_flat_index(stem)
        if idx is not None:
            tiles.append((f, idx, -1))          # col placeholder
            mode = 'flat'
            continue

        print(f"[WARN] Cannot parse coordinates from '{f.name}' – skipping.")

    if not tiles:
        sys.exit("[ERROR] Could not parse coordinates from any tile filename.")

    # Resolve flat indices → (row, col) using cols_hint
    if mode == 'flat':
        if cols_hint is None:
            n = len(tiles)
            # Try to guess a square-ish grid
            cols_hint = math.isqrt(n)
            while cols_hint > 1 and n % cols_hint != 0:
                cols_hint -= 1
            if cols_hint == 1:
                sys.exit(
                    "[ERROR] Tiles appear to use flat indices and the grid width "
                    "could not be guessed. Re-run with --cols N."
                )
            print(f"[INFO] Guessed grid width: {cols_hint} columns "
                  f"({n} tiles → {n // cols_hint} rows × {cols_hint} cols)")
        resolved = []
        for path, flat, _ in sorted(tiles, key=lambda t: t[1]):
            row, col = divmod(flat, cols_hint)
            resolved.append((path, row, col))
        tiles = resolved

    print(f"[INFO] Parsed {len(tiles)} tiles using mode='{mode}'.")
    return TileGrid(tiles)


def main():
    ap = argparse.ArgumentParser(
        description="Copy the south-western quarter of a tiled image to a new folder."
    )
    ap.add_argument("input_folder",  type=Path, help="Folder of input .tif tiles.")
    ap.add_argument("output_folder", type=Path, help="Destination folder for SW quarter.")
    ap.add_argument("--cols", type=int, default=None,
                    help="Number of tile columns (only needed for flat-indexed filenames).")
    ap.add_argument("--dry-run", action="store_true",
                    help="List tiles that would be copied without copying them.")
    ap.add_argument("--verbose", action="store_true",
                    help="Print every tile decision.")
    args = ap.parse_args()

    if not args.input_folder.is_dir():
        sys.exit(f"[ERROR] Input folder not found: {args.input_folder}")

    grid = build_grid(args.input_folder, args.cols)
    print(f"[INFO] Grid dimensions: {grid.n_rows} rows × {grid.n_cols} cols")

    sw_tiles = grid.sw_quarter()
    print(f"[INFO] SW quarter contains {len(sw_tiles)} tile(s).")

    if args.verbose:
        for path, r, c in sorted(sw_tiles, key=lambda t: (t[1], t[2])):
            print(f"       row={r} col={c}  →  {path.name}")

    if args.dry_run:
        print("[DRY-RUN] No files copied.")
        return

    args.output_folder.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path, r, c in sw_tiles:
        dest = args.output_folder / path.name
        shutil.copy2(path, dest)
        copied += 1

    print(f"[DONE] Copied {copied} tile(s) to: {args.output_folder}")


if __name__ == "__main__":
    main()