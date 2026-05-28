#!/usr/bin/env python3
"""
Unity yol JSON'larını X-Plane 12 DSF overlay scenery paketine dönüştürür.

Kullanım:
  python roads_to_xplane.py --roads-dir <json_klasörü> --tifs-dir <tif_klasörü> --output-dir <çıktı>

  Tüm argümanlar opsiyonel — verilmezse roads_to_xplane.ini config dosyasından
  veya aynı dizindeki varsayılan yollardan okunur.

Adımlar:
  1) Bu scripti çalıştır → DSF text dosyaları + scenery paketi oluşur
  2) DSFTool ile text → binary DSF dönüşümü yap (convert_to_dsf.bat)
  3) Oluşan klasörü X-Plane 12/Custom Scenery/ altına kopyala

Gereksinimler:
  pip install rasterio
"""

import os
import re
import sys
import json
import math
import glob
import argparse
import configparser
from collections import defaultdict
from pathlib import Path

# ─── Opsiyonel bağımlılıklar ───
try:
    import rasterio
    from rasterio.warp import transform_bounds
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

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
DEFAULT_DIRT_SUBTYPE = 70


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
        description="Unity yol JSON'larını X-Plane 12 DSF overlay'e dönüştürür.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python roads_to_xplane.py --roads-dir ./road_jsons --tifs-dir ./rgb_tifs --output-dir ./xplane_out
  python roads_to_xplane.py --config my_settings.ini
  python roads_to_xplane.py --roads-dir ./road_jsons --origin-lat 37.0 --origin-lon 36.5
        """,
    )

    parser.add_argument("--roads-dir", type=str,
                        help="Yol JSON dosyalarının bulunduğu klasör")
    parser.add_argument("--tifs-dir", type=str,
                        help="GeoTIFF dosyalarının bulunduğu klasör (georeferans için)")
    parser.add_argument("--output-dir", type=str,
                        help="Çıktı klasörü (scenery paketi burada oluşur)")
    parser.add_argument("--scenery-name", type=str, default="Custom_Roads_Overlay",
                        help="Scenery paketi adı (varsayılan: Custom_Roads_Overlay)")
    parser.add_argument("--origin-lat", type=float,
                        help="Manuel başlangıç enlemi (TIF yoksa kullanılır)")
    parser.add_argument("--origin-lon", type=float,
                        help="Manuel başlangıç boylamı (TIF yoksa kullanılır)")
    parser.add_argument("--tile-divisor", type=int, default=512,
                        help="TIF piksel offset → grid index böleni (varsayılan: 512)")
    parser.add_argument("--no-exclude", action="store_true",
                        help="Varsayılan yolları silme (exclusion zone ekleme)")
    parser.add_argument("--config", type=str,
                        help="Config dosyası yolu (.ini)")

    args = parser.parse_args()

    # Config dosyasından eksik argümanları doldur
    cfg = load_config(args.config)
    if cfg.has_section("paths"):
        if not args.roads_dir:
            args.roads_dir = cfg.get("paths", "roads_dir", fallback=None)
        if not args.tifs_dir:
            args.tifs_dir = cfg.get("paths", "tifs_dir", fallback=None)
        if not args.output_dir:
            args.output_dir = cfg.get("paths", "output_dir", fallback=None)
    if cfg.has_section("settings"):
        if not args.origin_lat:
            args.origin_lat = cfg.getfloat("settings", "origin_lat", fallback=None)
        if not args.origin_lon:
            args.origin_lon = cfg.getfloat("settings", "origin_lon", fallback=None)
        args.tile_divisor = cfg.getint("settings", "tile_divisor", fallback=args.tile_divisor)
        args.scenery_name = cfg.get("settings", "scenery_name", fallback=args.scenery_name)

    # Zorunlu alanları kontrol et
    if not args.roads_dir:
        parser.error("--roads-dir gerekli. JSON dosyalarının bulunduğu klasörü belirtin.")
    if not args.output_dir:
        args.output_dir = os.path.join(os.path.dirname(args.roads_dir), "XPlane_Roads_Scenery")

    return args


# ═══════════════════════════════════════════════════════════════
# Yardımcı fonksiyonlar
# ═══════════════════════════════════════════════════════════════

def meters_to_degrees_lat(meters):
    return meters / 110540.0


def meters_to_degrees_lon(meters, latitude):
    return meters / (111320.0 * math.cos(math.radians(latitude)))


def road_type_to_subtype(road_type):
    """JSON'daki road type string → X-Plane draped subtype numarası."""
    if road_type == "asphalt":
        return DEFAULT_ASPHALT_SUBTYPE
    elif road_type == "dirt":
        return DEFAULT_DIRT_SUBTYPE
    else:
        return DEFAULT_ASPHALT_SUBTYPE


# ═══════════════════════════════════════════════════════════════
# ADIM 1: TIF'lerden georeferans bilgisi toplama
# ═══════════════════════════════════════════════════════════════

def collect_tile_bounds(tifs_dir, tile_divisor):
    """
    Tüm TIF dosyalarından WGS84 bounds bilgisi toplar.
    Key: (json_x, json_y) — JSON dosya adındaki grid indeksleri
    """
    if not HAS_RASTERIO:
        print("  rasterio yüklü değil, TIF'ler okunamıyor.")
        return None

    if not tifs_dir or not os.path.isdir(tifs_dir):
        print(f"  TIF klasörü bulunamadı: {tifs_dir}")
        return None

    bounds_map = {}
    tif_files = [f for f in os.listdir(tifs_dir) if f.lower().endswith(".tif")]
    print(f"  {len(tif_files)} TIF dosyası taranıyor...")

    for fn in tif_files:
        m = TILE_RE.search(fn)
        if not m:
            continue

        val1, val2 = int(m.group(1)), int(m.group(2))
        json_x = val2 // tile_divisor
        json_y = val1 // tile_divisor

        tif_path = os.path.join(tifs_dir, fn)
        try:
            with rasterio.open(tif_path) as src:
                left, bottom, right, top = src.bounds
                crs = src.crs

            if crs is None or crs.to_epsg() == 4326:
                wgs_bounds = (left, bottom, right, top)
            else:
                wgs_bounds = transform_bounds(
                    crs, "EPSG:4326", left, bottom, right, top, densify_pts=21
                )
            bounds_map[(json_x, json_y)] = wgs_bounds
        except Exception as e:
            print(f"  UYARI: {fn} okunamadı: {e}")

    print(f"  {len(bounds_map)} tile için bounds toplandı.")
    return bounds_map if bounds_map else None


def compute_manual_bounds(json_data, unity_x, unity_y, origin_lat, origin_lon):
    """TIF yoksa JSON metadata + grid pozisyonundan yaklaşık WGS84 bounds hesapla."""
    width_m = json_data.get("width_m", 500.0)
    height_m = json_data.get("height_m", 500.0)
    tx = json_data.get("tile_x", unity_x)
    ty = json_data.get("tile_y", unity_y)

    lat_offset = meters_to_degrees_lat(ty * height_m)
    lon_offset = meters_to_degrees_lon(tx * width_m, origin_lat)

    wgs_left = origin_lon + lon_offset
    wgs_bottom = origin_lat + lat_offset
    wgs_right = wgs_left + meters_to_degrees_lon(width_m, origin_lat + lat_offset)
    wgs_top = wgs_bottom + meters_to_degrees_lat(height_m)
    return (wgs_left, wgs_bottom, wgs_right, wgs_top)


# ═══════════════════════════════════════════════════════════════
# ADIM 2: JSON'ları oku → 1°×1° degree tile'larına grupla
# ═══════════════════════════════════════════════════════════════

def collect_roads_by_degree(json_files, tile_bounds, origin_lat, origin_lon):
    """
    Tüm JSON dosyalarını okur, her yol segmentini WGS84'e çevirir
    ve X-Plane 1°×1° grid'ine göre gruplar.
    Döndürür: {(deg_lat, deg_lon): [road_dicts]}
    """
    degree_tiles = defaultdict(list)
    processed = 0
    skipped = 0
    unmatched = 0

    for jf in json_files:
        fn = os.path.basename(jf)
        m = TILE_RE.search(fn)
        if not m:
            continue

        ux, uy = int(m.group(1)), int(m.group(2))

        with open(jf, "r", encoding="utf-8") as f:
            data = json.load(f)

        roads = data.get("roads", [])
        if not roads:
            skipped += 1
            continue

        # Tile bounds bul
        if tile_bounds and (ux, uy) in tile_bounds:
            wgs_left, wgs_bottom, wgs_right, wgs_top = tile_bounds[(ux, uy)]
        elif origin_lat is not None and origin_lon is not None:
            wgs_left, wgs_bottom, wgs_right, wgs_top = compute_manual_bounds(
                data, ux, uy, origin_lat, origin_lon
            )
            unmatched += 1
        else:
            unmatched += 1
            continue

        tile_w_deg = wgs_right - wgs_left
        tile_h_deg = wgs_top - wgs_bottom

        for road in roads:
            pts_uv = road.get("points", [])
            if len(pts_uv) < 2:
                continue

            subtype = road_type_to_subtype(road.get("type", "asphalt"))

            wgs_points = []
            for pt in pts_uv:
                lon = wgs_left + pt.get("u", 0) * tile_w_deg
                lat = wgs_bottom + pt.get("v", 0) * tile_h_deg
                wgs_points.append((lon, lat))

            mid_lon = (wgs_points[0][0] + wgs_points[-1][0]) / 2
            mid_lat = (wgs_points[0][1] + wgs_points[-1][1]) / 2
            deg_lon = int(math.floor(mid_lon))
            deg_lat = int(math.floor(mid_lat))

            degree_tiles[(deg_lat, deg_lon)].append({
                "subtype": subtype,
                "points": wgs_points,
            })

        processed += 1

    print(f"  {processed} tile işlendi, {skipped} boş atlandı, {unmatched} eşleşmedi")
    return degree_tiles


# ═══════════════════════════════════════════════════════════════
# ADIM 3: 1°×1° DSF text dosyası üretimi
# ═══════════════════════════════════════════════════════════════

def generate_dsf_text(deg_lat, deg_lon, roads, exclusion_bounds=None):
    """Bir 1°×1° tile için DSF text overlay üretir."""
    lines = [
        "A",
        "800",
        "DSF2TEXT",
        "",
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

    # Junction yönetimi
    junction_id = 1
    junction_map = {}
    MERGE_THRESH = 0.000005  # ~0.5 m

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

        sub = road["subtype"]
        s_lon, s_lat = pts[0]
        e_lon, e_lat = pts[-1]
        s_jid = get_junction(s_lon, s_lat)
        e_jid = get_junction(e_lon, e_lat)

        lines.append(f"BEGIN_SEGMENT 0 {sub} {s_jid} {s_lon:.9f} {s_lat:.9f} 0.0")
        for lon, lat in pts[1:-1]:
            lines.append(f"SHAPE_POINT {lon:.9f} {lat:.9f} 0.0")
        lines.append(f"END_SEGMENT {e_jid} {e_lon:.9f} {e_lat:.9f} 0.0")

    lines.append("")
    return "\n".join(lines)


def compute_exclusion(roads, margin=0.001):
    """Yolların kapsadığı bölgeden exclusion zone hesapla."""
    all_lons, all_lats = [], []
    for road in roads:
        for lon, lat in road["points"]:
            all_lons.append(lon)
            all_lats.append(lat)
    if not all_lons:
        return None
    return (
        min(all_lons) - margin,
        min(all_lats) - margin,
        max(all_lons) + margin,
        max(all_lats) + margin,
    )


# ═══════════════════════════════════════════════════════════════
# ADIM 4: Scenery paketi oluşturma
# ═══════════════════════════════════════════════════════════════

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


def write_scenery_package(output_dir, scenery_name, degree_tiles, exclude):
    """Tam scenery paketini yazar: DSF text + library.txt + batch script'ler."""
    pack_dir = os.path.join(output_dir, scenery_name)
    nav_dir = os.path.join(pack_dir, "Earth nav data")
    os.makedirs(nav_dir, exist_ok=True)

    # library.txt
    lib_path = os.path.join(pack_dir, "library.txt")
    if not os.path.exists(lib_path):
        with open(lib_path, "w") as f:
            f.write("A\n800\nLIBRARY\n\n")

    total_roads = 0
    for (deg_lat, deg_lon), roads in degree_tiles.items():
        folder = dsf_tile_folder(deg_lat, deg_lon)
        name = dsf_tile_filename(deg_lat, deg_lon)
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

    # convert_to_dsf.bat
    bat_path = os.path.join(pack_dir, "convert_to_dsf.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
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

    # convert_to_dsf.sh
    sh_path = os.path.join(pack_dir, "convert_to_dsf.sh")
    with open(sh_path, "w", encoding="utf-8", newline="\n") as f:
        f.write('#!/bin/bash\n')
        f.write('echo "DSF Text -> Binary dönüşümü başlatılıyor..."\n')
        f.write('find "Earth nav data" -name "*.txt" | while read txt; do\n')
        f.write('    dsf="${txt%.txt}.dsf"\n')
        f.write('    echo "Converting: $txt"\n')
        f.write('    DSFTool --text2dsf "$txt" "$dsf"\n')
        f.write('    [ $? -eq 0 ] && rm "$txt" && echo "OK: $dsf" || echo "HATA: $txt"\n')
        f.write('done\necho "Tamam!"\n')

    # Örnek config dosyası
    ini_path = os.path.join(pack_dir, "roads_to_xplane.ini.example")
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write("[paths]\n")
        f.write("# JSON dosyalarının bulunduğu klasör\n")
        f.write("roads_dir = ./road_jsons\n")
        f.write("# GeoTIFF dosyalarının bulunduğu klasör\n")
        f.write("tifs_dir = ./rgb_tifs\n")
        f.write("# Çıktı klasörü\n")
        f.write("output_dir = ./XPlane_Roads_Scenery\n\n")
        f.write("[settings]\n")
        f.write("# Scenery paketi adı\n")
        f.write("scenery_name = Custom_Roads_Overlay\n")
        f.write("# TIF piksel offset → grid index böleni\n")
        f.write("tile_divisor = 512\n")
        f.write("# Manuel georef (TIF yoksa kullanılır)\n")
        f.write("# origin_lat = 37.0\n")
        f.write("# origin_lon = 36.5\n")

    # README.md
    total_degree_tiles = len(degree_tiles)
    degree_summary = "\n".join(
        f"  - `{dsf_tile_folder(dlat, dlon)}/{dsf_tile_filename(dlat, dlon)}.dsf` — {len(roads)} yol segmenti"
        for (dlat, dlon), roads in degree_tiles.items()
    )
    readme_path = os.path.join(pack_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(f"""# {scenery_name}

X-Plane 12 Custom Roads Overlay — OSM verilerinden oluşturulmuş yol ağı.

## Genel Bilgi

- **Toplam yol segmenti:** {total_roads}
- **DSF tile sayısı:** {total_degree_tiles}
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

Bu paket `roads_to_xplane.py` ile oluşturulmuştur.

```bash
# Komut satırı argümanlarıyla
python roads_to_xplane.py \\
    --roads-dir ./road_jsons \\
    --tifs-dir ./rgb_tifs \\
    --output-dir ./XPlane_Roads_Scenery

# Config dosyasıyla
python roads_to_xplane.py --config roads_to_xplane.ini

# Exclusion zone olmadan
python roads_to_xplane.py --roads-dir ./jsons --tifs-dir ./tifs --no-exclude
```

### Argümanlar

| Argüman | Açıklama |
|---------|----------|
| `--roads-dir` | Yol JSON dosyalarının klasörü |
| `--tifs-dir` | GeoTIFF dosyalarının klasörü (georef için) |
| `--output-dir` | Çıktı klasörü |
| `--scenery-name` | Scenery paketi adı (varsayılan: Custom_Roads_Overlay) |
| `--origin-lat/lon` | Manuel georef koordinatları (TIF yoksa) |
| `--tile-divisor` | TIF piksel → grid index böleni (varsayılan: 512) |
| `--no-exclude` | Varsayılan yolları silme |
| `--config` | Config dosyası (.ini) yolu |

## Bağımlılıklar

- Python 3.8+
- `rasterio` (TIF georef için): `pip install rasterio`
- DSFTool (binary dönüşüm için)

## Yol Tipleri

| OSM Tipi | X-Plane Subtype | Görsel |
|----------|-----------------|--------|
| Asfalt (motorway, primary, secondary, residential...) | 30 (secondary) | Çizgili asfalt yol |
| Toprak (track, path, footway, service...) | 70 (single lane) | Dar toprak yol |
""")

    return pack_dir, total_roads


# ═══════════════════════════════════════════════════════════════
# Ana akış
# ═══════════════════════════════════════════════════════════════

def main():
    args = parse_args()

    print("=" * 60)
    print("Unity Yol JSON → X-Plane 12 DSF Overlay")
    print("=" * 60)

    # 1) JSON dosyalarını bul
    json_pattern = os.path.join(args.roads_dir, "tile_*_*_roads.json")
    json_files = sorted(glob.glob(json_pattern))
    print(f"\n[1/4] {len(json_files)} JSON dosyası bulundu.")
    if not json_files:
        print("HATA: Hiç JSON bulunamadı!")
        print(f"  Aranan yol: {json_pattern}")
        sys.exit(1)

    # 2) TIF'lerden georef topla
    print(f"\n[2/4] TIF georeferans bilgisi toplanıyor...")
    tile_bounds = collect_tile_bounds(args.tifs_dir, args.tile_divisor)

    if not tile_bounds and not args.origin_lat:
        print("HATA: TIF okunamadı ve --origin-lat/--origin-lon belirtilmedi!")
        print("  Georeferans için TIF veya manuel koordinat gerekli.")
        sys.exit(1)

    # 3) 1°×1° degree tile'larına grupla
    print(f"\n[3/4] Yollar 1°×1° tile'larına gruplandırılıyor...")
    degree_tiles = collect_roads_by_degree(
        json_files, tile_bounds, args.origin_lat, args.origin_lon
    )
    print(f"  {len(degree_tiles)} adet 1°×1° DSF tile oluşturulacak:")
    for (dlat, dlon), roads in degree_tiles.items():
        print(f"    ({dlat}°N, {dlon}°E) → {len(roads)} yol segmenti")

    # 4) Scenery paketi yaz
    print(f"\n[4/4] Scenery paketi oluşturuluyor...")
    use_exclude = not args.no_exclude
    pack_dir, total = write_scenery_package(
        args.output_dir, args.scenery_name, degree_tiles, use_exclude
    )

    print(f"\n{'=' * 60}")
    print(f"TAMAMLANDI! {total} yol segmenti yazıldı.")
    print(f"{'=' * 60}")
    print(f"\nÇıktı: {pack_dir}")
    print(f"\nSonraki adımlar:")
    print(f"  1) cd \"{pack_dir}\"")
    print(f"  2) convert_to_dsf.bat çalıştır (DSFTool gerekli)")
    print(f"  3) Klasörü X-Plane 12/Custom Scenery/ altına kopyala")
    print(f"  4) scenery_packs.ini'de en üste koy")


if __name__ == "__main__":
    main()
