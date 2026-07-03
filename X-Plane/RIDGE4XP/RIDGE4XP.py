#!/usr/bin/env python3
"""
RIDGE4XP - Local data only mode (CLI only, no GUI)
Simple command-line interface for generating X-Plane terrain from local data.
"""
import shutil
import sys
import os
import traceback

RIDGE4XP_dir = '..' if getattr(sys, 'frozen', False) else '.'
sys.path.append(os.path.join(RIDGE4XP_dir, 'src'))
any_missing = False

import O4_File_Names as FNAMES
import O4_UI_Utils as UI
import O4_Config_Utils as CFG
import O4_Vector_Map as VMAP
import O4_Mesh_Utils as MESH
import O4_Mask_Utils as MASK
import O4_Tile_Utils as TILE
import Overlay.tree.tree_overlay_generator as TREE
import Overlay.building.building_overlay_generator as BUILDING
import Overlay.road.road_overlay_generator as ROAD
import Overlay.build_overlay_dsf as CSTM_OVL

def main():
    """Main entry point for CLI-only operation."""
    if not os.path.isdir(FNAMES.Utils_dir):
        UI.lvprint(1, "ERROR: Missing", FNAMES.Utils_dir, "directory. Check your install.")
        sys.exit(1)

    if not os.path.isdir(FNAMES.Data_dir):
        UI.lvprint(1, "ERROR: Missing", FNAMES.Data_dir, "directory. Check your install.")
        sys.exit(1)

    # Parse command line arguments
    if len(sys.argv) < 3:
        UI.lvprint(1, "Usage: python RIDGE4XP.py <lat> <lon>")
        UI.lvprint(1, "  Uses existing .cfg file in tile directory")
        sys.exit(1)

    try:
        lat = int(sys.argv[1])
        lon = int(sys.argv[2])
    except ValueError:
        UI.lvprint(1, "ERROR: lat and lon must be integers")
        sys.exit(1)

    # Load or create tile config
    try:
        tile = CFG.Tile(lat, lon, '')
        result = tile.read_from_config()
        if not result:
            UI.lvprint(1, f"WARNING: No config file found for tile {lat}/{lon}, using defaults")

        # Set local data root from config
        if tile.local_data_root:
            UI.local_data_root = tile.local_data_root
            UI.lvprint(1, f"Using local data from: {tile.local_data_root}")
        else:
            UI.lvprint(1, "ERROR: local_data_root not configured in tile config file")
            sys.exit(1)
    except Exception as e:
        UI.lvprint(1, f"ERROR: Could not load tile config: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Run pipeline
    try:
        UI.lvprint(1, f"Processing tile {lat}/{lon}...")

        if "Roads" in CSTM_OVL.generated_overlays or CSTM_OVL.clean_overlays:
            UI.lvprint(1, f"  Generating road overlay...")
            ROAD.generate_road_overlay(tile)

        if "Trees" in CSTM_OVL.generated_overlays or CSTM_OVL.clean_overlays:
            UI.lvprint(1, f"  Generating tree overlay...")
            TREE.generate_tree_overlay(tile)

        if "Buildings" in CSTM_OVL.generated_overlays or CSTM_OVL.clean_overlays:
            UI.lvprint(1, f"  Generating building overlay...")
            BUILDING.generate_building_overlay(tile)

        if CSTM_OVL.clean_overlays:
            shutil.rmtree(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tmp", f"polygons_{lat}_{lon}"), ignore_errors=True)

        if CFG.generate_terrain:
            UI.lvprint(1, "  Building vector map...")
            VMAP.build_poly_file(tile)
            UI.lvprint(1, "  Building mesh...")
            MESH.build_mesh(tile)
            UI.lvprint(1, "  Building masks...")
            MASK.build_masks(tile)
            UI.lvprint(1, "  Building tile...")
            TILE.build_tile(tile)

        if CSTM_OVL.generated_overlays or CSTM_OVL.clean_overlays:
            UI.lvprint(1, f"  Building overlay DSF(s)...")
            CSTM_OVL.build_overlay_dsfs(tile)

        UI.lvprint(1, f"✓ Tile {lat}/{lon} complete!")
        return 0
    except Exception as e:
        UI.lvprint(1, f"ERROR during tile generation: {e}")
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())