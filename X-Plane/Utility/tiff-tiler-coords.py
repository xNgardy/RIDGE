#!/usr/bin/env python3
"""
Tiff Tiler for X-Plane Scene Generator
Manual Coordinates Version
"""
import argparse, sys, os, math
from pathlib import Path
from typing import Dict, Tuple, List, Optional
import warnings
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds
from rasterio.enums import Resampling
from pyproj import Transformer
from PIL import Image

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

# ── RGB colour scaling ─────────────────────────────────────────────────────────

def compute_band_stretch(src: rasterio.DatasetReader, window: Window,
                         low_pct: float = 2.0, high_pct: float = 98.0,
                         max_sample_px: int = 1024) -> List[Tuple[float, float]]:
    col_start = max(0, int(window.col_off))
    row_start = max(0, int(window.row_off))
    col_end   = min(src.width,  int(window.col_off + window.width))
    row_end   = min(src.height, int(window.row_off + window.height))

    if col_end <= col_start or row_end <= row_start:
        return [(0.0, 255.0)] * src.count

    clamped = Window(col_start, row_start,
                     col_end - col_start, row_end - row_start)

    sample_w = min(max_sample_px, clamped.width)
    sample_h = min(max_sample_px, clamped.height)

    stats = []
    for band_idx in range(1, src.count + 1):
        band_data = src.read(band_idx, window=clamped,
                             out_shape=(sample_h, sample_w),
                             resampling=Resampling.nearest)
        valid = band_data.astype(np.float64).ravel()
        valid = valid[valid != 0]
        if src.nodata is not None:
            valid = valid[valid != src.nodata]
        if valid.size == 0:
            stats.append((0.0, 255.0))
            continue
        lo = float(np.percentile(valid, low_pct))
        hi = float(np.percentile(valid, high_pct))
        if hi <= lo:
            hi = lo + 1.0
        stats.append((lo, hi))
    return stats


def apply_stretch_to_uint8(data: np.ndarray,
                            band_stats: List[Tuple[float, float]]) -> np.ndarray:
    if data.dtype == np.uint8:
        return data
    out = np.empty(data.shape, dtype=np.uint8)
    for i, (lo, hi) in enumerate(band_stats):
        ch = data[..., i].astype(np.float64)
        ch = (ch - lo) / (hi - lo)
        ch = np.clip(ch, 0.0, 1.0)
        out[..., i] = (ch * 255.0).astype(np.uint8)
    return out

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

def load_rgb_metadata(rgb_path: str) -> Dict:
    with rasterio.open(rgb_path) as src:
        return {"path": rgb_path, "bounds": src.bounds, "crs": src.crs, "transform": src.transform,
                "width": src.width, "height": src.height, "count": src.count, "dtype": src.dtypes[0],
                "needs_reprojection": crs_requires_reprojection(src.crs)}

def get_tile_bounds_wgs84(lat, lon): return float(lon), float(lat), float(lon + 1), float(lat + 1)

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
        if src.nodata is not None:
            data = data.astype(float)
            data[data == src.nodata] = np.nan
        if np.isnan(data).any():
            vd = data[~np.isnan(data)]
            fv = float(np.min(vd)) if len(vd) > 0 else 0.0
            data[np.isnan(data)] = fv
        return data

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

# ── RGB chunk tiler ────────────────────────────────────────────────────────────

def process_rgb_chunks_tiler(src_path, bounds_crs, lat, lon, out_dir, chunk_size=4096):
    with rasterio.open(src_path) as src:
        window = from_bounds(*bounds_crs, src.transform).round_offsets().round_shape()
        c_off, r_off, w, h = window.col_off, window.row_off, window.width, window.height
        nc = math.ceil(w / chunk_size); nr = math.ceil(h / chunk_size)
        ts = f"{(lat>=0 and '+' or '-')}{abs(lat)}{(lon>=0 and '+' or '-')}{abs(lon):03d}"
        td = out_dir / ts; td.mkdir(parents=True, exist_ok=True)

        band_stats = compute_band_stretch(src, window)

        for ri in range(nr):
            for ci in range(nc):
                cwnd = Window(c_off + ci * chunk_size, r_off + ri * chunk_size,
                              chunk_size, chunk_size)
                data = src.read(window=cwnd, boundless=True, fill_value=0)
                if data.ndim == 3:
                    data = np.transpose(data, (1, 2, 0))
                data_u8 = apply_stretch_to_uint8(data, band_stats)
                Image.fromarray(data_u8).save(td / f"{ts}_{ri}_{ci}_RGB.jpg", quality=95)

# ── Entry point ────────────────────────────────────────────────────────────────

def format_tile_name(lat, lon):
    return f"{(lat>=0 and '+' or '-')}{abs(lat)}{(lon>=0 and '+' or '-')}{abs(lon):03d}"

def main(dem_path, rgb_path, lat, lon):
    print("Loading metadata...")
    dem_meta = load_dem_metadata(dem_path)
    rgb_meta = load_rgb_metadata(rgb_path)
    
    # We only have one tile to process based on user input
    tiles = [(lat, lon)]
    
    dem_dir = Path("dem"); rgb_dir = Path("rgb")
    dem_dir.mkdir(exist_ok=True); rgb_dir.mkdir(exist_ok=True)
    
    for i, (t_lat, t_lon) in enumerate(tiles, 1):
        tn = format_tile_name(t_lat, t_lon)
        try:
            db_crs = get_tile_bounds_in_crs(t_lat, t_lon, dem_meta["crs"])
            rb_crs = get_tile_bounds_in_crs(t_lat, t_lon, rgb_meta["crs"])
            
            print(f"Extracting DEM for tile {tn}...")
            write_tile_geotiff(extract_dem_tile(dem_path, db_crs), t_lat, t_lon,
                               str(dem_dir / f"{tn}_DEM.tif"), dem_meta["crs"])
                               
            print(f"Extracting RGB for tile {tn}...")
            process_rgb_chunks_tiler(rgb_path, rb_crs, t_lat, t_lon, rgb_dir)
        except Exception as e: 
            print(f"ERROR: {e}")
            return 1
            
    print("Coordinates processing completed.")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tiff Tiler with manual lat/lon coordinates.")
    parser.add_argument("dem_path", help="Path to DEM GeoTIFF")
    parser.add_argument("rgb_path", help="Path to RGB GeoTIFF")
    parser.add_argument("--lat", type=int, required=True, help="Latitude of the bottom-left corner of the region")
    parser.add_argument("--lon", type=int, required=True, help="Longitude of the bottom-left corner of the region")
    
    args = parser.parse_args()
    sys.exit(main(args.dem_path, args.rgb_path, args.lat, args.lon))
