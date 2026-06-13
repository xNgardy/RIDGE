import os
from pathlib import Path
from Overlay.road.roads_to_xplane import process_roads_from_tif

def generate_road_overlay(tile):
    """
    Generates a road overlay package for a single given tile.
    Reads the 'rgb.tif' directly.
    """
    lat = tile.lat
    lon = tile.lon

    data_root = Path(tile.local_data_root)
    tile_data_dir = data_root / str(lat) / str(lon)

    # Directly pinpoint the rgb.tif for this singular tile
    rgb_path = tile_data_dir / "rgb.tif"
    if not rgb_path.exists():
        print(f"Error: Required rgb.tif not found at {rgb_path}")
        return

    print(f"--- Starting Road Overlay Generation for Tile {lat}/{lon} ---")

    # Target output structure (e.g. build_dir / "Roads")
    build_dir = Path(tile.build_dir)

    # Pass everything to our refactored function
    try:
        pack_dir = process_roads_from_tif(
            tif_path=str(rgb_path),
            output_dir=str(build_dir),
            scenery_name="Roads",
            skip_empty=skip_empty,
            no_exclude=no_exclude
        )
        if pack_dir:
            print(f"Road package generated at: {pack_dir}")
        else:
            print("Road generation concluded but no package was returned (possibly empty or encountered an error).")
    except Exception as e:
        print(f"Error during road overlay generation: {e}")
        return

    print(f"--- Finished Road Overlay Generation for Tile {lat}/{lon} ---")