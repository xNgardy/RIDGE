#!/usr/bin/env python3
"""
Tiff Tiler for X-Plane Scene Generator
DEM Only Version - Creates 1-degree x 1-degree DEM tiles
"""
import argparse, sys, os
from pathlib import Path
from typing import Dict
import warnings
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds
from pyproj import Transformer

warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)

# ── DEM helpers ────────────────────────────────────────────────────────────────

def get_dtype_range(dt):
    dt_obj = np.dtype(dt)
    if np.issubdtype(dt_obj, np.integer):
        info = np.iinfo(dt_obj)
        return float(info.min), float(info.max)
    elif np.issubdtype(dt_obj, np.floating):
        return 0.0, 1.0
    return 0.0, 255.0

def scale_to_uint8_dtype_based(data: np.ndarray, dt) -> np.ndarray:
    dt_obj = np.dtype(dt)
    if dt_obj == np.uint8:
        return data
    dmin, dmax = get_dtype_range(dt)
    if dmax == dmin: return np.zeros_like(data, dtype=np.uint8)
    data_scaled = (data.astype(float) - dmin) / (dmax - dmin)
    data_scaled = np.clip(data_scaled, 0.0, 1.0)
    return (data_scaled * 255.0).astype(np.uint8)

# ── CRS / metadata helpers ────────────────────────────────────────────────────

def crs_requires_reprojection(crs: CRS) -> bool:
    if crs is None: return False
    try: return crs.to_epsg() != 4326
    except: return str(crs).find("4326") == -1

def load_dem_metadata(dem_path: str) -> Dict:
    with rasterio.open(dem_path) as src:
        b = src.read(1); nd = src.nodata
        vd = b[b != nd] if nd is not None else (b[~np.isnan(b)] if b.dtype == np.float32 else b)
        me = float(np.min(vd)) if len(vd) > 0 else 0.0
        return {"path": dem_path, "bounds": src.bounds, "crs": src.crs, "transform": src.transform,
                "width": src.width, "height": src.height, "nodata": nd, "dtype": src.dtypes[0], "min_elevation": me,
                "needs_reprojection": crs_requires_reprojection(src.crs)}

def get_tile_bounds_wgs84(lat, lon): 
    return float(lon), float(lat), float(lon + 1), float(lat + 1)

def get_tile_bounds_in_crs(lat, lon, target_crs):
    l, b, r, t = get_tile_bounds_wgs84(lat, lon)
    if not crs_requires_reprojection(target_crs): return l, b, r, t
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    lt, bt = transformer.transform(l, b); rt, tt = transformer.transform(r, t)
    return lt, bt, rt, tt

# ── DEM tile writer ──────────────────────────────────────────────────────────

def extract_dem_tile(src_path, bounds_crs) -> np.ndarray:
    with rasterio.open(src_path) as src:
        window = from_bounds(*bounds_crs, src.transform).round_offsets().round_shape()
        data = src.read(1, window=window, boundless=True, fill_value=0)
        original_dtype = data.dtype
        if src.nodata is not None:
            data = data.astype(float)
            data[data == src.nodata] = np.nan
        if np.isnan(data).any():
            vd = data[~np.isnan(data)]
            fv = float(np.min(vd)) if len(vd) > 0 else 0.0
            data[np.isnan(data)] = fv
        return data.astype(original_dtype)

def write_tile_geotiff(data, lat, lon, output_path, crs):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    out_crs = CRS.from_epsg(4326)
    l, b, r, t = get_tile_bounds_wgs84(lat, lon)
    h, w = data.shape if len(data.shape) == 2 else data.shape[1:]
    transform = Affine.translation(l, t) * Affine.scale((r - l) / w, -(t - b) / h)
    c = 1 if len(data.shape) == 2 else data.shape[0]
    with rasterio.open(output_path, "w", driver="GTiff", height=h, width=w, count=c,
                       dtype=data.dtype, crs=out_crs, transform=transform, compress="lzw") as dst:
        if len(data.shape) == 2: dst.write(data, 1)
        else:
            for i in range(c): dst.write(data[i], i + 1)

# ── Entry point ────────────────────────────────────────────────────────────────

def format_tile_name(lat, lon):
    return f"{(lat>=0 and '+' or '-')}{abs(lat)}{(lon>=0 and '+' or '-')}{abs(lon):03d}"

def main(dem_path, lat, lon):
    print("Loading DEM metadata...")
    dem_meta = load_dem_metadata(dem_path)
    
    dem_dir = Path("dem")
    dem_dir.mkdir(exist_ok=True)
    
    tn = format_tile_name(lat, lon)
    try:
        db_crs = get_tile_bounds_in_crs(lat, lon, dem_meta["crs"])
        
        print(f"Extracting DEM for tile {tn}...")
        write_tile_geotiff(extract_dem_tile(dem_path, db_crs), lat, lon,
                           str(dem_dir / f"{tn}_DEM.tif"), dem_meta["crs"])
        print(f"Successfully created DEM tile: {tn}_DEM.tif")
    except Exception as e: 
        print(f"ERROR: {e}")
        return 1
            
    print("DEM tile extraction completed.")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract a 1-degree x 1-degree DEM tile from a GeoTIFF.")
    parser.add_argument("dem_path", help="Path to DEM GeoTIFF")
    parser.add_argument("--lat", type=int, required=True, help="Latitude of the bottom-left corner of the tile")
    parser.add_argument("--lon", type=int, required=True, help="Longitude of the bottom-left corner of the tile")
    
    args = parser.parse_args()
    sys.exit(main(args.dem_path, args.lat, args.lon))
