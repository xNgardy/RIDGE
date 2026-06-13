#!/usr/bin/env python3
"""
Kullanım:
  python roads_to_xplane.py --tif-path <tif_dosyasi> --output-dir <çıktı>

Adımlar:
  1) Bu scripti çalıştır → DSF text dosyaları + scenery paketi oluşur
  2) DSFTool ile text → binary DSF dönüşümü yap (convert_to_dsf.bat)
  3) Oluşan klasörü X-Plane 12/Custom Scenery/ altına kopyala

Gereksinimler:
  pip install rasterio osmnx geopandas shapely
"""

import os
import sys
import math
import time
import argparse
from collections import defaultdict
from pathlib import Path

# ─── Zorunlu bağımlılıklar ───
try:
    import rasterio
    from rasterio.warp import transform_bounds
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False
    print("HATA: rasterio yüklü değil. pip install rasterio")
    sys.exit(1)

try:
    import osmnx as ox
    import geopandas as gpd
    from shapely.geometry import box, LineString, MultiLineString
    from shapely.strtree import STRtree
except ImportError as e:
    print(f"HATA: Eksik bağımlılık: {e}")
    print("pip install osmnx geopandas shapely")
    sys.exit(1)

# ─── Sabitler ───
ROAD_SUBTYPES = {
    "motorway":      100,
    "trunk":         100,
    "primary":        10,
    "secondary":      30,
    "tertiary":       30,
    "residential":    50,
    "living_street":  50,
    "unclassified":   50,
    "service":        70,
    "track":          70,
    "path":           70,
    "footway":        70,
    "cycleway":       70,
    "pedestrian":     50,
}
DEFAULT_ASPHALT_SUBTYPE = 30
DEFAULT_DIRT_SUBTYPE    = 70

PAVED_TYPES   = {"motorway","trunk","primary","secondary","tertiary",
                 "residential","living_street","unclassified","pedestrian"}
UNPAVED_TYPES = {"track","path","footway","service","cycleway"}

MAX_AREA_DEG2 = 0.25
MERGE_THRESH = 0.000005


# ═══════════════════════════════════════════════════════════════
# Argüman yönetimi
# ═══════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="Tek bir TIF dosyasından direkt X-Plane 12 DSF overlay üretir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python roads_to_xplane.py --tif-path ./rgb_tifs/rgb.tif --output-dir ./xplane_out
        """,
    )

    parser.add_argument("--tif-path",      type=str, required=True, help="Hedef GeoTIFF dosyasının yolu")
    parser.add_argument("--output-dir",    type=str, help="Çıktı klasörü (scenery paketi burada oluşur)")
    parser.add_argument("--scenery-name",  type=str, default="Custom_Roads_Overlay",
                        help="Scenery paketi adı (varsayılan: Custom_Roads_Overlay)")
    parser.add_argument("--no-exclude",    action="store_true",
                        help="Varsayılan yolları silme (exclusion zone ekleme)")
    parser.add_argument("--skip-empty",    action="store_true", default=True,
                        help="Yolu olmayan tile'ları atla (varsayılan: True)")

    args = parser.parse_args()

    if not args.output_dir:
        args.output_dir = os.path.join(os.path.dirname(args.tif_path), "XPlane_Roads_Scenery")

    return args


# ═══════════════════════════════════════════════════════════════
# Yardımcı fonksiyonlar
# ═══════════════════════════════════════════════════════════════

def classify_highway(highway_value):
    s = str(highway_value)
    for htype in PAVED_TYPES | UNPAVED_TYPES:
        if htype in s:
            return ROAD_SUBTYPES.get(htype, DEFAULT_ASPHALT_SUBTYPE)
    return None

def dsf_tile_folder(lat, lon):
    lat_base = int(math.floor(lat / 10.0)) * 10
    lon_base = int(math.floor(lon / 10.0)) * 10
    lat_s = "+" if lat_base >= 0 else ""
    lon_s = "+" if lon_base >= 0 else ""
    return f"{lat_s}{lat_base:02d}{lon_s}{lon_base:03d}"

def dsf_tile_filename(lat, lon):
    lat_s = "+" if lat >= 0 else ""
    lon_s = "+" if lon >= 0 else ""
    return f"{lat_s}{lat:02d}{lon_s}{lon:03d}"


# ═══════════════════════════════════════════════════════════════
# ADIM 1: TIF'den tile bilgisini topla (Tek Dosya)
# ═══════════════════════════════════════════════════════════════

def collect_tile_info(tif_path):
    if not os.path.isfile(tif_path):
        print(f"HATA: TIF dosyası bulunamadı: {tif_path}")
        return []

    print(f"  TIF okunuyor: {tif_path}")
    tiles = []
    
    try:
        with rasterio.open(tif_path) as src:
            left, bottom, right, top = src.bounds
            crs = src.crs
    except Exception as e:
        print(f"  UYARI: {tif_path} okunamadı: {e}")
        return []

    if crs is not None and crs.is_geographic:
        mid_lat  = (bottom + top) / 2.0
        width_m  = (right - left) * 111320.0 * math.cos(math.radians(mid_lat))
        height_m = (top - bottom) * 110540.0
    else:
        width_m  = right - left
        height_m = top - bottom

    if crs is None or crs.to_epsg() == 4326:
        wgs_bounds = (left, bottom, right, top)
    else:
        wgs_bounds = transform_bounds(crs, "EPSG:4326", left, bottom, right, top, densify_pts=21)

    tiles.append({
        "native_bounds": (left, bottom, right, top),
        "wgs_bounds":    wgs_bounds,
        "crs":           crs,
        "width_m":       width_m,
        "height_m":      height_m,
    })

    print(f"  Bounds: {wgs_bounds}")
    return tiles


def fetch_osm_roads(tiles):
    all_wgs = [t["wgs_bounds"] for t in tiles]
    gl = min(b[0] for b in all_wgs)
    gb = min(b[1] for b in all_wgs)
    gr = max(b[2] for b in all_wgs)
    gt = max(b[3] for b in all_wgs)

    print(f"  Bbox: ({gl:.6f}, {gb:.6f}) -> ({gr:.6f}, {gt:.6f})")
    area = (gr - gl) * (gt - gb)
    print(f"  Alan: ~{area:.4f} derece²")

    if area <= MAX_AREA_DEG2:
        print("  OSM tek sorguyla çekiliyor...")
        return _osm_single(gl, gb, gr, gt)

    n = max(1, math.ceil(math.sqrt(area / MAX_AREA_DEG2)))
    dx = (gr - gl) / n
    dy = (gt - gb) / n
    total = n * n
    print(f"  Alan büyük → {n}x{n}={total} parçaya bölünüyor...")

    all_gdfs = []
    done = 0
    for ix in range(n):
        for iy in range(n):
            done += 1
            cl, cb = gl + ix * dx, gb + iy * dy
            cr, ct = cl + dx, cb + dy
            print(f"  [{done}/{total}] chunk ({ix},{iy})...", end=" ", flush=True)
            gdf = _osm_single(cl, cb, cr, ct)
            if gdf is not None and len(gdf) > 0:
                all_gdfs.append(gdf)
                print(f"{len(gdf)} yol")
            else:
                print("boş")
            time.sleep(1.0)

    if not all_gdfs:
        return None
    combined = gpd.pd.concat(all_gdfs, ignore_index=True)
    combined = combined.drop_duplicates(subset="geometry")
    print(f"  Toplam: {len(combined)} yol segmenti")
    return combined

def _osm_single(left, bottom, right, top):
    try:
        gdf = ox.features_from_bbox(
            bbox=(left, bottom, right, top),
            tags={"highway": True},
        )
        return gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])]
    except Exception as e:
        print(f"  OSM fetch hatası: {e}")
        return None

def build_degree_tiles(tiles, gdf, skip_empty=True):
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        print("  OSM verisi WGS84'e dönüştürülüyor...")
        gdf = gdf.to_crs("EPSG:4326")

    all_geoms    = list(gdf.geometry)
    all_highways = list(gdf.get("highway", [""] * len(gdf)))
    strtree      = STRtree(all_geoms)

    degree_tiles = defaultdict(list)
    empty_count  = 0

    for i, tile in enumerate(tiles):
        wl, wb, wr, wt = tile["wgs_bounds"]
        tile_poly = box(wl, wb, wr, wt)
        tile_w    = wr - wl
        tile_h    = wt - wb

        candidates = strtree.query(tile_poly)
        roads_found = 0

        for idx in candidates:
            geom        = all_geoms[idx]
            highway_val = all_highways[idx]

            subtype = classify_highway(highway_val)
            if subtype is None or geom is None or geom.is_empty:
                continue

            try:
                clipped = geom.intersection(tile_poly)
            except Exception:
                continue

            if clipped.is_empty:
                continue

            if isinstance(clipped, LineString):
                lines = [clipped]
            elif isinstance(clipped, MultiLineString):
                lines = list(clipped.geoms)
            elif hasattr(clipped, "geoms"):
                lines = [g for g in clipped.geoms if isinstance(g, LineString)]
            else:
                continue

            for ls in lines:
                if ls.length < 1e-9 or len(ls.coords) < 2:
                    continue

                wgs_pts = [(lon, lat) for lon, lat in ls.coords]
                mid_lon = (wgs_pts[0][0] + wgs_pts[-1][0]) / 2
                mid_lat = (wgs_pts[0][1] + wgs_pts[-1][1]) / 2
                deg_lon = int(math.floor(mid_lon))
                deg_lat = int(math.floor(mid_lat))

                degree_tiles[(deg_lat, deg_lon)].append({
                    "subtype": subtype,
                    "points":  wgs_pts,
                })
                roads_found += 1

        if roads_found == 0:
            empty_count += 1

    return degree_tiles

def generate_dsf_text(deg_lat, deg_lon, roads, exclusion_bounds=None):
    lines = [
        "A", "800", "DSF2TEXT", "",
        "PROPERTY sim/planet earth",
        "PROPERTY sim/overlay 1",
        f"PROPERTY sim/south {deg_lat}",
        f"PROPERTY sim/west {deg_lon}",
        f"PROPERTY sim/north {deg_lat + 1}",
        f"PROPERTY sim/east {deg_lon + 1}",
        "PROPERTY sim/creation_agent roads_to_xplane.py",
    ]

    if exclusion_bounds:
        w, s, e, n = exclusion_bounds
        lines.append(f"PROPERTY sim/exclude_net {w:.6f}/{s:.6f}/{e:.6f}/{n:.6f}")

    lines += ["", "NETWORK_DEF lib/g10/roads.net", ""]

    junction_id  = 1
    junction_map = {}

    def get_junction(lon, lat):
        nonlocal junction_id
        for (jlon, jlat), jid in junction_map.items():
            if abs(jlon - lon) < MERGE_THRESH and abs(jlat - lat) < MERGE_THRESH:
                return jid
        jid = junction_id
        junction_map[(lon, lat)] = jid
        junction_id += 1
        return jid

    for road in roads:
        pts = road["points"]
        if len(pts) < 2:
            continue
        sub           = road["subtype"]
        s_lon, s_lat  = pts[0]
        e_lon, e_lat  = pts[-1]
        s_jid         = get_junction(s_lon, s_lat)
        e_jid         = get_junction(e_lon, e_lat)

        lines.append(f"BEGIN_SEGMENT 0 {sub} {s_jid} {s_lon:.9f} {s_lat:.9f} 0.0")
        for lon, lat in pts[1:-1]:
            lines.append(f"SHAPE_POINT {lon:.9f} {lat:.9f} 0.0")
        lines.append(f"END_SEGMENT {e_jid} {e_lon:.9f} {e_lat:.9f} 0.0")

    lines.append("")
    return "\n".join(lines)

def compute_exclusion(roads, margin=0.001):
    all_lons, all_lats = [], []
    for road in roads:
        for lon, lat in road["points"]:
            all_lons.append(lon)
            all_lats.append(lat)
    if not all_lons:
        return None
    return (
        min(all_lons) - margin, min(all_lats) - margin,
        max(all_lons) + margin, max(all_lats) + margin,
    )

def write_scenery_package(output_dir, scenery_name, degree_tiles, exclude):
    pack_dir = os.path.join(output_dir, scenery_name)
    nav_dir  = os.path.join(pack_dir, "Earth nav data")
    os.makedirs(nav_dir, exist_ok=True)

    lib_path = os.path.join(pack_dir, "library.txt")
    if not os.path.exists(lib_path):
        with open(lib_path, "w") as f:
            f.write("A\n800\nLIBRARY\n\n")

    total_roads = 0
    for (deg_lat, deg_lon), roads in degree_tiles.items():
        folder   = dsf_tile_folder(deg_lat, deg_lon)
        name     = dsf_tile_filename(deg_lat, deg_lon)
        tile_dir = os.path.join(nav_dir, folder)
        os.makedirs(tile_dir, exist_ok=True)

        excl = compute_exclusion(roads) if exclude else None
        if excl:
            print(f"  Exclusion: ({excl[0]:.4f}, {excl[1]:.4f}) -> ({excl[2]:.4f}, {excl[3]:.4f})")

        dsf_text = generate_dsf_text(deg_lat, deg_lon, roads, excl)
        txt_path = os.path.join(tile_dir, f"{name}.txt")
        with open(txt_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(dsf_text)

        total_roads += len(roads)
        print(f"  {folder}/{name}.txt  ({len(roads)} yol)")

    # Scripts for binary conversion
    with open(os.path.join(pack_dir, "convert_to_dsf.bat"), "w", encoding="utf-8") as f:
        f.write('@echo off\ncd /d "%~dp0"\nfor /R "Earth nav data" %%f in (*.txt) do DSFTool --text2dsf "%%f" "%%~dpnf.dsf"\npause\n')

    with open(os.path.join(pack_dir, "convert_to_dsf.sh"), "w", encoding="utf-8", newline="\n") as f:
        f.write('#!/bin/bash\nfind "Earth nav data" -name "*.txt" | while read txt; do DSFTool --text2dsf "$txt" "${txt%.txt}.dsf"; done\n')

    return pack_dir, total_roads

# ═══════════════════════════════════════════════════════════════
# Ana İşlem Akışı (Callable Interface)
# ═══════════════════════════════════════════════════════════════

def process_roads_from_tif(tif_path, output_dir, scenery_name="Custom_Roads_Overlay", skip_empty=True, no_exclude=False):
    """
    Main programmatic interface to build road overlays from a single GeoTIFF.
    Returns: pack_dir (str)
    """
    tiles = collect_tile_info(tif_path)
    if not tiles:
        print("HATA: TIF dosyası işlenemedi!")
        return None

    gdf = fetch_osm_roads(tiles)
    if gdf is None or len(gdf) == 0:
        print("HATA: Bu TIF sınırları içinde hiç yol bulunamadı!")
        return None

    degree_tiles = build_degree_tiles(tiles, gdf, skip_empty=skip_empty)
    use_exclude = not no_exclude
    pack_dir, total = write_scenery_package(output_dir, scenery_name, degree_tiles, use_exclude)
    return pack_dir


def main():
    t_start = time.time()
    args = parse_args()

    print("=" * 60)
    print("TIF → OSM → X-Plane 12 DSF Overlay")
    print("=" * 60)

    pack_dir = process_roads_from_tif(
        tif_path=args.tif_path,
        output_dir=args.output_dir,
        scenery_name=args.scenery_name,
        skip_empty=args.skip_empty,
        no_exclude=args.no_exclude
    )

    if pack_dir:
        elapsed = time.time() - t_start
        print(f"\n{'=' * 60}")
        print(f"TAMAMLANDI! Toplam süre: {int(elapsed // 60)} dk {elapsed % 60:.1f} sn")
        print(f"Çıktı: {pack_dir}")
    else:
        print("\nİşlem başarısız oldu veya yol bulunamadı.")

if __name__ == "__main__":
    main()