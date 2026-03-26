#!/usr/bin/env python3
# Slices a large RGB GeoTIFF into smaller georeferenced tiles compatible with tiler.py.
# Each output tile is a GeoTIFF with the same CRS, band count, and dtype as the source.
# Tiles are power-of-two pixels (default 512x512), edge-to-edge with no overlap or gaps.
# Edge tiles that extend beyond the source raster are zero-padded to maintain uniform size.
#
# Requirements: rasterio, numpy  (already in requirements.txt)
#
# Usage:
#   python rgb_slicer.py <input_geotiff> [output_folder] [--tile-size 512]
#
# Examples:
#   python rgb_slicer.py "C:\path\to\large_rgb.tif"
#   python rgb_slicer.py "C:\path\to\large_rgb.tif" "C:\path\to\output" --tile-size 1024

import sys
import os
import math
import argparse
import platform
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window, transform as window_transform


def is_power_of_two(n):
    """Check if n is a positive power of two."""
    return n > 0 and (n & (n - 1)) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Slice a large RGB GeoTIFF into smaller georeferenced tiles for tiler.py."
    )
    parser.add_argument(
        "input_geotiff",
        type=str,
        help="Path to the input large RGB GeoTIFF file.",
    )
    parser.add_argument(
        "output_folder",
        type=str,
        nargs="?",
        default=None,
        help="Output folder for sliced tiles. Defaults to 'rgb_tiles' next to the input file.",
    )
    parser.add_argument(
        "--tile-size",
        type=int,
        default=512,
        help="Tile size in pixels (must be a power of two). Default: 512.",
    )

    args = parser.parse_args()

    input_path = Path(args.input_geotiff)
    tile_size = args.tile_size

    # Validate input file
    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}")
        raise SystemExit(1)

    # Validate tile size
    if not is_power_of_two(tile_size):
        print(f"Error: --tile-size must be a power of two (e.g. 256, 512, 1024). Got: {tile_size}")
        raise SystemExit(1)

    # Determine output folder
    if args.output_folder is not None:
        out_dir = Path(args.output_folder)
    else:
        out_dir = input_path.parent / "rgb_tiles"

    out_dir.mkdir(parents=True, exist_ok=True)

    # Open source raster and read metadata
    with rasterio.open(str(input_path)) as src:
        src_width = src.width
        src_height = src.height
        src_crs = src.crs
        src_transform = src.transform
        src_dtype = src.dtypes[0]  # all bands assumed same dtype
        src_count = src.count
        src_nodata = src.nodata

        # Compute pixel resolution for display
        pixel_res_x = abs(src_transform.a)
        pixel_res_y = abs(src_transform.e)

        # Compute grid dimensions
        n_tiles_x = math.ceil(src_width / tile_size)
        n_tiles_y = math.ceil(src_height / tile_size)
        total_tiles = n_tiles_x * n_tiles_y

        # Print summary
        print(f"Input:          {input_path.name}")
        print(f"Dimensions:     {src_width} x {src_height} px")
        print(f"Bands:          {src_count} ({src_dtype})")
        print(f"CRS:            {src_crs}")
        print(f"Pixel size:     {pixel_res_x:.10g} x {pixel_res_y:.10g}")
        print(f"Tile size:      {tile_size} x {tile_size} px")
        print(f"Grid:           {n_tiles_x} cols x {n_tiles_y} rows = {total_tiles} tiles")
        print(f"Output:         {out_dir}")
        print()

        # Determine fill value: use nodata if set, otherwise 0
        fill = int(src_nodata) if src_nodata is not None else 0

        # Profile template for output tiles
        profile = {
            "driver": "GTiff",
            "width": tile_size,
            "height": tile_size,
            "count": src_count,
            "dtype": src_dtype,
            "crs": src_crs,
            "compress": "lzw",
        }
        if src_nodata is not None:
            profile["nodata"] = src_nodata

        # Iterate over grid and write tiles
        for row in range(n_tiles_y):
            for col in range(n_tiles_x):
                # Pixel offsets in the source image
                px_col = col * tile_size
                px_row = row * tile_size

                # Build a window (may extend beyond source bounds for edge tiles)
                window = Window(px_col, px_row, tile_size, tile_size)

                # Read all bands with boundless=True so out-of-bounds pixels are filled
                data = src.read(
                    window=window,
                    boundless=True,
                    fill_value=fill,
                )
                # data shape: (bands, tile_size, tile_size)

                # Compute the georeferenced transform for this tile
                tile_transform = window_transform(window, src_transform)

                # Output filename: tile_{pixelRow}_{pixelCol}.tif
                tile_name = f"tile_{px_row}_{px_col}.tif"
                tile_path = out_dir / tile_name

                # Write tile
                tile_profile = profile.copy()
                tile_profile["transform"] = tile_transform

                with rasterio.open(str(tile_path), "w", **tile_profile) as dst:
                    dst.write(data)

                # Progress
                tile_num = row * n_tiles_x + col + 1
                print(f"\r  [{tile_num}/{total_tiles}] {tile_name}", end="", flush=True)

        print()  # newline after progress

    print()
    print("Done.")
    print(f"Output written to: {out_dir}")
    print(f"Tile count: {total_tiles}")

    # Completion sound (matches tiler.py convention)
    system = platform.system()
    if system == "Windows":
        print("\007")
        os.system("rundll32 user32.dll,MessageBeep")
    elif system == "Darwin":
        os.system("afplay /System/Library/Sounds/Glass.aiff")
    else:
        os.system(
            'paplay /usr/share/sounds/freedesktop/stereo/complete.oga 2>/dev/null '
            '|| beep 2>/dev/null || echo "\\a"'
        )

    print("✓ SLICING COMPLETE!")


if __name__ == "__main__":
    main()
