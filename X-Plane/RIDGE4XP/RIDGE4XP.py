#!/usr/bin/env python3
"""
Ortho4XP - Local data only mode (CLI only, no GUI)
Simple command-line interface for generating X-Plane terrain from local data.
"""
import sys
import os
import traceback

Ortho4XP_dir = '..' if getattr(sys, 'frozen', False) else '.'
sys.path.append(os.path.join(Ortho4XP_dir, 'src'))
any_missing = False

import O4_File_Names as FNAMES
import O4_UI_Utils as UI
import O4_Config_Utils as CFG
import O4_Vector_Map as VMAP
import O4_Mesh_Utils as MESH
import O4_Mask_Utils as MASK
import O4_Tile_Utils as TILE

def main():
    """Main entry point for CLI-only operation."""
    if not os.path.isdir(FNAMES.Utils_dir):
        print("ERROR: Missing", FNAMES.Utils_dir, "directory. Check your install.")
        sys.exit(1)

    # # Ensure required directories exist
    # for directory in (FNAMES.Mask_dir, FNAMES.OSM_dir, FNAMES.Elevation_dir,
    #                   FNAMES.Geotiff_dir, FNAMES.Tile_dir, FNAMES.Tmp_dir):
    #     if not os.path.isdir(directory):
    #         any_missing = True
    #         print(f"MISSING: {directory}")

    # if any_missing:
    #     print("ERROR: One or more required directories are missing. Please create them and add the necessary data.")
    #     sys.exit(1)

    # Parse command line arguments
    if len(sys.argv) < 3:
        print("Usage: python Ortho4XP.py <lat> <lon>")
        print("  Uses existing .cfg file in tile directory")
        sys.exit(1)

    try:
        lat = int(sys.argv[1])
        lon = int(sys.argv[2])
    except ValueError:
        print("ERROR: lat and lon must be integers")
        sys.exit(1)

    # Load or create tile config
    try:
        tile = CFG.Tile(lat, lon, '')
        result = tile.read_from_config()
        if not result:
            print(f"WARNING: No config file found for tile {lat}/{lon}, using defaults")

        # Set local data root from config
        if tile.local_data_root:
            UI.local_data_root = tile.local_data_root
            print(f"Using local data from: {tile.local_data_root}")
        else:
            print("ERROR: local_data_root not configured in tile config file")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: Could not load tile config: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Run pipeline
    try:
        print(f"Processing tile {lat}/{lon}...")
        print("  Building vector map...")
        VMAP.build_poly_file(tile)
        print("  Building mesh...")
        MESH.build_mesh(tile)
        print("  Building masks...")
        MASK.build_masks(tile)
        print("  Building tile...")
        TILE.build_tile(tile)
        print(f"✓ Tile {lat}/{lon} complete!")
        return 0
    except Exception as e:
        print(f"ERROR during tile generation: {e}")
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
 
        
