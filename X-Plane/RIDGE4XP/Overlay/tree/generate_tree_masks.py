#!/usr/bin/env python3
"""
Generates tree placement masks from NDVI tiles.
Creates binary masks and tree position data for Unity.

Usage:
    python generate_tree_masks.py <unity_output_folder> [options]

Example:
    python generate_tree_masks.py ./unity_output --threshold 0.55 --density 0.1
    python generate_tree_masks.py ./unity_output --threshold 0.4 --invert  # Ters mantık
"""

import sys
import json
import argparse
from pathlib import Path
import numpy as np
from PIL import Image

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def generate_masks(unity_output: Path, threshold=0.55, density=0.05, min_ndvi=0.4, invert=False, band=1, low_is_tree=False, seed=42):
    """
    Generate tree masks from NDVI tiles.
    Only creates binary masks (no positions JSON).
    """
    np.random.seed(seed)
    
    tiles_ndvi_dir = unity_output / "tiles_ndvi"
    tiles_trees_out = unity_output / "tiles_trees"
    
    ensure_dir(tiles_trees_out)
    
    if not tiles_ndvi_dir.exists():
        print(f"Error: tiles_ndvi folder not found at {tiles_ndvi_dir}")
        raise SystemExit(1)
    
    ndvi_tifs = sorted(tiles_ndvi_dir.glob("*.tif"))
    
    if not ndvi_tifs:
        print(f"Error: No NDVI tiles found in {tiles_ndvi_dir}")
        raise SystemExit(1)
    
    print(f"Found {len(ndvi_tifs)} NDVI tiles")
    print(f"Settings:")
    print(f"  Tree threshold: {threshold}")
    print(f"  Invert mask: {invert}")
    print(f"  Low is tree: {low_is_tree}")
    print()
    
    output_mask_paths = []

    for ndvi_path in ndvi_tifs:
        tile_name = ndvi_path.stem
        
        # Load NDVI data
        try:
            import rasterio
            with rasterio.open(str(ndvi_path)) as src:
                band_to_read = min(band, src.count)
                ndvi_data = src.read(band_to_read).astype(np.float32)
        except:
            img = Image.open(str(ndvi_path))
            ndvi_data = np.array(img).astype(np.float32)
            if ndvi_data.max() > 1:
                ndvi_data = ndvi_data / 255.0
        
        # Create tree mask based on mode
        if low_is_tree:
            # Low NDVI = trees (inverted interpretation)
            tree_mask = (ndvi_data <= threshold).astype(np.uint8)
        else:
            # Normal: High NDVI = trees
            tree_mask = (ndvi_data >= threshold).astype(np.uint8)
        
        # Invert if requested
        if invert:
            tree_mask = 1 - tree_mask
        
        tree_pixels = np.sum(tree_mask)
        total_pixels = ndvi_data.size
        
        # Save binary mask
        mask_img = Image.fromarray(tree_mask * 255)
        mask_path = tiles_trees_out / f"{tile_name}_mask.png"
        mask_img.save(str(mask_path))
        output_mask_paths.append(mask_path)
        
        print(f"  ✓ {tile_name}: ({100*tree_pixels/total_pixels:.1f}% tree area)")
    
    print()
    print("=" * 50)
    print(f"✓ Tree masks generated!")
    print(f"  Output: {tiles_trees_out}")
    print("=" * 50)

    # Return the first mask generated (usually there's only one in this context)
    return output_mask_paths[0] if output_mask_paths else None


# def generate_tree_positions(mask: np.ndarray, density: float, tile_x: int, tile_y: int, 
#                             tile_width: int, tile_height: int) -> list:
#     """
#     Generate tree positions from binary mask.
#     Returns list of normalized positions (0-1 range within tile).
#     """
#     positions = []
    
#     # Find all pixels where trees can be placed
#     tree_pixels = np.argwhere(mask > 0)
    
#     if len(tree_pixels) == 0:
#         return positions
    
#     # Sample based on density
#     num_trees = int(len(tree_pixels) * density)
#     if num_trees == 0 and len(tree_pixels) > 0:
#         num_trees = 1
    
#     # Random sampling
#     if num_trees < len(tree_pixels):
#         indices = np.random.choice(len(tree_pixels), num_trees, replace=False)
#         selected_pixels = tree_pixels[indices]
#     else:
#         selected_pixels = tree_pixels
    
#     # Convert to normalized positions
#     for py, px in selected_pixels:
#         norm_x = px / mask.shape[1]
#         norm_y = py / mask.shape[0]
        
#         # Add small random offset
#         norm_x += np.random.uniform(-0.5, 0.5) / mask.shape[1]
#         norm_y += np.random.uniform(-0.5, 0.5) / mask.shape[0]
        
#         norm_x = max(0, min(1, norm_x))
#         norm_y = max(0, min(1, norm_y))
        
#         positions.append({
#             "x": float(norm_x),
#             "y": float(norm_y)
#         })
    
#     return positions

def main():
    parser = argparse.ArgumentParser(description='Generate tree masks from NDVI tiles')
    parser.add_argument('unity_output', type=str, help='Path to unity_output folder')
    parser.add_argument('--threshold', type=float, default=0.55, 
                        help='NDVI threshold for tree detection (default: 0.55)')
    parser.add_argument('--density', type=float, default=0.05,
                        help='Tree density (default: 0.05)')
    parser.add_argument('--min-ndvi', type=float, default=0.4,
                        help='Minimum NDVI for any vegetation (default: 0.4)')
    parser.add_argument('--seed', type=int, default=42,
                        help='Random seed (default: 42)')
    parser.add_argument('--invert', action='store_true',
                        help='Invert mask - use when trees appear in wrong places')
    parser.add_argument('--band', type=int, default=1,
                        help='Which band to use from NDVI file (default: 1)')
    parser.add_argument('--low-is-tree', action='store_true',
                        help='Low NDVI values = trees (inverted NDVI interpretation)')
    
    args = parser.parse_args()
    
    unity_output = Path(args.unity_output)
    
    generate_masks(
        unity_output=unity_output,
        threshold=args.threshold,
        density=args.density,
        min_ndvi=args.min_ndvi,
        invert=args.invert,
        band=args.band,
        low_is_tree=args.low_is_tree,
        seed=args.seed
    )

if __name__ == "__main__":
    main()
