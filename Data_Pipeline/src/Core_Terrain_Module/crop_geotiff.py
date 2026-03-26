#!/usr/bin/env python3
# Crops a GeoTIFF file to a bounding box defined by 4 lat/lon corner coordinates.
# The corners can be given in any order; the script extracts the bounding box automatically.
# If the source GeoTIFF is in a different CRS, the coordinates are reprojected on the fly.
# Output preserves the source CRS, band count, dtype, and nodata value.
#
# Requirements: rasterio, numpy  (already in requirements.txt)
#
# Usage:
#   python crop_geotiff.py <input_geotiff> <lat1,lon1> <lat2,lon2> <lat3,lon3> <lat4,lon4> [output_file]
#
# Examples:
#   python crop_geotiff.py "large.tif" 40.5,29.0 40.5,29.5 40.0,29.0 40.0,29.5
#   python crop_geotiff.py "large.tif" 40.5,29.0 40.5,29.5 40.0,29.0 40.0,29.5 "cropped.tif"

import sys
import os
import argparse
import platform
from pathlib import Path

import numpy as np
import rasterio
import rasterio.windows
from rasterio.warp import transform as warp_transform
from rasterio.windows import from_bounds, transform as window_transform


def parse_coord(s):
    """Parse a 'lat,lon' string into (lat, lon) floats."""
    parts = s.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"Coordinate must be in 'lat,lon' format. Got: '{s}'"
        )
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Coordinate values must be numbers. Got: '{s}'"
        )
    if not (-90 <= lat <= 90):
        raise argparse.ArgumentTypeError(
            f"Latitude must be between -90 and 90. Got: {lat}"
        )
    if not (-180 <= lon <= 180):
        raise argparse.ArgumentTypeError(
            f"Longitude must be between -180 and 180. Got: {lon}"
        )
    return lat, lon


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Crop a GeoTIFF to a bounding box defined by 4 lat/lon corner coordinates. "
            "Corners can be given in any order."
        ),
        epilog=(
            "Example:\n"
            '  python crop_geotiff.py "large.tif" 40.5,29.0 40.5,29.5 40.0,29.0 40.0,29.5\n'
            '  python crop_geotiff.py "large.tif" 40.5,29.0 40.5,29.5 40.0,29.0 40.0,29.5 "cropped.tif"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input_geotiff",
        type=str,
        help="Path to the input GeoTIFF file.",
    )
    parser.add_argument(
        "corners",
        type=parse_coord,
        nargs=4,
        metavar="lat,lon",
        help="Four corner coordinates in 'lat,lon' format (WGS84 / EPSG:4326).",
    )
    parser.add_argument(
        "output_file",
        type=str,
        nargs="?",
        default=None,
        help="Output file path. Defaults to '<input_name>_cropped.tif' next to the input.",
    )

    args = parser.parse_args()

    input_path = Path(args.input_geotiff)
    corners = args.corners  # list of (lat, lon) tuples

    # Validate input file
    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}")
        raise SystemExit(1)

    # Determine output path
    if args.output_file is not None:
        output_path = Path(args.output_file)
    else:
        output_path = input_path.parent / (input_path.stem + "_cropped.tif")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Extract lat/lon bounds from the 4 corners
    lats = [c[0] for c in corners]
    lons = [c[1] for c in corners]

    bbox_lat_min = min(lats)
    bbox_lat_max = max(lats)
    bbox_lon_min = min(lons)
    bbox_lon_max = max(lons)

    # Validate that the bbox has non-zero area
    if bbox_lat_min == bbox_lat_max or bbox_lon_min == bbox_lon_max:
        print("Error: the 4 corners define a line or point, not an area.")
        print(f"  Lat range: {bbox_lat_min} to {bbox_lat_max}")
        print(f"  Lon range: {bbox_lon_min} to {bbox_lon_max}")
        raise SystemExit(1)

    print(f"Input:      {input_path.name}")
    print(f"Crop box:   lat [{bbox_lat_min}, {bbox_lat_max}]  lon [{bbox_lon_min}, {bbox_lon_max}]")

    with rasterio.open(str(input_path)) as src:
        src_crs = src.crs
        src_transform = src.transform
        src_width = src.width
        src_height = src.height
        src_count = src.count
        src_dtype = src.dtypes[0]
        src_nodata = src.nodata

        print(f"Source CRS: {src_crs}")
        print(f"Source size: {src_width} x {src_height} px, {src_count} band(s) ({src_dtype})")

        # Convert lat/lon bbox corners to source CRS if needed
        # rasterio.warp.transform takes (lons, lats) → (xs, ys)
        bbox_lons = [bbox_lon_min, bbox_lon_max, bbox_lon_min, bbox_lon_max]
        bbox_lats = [bbox_lat_min, bbox_lat_min, bbox_lat_max, bbox_lat_max]

        if src_crs and not src_crs.to_epsg() == 4326:
            print("Reprojecting coordinates to source CRS...")
            xs, ys = warp_transform(
                "EPSG:4326", src_crs, bbox_lons, bbox_lats
            )
        else:
            xs = bbox_lons
            ys = bbox_lats

        # Compute bounding box in source CRS
        left = min(xs)
        right = max(xs)
        bottom = min(ys)
        top = max(ys)

        print(f"Crop bounds (source CRS): left={left:.6f}  bottom={bottom:.6f}  right={right:.6f}  top={top:.6f}")

        # Check overlap with the source raster
        src_bounds = src.bounds
        if (left >= src_bounds.right or right <= src_bounds.left or
                bottom >= src_bounds.top or top <= src_bounds.bottom):
            print("Error: the crop box does not overlap with the input raster.")
            print(f"  Raster bounds: {src_bounds}")
            print(f"  Crop bounds:   left={left}, bottom={bottom}, right={right}, top={top}")
            raise SystemExit(1)

        # Compute the pixel window from the bounds
        window = from_bounds(left, bottom, right, top, src_transform)

        # Round to whole pixels
        window = window.round_offsets().round_lengths()

        # Clamp window to raster extent (no boundless reading for crop)
        col_off = max(0, int(window.col_off))
        row_off = max(0, int(window.row_off))
        col_end = min(src_width, int(window.col_off + window.width))
        row_end = min(src_height, int(window.row_off + window.height))
        win_width = col_end - col_off
        win_height = row_end - row_off

        if win_width <= 0 or win_height <= 0:
            print("Error: crop region has zero size after rounding to pixel boundaries.")
            raise SystemExit(1)

        clamped_window = rasterio.windows.Window(col_off, row_off, win_width, win_height)

        print(f"Pixel window: col={col_off}, row={row_off}, width={win_width}, height={win_height}")

        # Read data
        print("Reading cropped region...")
        data = src.read(window=clamped_window)

        # Compute transform for the output
        out_transform = window_transform(clamped_window, src_transform)

        # Build output profile
        profile = {
            "driver": "GTiff",
            "width": win_width,
            "height": win_height,
            "count": src_count,
            "dtype": src_dtype,
            "crs": src_crs,
            "transform": out_transform,
            "compress": "lzw",
        }
        if src_nodata is not None:
            profile["nodata"] = src_nodata

        # Write output
        print(f"Writing: {output_path.name} ({win_width} x {win_height} px)")
        with rasterio.open(str(output_path), "w", **profile) as dst:
            dst.write(data)

    print()
    print("Done.")
    print(f"Output written to: {output_path}")

    # Completion sound (matches project convention)
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

    print("✓ CROP COMPLETE!")


if __name__ == "__main__":
    main()