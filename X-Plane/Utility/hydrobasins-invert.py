"""
Inverts Level 1 HydroBASINS shapefile to create ocean/water polygons.
Takes land polygons and creates the inverse (water areas).

Required input files in input directory:
    - *.shp (shapefile geometry)
    - *.shx (shapefile index - required)
    - *.dbf (attribute database)
    - *.prj (projection info, optional but recommended)

Usage:
    python hydrobasins-invert.py <input_dir> <output_dir>
    python hydrobasins-invert.py ./land_data/ ./ocean_data/
"""

import sys
import os
import geopandas as gpd
from shapely.geometry import box
from shapely.ops import unary_union
import warnings

warnings.filterwarnings('ignore')


def find_shapefile(directory):
    """
    Find the first .shp file in the directory.

    Args:
        directory: Path to directory containing shapefile

    Returns:
        Path to the .shp file, or None if not found
    """
    for file in os.listdir(directory):
        if file.endswith('.shp'):
            return os.path.join(directory, file)
    return None


def invert_hydrobasins(input_dir, output_dir):
    """
    Inverts HydroBASINS land polygons to create ocean/water polygons.

    Args:
        input_dir: Directory containing input HydroBASINS shapefile
        output_dir: Directory where output shapefile will be saved
    """
    # Find the shapefile
    input_shp = find_shapefile(input_dir)
    if not input_shp:
        raise FileNotFoundError(f"No .shp file found in {input_dir}")

    print(f"Found shapefile: {os.path.basename(input_shp)}")
    print(f"Loading HydroBASINS file from: {input_dir}")

    # Load the land polygons
    gdf = gpd.read_file(input_shp)
    print(f"Loaded {len(gdf)} land polygons")

    # Get the CRS
    original_crs = gdf.crs
    print(f"CRS: {original_crs}")

    # Create world boundary (longitude: -180 to 180, latitude: -90 to 90)
    world_bounds = box(-180, -90, 180, 90)

    # Convert land polygons to single geometry (dissolve all)
    land_union = unary_union(gdf.geometry)
    print("Merged land polygons")

    # Calculate the difference: world - land = oceans
    print("Computing ocean polygons (world boundary - land)...")
    ocean_geometry = world_bounds.difference(land_union)

    # Create a new GeoDataFrame for oceans
    ocean_gdf = gpd.GeoDataFrame(
        {'geometry': [ocean_geometry]},
        crs=original_crs
    )

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Save to shapefile
    output_shp = os.path.join(output_dir, 'ocean.shp')
    print(f"Saving ocean polygons to: {output_dir}")
    ocean_gdf.to_file(output_shp, driver='ESRI Shapefile')

    print(f"✓ Success! Ocean shapefile created.")
    print(f"  Output files: {output_dir}/ocean.*")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        print("Error: Missing arguments")
        print(f"Usage: {sys.argv[0]} <input_dir> <output_dir>")
        sys.exit(1)

    input_directory = sys.argv[1]
    output_directory = sys.argv[2]

    # Validate input directory
    if not os.path.isdir(input_directory):
        print(f"Error: Input directory does not exist: {input_directory}", file=sys.stderr)
        sys.exit(1)

    try:
        invert_hydrobasins(input_directory, output_directory)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
