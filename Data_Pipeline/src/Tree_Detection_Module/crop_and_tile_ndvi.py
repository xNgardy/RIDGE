#!/usr/bin/env python3
"""
Crops and tiles NDVI TIFF to match RGB tile grid structure.
Uses tiles_height_tif as reference (they have proper georeferencing).

Usage: 
    python crop_and_tile_ndvi_fixed.py <ndvi_file> <unity_output_folder>

Example:
    python crop_and_tile_ndvi_fixed.py ndvi_aligned_to_rgb.tiff ./unity_output
"""

import sys
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds
from PIL import Image

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def main():
    if len(sys.argv) < 3:
        print("Usage: python crop_and_tile_ndvi_fixed.py <ndvi_file> <unity_output_folder>")
        print("Example: python crop_and_tile_ndvi_fixed.py ndvi_aligned_to_rgb.tiff ./unity_output")
        raise SystemExit(1)

    ndvi_path = Path(sys.argv[1])
    unity_output = Path(sys.argv[2])
    
    # Paths
    tile_metadata_path = unity_output / "tile_metadata.json"
    tiles_height_tif_dir = unity_output / "tiles_height_tif"  # GeoTIFF reference
    tiles_ndvi_out = unity_output / "tiles_ndvi"
    
    ensure_dir(tiles_ndvi_out)

    # Validate inputs
    if not ndvi_path.exists():
        print(f"Error: NDVI file not found at {ndvi_path}")
        raise SystemExit(1)
        
    if not tile_metadata_path.exists():
        print(f"Error: tile_metadata.json not found at {tile_metadata_path}")
        raise SystemExit(1)
        
    if not tiles_height_tif_dir.exists():
        print(f"Error: tiles_height_tif folder not found at {tiles_height_tif_dir}")
        print("Please run tiler.py first to generate height tiles.")
        raise SystemExit(1)

    # Load tile metadata
    print("Loading tile metadata...")
    with open(tile_metadata_path, "r") as f:
        metadata = json.load(f)
    
    print(f"Found {len(metadata['tiles'])} tiles in metadata")

    # Open NDVI file
    print(f"Opening NDVI file: {ndvi_path}")
    with rasterio.open(str(ndvi_path)) as ndvi_src:
        ndvi_crs = ndvi_src.crs
        ndvi_bounds = ndvi_src.bounds
        print(f"  NDVI size: {ndvi_src.width}x{ndvi_src.height}")
        print(f"  NDVI CRS: {ndvi_crs}")
        print(f"  NDVI bounds: {ndvi_bounds}")
        print(f"  NDVI bands: {ndvi_src.count}")

    print("\nProcessing NDVI tiles...")
    ndvi_stats = []
    processed = 0
    skipped = 0

    # Process each tile
    for tile_info in metadata['tiles']:
        tx = tile_info['tile_x']
        ty = tile_info['tile_y']
        tile_name = f"tile_{tx}_{ty}"
        
        # Get reference GeoTIFF from tiles_height_tif
        ref_tif_path = tiles_height_tif_dir / f"{tile_name}.tif"
        
        if not ref_tif_path.exists():
            print(f"  ⚠ Skipping {tile_name}: reference TIF not found")
            skipped += 1
            continue
        
        # Read reference tile properties
        with rasterio.open(str(ref_tif_path)) as ref_src:
            ref_bounds = ref_src.bounds
            ref_crs = ref_src.crs
            ref_transform = ref_src.transform
            ref_width = ref_src.width
            ref_height = ref_src.height
        
        # Create NDVI tile matching reference dimensions
        ndvi_tile = np.zeros((ref_height, ref_width), dtype=np.float32)
        
        # Reproject NDVI to this tile's grid
        with rasterio.open(str(ndvi_path)) as ndvi_src:
            reproject(
                source=rasterio.band(ndvi_src, 1),
                destination=ndvi_tile,
                src_transform=ndvi_src.transform,
                src_crs=ndvi_src.crs,
                dst_transform=ref_transform,
                dst_crs=ref_crs,
                resampling=Resampling.bilinear
            )
        
        # Save tile as GeoTIFF (float32)
        ndvi_tile_path = tiles_ndvi_out / f"{tile_name}.tif"
        
        with rasterio.open(
            str(ndvi_tile_path),
            "w",
            driver="GTiff",
            height=ref_height,
            width=ref_width,
            count=1,
            dtype="float32",
            crs=ref_crs,
            transform=ref_transform,
            compress="lzw"
        ) as dst:
            dst.write(ndvi_tile, 1)
        
        # Calculate stats
        ndvi_min = float(np.nanmin(ndvi_tile))
        ndvi_max = float(np.nanmax(ndvi_tile))
        ndvi_mean = float(np.nanmean(ndvi_tile))
        
        # Save as PNG preview (normalized to 0-255, colorized)
        if ndvi_max > ndvi_min:
            ndvi_norm = ((ndvi_tile - ndvi_min) / (ndvi_max - ndvi_min) * 255).astype(np.uint8)
        else:
            ndvi_norm = np.zeros_like(ndvi_tile, dtype=np.uint8)
        
        ndvi_png_path = tiles_ndvi_out / f"{tile_name}.png"
        im = Image.fromarray(ndvi_norm)
        im.save(str(ndvi_png_path))
        
        # Also save a colorized version (green gradient)
        colorized = np.zeros((ref_height, ref_width, 3), dtype=np.uint8)
        # Red to Green gradient based on NDVI
        colorized[:, :, 0] = (255 - ndvi_norm).astype(np.uint8)  # Red (low NDVI)
        colorized[:, :, 1] = ndvi_norm  # Green (high NDVI)
        colorized[:, :, 2] = 0  # Blue
        
        ndvi_color_path = tiles_ndvi_out / f"{tile_name}_color.png"
        im_color = Image.fromarray(colorized)
        im_color.save(str(ndvi_color_path))
        
        ndvi_stats.append({
            "tile": tile_name,
            "tile_x": tx,
            "tile_y": ty,
            "min": ndvi_min,
            "max": ndvi_max,
            "mean": ndvi_mean,
            "tif_path": str(ndvi_tile_path),
            "png_path": str(ndvi_png_path)
        })
        
        processed += 1
        print(f"  ✓ {tile_name}: NDVI range [{ndvi_min:.4f}, {ndvi_max:.4f}], mean: {ndvi_mean:.4f}")

    # Save statistics
    stats_path = tiles_ndvi_out / "ndvi_stats.json"
    with open(stats_path, "w") as f:
        json.dump({
            "global_ndvi_min": min(s["min"] for s in ndvi_stats) if ndvi_stats else 0,
            "global_ndvi_max": max(s["max"] for s in ndvi_stats) if ndvi_stats else 0,
            "tiles": ndvi_stats
        }, f, indent=2)
    
    print(f"\n{'='*50}")
    print(f"✓ NDVI tiles processed successfully!")
    print(f"  Output directory: {tiles_ndvi_out}")
    print(f"  Tiles created: {processed}")
    print(f"  Tiles skipped: {skipped}")
    print(f"  Stats saved to: {stats_path}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
