#!/usr/bin/env python3
# Tiles a large DEM to match georeferenced RGB tiles, converts RGB TIFFs to PNG,
# creates unity_output/tile_metadata.json in the exact format shown in your example.
# Requirements: rasterio, numpy, pillow
# Usage:
#   pip install rasterio numpy pillow
#   python tile_dem_for_unity.py <rgb_tif_folder> <dem_file> [output_folder]
#
# Example:
#   python tile_dem_for_unity.py "C:\path\to\rgb_tiles" "C:\path\to\AP_12483_FBD_F0730_RT1.dem.tif"

import sys
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds
from PIL import Image
import os
import platform
import math

# Optional: number of box-blur iterations to apply to the DEM slice before quantizing.
# Set to 0 to disable smoothing (default). Increase to 1-3 to reduce visible quantization banding.
SMOOTH_ITERATIONS = 0

def degrees_to_meters(center_lat, lon_diff, lat_diff):
    """Convert lat/lon differences to meters at a given latitude."""
    # Earth's radius in meters
    R = 6378137.0
    
    # Latitude difference to meters (constant everywhere)
    lat_meters = abs(lat_diff) * (math.pi / 180.0) * R
    
    # Longitude difference to meters (depends on latitude)
    lon_meters = abs(lon_diff) * (math.pi / 180.0) * R * math.cos(math.radians(center_lat))
    
    return lon_meters, lat_meters

def box_blur_3x3(arr, iterations=1):
    """Simple 3x3 box blur applied 'iterations' times. Operates on 2D float32 numpy arrays."""
    if iterations <= 0:
        return arr
    out = arr.astype(np.float32)
    for _ in range(iterations):
        padded = np.pad(out, ((1,1),(1,1)), mode='edge')
        # sum 3x3 neighbourhood
        s = (padded[0:-2,0:-2] + padded[0:-2,1:-1] + padded[0:-2,2:] +
             padded[1:-1,0:-2] + padded[1:-1,1:-1] + padded[1:-1,2:] +
             padded[2:,0:-2]   + padded[2:,1:-1]   + padded[2:,2:])
        out = s / 9.0
    return out

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def unique_coords(coords, tol=1e-6):
    coords = sorted(coords)
    groups = []
    for c in coords:
        if not groups or abs(c - groups[-1]) > tol:
            groups.append(c)
    return groups

def main():
    if len(sys.argv) < 3:
        print("Usage: python tile_dem_for_unity.py <rgb_tif_folder> <dem_file> [output_folder]")
        raise SystemExit(1)

    rgb_folder = Path(sys.argv[1])
    dem_path = Path(sys.argv[2])
    out_root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path.cwd() / "unity_output"

    tiles_rgb_out = out_root / "tiles_rgb"
    tiles_height_out = out_root / "tiles_height"
    ensure_dir(tiles_rgb_out)
    ensure_dir(tiles_height_out)

    # read DEM global stats
    print("Reading DEM global stats...")
    with rasterio.open(str(dem_path)) as dem_src:
        dem_crs = dem_src.crs
        dem_nodata = dem_src.nodata
        dem_dtype = dem_src.dtypes[0]
        dem_bounds = dem_src.bounds
        dem_transform = dem_src.transform
        dem_arr = dem_src.read(1, masked=True)
        # convert masked integer array to a float masked array, then fill masked with nan
        dem_float = dem_arr.astype(np.float32)
        dem_data = dem_float.filled(np.nan)
        global_min = float(np.nanmin(dem_data))
        global_max = float(np.nanmax(dem_data))
        global_height_range = global_max - global_min

    # collect rgb tiles (skip hidden/invalid files)
    print("Scanning RGB tiles...")
    tif_candidates = sorted(rgb_folder.glob("*.tif")) + sorted(rgb_folder.glob("*.tiff"))
    tif_list = []
    for p in tif_candidates:
        # skip hidden/aux files like ._xxx or files starting with dot
        if p.name.startswith("."):
            continue
        # skip common sidecar/aux names
        if p.name.lower().endswith(".aux.xml"):
            continue
        tif_list.append(p)

    if not tif_list:
        print("No RGB TIFFs found in", rgb_folder)
        raise SystemExit(1)

    # Step 1: Check each RGB file and collect metadata
    lefts = []
    tops = []
    rights = []
    bottoms = []
    tile_infos = []

    for tif in tif_list:
        try:
            with rasterio.open(str(tif)) as src:
                bounds = src.bounds
                w = src.width
                h = src.height
                crs = src.crs
                # Save for indexing
                lefts.append(bounds.left)
                tops.append(bounds.top)
                rights.append(bounds.right)
                bottoms.append(bounds.bottom)
                tile_infos.append({
                    "path": tif,
                    "bounds": bounds,
                    "width": w,
                    "height": h,
                    "crs": crs,
                    "name": tif.name
                })
        except rasterio.errors.RasterioIOError as e:
            print(f"Warning: skipping unreadable file {tif.name}: {e}")
        except Exception as e:
            print(f"Warning: unexpected error reading {tif.name}: {e}")

    if not tile_infos:
        print("No valid RGB tiles found")
        raise SystemExit(1)

    # build grid indices: X by increasing left, Y by decreasing top (so top row y=0)
    uniq_lefts = unique_coords(lefts)
    uniq_tops = unique_coords(tops)
    uniq_tops.sort(reverse=True)

    # Step 2: Calculate overall bounds for the entire DEM slice
    # We need one extra pixel on the right and bottom
    overall_left = min(lefts)
    overall_top = max(tops)
    overall_right = max(rights)
    overall_bottom = min(bottoms)

    # Get a representative tile to calculate pixel size
    first_tile = tile_infos[0]
    pixel_width = (first_tile["bounds"].right - first_tile["bounds"].left) / first_tile["width"]
    pixel_height = (first_tile["bounds"].top - first_tile["bounds"].bottom) / first_tile["height"]

    # Calculate total heightmap dimensions with overlap
    total_tex_w = int(round((overall_right - overall_left) / pixel_width))
    total_tex_h = int(round((overall_top - overall_bottom) / pixel_height))
    
    # Add one extra pixel on right and bottom for overlap
    total_hm_w = total_tex_w + 1
    total_hm_h = total_tex_h + 1

    # Extend bounds by 1 pixel right and down
    slice_left = overall_left
    slice_right = overall_left + (total_hm_w * pixel_width)
    slice_bottom = overall_top - (total_hm_h * pixel_height)
    slice_top = overall_top

    # Step 3: Extract the entire DEM section as a single slice
    print(f"Extracting DEM slice ({total_hm_w}x{total_hm_h} pixels)...")
    slice_transform = from_bounds(slice_left, slice_bottom, slice_right, slice_top, total_hm_w, total_hm_h)
    
    # Prepare destination array for the entire slice
    dem_slice = np.full((total_hm_h, total_hm_w), np.nan, dtype=np.float32)

    # Reproject/resample DEM into this grid
    with rasterio.open(str(dem_path)) as dem_src:
        reproject(
            source=rasterio.band(dem_src, 1),
            destination=dem_slice,
            src_transform=dem_src.transform,
            src_crs=dem_src.crs,
            dst_transform=slice_transform,
            dst_crs=first_tile["crs"],
            resampling=Resampling.cubic,
            src_nodata=dem_nodata,
            dst_nodata=np.nan
        )

    # Step 4: Convert data for Unity (normalize and type cast)
    print("Normalizing and converting DEM data for Unity...")
    # Shift elevations using global_min (consistent across all tiles)
    elev_shifted = dem_slice - global_min  # Now values are >= 0 where valid; invalid are nan
    elev_shifted = np.where(np.isnan(elev_shifted), 0.0, elev_shifted)

    # Optional smoothing (done here in python). This reduces tiny quantization steps visually.
    if SMOOTH_ITERATIONS > 0:
        elev_shifted = box_blur_3x3(elev_shifted, iterations=SMOOTH_ITERATIONS)

    # Scale to use the full uint16 range (0..65535). This maximizes vertical precision.
    if global_height_range > 0.0:
        scaled = np.rint((elev_shifted / global_height_range) * 65535.0).clip(0, 65535).astype(np.uint16)
    else:
        # degenerate case: flat area; just round to 0..65535 safely.
        scaled = np.rint(elev_shifted).clip(0, 65535).astype(np.uint16)

    # Keep a float32 copy for per-tile GeoTIFF output (absolute elevation)
    elev_shifted_absolute = elev_shifted + global_min  # absolute elevation float32 for TIFFs

    # Step 5: Slice the large heightmap into tiles with 1 pixel overlap
    print("Slicing into individual tiles...")
    tile_records = []

    for info in tile_infos:
        bounds = info["bounds"]
        tex_w = int(info["width"])
        tex_h = int(info["height"])
        hm_w = tex_w + 1
        hm_h = tex_h + 1

        # compute indices
        def find_index(val, arr):
            diffs = [abs(val - a) for a in arr]
            return int(np.argmin(diffs))

        tx = find_index(bounds.left, uniq_lefts)
        ty = find_index(bounds.top, uniq_tops)

        # Calculate pixel position in the large slice
        col_start = int(round((bounds.left - slice_left) / pixel_width))
        row_start = int(round((slice_top - bounds.top) / pixel_height))
        
        # Extract tile from the large slice (with 1 pixel overlap)
        row_end = row_start + hm_h
        col_end = col_start + hm_w
        
        # uint16 tile used for Unity .bytes/.raw (values in 0..65535 representing normalized [0..1])
        tile_heightmap = scaled[row_start:row_end, col_start:col_end]
        # float32 tile used for GeoTIFF (absolute elevation)
        tile_elev_tif = elev_shifted_absolute[row_start:row_end, col_start:col_end].astype(np.float32)

        # Verify dimensions
        if tile_heightmap.shape != (hm_h, hm_w):
            print(f"Warning: tile_{tx}_{ty} has unexpected shape {tile_heightmap.shape}, expected ({hm_h}, {hm_w})")

        # Unity expects heightmaps with the origin at the bottom-left.
        # Rasterio/NumPy arrays are top-left origin, so flip vertically.
        # If your tiles appear rotated 90°, also try transposing (uncomment the transpose line).
        tile_heightmap_to_write = np.flipud(tile_heightmap)
        # tile_heightmap_to_write = tile_heightmap_to_write.T  # uncomment if you need to swap axes

        # Write heightmap as uint16 little-endian
        filename_base = f"tile_{tx}_{ty}"
        bytes_path = tiles_height_out / (filename_base + ".bytes")

        # Write .bytes as little-endian uint16 (use the flipped/adjusted array)
        elev_le = tile_heightmap_to_write.astype('<u2')  # little-endian unsigned 16-bit
        with bytes_path.open("wb") as fh:
            fh.write(elev_le.tobytes())

        # Also write a GeoTIFF for this tile into a separate folder (store absolute elevation as float32)
        tiles_height_tif = out_root / "tiles_height_tif"
        ensure_dir(tiles_height_tif)
        tif_path = tiles_height_tif / (filename_base + ".tif")

        # Calculate tile-specific transform
        tile_left = bounds.left
        tile_right = bounds.left + (hm_w * pixel_width)
        tile_bottom = bounds.top - (hm_h * pixel_height)
        tile_top = bounds.top
        tile_transform = from_bounds(tile_left, tile_bottom, tile_right, tile_top, hm_w, hm_h)

        with rasterio.open(
            str(tif_path),
            "w",
            driver="GTiff",
            height=hm_h,
            width=hm_w,
            count=1,
            dtype="float32",
            crs=info["crs"],
            transform=tile_transform,
            nodata=dem_nodata if dem_nodata is not None else None,
            compress="lzw"
        ) as dst_tif:
            dst_tif.write(tile_elev_tif, 1)

        # Also write .raw int16 files into a separate folder
        tiles_height_raw = out_root / "tiles_height_raw"
        ensure_dir(tiles_height_raw)
        raw_path = tiles_height_raw / (filename_base + ".raw")
        with raw_path.open("wb") as fh2:
            fh2.write(elev_le.tobytes())

        # Convert RGB tif to png and store under tiles_rgb with same base name tile_x_y.png
        rgb_out_path = tiles_rgb_out / (filename_base + ".png")
        with rasterio.open(str(info["path"])) as src_rgb:
            # read up to 3 bands (common RGB)
            bands = []
            for b in (1, 2, 3):
                if b <= src_rgb.count:
                    arr = src_rgb.read(b)
                    bands.append(arr)
            if len(bands) == 0:
                raise RuntimeError(f"No bands found in {info['path']}")
            # If single band, replicate to RGB
            if len(bands) == 1:
                rgb_arr = np.stack([bands[0]]*3, axis=-1)
            else:
                rgb_arr = np.dstack(bands[:3])

            # Normalize if needed for uint16 -> 8bit
            if rgb_arr.dtype == np.uint16:
                rgb_arr = (rgb_arr // 256).astype(np.uint8)
            elif rgb_arr.dtype != np.uint8:
                mn = np.nanmin(rgb_arr)
                mx = np.nanmax(rgb_arr)
                if mx <= mn:
                    rgb_arr = np.zeros_like(rgb_arr, dtype=np.uint8)
                else:
                    scale = 255.0 / (mx - mn)
                    rgb_arr = ((rgb_arr - mn) * scale).clip(0,255).astype(np.uint8)

            # If the source tile is smaller than its declared tile size, pad it (edge replicate)
            src_h, src_w = rgb_arr.shape[0], rgb_arr.shape[1]
            tgt_w = int(info["width"])
            tgt_h = int(info["height"])

            if (src_w, src_h) == (tgt_w, tgt_h):
                im = Image.fromarray(rgb_arr)
                im.save(str(rgb_out_path))
            else:
                # compute tile index expected position (tx, ty already computed above)
                expected_left = uniq_lefts[tx]
                expected_top = uniq_tops[ty]
                # pixel offsets inside target canvas where the source should be placed
                offset_x = int(round((bounds.left - expected_left) / pixel_width))
                offset_y = int(round((expected_top - bounds.top) / pixel_height))

                # clamp offsets to valid ranges
                offset_x = max(0, min(offset_x, tgt_w))
                offset_y = max(0, min(offset_y, tgt_h))

                # create target canvas and blit source at computed offset
                canvas = np.zeros((tgt_h, tgt_w, 3), dtype=np.uint8)

                # compute copy extents (ensure we don't overflow)
                copy_w = min(src_w, tgt_w - offset_x)
                copy_h = min(src_h, tgt_h - offset_y)
                if copy_w <= 0 or copy_h <= 0:
                    # fallback: center the source if placement is invalid
                    cx = max(0, (tgt_w - src_w) // 2)
                    cy = max(0, (tgt_h - src_h) // 2)
                    copy_w = min(src_w, tgt_w - cx)
                    copy_h = min(src_h, tgt_h - cy)
                    canvas[cy:cy+copy_h, cx:cx+copy_w] = rgb_arr[0:copy_h, 0:copy_w]
                else:
                    canvas[offset_y:offset_y+copy_h, offset_x:offset_x+copy_w] = rgb_arr[0:copy_h, 0:copy_w]

                # replicate left/right columns of the pasted area
                if offset_x > 0:
                    canvas[offset_y:offset_y+copy_h, 0:offset_x] = np.repeat(
                        canvas[offset_y:offset_y+copy_h, offset_x:offset_x+1], offset_x, axis=1)
                right_start = offset_x + copy_w
                if right_start < tgt_w:
                    canvas[offset_y:offset_y+copy_h, right_start:tgt_w] = np.repeat(
                        canvas[offset_y:offset_y+copy_w, right_start-1:right_start], tgt_w-right_start, axis=1)

                # replicate top/bottom rows for entire canvas
                if offset_y > 0:
                    canvas[0:offset_y, :] = np.repeat(canvas[offset_y:offset_y+1, :], offset_y, axis=0)
                bottom_start = offset_y + copy_h
                if bottom_start < tgt_h:
                    canvas[bottom_start:tgt_h, :] = np.repeat(canvas[bottom_start-1:bottom_start, :], tgt_h-bottom_start, axis=0)

                im = Image.fromarray(canvas)
                im.save(str(rgb_out_path))

        # Calculate ground dimensions in meters
        center_lat = (bounds.top + bounds.bottom) / 2.0
        lon_diff = bounds.right - bounds.left
        lat_diff = bounds.top - bounds.bottom
        ground_width, ground_height = degrees_to_meters(center_lat, lon_diff, lat_diff)

        tile_records.append({
            "tile_x": int(tx),
            "tile_y": int(ty),
            "texture": str((tiles_rgb_out / (filename_base + ".png")).as_posix()).replace('/', '\\'),
            "heightmap": str((tiles_height_out / (filename_base + ".bytes")).as_posix()).replace('/', '\\'),
            "texture_width": tex_w,
            "texture_height": tex_h,
            "heightmap_width": hm_w,
            "heightmap_height": hm_h,
            "tile_max_height": float(global_height_range),
            "ground_width_meters": float(ground_width),
            "ground_height_meters": float(ground_height)
        })

    # assemble final json
    out_json = {
        "global_min_elevation": float(global_min),
        "global_max_elevation": float(global_max),
        "global_max_height_after_scale": float(global_height_range),
        "global_nodata": 0,
        "tiles": sorted(tile_records, key=lambda t: (t["tile_y"], t["tile_x"]))
    }

    json_path = out_root / "tile_metadata.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(out_json, f, indent=4)

    print("Done.")
    print("Output written to:", out_root)
    print("tile count:", len(tile_records))

if __name__ == "__main__":
    main()
    
    system = platform.system()
    if system == "Windows":
        # Works in Windows terminal, PowerShell, CMD
        print('\007')  # Alternative bell character
        os.system('rundll32 user32.dll,MessageBeep')  # Windows system beep
    elif system == "Darwin":  # macOS
        os.system('afplay /System/Library/Sounds/Glass.aiff')
    else:  # Linux
        os.system('paplay /usr/share/sounds/freedesktop/stereo/complete.oga 2>/dev/null || beep 2>/dev/null || echo "\a"')
    
    print("✓ PROCESSING COMPLETE!")