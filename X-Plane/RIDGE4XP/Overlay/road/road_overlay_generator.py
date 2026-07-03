import os
from pathlib import Path
import O4_UI_Utils as UI
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

    base_tmp_dir = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tmp"))
    temp_dir = base_tmp_dir / f"road_gen_{lat}_{lon}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Directly pinpoint the rgb.tif for this singular tile
    rgb_path = tile_data_dir / "rgb.tif"
    if not rgb_path.exists():
        UI.lvprint(1, f"Error: Required rgb.tif not found at {rgb_path}")
        return

    UI.lvprint(1, f"--- Starting Road Overlay Generation for Tile {lat}/{lon} ---")

    # Target output structure (e.g. build_dir / "Roads")
    build_dir = Path(tile.build_dir)

    polygon_dir = base_tmp_dir / f"polygons_{lat}_{lon}"
    polygon_dir.mkdir(parents=True, exist_ok=True)

    # Pass everything to our refactored function
    try:
        pack_dir = process_roads_from_tif(
            tif_path=str(rgb_path),
            output_dir=str(build_dir),
            polygon_dir=str(polygon_dir),
            scenery_name="Roads",
            skip_empty=skip_empty,
            no_exclude=no_exclude
        )
        if pack_dir:
            UI.lvprint(1, f"Road package generated at: {pack_dir}")
        else:
            UI.lvprint(1, "Road generation concluded but no package was returned (possibly empty or encountered an error).")
    except Exception as e:
        UI.lvprint(1, f"Error during road overlay generation: {e}")
        return

    UI.lvprint(1, f"--- Finished Road Overlay Generation for Tile {lat}/{lon} ---")