import os
import shutil
from pathlib import Path

import O4_File_Names as FNAMES

from Overlay.tree.crop_ndvi import crop_ndvi
from Overlay.tree.generate_tree_masks import generate_masks
from Overlay.tree.export_xplane_forest_masks import export_forest_masks

def generate_tree_overlay(tile):
    """
    Generates a tree overlay DSF text file for a given tile.
    Requires ndvi.tif(f) and rgb.tif to be present in the local data root.
    """
    lat = tile.lat
    lon = tile.lon

    if not getattr(tile, 'local_data_root', None):
        print("ERROR: local_data_root not configured for tree mask generation.")
        return

    data_root = Path(tile.local_data_root)
    tile_data_dir = data_root / str(lat) / str(lon)

    # Check for inputs
    rgb_path = tile_data_dir / "rgb.tif"
    if not rgb_path.exists():
        print(f"Error: Required rgb.tif not found at {rgb_path}")
        return

    # Either ndvi.tif or ndvi.tiff
    ndvi_path = tile_data_dir / "ndvi.tif"
    if not ndvi_path.exists():
        ndvi_path = tile_data_dir / "ndvi.tiff"
        if not ndvi_path.exists():
            print(f"Error: Required ndvi.tif/tiff not found at {tile_data_dir}")
            return

    # Prepare temp directory in ./tmp/
    base_tmp_dir = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tmp"))
    base_tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = base_tmp_dir / f"tree_gen_{lat}_{lon}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    print(f"--- Starting Tree Overlay Generation for Tile {lat}/{lon} ---")

    # Step 1: Crop NDVI bounds
    try:
        ndvi_tif_path = crop_ndvi(ndvi_path, rgb_path, temp_dir)
    except Exception as e:
        print(f"Error during NDVI crop: {e}")
        return

    # Step 2: Generate Tree Masks
    try:
        mask_path = generate_masks(
            unity_output=temp_dir,
            threshold=threshold,
            density=density,
            min_ndvi=min_ndvi,
            invert=invert,
            band=band,
            low_is_tree=low_is_tree,
            seed=seed,
        )
    except Exception as e:
        print(f"Error during tree mask generation: {e}")
        return

    if not mask_path:
        print("Skipping export: No masks were generated.")
        return

    # Step 3: Export Forest Masks
    build_dir = Path(tile.build_dir)
    trees_out_dir = build_dir / "Trees"
    trees_out_dir.mkdir(parents=True, exist_ok=True)

    out_file = trees_out_dir / "Earth nav data" / FNAMES.round_latlon(lat, lon) / (FNAMES.short_latlon(lat, lon) + ".txt")
    try:
        export_forest_masks(
            mask_file=mask_path,
            rgb_tif=rgb_path,
            output_file=out_file,
            forest=forest,
            density=xplane_density,
            min_area_px=min_area_px,
            min_hole_area_px=min_hole_area_px,
            simplify_px=simplify_px,
            open_radius_px=open_radius_px,
            close_radius_px=close_radius_px,
            exclude_default_forests=not no_exclude_default_forests,
            exclude_objects=exclude_objects,
        )
    except Exception as e:
        print(f"Error during forest mask export: {e}")
        return

    print(f"--- Finished Tree Overlay Generation for Tile {lat}/{lon} ---")

    # Step 4: Cleanup
    cleaning_level = getattr(tile, 'cleaning_level', 1)
    if cleaning_level >= 2:
        print("Cleaning up temporary tree generation files...")
        try:
            shutil.rmtree(temp_dir)
            print("Cleanup successful.")
        except Exception as e:
            print(f"Error during cleanup: {e}")
