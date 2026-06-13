#!/usr/bin/env python3
"""
Crops NDVI TIFF to match a single RGB GeoTIFF bounds.

Usage: 
    python crop_and_tile_ndvi.py <ndvi_file> <rgb_geotiff> <output_folder>

Example:
    python crop_and_tile_ndvi.py ndvi.tiff rgb_image.tif ./unity_output
"""

import sys
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from PIL import Image

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def crop_ndvi(ndvi_path: Path, rgb_tif_path: Path, unity_output: Path) -> Path:
    """
    Crops NDVI TIFF to match the given RGB GeoTIFF, outputting just a PNG file.
    Returns the path to the output PNG.
    """
    # Output path
    tiles_ndvi_out = unity_output / "tiles_ndvi"
    ensure_dir(tiles_ndvi_out)

    # Validate inputs
    if not ndvi_path.exists():
        print(f"Error: NDVI file not found at {ndvi_path}")
        raise SystemExit(1)
        
    if not rgb_tif_path.exists():
        print(f"Error: RGB GeoTIFF not found at {rgb_tif_path}")
        raise SystemExit(1)

    print(f"Opening NDVI file: {ndvi_path}")
    print(f"Aligning to RGB GeoTIFF: {rgb_tif_path}")

    # Read reference tile properties
    fallback_crs = rasterio.crs.CRS.from_epsg(4326) # Setup WGS84 fallback

    with rasterio.open(str(rgb_tif_path)) as ref_src:
        ref_crs = ref_src.crs or fallback_crs
        ref_transform = ref_src.transform
        ref_width = ref_src.width
        ref_height = ref_src.height
        
        print("\n--- DEBUG INFO ---")
        print(f"RGB CRS:     {ref_crs}")
        print(f"RGB Bounds:  {ref_src.bounds}")
    
    # Create NDVI array matching reference dimensions
    ndvi_cropped = np.zeros((ref_height, ref_width), dtype=np.float32)
    
    # Reproject NDVI to this grid
    with rasterio.open(str(ndvi_path)) as ndvi_src:
        src_crs = ndvi_src.crs or fallback_crs
        
        print(f"NDVI CRS:    {src_crs}")
        print(f"NDVI Bounds: {ndvi_src.bounds}")
        print("------------------\n")

        reproject(
            source=rasterio.band(ndvi_src, 1),
            destination=ndvi_cropped,
            src_transform=ndvi_src.transform,
            src_crs=src_crs,
            dst_transform=ref_transform,
            dst_crs=ref_crs,
            resampling=Resampling.bilinear
        )
    
    
    out_name = "ndvi_cropped"
    ndvi_out_path = tiles_ndvi_out / f"{out_name}.tif"
    
    with rasterio.open(
        str(ndvi_out_path),
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
        dst.write(ndvi_cropped, 1)

    # Calculate stats for normalization
    ndvi_min = float(np.nanmin(ndvi_cropped))
    ndvi_max = float(np.nanmax(ndvi_cropped))
    
    # Save as PNG
    if ndvi_max > ndvi_min:
        ndvi_norm = ((ndvi_cropped - ndvi_min) / (ndvi_max - ndvi_min) * 255).astype(np.uint8)
    else:
        ndvi_norm = np.zeros_like(ndvi_cropped, dtype=np.uint8)
    
    ndvi_png_path = tiles_ndvi_out / f"{out_name}.png"
    im = Image.fromarray(ndvi_norm)
    im.save(str(ndvi_png_path))
    
    print(f"\n{'='*50}")
    print(f"✓ NDVI image cropped successfully!")
    print(f"  Dimensions: {ref_width}x{ref_height}")
    print(f"  Output: {ndvi_out_path}")
    print(f"{'='*50}")

    return ndvi_out_path

def main():
    if len(sys.argv) < 4:
        print("Usage: python crop_and_tile_ndvi.py <ndvi_file> <rgb_geotiff> <output_folder>")
        raise SystemExit(1)

    ndvi_path = Path(sys.argv[1])
    rgb_tif_path = Path(sys.argv[2])
    unity_output = Path(sys.argv[3])
    
    crop_ndvi(ndvi_path, rgb_tif_path, unity_output)

if __name__ == "__main__":
    main()
