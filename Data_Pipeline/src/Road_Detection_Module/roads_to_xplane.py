#!/usr/bin/env python3
"""
Kullanım:
  python roads_to_xplane.py --tifs-dir <tif_klasörü> --output-dir <çıktı>
  python roads_to_xplane.py --config roads_to_xplane.ini

Adımlar:
  1) Bu scripti çalıştır → DSF text dosyaları + scenery paketi oluşur
  2) DSFTool ile text → binary DSF dönüşümü yap (convert_to_dsf.bat)
  3) Oluşan klasörü X-Plane 12/Custom Scenery/ altına kopyala

Gereksinimler:
  pip install rasterio osmnx geopandas shapely
"""

import os
import re
import sys
import math
import time
import argparse
import configparser
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
TILE_RE = re.compile(r"tile_(\d+)_(\d+)", re.IGNORECASE)
CONFIG_FILENAME = "roads_to_xplane.ini"

# X-Plane ROAD_DRAPED subtype numaraları (roads.net / roads_EU.net)
#   10 = primary        30 = secondary       50 = local
#   70 = single_lane    100 = highway_6lane   110 = highway_4lane
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

# Overpass API: tek sorguda güvenli maksimum alan (derece²)
MAX_AREA_DEG2 = 0.25

# Junction birleştirme eşiği (~0.5 metre)
MERGE_THRESH = 0.000005


# ═══════════════════════════════════════════════════════════════
# Config & Argüman yönetimi
# ═══════════════════════════════════════════════════════════════

def load_config(config_path=None):
    """roads_to_xplane.ini dosyasından ayarları oku."""
    cfg = configparser.ConfigParser()
    search_paths = [
        config_path,
        Path.cwd() / CONFIG_FILENAME,
        Path(__file__).parent / CONFIG_FILENAME,
    ]
    for p in search_paths:
        if p and Path(p).exists():
            cfg.read(str(p))
            print(f"Config yüklendi: {p}")
            return cfg
    return cfg


def parse_args():
    parser = argparse.ArgumentParser(
        description="TIF dosyalarından direkt X-Plane 12 DSF overlay üretir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python roads_to_xplane.py --tifs-dir ./rgb_tifs --output-dir ./xplane_out
  python roads_to_xplane.py --config my_settings.ini
  python roads_to_xplane.py --tifs-dir ./rgb_tifs --no-exclude
        """,
    )

    parser.add_argument("--tifs-dir",      type=str, help="GeoTIFF dosyalarının bulunduğu klasör")
    parser.add_argument("--output-dir",    type=str, help="Çıktı klasörü (scenery paketi burada oluşur)")
    parser.add_argument("--scenery-name",  type=str, default="Custom_Roads_Overlay",
                        help="Scenery paketi adı (varsayılan: Custom_Roads_Overlay)")
    parser.add_argument("--tile-divisor",  type=int, default=512,
                        help="TIF piksel offset → grid index böleni (varsayılan: 512)")
    parser.add_argument("--no-exclude",    action="store_true",
                        help="Varsayılan yolları silme (exclusion zone ekleme)")
    parser.add_argument("--skip-empty",    action="store_true", default=True,
                        help="Yolu olmayan tile'ları atla (varsayılan: True)")
    parser.add_argument("--config",        type=str, help="Config dosyası yolu (.ini)")

    args = parser.parse_args()

    # Config dosyasından eksik argümanları doldur
    cfg = load_config(args.config)
    if cfg.has_section("paths"):
        if not args.tifs_dir:
            args.tifs_dir = cfg.get("paths", "tifs_dir", fallback=None)
        if not args.output_dir:
            args.output_dir = cfg.get("paths", "output_dir", fallback=None)
    if cfg.has_section("settings"):
        args.tile_divisor = cfg.getint("settings", "tile_divisor", fallback=args.tile_divisor)
        args.scenery_name = cfg.get("settings", "scenery_name", fallback=args.scenery_name)

    # Zorunlu alanları kontrol et
    if not args.tifs_dir:
        parser.error("--tifs-dir gerekli. GeoTIFF dosyalarının bulunduğu klasörü belirtin.")
    if not args.output_dir:
        args.output_dir = os.path.join(os.path.dirname(args.tifs_dir), "XPlane_Roads_Scenery")

    return args


# ═══════════════════════════════════════════════════════════════
# Yardımcı fonksiyonlar
# ═══════════════════════════════════════════════════════════════

def classify_highway(highway_value):
    """
    highway tag string'inden X-Plane subtype döner.
    Bilinmeyen tip için None döner.
    """
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
# ADIM 1: TIF'lerden tile bilgilerini topla
# ═══════════════════════════════════════════════════════════════

def collect_tile_info(tifs_dir, tile_divisor, only_tiles=None):
    """
    Tüm TIF dosyalarını tarar, WGS84 bounds + boyut bilgisi döndürür.
    Döndürür: [tile_info_dict, ...]
    """
    if not os.path.isdir(tifs_dir):
        print(f"HATA: TIF klasörü bulunamadı: {tifs_dir}")
        sys.exit(1)

    tif_files = [f for f in os.listdir(tifs_dir) if f.lower().endswith(".tif")]
    print(f"  {len(tif_files)} TIF bulundu. Bounds okunuyor...")

    tiles = []
    for fn in tif_files:
        m = TILE_RE.search(fn)
        if m:
            val1, val2 = int(m.group(1)), int(m.group(2))
            unity_x = val2 // tile_divisor
            unity_y = val1 // tile_divisor
        else:
            # Tek parça (bölünmemiş) TIF: dosya adında tile_X_Y kalıbı yok.
            # Atlamak yerine 0,0 grid index ile tek tile olarak işle.
            unity_x = unity_y = 0

        if only_tiles and (unity_x, unity_y) not in only_tiles:
            continue

        tif_path = os.path.join(tifs_dir, fn)
        try:
            with rasterio.open(tif_path) as src:
                left, bottom, right, top = src.bounds
                crs = src.crs
        except Exception as e:
            print(f"  UYARI: {fn} okunamadı: {e}")
            continue

        # Metre cinsinden boyut
        if crs is not None and crs.is_geographic:
            mid_lat  = (bottom + top) / 2.0
            width_m  = (right - left) * 111320.0 * math.cos(math.radians(mid_lat))
            height_m = (top - bottom) * 110540.0
        else:
            width_m  = right - left
            height_m = top - bottom

        # WGS84 bounds
        if crs is None or crs.to_epsg() == 4326:
            wgs_bounds = (left, bottom, right, top)
        else:
            wgs_bounds = transform_bounds(crs, "EPSG:4326", left, bottom, right, top, densify_pts=21)

        tiles.append({
            "unity_x":      unity_x,
            "unity_y":      unity_y,
            "native_bounds": (left, bottom, right, top),
            "wgs_bounds":    wgs_bounds,
            "crs":           crs,
            "width_m":       width_m,
            "height_m":      height_m,
        })

    print(f"  {len(tiles)} tile işlenecek.")
    return tiles


# ═══════════════════════════════════════════════════════════════
# ADIM 2: OSM'den tüm yolları tek seferde çek
# ═══════════════════════════════════════════════════════════════

def fetch_osm_roads(tiles):
    """
    Tüm tile'ların birleşik WGS84 bbox'ından OSM yollarını çeker.
    Büyük alanlarda otomatik olarak parçalara böler.
    Döndürür: GeoDataFrame (WGS84, CRS=4326)
    """
    all_wgs = [t["wgs_bounds"] for t in tiles]
    gl = min(b[0] for b in all_wgs)
    gb = min(b[1] for b in all_wgs)
    gr = max(b[2] for b in all_wgs)
    gt = max(b[3] for b in all_wgs)

    print(f"  Birleşik bbox: ({gl:.6f}, {gb:.6f}) -> ({gr:.6f}, {gt:.6f})")
    area = (gr - gl) * (gt - gb)
    print(f"  Alan: ~{area:.4f} derece²")

    if area <= MAX_AREA_DEG2:
        print("  OSM tek sorguyla çekiliyor...")
        return _osm_single(gl, gb, gr, gt)

    # Parçalara böl
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
    """Tek bbox için OSM highway verisi çeker."""
    try:
        gdf = ox.features_from_bbox(
            bbox=(left, bottom, right, top),
            tags={"highway": True},
        )
        return gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])]
    except Exception as e:
        print(f"  OSM fetch hatası: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# ADIM 3: Yolları tile'lara kırp ve 1°×1° DSF gruplarına dönüştür
# ═══════════════════════════════════════════════════════════════

def build_degree_tiles(tiles, gdf, skip_empty=True):
    """
    OSM yollarını her tile'ın WGS84 sınırına kırpar,
    WGS84 koordinatlarına çevirir ve X-Plane 1°×1° grid'ine gruplar.
    Döndürür: {(deg_lat, deg_lon): [road_dicts]}
    """
    # WGS84'e dönüştür (henüz değilse)
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

            # LineString'leri çıkar
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

                # ls.coords zaten gerçek WGS84 lon/lat döner (intersection
                # WGS84 tile_poly ile yapıldı). Yeniden ölçeklemeye GEREK YOK.
                wgs_pts = [(lon, lat) for lon, lat in ls.coords]

                # Hangi 1°×1° degree tile'a düştüğü
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

        if (i + 1) % 100 == 0 or (i + 1) == len(tiles):
            print(f"  [{i+1}/{len(tiles)}] tile işlendi ({empty_count} boş)...")

    return degree_tiles


# ═══════════════════════════════════════════════════════════════
# ADIM 4: DSF text dosyası üretimi
# ═══════════════════════════════════════════════════════════════

def generate_dsf_text(deg_lat, deg_lon, roads, exclusion_bounds=None):
    """Bir 1°×1° tile için DSF text overlay üretir."""
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
    """Yolların kapladığı alandan exclusion zone hesapla."""
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


# ═══════════════════════════════════════════════════════════════
# ADIM 5: Scenery paketi yaz
# ═══════════════════════════════════════════════════════════════

def write_scenery_package(output_dir, scenery_name, degree_tiles, exclude):
    """Tam scenery paketini yazar: DSF text + library.txt + batch script'ler + README."""
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

    # convert_to_dsf.bat (Windows)
    with open(os.path.join(pack_dir, "convert_to_dsf.bat"), "w", encoding="utf-8") as f:
        f.write('@echo off\n')
        f.write('echo DSF Text -> Binary dönüşümü başlatılıyor...\n')
        f.write('echo.\n')
        f.write('for /R "Earth nav data" %%f in (*.txt) do (\n')
        f.write('    echo Converting: %%f\n')
        f.write('    DSFTool --text2dsf "%%f" "%%~dpnf.dsf"\n')
        f.write('    if errorlevel 1 (\n')
        f.write('        echo HATA: %%f\n')
        f.write('    ) else (\n')
        f.write('        echo OK: %%~dpnf.dsf\n')
        f.write('        del "%%f"\n')
        f.write('    )\n')
        f.write(')\n')
        f.write('echo.\necho Tamam!\npause\n')

    # convert_to_dsf.sh (Linux/Mac)
    with open(os.path.join(pack_dir, "convert_to_dsf.sh"), "w", encoding="utf-8", newline="\n") as f:
        f.write('#!/bin/bash\n')
        f.write('echo "DSF Text -> Binary dönüşümü başlatılıyor..."\n')
        f.write('find "Earth nav data" -name "*.txt" | while read txt; do\n')
        f.write('    dsf="${txt%.txt}.dsf"\n')
        f.write('    echo "Converting: $txt"\n')
        f.write('    DSFTool --text2dsf "$txt" "$dsf"\n')
        f.write('    [ $? -eq 0 ] && rm "$txt" && echo "OK: $dsf" || echo "HATA: $txt"\n')
        f.write('done\necho "Tamam!"\n')

    # Örnek config dosyası
    with open(os.path.join(pack_dir, "roads_to_xplane.ini.example"), "w", encoding="utf-8") as f:
        f.write("[paths]\n")
        f.write("# GeoTIFF dosyalarının bulunduğu klasör\n")
        f.write("tifs_dir = ./rgb_tifs\n")
        f.write("# Çıktı klasörü\n")
        f.write("output_dir = ./XPlane_Roads_Scenery\n\n")
        f.write("[settings]\n")
        f.write("# Scenery paketi adı\n")
        f.write("scenery_name = Custom_Roads_Overlay\n")
        f.write("# TIF piksel offset → grid index böleni\n")
        f.write("tile_divisor = 512\n")

    # README.md
    degree_summary = "\n".join(
        f"  - `{dsf_tile_folder(dlat, dlon)}/{dsf_tile_filename(dlat, dlon)}.dsf` — {len(roads)} yol segmenti"
        for (dlat, dlon), roads in degree_tiles.items()
    )
    with open(os.path.join(pack_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(f"""# {scenery_name}

X-Plane 12 Custom Roads Overlay — OSM verilerinden oluşturulmuş yol ağı.

## Genel Bilgi

- **Toplam yol segmenti:** {total_roads}
- **DSF tile sayısı:** {len(degree_tiles)}
- **Oluşturulan tile'lar:**
{degree_summary}
- **Road network:** `lib/g10/roads.net` (X-Plane varsayılan)
- **Elevation:** AGL 0 (draped — zemine yapışır)
- **Exclusion:** {"Aktif — varsayılan yollar bölge içinde siliniyor" if exclude else "Kapalı"}

## Kurulum

### 1. DSF Dönüşümü

DSFTool gereklidir: https://developer.x-plane.com/tools/xptools/

**Windows:**
```
cd "{pack_dir}"
convert_to_dsf.bat
```

**Linux/Mac:**
```
cd "{pack_dir}"
chmod +x convert_to_dsf.sh
./convert_to_dsf.sh
```

### 2. X-Plane'a Kopyalama

`{scenery_name}` klasörünün tamamını kopyalayın:
```
X-Plane 12/Custom Scenery/{scenery_name}/
```

### 3. scenery_packs.ini Sıralaması

`X-Plane 12/Custom Scenery/scenery_packs.ini` dosyasında bu paket
**Global Scenery'nin üstünde** olmalı:
```
SCENERY_PACK Custom Scenery/{scenery_name}/
...
SCENERY_PACK Global Scenery/X-Plane 12 Global Scenery/
```

## Script Kullanımı

```bash
# Komut satırı argümanlarıyla
python roads_to_xplane.py \\
    --tifs-dir ./rgb_tifs \\
    --output-dir ./XPlane_Roads_Scenery

# Config dosyasıyla
python roads_to_xplane.py --config roads_to_xplane.ini

# Exclusion zone olmadan
python roads_to_xplane.py --tifs-dir ./tifs --no-exclude
```

### Argümanlar

| Argüman | Açıklama |
|---------|----------|
| `--tifs-dir` | GeoTIFF dosyalarının klasörü |
| `--output-dir` | Çıktı klasörü |
| `--scenery-name` | Scenery paketi adı (varsayılan: Custom_Roads_Overlay) |
| `--tile-divisor` | TIF piksel → grid index böleni (varsayılan: 512) |
| `--no-exclude` | Varsayılan yolları silme |
| `--config` | Config dosyası (.ini) yolu |

## Bağımlılıklar

- Python 3.8+
- `rasterio`: `pip install rasterio`
- `osmnx`: `pip install osmnx`
- `geopandas`: `pip install geopandas`
- `shapely`: `pip install shapely`
- DSFTool (binary dönüşüm için)

## Yol Subtypes

| OSM Tipi | X-Plane Subtype |
|----------|-----------------|
| motorway, trunk | 100 (highway 6-lane) |
| primary | 10 (primary) |
| secondary, tertiary | 30 (secondary) |
| residential, living_street, unclassified, pedestrian | 50 (local) |
| service, track, path, footway, cycleway | 70 (single lane) |
""")

    return pack_dir, total_roads


# ═══════════════════════════════════════════════════════════════
# Ana akış
# ═══════════════════════════════════════════════════════════════

def main():
    t_start = time.time()
    args = parse_args()

    print("=" * 60)
    print("TIF → OSM → X-Plane 12 DSF Overlay")
    print("=" * 60)

    # 1) TIF'lerden tile bilgilerini topla
    print(f"\n[1/4] TIF tile bilgileri toplanıyor...")
    tiles = collect_tile_info(args.tifs_dir, args.tile_divisor)
    if not tiles:
        print("HATA: Hiç tile bulunamadı!")
        sys.exit(1)

    # 2) OSM'den yolları çek
    print(f"\n[2/4] OSM yol verisi çekiliyor...")
    gdf = fetch_osm_roads(tiles)
    if gdf is None or len(gdf) == 0:
        print("HATA: Hiç yol bulunamadı!")
        sys.exit(1)
    print(f"  Toplam {len(gdf)} yol segmenti çekildi.")

    # 3) Yolları 1°×1° DSF tile'larına dönüştür
    print(f"\n[3/4] Yollar kırpılıyor ve DSF tile'larına gruplandırılıyor...")
    degree_tiles = build_degree_tiles(tiles, gdf, skip_empty=args.skip_empty)
    print(f"  {len(degree_tiles)} adet 1°×1° DSF tile oluşturulacak:")
    for (dlat, dlon), roads in degree_tiles.items():
        print(f"    ({dlat}°N, {dlon}°E) → {len(roads)} yol segmenti")

    # 4) Scenery paketi yaz
    print(f"\n[4/4] Scenery paketi oluşturuluyor...")
    use_exclude = not args.no_exclude
    pack_dir, total = write_scenery_package(
        args.output_dir, args.scenery_name, degree_tiles, use_exclude
    )

    elapsed = time.time() - t_start
    print(f"\n{'=' * 60}")
    print(f"TAMAMLANDI! {total} yol segmenti yazıldı.")
    print(f"Toplam süre: {int(elapsed // 60)} dk {elapsed % 60:.1f} sn")
    print(f"{'=' * 60}")
    print(f"\nÇıktı: {pack_dir}")
    print(f"\nSonraki adımlar:")
    print(f"  1) cd \"{pack_dir}\"")
    print(f"  2) convert_to_dsf.bat çalıştır (DSFTool gerekli)")
    print(f"  3) Klasörü X-Plane 12/Custom Scenery/ altına kopyala")
    print(f"  4) scenery_packs.ini'de en üste koy")


if __name__ == "__main__":
    main()
