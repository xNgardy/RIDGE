"""
OSM yollarını her tile için POLYLINE (çizgi) listesi olarak JSON'a export eder.
>>> OPTİMİZE VERSİYON: OSM verisi TÜM BÖLGE için TEK SEFERDE çekilir,
    sonra tile'lara lokal olarak kırpılır. 700 ayrı Overpass sorgusu yerine 1 sorgu.

Çıktı formatı değişmez (tile başına bir JSON dosyası):
{
  "tile_x": 10, "tile_y": 21,
  "width_m": 500.0, "height_m": 500.0,
  "roads": [
    {
      "type": "asphalt",
      "width_m": 6.0,
      "points": [
        {"u": 0.12, "v": 0.34},
        ...
      ]
    },
    ...
  ]
}
"""
import os
import re
import json
import math
import time
import rasterio
from rasterio.warp import transform_bounds
import osmnx as ox
import geopandas as gpd
from shapely.geometry import box, LineString, MultiLineString
from shapely.strtree import STRtree
from concurrent.futures import ProcessPoolExecutor, as_completed

# --- AYARLAR ---
TIFS_DIR = r"C:\Users\suimd\OneDrive\Desktop\projeler\Bitirme Projesi\road 2\RGB tifs"
OUT_DIR  = os.path.join(TIFS_DIR, "_roads_polylines")

# Paralel JSON yazma için worker sayısı (artık OSM sorgusu yok, sadece clip+write)
MAX_WORKERS = 8

# Sadece belirli tile'ları işle. Boş set = HEPSİ
ONLY_TILES = set()

# Boş tile için JSON yazma
SKIP_EMPTY = True

# Farklı yol tipleri için genişlikler (metre)
ROAD_WIDTHS = {
    'motorway': 12.0, 'trunk': 10.0, 'primary': 9.0,
    'secondary': 8.0, 'tertiary': 7.0,
    'residential': 6.0, 'living_street': 5.0, 'unclassified': 5.0,
    'service': 4.0, 'track': 4.0, 'path': 2.0,
    'footway': 2.0, 'cycleway': 2.5, 'pedestrian': 3.0,
}
DEFAULT_WIDTH = 5.0

PAVED_TYPES   = {'motorway','trunk','primary','secondary','tertiary',
                 'residential','living_street','unclassified'}
UNPAVED_TYPES = {'track','path','footway','service','cycleway','pedestrian'}

os.makedirs(OUT_DIR, exist_ok=True)
tile_re = re.compile(r"tile_(\d+)_(\d+)", re.IGNORECASE)


def classify(highway_value):
    """highway değerinden (string veya list) (type, width) döner."""
    s = str(highway_value)
    picked = None
    for t in PAVED_TYPES | UNPAVED_TYPES:
        if t in s:
            picked = t
            break
    if picked is None:
        return None, None
    kind = "asphalt" if picked in PAVED_TYPES else "dirt"
    width = ROAD_WIDTHS.get(picked, DEFAULT_WIDTH)
    return kind, width


def linestring_to_points(ls, left, bottom, bounds_w, bounds_h):
    """Shapely LineString -> normalize (u,v) listesi."""
    pts = []
    for x, y in ls.coords:
        u = (x - left) / bounds_w
        v = (y - bottom) / bounds_h
        pts.append({"u": round(u, 6), "v": round(v, 6)})
    return pts


# ─────────────────────────────────────────────────────────────
# ADIM 1: Tüm tile TIF'lerinin bounds bilgisini topla
# ─────────────────────────────────────────────────────────────
def collect_tile_info(tifs_dir):
    """Tüm TIF'leri tara, bounds + CRS bilgisi topla."""
    tiles = []
    tifs = [f for f in os.listdir(tifs_dir) if f.lower().endswith(".tif")]
    
    print(f"Toplam {len(tifs)} TIF bulundu. Bounds okunuyor...")
    
    # Ortak CRS belirlemek için ilkini oku
    common_crs = None
    
    for fn in tifs:
        m = tile_re.search(fn)
        if not m:
            continue
        val1, val2 = int(m.group(1)), int(m.group(2))

        unity_x = val2 // 512
        unity_y = val1 // 512
        
        if ONLY_TILES and (unity_x, unity_y) not in ONLY_TILES:
            continue
        
        tif_path = os.path.join(tifs_dir, fn)
        with rasterio.open(tif_path) as src:
            left, bottom, right, top = src.bounds
            crs = src.crs
        
        if common_crs is None:
            common_crs = crs
        
        is_geographic = (crs is not None and crs.is_geographic)
        if is_geographic:
            mid_lat = (bottom + top) / 2.0
            width_m  = (right - left) * 111320.0 * math.cos(math.radians(mid_lat))
            height_m = (top - bottom) * 110540.0
        else:
            width_m  = right - left
            height_m = top - bottom
        
        # WGS84 bounds hesapla
        if crs is None or crs.to_epsg() == 4326:
            wgs_bounds = (left, bottom, right, top)
        else:
            wgs_bounds = transform_bounds(crs, "EPSG:4326", left, bottom, right, top, densify_pts=21)
        
        tiles.append({
            "fn": fn,
            "unity_x": unity_x,
            "unity_y": unity_y,
            "native_bounds": (left, bottom, right, top),
            "wgs_bounds": wgs_bounds,
            "crs": crs,
            "width_m": width_m,
            "height_m": height_m,
        })
    
    print(f"  {len(tiles)} tile işlenecek.")
    return tiles, common_crs


# ─────────────────────────────────────────────────────────────
# ADIM 2: Tüm tile'ların birleşik bbox'ını bul + TEK OSM sorgusu
# ─────────────────────────────────────────────────────────────
def fetch_all_roads(tiles):
    """Tüm tile'ların birleşik WGS84 bbox'ından OSM yollarını TEK SEFERDE çek."""
    
    # Birleşik WGS84 bbox
    all_lefts   = [t["wgs_bounds"][0] for t in tiles]
    all_bottoms = [t["wgs_bounds"][1] for t in tiles]
    all_rights  = [t["wgs_bounds"][2] for t in tiles]
    all_tops    = [t["wgs_bounds"][3] for t in tiles]
    
    global_left   = min(all_lefts)
    global_bottom = min(all_bottoms)
    global_right  = max(all_rights)
    global_top    = max(all_tops)
    
    print(f"\nBirleşik WGS84 bbox:")
    print(f"  ({global_left:.6f}, {global_bottom:.6f}) -> ({global_right:.6f}, {global_top:.6f})")
    
    # Bbox alanını kontrol et - çok büyükse parçalara böl
    area_deg2 = (global_right - global_left) * (global_top - global_bottom)
    print(f"  Alan: ~{area_deg2:.4f} derece² ")
    
    # Eğer alan çok büyükse (>0.5 derece² gibi), bbox'ı grid şeklinde parçala
    MAX_AREA_DEG2 = 0.25  # Overpass API için güvenli tek sorgu boyutu
    
    if area_deg2 <= MAX_AREA_DEG2:
        # Tek sorguda çek
        print(f"\nOSM verileri TEK sorguyla çekiliyor...")
        gdf = _fetch_osm_bbox(global_left, global_bottom, global_right, global_top)
    else:
        # Grid'e böl ve birleştir
        n_splits_x = max(1, math.ceil(math.sqrt(area_deg2 / MAX_AREA_DEG2)))
        n_splits_y = max(1, math.ceil(math.sqrt(area_deg2 / MAX_AREA_DEG2)))
        print(f"\nAlan büyük, {n_splits_x}x{n_splits_y} = {n_splits_x * n_splits_y} parçaya bölünüyor...")
        
        dx = (global_right - global_left) / n_splits_x
        dy = (global_top - global_bottom) / n_splits_y
        
        all_gdfs = []
        total_chunks = n_splits_x * n_splits_y
        done_chunks = 0
        
        for ix in range(n_splits_x):
            for iy in range(n_splits_y):
                chunk_left   = global_left   + ix * dx
                chunk_bottom = global_bottom + iy * dy
                chunk_right  = global_left   + (ix + 1) * dx
                chunk_top    = global_bottom + (iy + 1) * dy
                
                done_chunks += 1
                print(f"  [{done_chunks}/{total_chunks}] OSM chunk ({ix},{iy}) çekiliyor...", end=" ")
                
                chunk_gdf = _fetch_osm_bbox(chunk_left, chunk_bottom, chunk_right, chunk_top)
                if chunk_gdf is not None and len(chunk_gdf) > 0:
                    all_gdfs.append(chunk_gdf)
                    print(f"{len(chunk_gdf)} yol")
                else:
                    print("boş")
                
                # Overpass rate limit'e takılmamak için küçük bekleme
                time.sleep(1.0)
        
        if all_gdfs:
            gdf = gpd.pd.concat(all_gdfs, ignore_index=True)
            # Duplike geometrileri kaldır (overlap bölgelerinden gelen)
            gdf = gdf.drop_duplicates(subset="geometry")
            print(f"\nToplam birleştirilmiş yol sayısı: {len(gdf)}")
        else:
            gdf = None
    
    return gdf


def _fetch_osm_bbox(left, bottom, right, top):
    """Tek bir bbox için OSM yollarını çek."""
    try:
        tags = {"highway": True}
        gdf = ox.features_from_bbox(
            bbox=(left, bottom, right, top),
            tags=tags,
        )
        gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])]
        return gdf
    except Exception as e:
        print(f"  OSM fetch hatası: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# ADIM 3: STRtree spatial index ile hızlı tile-road eşleştirme
# ─────────────────────────────────────────────────────────────
def clip_roads_to_tile(tile_info, gdf_native, spatial_index, all_geoms, all_highways):
    """Tek bir tile için yolları kırp ve JSON formatına çevir."""
    left, bottom, right, top = tile_info["native_bounds"]
    bounds_w = right - left
    bounds_h = top - bottom
    tile_poly = box(left, bottom, right, top)
    
    # Spatial index ile hızlı aday bulma
    candidate_indices = spatial_index.query(tile_poly)
    
    roads_out = []
    for idx in candidate_indices:
        geom = all_geoms[idx]
        highway_val = all_highways[idx]
        
        kind, width = classify(highway_val)
        if kind is None:
            continue
        
        if geom is None or geom.is_empty:
            continue
        
        # Tile sınırına kırp
        try:
            clipped = geom.intersection(tile_poly)
        except Exception:
            continue
        
        if clipped.is_empty:
            continue
        
        lines = []
        if isinstance(clipped, LineString):
            lines = [clipped]
        elif isinstance(clipped, MultiLineString):
            lines = list(clipped.geoms)
        else:
            # GeometryCollection olabilir, LineString'leri çıkar
            if hasattr(clipped, 'geoms'):
                for g in clipped.geoms:
                    if isinstance(g, LineString):
                        lines.append(g)
            else:
                continue
        
        for ls in lines:
            if ls.length < 1e-9:
                continue
            pts = linestring_to_points(ls, left, bottom, bounds_w, bounds_h)
            if len(pts) < 2:
                continue
            roads_out.append({
                "type": kind,
                "width_m": width,
                "points": pts,
            })
    
    return {
        "tile_x": tile_info["unity_x"],
        "tile_y": tile_info["unity_y"],
        "width_m": tile_info["width_m"],
        "height_m": tile_info["height_m"],
        "roads": roads_out,
    }


def main():
    t_start = time.time()
    
    # ADIM 1: Tile bilgilerini topla
    tiles, common_crs = collect_tile_info(TIFS_DIR)
    if not tiles:
        print("Hiç tile bulunamadı!")
        return
    
    # ADIM 2: Tüm yolları tek seferde çek
    gdf = fetch_all_roads(tiles)
    if gdf is None or len(gdf) == 0:
        print("Hiç yol bulunamadı!")
        return
    
    print(f"\nToplam {len(gdf)} yol segmenti çekildi.")
    
    # GeoDataFrame'i tile'ların native CRS'ine projekte et
    if common_crs is not None and gdf.crs != common_crs:
        print(f"CRS dönüşümü yapılıyor: {gdf.crs} -> {common_crs}")
        gdf = gdf.to_crs(common_crs)
    
    # Spatial index oluştur (STRtree) — TÜM yollar için bir kez
    print("Spatial index oluşturuluyor...")
    all_geoms = list(gdf.geometry)
    all_highways = list(gdf.get("highway", [""] * len(gdf)))
    spatial_index = STRtree(all_geoms)
    
    # ADIM 3: Her tile için kırp ve JSON yaz
    print(f"\n{len(tiles)} tile için yollar kırpılıyor ve JSON yazılıyor...")
    
    saved = 0
    skipped = 0
    
    for i, tile_info in enumerate(tiles):
        data = clip_roads_to_tile(tile_info, gdf, spatial_index, all_geoms, all_highways)
        
        n_roads = len(data["roads"])
        ux, uy = tile_info["unity_x"], tile_info["unity_y"]
        prefix = f"[{i+1}/{len(tiles)}]"
        
        if SKIP_EMPTY and n_roads == 0:
            skipped += 1
            if (i + 1) % 50 == 0:
                print(f"{prefix} ... ({skipped} boş tile atlandı)")
            continue
        
        out_name = f"tile_{ux}_{uy}_roads.json"
        with open(os.path.join(OUT_DIR, out_name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        saved += 1
        print(f"{prefix} {out_name}  ({n_roads} yol)")
    
    elapsed = time.time() - t_start
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    
    print(f"\n{'='*50}")
    print(f"Bitti! {saved} dosya kaydedildi, {skipped} boş tile atlandı.")
    print(f"Toplam süre: {minutes} dk {seconds:.1f} sn")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()