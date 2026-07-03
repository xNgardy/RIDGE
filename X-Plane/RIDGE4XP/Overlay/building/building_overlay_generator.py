import os
from pathlib import Path
import json
import shutil
import O4_UI_Utils as UI
from Overlay.building.Ramp_Building_Detector_WGS84 import BuildingDetector
from Overlay.building.XPlaneExporter import export

def generate_building_overlay(tile):
    """
    Generates a building overlay DSF text file for a given tile.
    Requires rgb.tif to be present in the local data root.
    """
    lat = tile.lat
    lon = tile.lon

    if not getattr(tile, 'local_data_root', None):
        UI.lvprint(1, "ERROR: local_data_root not configured for building overlay generation.")
        return

    data_root = Path(tile.local_data_root)
    tile_data_dir = data_root / str(lat) / str(lon)

    # Check for inputs
    rgb_path = tile_data_dir / "rgb.tif"
    if not rgb_path.exists():
        UI.lvprint(1, f"Error: Required rgb.tif not found at {rgb_path}")
        return

    # Prepare temp directory in ./tmp/
    base_tmp_dir = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tmp"))
    base_tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = base_tmp_dir / f"building_gen_{lat}_{lon}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    model_path = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", model_name))

    json_path = temp_dir / "buildings.json"

    UI.lvprint(1, f"--- Starting Building Overlay Generation for Tile {lat}/{lon} ---")


    try:
        # Step 1: Detect buildings and generate overlay
        detector = BuildingDetector(model_path=model_path)

        UI.lvprint(1, f"Processing {rgb_path} with confidence threshold {confidence}...")

        detector.process_image(rgb_path, confidence=confidence)

        with open(json_path, 'w') as f:
            json.dump({"tileBuildingsList": detector.json_list}, f, indent=2)
        UI.lvprint(1, f"\nDone. JSON saved to {json_path}")
        UI.lvprint(1, f"✓ Building overlay generated at {temp_dir}")
        # Step 2: Export to X-Plane DSF format
        build_dir = Path(tile.build_dir)
        building_out_dir = build_dir / "Buildings"
        building_out_dir.mkdir(parents=True, exist_ok=True)
        
        output_dir = building_out_dir
        package_name = Path(output_dir).name

        polygon_dir = base_tmp_dir / f"polygons_{lat}_{lon}"
        polygon_dir.mkdir(parents=True, exist_ok=True)

        export(
            json_path       = json_path,
            out_dir         = output_dir,
            package_name    = package_name,
            xplane_root     = xplane_root,
            gsd             = gsd,
            exclude_autogen = exclude_autogen,
            min_area_m2     = min_area_m2,
            polygon_dir     = polygon_dir,
        )
    except Exception as e:
        UI.lvprint(1, f"Error during building overlay generation: {e}")
        return
    
    # Step 3: Clean up temp files
    cleaning_level = getattr(tile, 'cleaning_level', 1)
    if cleaning_level >= 2:
        UI.lvprint(1, "Cleaning up temporary building generation files...")
        try:
            shutil.rmtree(temp_dir)
            UI.lvprint(1, "Cleanup successful.")
        except Exception as e:
            UI.lvprint(1, f"Error during cleanup: {e}")