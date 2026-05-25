#!/usr/bin/env python3
"""
Tiff Tiler Full for X-Plane Scene Generator
"""
import argparse, sys, os
from pathlib import Path
from typing import Dict, Tuple, List, Optional
import warnings
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds
from pyproj import Transformer
warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)

def get_dtype_range(dt):
    dt_obj = np.dtype(dt)
    if np.issubdtype(dt_obj, np.integer): info = np.iinfo(dt_obj); return float(info.min), float(info.max)
    elif np.issubdtype(dt_obj, np.floating): return 0.0, 1.0
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

def crs_requires_reprojection(crs: CRS) -> bool:
    if crs is None: return False
    try: return crs.to_epsg() != 4326
    except: return str(crs).find("4326") == -1

def calculate_tile_grid(dem_bounds, rgb_bounds, dem_crs, rgb_crs) -> List[Tuple[int, int]]:
    t1 = Transformer.from_crs(dem_crs, "EPSG:4326", always_xy=True)
    dl, db = t1.transform(dem_bounds.left, dem_bounds.bottom)
    dr, dt = t1.transform(dem_bounds.right, dem_bounds.top)
    t2 = Transformer.from_crs(rgb_crs, "EPSG:4326", always_xy=True)
    rl, rb = t2.transform(rgb_bounds.left, rgb_bounds.bottom)
    rr, rt = t2.transform(rgb_bounds.right, rgb_bounds.top)
    l = max(dl, rl); b = max(db, rb); r = min(dr, rr); t = min(dt, rt)
    if l >= r or b >= t: return []
    return [(lat, lon) for lat in range(int(np.floor(b)), int(np.ceil(t))) for lon in range(int(np.floor(l)), int(np.ceil(r)))]

def get_tile_bounds_wgs84(lat, lon): return float(lon), float(lat), float(lon + 1), float(lat + 1)

def get_tile_bounds_in_crs(lat, lon, target_crs):
    l, b, r, t = get_tile_bounds_wgs84(lat, lon)
    if not crs_requires_reprojection(target_crs): return l, b, r, t
    ts = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    lt, bt = ts.transform(l, b); rt, tt = ts.transform(r, t); return lt, bt, rt, tt

def extract_dem_tile(src_path, bounds_crs) -> np.ndarray:
    with rasterio.open(src_path) as src:
        w = from_bounds(*bounds_crs, src.transform).round_offsets().round_shape()
        data = src.read(1, window=w, boundless=True, fill_value=0)
        if src.nodata is not None:
            data = data.astype(float); data[data == src.nodata] = np.nan
        if np.isnan(data).any():
            vd = data[~np.isnan(data)]
            fv = float(np.min(vd)) if len(vd) > 0 else 0.0
            data[np.isnan(data)] = fv
        return data

def extract_rgb_tile(src_path, bounds_crs) -> np.ndarray:
    with rasterio.open(src_path) as src:
        w = from_bounds(*bounds_crs, src.transform).round_offsets().round_shape()
        data = src.read(window=w, boundless=True, fill_value=0)
        return scale_to_uint8_dtype_based(data, src.dtypes[0])

def write_tile_geotiff(data, lat, lon, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    l, b, r, t = get_tile_bounds_wgs84(lat, lon)
    c, h, w = (1, *data.shape) if len(data.shape) == 2 else data.shape
    transform = Affine.translation(l, t) * Affine.scale((r - l) / w, -(t - b) / h)
    with rasterio.open(out_path, "w", driver="GTiff", height=h, width=w, count=c,
                       dtype=data.dtype, crs=CRS.from_epsg(4326), transform=transform, compress="lzw", bigtiff="yes") as dst:
        if c == 1: dst.write(data, 1)
        else:
            for i in range(c): dst.write(data[i], i + 1)

def main(dem_path, rgb_path):
    with rasterio.open(dem_path) as s: d_crs, d_bounds = s.crs, s.bounds
    with rasterio.open(rgb_path) as s: r_crs, r_bounds = s.crs, s.bounds
    tiles = calculate_tile_grid(d_bounds, r_bounds, d_crs, r_crs)
    if not tiles: return 1
    dd = Path("dem"); rd = Path("rgb"); dd.mkdir(exist_ok=True); rd.mkdir(exist_ok=True)
    for lat, lon in tiles:
        tn = f"{(lat>=0 and '+' or '-')}{abs(lat)}{(lon>=0 and '+' or '-')}{abs(lon):03d}"
        try:
            write_tile_geotiff(extract_dem_tile(dem_path, get_tile_bounds_in_crs(lat, lon, d_crs)), lat, lon, str(dd / f"{tn}_DEM.tif"))
            write_tile_geotiff(extract_rgb_tile(rgb_path, get_tile_bounds_in_crs(lat, lon, r_crs)), lat, lon, str(rd / f"{tn}_RGB.tif"))
        except Exception as e: print(e); return 1
    return 0

if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("dem"); p.add_argument("rgb")
    sys.exit(main(p.parse_args().dem, p.parse_args().rgb))
