import os
from pathlib import Path
import json
import shutil

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
        print("ERROR: local_data_root not configured for building overlay generation.")
        return

    data_root = Path(tile.local_data_root)
    tile_data_dir = data_root / str(lat) / str(lon)

    # Check for inputs
    rgb_path = tile_data_dir / "rgb.tif"
    if not rgb_path.exists():
        print(f"Error: Required rgb.tif not found at {rgb_path}")
        return

    # Prepare temp directory in ./tmp/
    base_tmp_dir = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tmp"))
    base_tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = base_tmp_dir / f"building_gen_{lat}_{lon}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    model_path = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", model_name)) # !!!!!!!!!!!

    # confidence = 0.5  # Adjust as needed # !!!!!!!!!!
    json_path = temp_dir / "buildings.json"

    print(f"--- Starting Building Overlay Generation for Tile {lat}/{lon} ---")


    try:
        # Step 1: Detect buildings and generate overlay
        detector = BuildingDetector(model_path=model_path)

        print(f"Processing {rgb_path} with confidence threshold {confidence}...")

        detector.process_image(rgb_path, confidence=confidence)

        with open(json_path, 'w') as f:
            json.dump({"tileBuildingsList": detector.json_list}, f, indent=2)
        print(f"\nDone. JSON saved to {json_path}")
        print(f"✓ Building overlay generated at {temp_dir}")
        # Step 2: Export to X-Plane DSF format
        build_dir = Path(tile.build_dir)
        building_out_dir = build_dir / "Buildings"
        building_out_dir.mkdir(parents=True, exist_ok=True)
        
        output_dir = building_out_dir
        package_name = Path(output_dir).name
        # xplane_root = None  # Not needed for building overlay, as we only export the DSF text file
        # gsd = 0.5  # Ground sample distance for export, adjust as needed
        # exclude_autogen = True  # Exclude autogen buildings from export
        # min_area_m2 = 25.0  # Minimum building area in square meters to include in export

        export(
            json_path       = json_path,
            out_dir         = output_dir,
            package_name    = package_name,
            xplane_root     = xplane_root,
            gsd             = gsd,
            exclude_autogen = exclude_autogen,
            min_area_m2     = min_area_m2,
        )
    except Exception as e:
        print(f"Error during building overlay generation: {e}")
        return
    
    # Step 3: Clean up temp files
    cleaning_level = getattr(tile, 'cleaning_level', 1)
    if cleaning_level >= 2:
        print("Cleaning up temporary building generation files...")
        try:
            shutil.rmtree(temp_dir)
            print("Cleanup successful.")
        except Exception as e:
            print(f"Error during cleanup: {e}")