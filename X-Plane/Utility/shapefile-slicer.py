#!/usr/bin/env python3
"""
Shapefile 1-Degree Region Slicer

Clips a shapefile to a user-specified 1-degree by 1-degree geographic region
defined by integer bottom-left coordinates (latitude, longitude).

Usage:
    python shapefile-slicer.py <input_shapefile_or_dir> <latitude> <longitude> [output_path]

Examples:
  python shapefile-slicer.py ./land_data 36 37
  python shapefile-slicer.py ./land_data/hybas_lake_eu_lev01_v1c.shp 36 37
  python shapefile-slicer.py ./land_data 36 37 ./output
  python shapefile-slicer.py ./land_data 36 37 ./output/custom_region.shp

Requirements:
    - geopandas
    - shapely
    - fiona
    - pyproj

Install with:
    pip install geopandas shapely fiona pyproj
"""

import sys
import os
import argparse
from pathlib import Path
from typing import Optional, Tuple
import warnings

import geopandas as gpd
from shapely.geometry import box
from shapely.errors import ShapelyDeprecationWarning

warnings.filterwarnings('ignore', category=ShapelyDeprecationWarning)


def find_shapefile(directory: str) -> Optional[str]:
    """
    Find the first .shp file in the directory.

    Args:
        directory: Path to directory containing shapefile

    Returns:
        Path to the .shp file, or None if not found
    """
    dir_path = Path(directory)
    for file in dir_path.glob("*.shp"):
        return str(file)
    return None


def validate_coordinates(lat: int, lon: int) -> bool:
    """
    Validate that coordinates are integers within valid ranges.

    Args:
        lat: Latitude value
        lon: Longitude value

    Returns:
        True if valid, raises ValueError otherwise
    """
    if not isinstance(lat, int) or not isinstance(lon, int):
        raise ValueError(f"Coordinates must be integers. Got lat={lat}, lon={lon}")
    if not (-90 <= lat <= 89):
        raise ValueError(f"Latitude must be between -90 and 89. Got {lat}")
    if not (-180 <= lon <= 179):
        raise ValueError(f"Longitude must be between -180 and 179. Got {lon}")
    return True


def validate_shapefile_components(shapefile_path: str) -> bool:
    """
    Validate that all required shapefile components exist.

    Args:
        shapefile_path: Path to the .shp file

    Returns:
        True if all required components exist, raises FileNotFoundError otherwise
    """
    path = Path(shapefile_path)
    base = path.with_suffix('')
    required_extensions = ['.shp', '.shx', '.dbf']
    
    for ext in required_extensions:
        component = base.with_suffix(ext)
        if not component.exists():
            raise FileNotFoundError(
                f"Missing required shapefile component: {component}"
            )
    
    # .prj is optional but recommended
    prj_file = base.with_suffix('.prj')
    if not prj_file.exists():
        print(f"⚠️  Warning: .prj file not found. CRS detection may be unreliable.")
    
    return True


def slice_shapefile(
    input_shapefile: str,
    latitude: int,
    longitude: int,
    output_path: Optional[str] = None,
    verbose: bool = False
) -> str:
    """
    Slice a shapefile to a 1-degree by 1-degree region.

    Args:
        input_shapefile: Path to input shapefile (.shp file or directory containing .shp)
        latitude: Bottom-left latitude (integer)
        longitude: Bottom-left longitude (integer)
        output_path: Path for output shapefile (optional, auto-generated if not provided)
        verbose: Print detailed progress information

    Returns:
        Path to the output shapefile
    """
    # Resolve input shapefile path
    input_path = Path(input_shapefile)
    
    if input_path.is_dir():
        shapefile_path = find_shapefile(str(input_path))
        if not shapefile_path:
            raise FileNotFoundError(f"No shapefile (.shp) found in directory: {input_path}")
    elif input_path.suffix.lower() == '.shp':
        shapefile_path = str(input_path)
    else:
        raise ValueError(f"Input must be a .shp file or directory containing one. Got: {input_shapefile}")
    
    # Validate coordinates
    validate_coordinates(latitude, longitude)
    
    # Validate shapefile components
    validate_shapefile_components(shapefile_path)
    
    if verbose:
        print(f"📂 Input shapefile: {shapefile_path}")
        print(f"🗺️  Region: [{latitude}°, {longitude}°] to [{latitude + 1}°, {longitude + 1}°]")
    
    # Load shapefile
    if verbose:
        print("📖 Loading shapefile...")
    try:
        gdf = gpd.read_file(shapefile_path)
    except Exception as e:
        raise RuntimeError(f"Failed to read shapefile: {e}")
    
    if verbose:
        print(f"   Loaded {len(gdf)} geometries")
        print(f"   CRS: {gdf.crs}")
    
    # Check and reproject CRS if needed
    if gdf.crs is None:
        print("⚠️  Warning: CRS not detected. Assuming WGS84 (EPSG:4326)")
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        if verbose:
            print(f"🔄 Reprojecting from {gdf.crs} to WGS84 (EPSG:4326)...")
        gdf = gdf.to_crs("EPSG:4326")
    
    # Create 1x1 degree bounding box
    # (longitude, latitude) order for shapely box
    bounds = box(longitude, latitude, longitude + 1, latitude + 1)
    
    if verbose:
        print(f"✂️  Clipping to bounding box...")
    
    # Clip to bounding box
    clipped = gpd.clip(gdf, bounds)
    
    if verbose:
        print(f"   Retained {len(clipped)} geometries after clipping")
    
    if len(clipped) == 0:
        print("⚠️  Warning: No geometries found in the specified region")
    
    # Generate output path if not provided
    if output_path is None:
        # Create a folder for this region and place the shapefile inside
        output_dir = Path(f"sliced_{latitude}_{longitude}")
        output_path = output_dir / f"sliced_{latitude}_{longitude}.shp"
    else:
        output_path = Path(output_path)
        # If output_path is a directory, create filename inside it
        if not output_path.suffix:  # No file extension, treat as directory
            output_path = output_path / f"sliced_{latitude}_{longitude}.shp"
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Ensure output is in WGS84
    clipped = clipped.to_crs("EPSG:4326")
    
    # Write output
    if verbose:
        print(f"💾 Writing output to {output_path}...")
    try:
        clipped.to_file(str(output_path))
    except Exception as e:
        raise RuntimeError(f"Failed to write output shapefile: {e}")
    
    if verbose:
        print(f"✅ Success! Output shapefile: {output_path}")
    else:
        print(f"✅ Sliced shapefile saved to: {output_path}")
    
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Slice a shapefile to a 1-degree by 1-degree geographic region",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python shapefile-slicer.py ./land_data 36 37
    → Creates folder: sliced_36_37/ containing all shapefile components
  
  python shapefile-slicer.py ./land_data 36 37 ./output
    → Creates folder: output/ containing sliced_36_37.shp and components
  
  python shapefile-slicer.py ./land_data 36 37 ./results/my_slice.shp
    → Creates folder: results/ containing my_slice.shp and components
  
  python shapefile-slicer.py ./land_data 36 37 --verbose
    → Verbose output showing all steps
        """
    )
    
    parser.add_argument(
        'input',
        help='Path to shapefile (.shp) or directory containing the shapefile'
    )
    parser.add_argument(
        'latitude',
        type=int,
        help='Bottom-left latitude (integer, -90 to 89)'
    )
    parser.add_argument(
        'longitude',
        type=int,
        help='Bottom-left longitude (integer, -180 to 179)'
    )
    parser.add_argument(
        'output',
        nargs='?',
        default=None,
        help='Output folder or shapefile path (default: sliced_<lat>_<lon>/ folder in current directory)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print detailed progress information'
    )
    
    args = parser.parse_args()
    
    try:
        slice_shapefile(
            args.input,
            args.latitude,
            args.longitude,
            args.output,
            args.verbose
        )
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
