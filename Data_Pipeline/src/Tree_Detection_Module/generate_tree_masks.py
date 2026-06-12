#!/usr/bin/env python3

import sys
import json
import argparse
from pathlib import Path
import numpy as np
from PIL import Image

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def generate_tree_positions(mask: np.ndarray, density: float, tile_x: int, tile_y: int, 
                            tile_width: int, tile_height: int) -> list:
    positions = []
    
    tree_pixels = np.argwhere(mask > 0)
    
    if len(tree_pixels) == 0:
        return positions
    
    num_trees = int(len(tree_pixels) * density)
    if num_trees == 0 and len(tree_pixels) > 0:
        num_trees = 1
    
    if num_trees < len(tree_pixels):
        indices = np.random.choice(len(tree_pixels), num_trees, replace=False)
        selected_pixels = tree_pixels[indices]
    else:
        selected_pixels = tree_pixels
    
    for py, px in selected_pixels:
        norm_x = px / mask.shape[1]
        norm_y = py / mask.shape[0]
        
        norm_x += np.random.uniform(-0.5, 0.5) / mask.shape[1]
        norm_y += np.random.uniform(-0.5, 0.5) / mask.shape[0]
        
        norm_x = max(0, min(1, norm_x))
        norm_y = max(0, min(1, norm_y))
        
        positions.append({
            "x": float(norm_x),
            "y": float(norm_y)
        })
    
    return positions

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
    
    np.random.seed(args.seed)
    
    unity_output = Path(args.unity_output)
    tiles_ndvi_dir = unity_output / "tiles_ndvi"
    tiles_trees_out = unity_output / "tiles_trees"
    
    ensure_dir(tiles_trees_out)
    
    if not tiles_ndvi_dir.exists():
        print(f"Error: tiles_ndvi folder not found at {tiles_ndvi_dir}")
        raise SystemExit(1)
    
    ndvi_tifs = sorted(tiles_ndvi_dir.glob("tile_*.tif"))
    
    if not ndvi_tifs:
        print(f"Error: No NDVI tiles found in {tiles_ndvi_dir}")
        raise SystemExit(1)
    
    print(f"Found {len(ndvi_tifs)} NDVI tiles")
    print(f"Settings:")
    print(f"  Tree threshold: {args.threshold}")
    print(f"  Tree density: {args.density}")
    print(f"  Invert mask: {args.invert}")
    print(f"  Low is tree: {args.low_is_tree}")
    print(f"  Band: {args.band}")
    print()
    
    all_tree_data = []
    total_trees = 0
    
    for ndvi_path in ndvi_tifs:
        tile_name = ndvi_path.stem
        parts = tile_name.split("_")
        tile_x = int(parts[1])
        tile_y = int(parts[2])
        
        try:
            import rasterio
            with rasterio.open(str(ndvi_path)) as src:
                band_to_read = min(args.band, src.count)
                ndvi_data = src.read(band_to_read).astype(np.float32)
        except:
            img = Image.open(str(ndvi_path))
            ndvi_data = np.array(img).astype(np.float32)
            if ndvi_data.max() > 1:
                ndvi_data = ndvi_data / 255.0
        
        height, width = ndvi_data.shape
        
        if args.low_is_tree:
            tree_mask = (ndvi_data <= args.threshold).astype(np.uint8)
        else:
            tree_mask = (ndvi_data >= args.threshold).astype(np.uint8)
        
        if args.invert:
            tree_mask = 1 - tree_mask
        
        tree_pixels = np.sum(tree_mask)
        total_pixels = ndvi_data.size
        
        positions = generate_tree_positions(
            tree_mask, args.density, tile_x, tile_y, width, height
        )
        
        mask_img = Image.fromarray(tree_mask * 255)
        mask_path = tiles_trees_out / f"{tile_name}_mask.png"
        mask_img.save(str(mask_path))
        
        density_map = np.zeros_like(ndvi_data, dtype=np.uint8)
        if args.low_is_tree:
            normalized = 1.0 - ndvi_data
        else:
            normalized = ndvi_data
        normalized = np.clip(normalized, 0, 1)
        density_map = (normalized * 255).astype(np.uint8)
        
        density_path = tiles_trees_out / f"{tile_name}_density.png"
        Image.fromarray(density_map).save(str(density_path))
        
        tile_data = {
            "tile_name": tile_name,
            "tile_x": tile_x,
            "tile_y": tile_y,
            "width": width,
            "height": height,
            "tree_pixel_count": int(tree_pixels),
            "tree_pixel_percent": float(100 * tree_pixels / total_pixels),
            "ndvi_min": float(np.nanmin(ndvi_data)),
            "ndvi_max": float(np.nanmax(ndvi_data)),
            "ndvi_mean": float(np.nanmean(ndvi_data)),
            "tree_count": len(positions),
            "tree_positions": positions
        }
        
        all_tree_data.append(tile_data)
        total_trees += len(positions)
        
        print(f"  ✓ {tile_name}: {len(positions)} trees ({100*tree_pixels/total_pixels:.1f}% tree area)")
    
    output_json = {
        "settings": {
            "threshold": args.threshold,
            "density": args.density,
            "invert": args.invert,
            "low_is_tree": args.low_is_tree,
            "band": args.band,
            "seed": args.seed
        },
        "summary": {
            "total_tiles": len(all_tree_data),
            "total_trees": total_trees
        },
        "tiles": all_tree_data
    }
    
    json_path = tiles_trees_out / "tree_data.json"
    with open(json_path, "w") as f:
        json.dump(output_json, f, indent=2)
    
    positions_only = {}
    for tile in all_tree_data:
        positions_only[tile["tile_name"]] = tile["tree_positions"]
    
    positions_path = tiles_trees_out / "tree_positions.json"
    with open(positions_path, "w") as f:
        json.dump(positions_only, f)
    
    print()
    print("=" * 50)
    print(f"✓ Tree masks generated!")
    print(f"  Total trees: {total_trees}")
    print(f"  Output: {tiles_trees_out}")
    print("=" * 50)

if __name__ == "__main__":
    main()
