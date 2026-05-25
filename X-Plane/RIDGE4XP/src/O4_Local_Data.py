"""
O4_Local_Data.py - Local geospatial data loading module

Provides functions to load local GeoTIFF and Shapefile data for terrain mesh generation.
Replaces internet-based data fetching with local file I/O.
"""

import os
import numpy as np
import rasterio
from rasterio.io import MemoryFile
import fiona
from shapely.geometry import shape
import O4_UI_Utils as UI


def load_dem_from_geotiff(geotiff_path):
    """
    Load Digital Elevation Model (DEM) data from a GeoTIFF file.

    Args:
        geotiff_path: Path to GeoTIFF file containing elevation data

    Returns:
        tuple (numpy array with elevation data in meters, rasterio affine transform)
    """
    try:
        with rasterio.open(geotiff_path) as src:
            # Read first band (elevation data)
            dem_data = src.read(1).astype(np.float32)

            # Identify nodata and common extreme values before scaling
            nodata_mask = np.zeros_like(dem_data, dtype=bool)
            if src.nodata is not None:
                nodata_mask |= (dem_data == src.nodata)
            for extreme in [32767, 65535, -9999]:
                nodata_mask |= (dem_data == extreme)

            # Apply scale and offset if present
            scale = src.scales[0] if src.scales else 1.0
            offset = src.offsets[0] if src.offsets else 0.0
            if scale != 1.0 or offset != 0.0:
                dem_data = dem_data * scale + offset

            # Set all missing/extreme data to RIDGE4XP's native nodata value
            dem_data[nodata_mask] = -32768

            UI.vprint(1, f"Loaded DEM from {os.path.basename(geotiff_path)}: shape {dem_data.shape}")
            return (dem_data, src.transform)
    except Exception as e:
        UI.vprint(0, f"ERROR loading DEM from {geotiff_path}: {e}")
        raise


def load_imagery_from_geotiff(geotiff_path):
    """
    Load RGB imagery from a GeoTIFF file.

    Args:
        geotiff_path: Path to GeoTIFF file containing RGB imagery

    Returns:
        numpy array with shape (height, width, bands) containing imagery data
    """
    try:
        with rasterio.open(geotiff_path) as src:
            # Read all bands (typically 3 for RGB, 4 for RGBA)
            imagery_data = src.read()

            # Convert from (bands, height, width) to (height, width, bands)
            imagery_data = np.transpose(imagery_data, (1, 2, 0))

            UI.vprint(1, f"Loaded imagery from {os.path.basename(geotiff_path)}: shape {imagery_data.shape}")
            return imagery_data.astype(np.uint8)
    except Exception as e:
        UI.vprint(0, f"ERROR loading imagery from {geotiff_path}: {e}")
        raise


def load_vector_data_from_shapefile(shapefile_path):
    """
    Load vector data (water, coastlines, roads) from a Shapefile.

    Args:
        shapefile_path: Path to .shp file containing vector features

    Returns:
        Dictionary with features, each containing geometry and properties
    """
    try:
        features = []

        with fiona.open(shapefile_path) as src:
            for record in src:
                try:
                    geom = shape(record['geometry'])
                    feature = {
                        'geometry': geom,
                        'properties': record.get('properties', {})
                    }
                    features.append(feature)
                except Exception as e:
                    UI.vprint(2, f"Warning: Could not parse feature from {shapefile_path}: {e}")
                    continue

        UI.vprint(1, f"Loaded {len(features)} features from {os.path.basename(shapefile_path)}")
        return features

    except Exception as e:
        UI.vprint(0, f"ERROR loading vector data from {shapefile_path}: {e}")
        raise


def get_local_dem_tile(lat, lon, data_root):
    """
    Load DEM data for a specific tile from local files.

    Args:
        lat: Latitude integer
        lon: Longitude integer
        data_root: Root directory containing lat/lon subdirectories

    Returns:
        tuple with elevation data and transform, or None if not found
    """
    dem_path = os.path.join(data_root, str(lat), str(lon), "dem.tif")

    if not os.path.isfile(dem_path):
        UI.vprint(1, f"DEM file not found: {dem_path}")
        return None

    return load_dem_from_geotiff(dem_path)


def get_local_imagery_tile(lat, lon, data_root):
    """
    Load imagery data for a specific tile from local files.

    Args:
        lat: Latitude integer
        lon: Longitude integer
        data_root: Root directory containing lat/lon subdirectories

    Returns:
        numpy array with imagery data or None if not found
    """
    # Try different common filenames
    possible_names = ["rgb.tif", "imagery.tif", "ortho.tif"]

    for filename in possible_names:
        imagery_path = os.path.join(data_root, str(lat), str(lon), filename)
        if os.path.isfile(imagery_path):
            return load_imagery_from_geotiff(imagery_path)

    UI.vprint(1, f"Imagery file not found for tile {lat}/{lon}")
    return None


def get_local_water_features(lat, lon, data_root):
    """
    Load water/coastline vector data for a specific tile from local files.

    Args:
        lat: Latitude integer
        lon: Longitude integer
        data_root: Root directory containing lat/lon subdirectories

    Returns:
        List of features with geometry or None if not found
    """
    water_path = os.path.join(data_root, str(lat), str(lon), "water.shp")

    if not os.path.isfile(water_path):
        UI.vprint(1, f"Water shapefile not found: {water_path}")
        return None

    return load_vector_data_from_shapefile(water_path)


def get_local_road_features(lat, lon, data_root):
    """
    Load road/railway vector data for a specific tile from local files.

    Args:
        lat: Latitude integer
        lon: Longitude integer
        data_root: Root directory containing lat/lon subdirectories

    Returns:
        List of features with geometry or None if not found
    """
    roads_path = os.path.join(data_root, str(lat), str(lon), "roads.shp")

    if not os.path.isfile(roads_path):
        return None  # Roads are optional

    return load_vector_data_from_shapefile(roads_path)
