#!/usr/bin/env python3
"""
Create a south-western-quarter tree-mask evaluation set.

The original extract_sw_quarter.py copies only .tif tiles. Tree predictions are
PNG masks, so this script uses the reference GeoTIFF grid to choose the SW
tiles, then copies the matching tree mask PNGs and reference GeoTIFFs together.
It also writes a sw_extent.geojson file that can be used to clip GT shapefiles
during evaluation.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import geopandas as gpd
import rasterio
from shapely.geometry import box


def parse_tile_name(path: Path):
    match = re.search(r"tile_(\d+)_(\d+)", path.stem)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def sw_tiles(ref_dir: Path, tile_order: str):
    tiles = []
    for tif_path in sorted(ref_dir.glob("tile_*.tif")) + sorted(ref_dir.glob("tile_*.tiff")):
        parsed = parse_tile_name(tif_path)
        if not parsed:
            continue
        first, second = parsed
        if tile_order == "xy":
            row, col = second, first
        else:
            row, col = first, second
        tiles.append((tif_path, row, col, first, second))

    if not tiles:
        raise SystemExit(f"[ERROR] No parseable tile_{{row}}_{{col}} GeoTIFFs found in {ref_dir}")

    rows = [row for _path, row, _col, _first, _second in tiles]
    cols = [col for _path, _row, col, _first, _second in tiles]
    min_row, max_row = min(rows), max(rows)
    min_col, max_col = min(cols), max(cols)
    n_rows = max_row - min_row + 1
    n_cols = max_col - min_col + 1
    row_threshold = min_row + n_rows / 2
    col_threshold = min_col + n_cols / 2

    selected = [
        (path, row, col, first, second)
        for path, row, col, first, second in tiles
        if row >= row_threshold and col < col_threshold
    ]
    return selected, (n_rows, n_cols)


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def write_extent(selected, out_path: Path):
    polygons = []
    crs = None
    for tif_path, row, col, first, second in selected:
        with rasterio.open(tif_path) as src:
            crs = src.crs
            polygons.append(
                {
                    "tile": f"tile_{first}_{second}",
                    "grid_row": row,
                    "grid_col": col,
                    "geometry": box(*src.bounds),
                }
            )

    extent = gpd.GeoDataFrame(polygons, geometry="geometry", crs=crs)
    union = gpd.GeoDataFrame([{"name": "south_west_quarter", "geometry": extent.geometry.union_all()}], crs=crs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    union.to_file(out_path, driver="GeoJSON")


def main():
    parser = argparse.ArgumentParser(description="Extract SW-quarter tree masks and reference GeoTIFFs.")
    parser.add_argument("unity_output", type=Path, help="Folder containing tiles_trees and tiles_height_tif.")
    parser.add_argument("output_folder", type=Path, help="Destination folder for the SW evaluation set.")
    parser.add_argument(
        "--tile-order",
        choices=("xy", "rowcol"),
        default="xy",
        help="Interpret tile_A_B as x/y or row/col. Tree masks use xy by default.",
    )
    args = parser.parse_args()

    src_ref_dir = args.unity_output / "tiles_height_tif"
    src_mask_dir = args.unity_output / "tiles_trees"
    if not src_ref_dir.is_dir():
        raise SystemExit(f"[ERROR] Reference GeoTIFF folder not found: {src_ref_dir}")
    if not src_mask_dir.is_dir():
        raise SystemExit(f"[ERROR] Tree mask folder not found: {src_mask_dir}")

    selected, grid_size = sw_tiles(src_ref_dir, args.tile_order)
    out_ref_dir = args.output_folder / "tiles_height_tif"
    out_mask_dir = args.output_folder / "tiles_trees"

    copied_refs = 0
    copied_masks = 0
    copied_density = 0
    missing_masks = []

    for tif_path, row, col, first, second in selected:
        tile = f"tile_{first}_{second}"
        copied_refs += copy_if_exists(tif_path, out_ref_dir / tif_path.name)
        if copy_if_exists(src_mask_dir / f"{tile}_mask.png", out_mask_dir / f"{tile}_mask.png"):
            copied_masks += 1
        else:
            missing_masks.append(f"{tile}_mask.png")
        copied_density += copy_if_exists(src_mask_dir / f"{tile}_density.png", out_mask_dir / f"{tile}_density.png")

    write_extent(selected, args.output_folder / "sw_extent.geojson")

    print(f"[INFO] Full grid: {grid_size[0]} rows x {grid_size[1]} cols")
    print(f"[INFO] SW quarter tiles: {len(selected)}")
    print(f"[DONE] Copied reference GeoTIFFs: {copied_refs}")
    print(f"[DONE] Copied tree masks: {copied_masks}")
    print(f"[DONE] Copied density PNGs: {copied_density}")
    print(f"[DONE] Wrote extent: {args.output_folder / 'sw_extent.geojson'}")
    if missing_masks:
        print(f"[WARN] Missing masks: {len(missing_masks)}")
        for name in missing_masks[:20]:
            print(f"       {name}")


if __name__ == "__main__":
    main()
