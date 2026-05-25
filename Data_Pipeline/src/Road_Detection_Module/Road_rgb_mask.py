import os
import re
import numpy as np
import rasterio
from rasterio.features import rasterize
from PIL import Image
import osmnx as ox
import geopandas as gpd
from shapely.geometry import box
from osmnx._errors import InsufficientResponseError

TIFS_DIR = os.environ.get(
    "TIFS_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../outputs/RGB_tifs")),
)
OUT_DIR  = os.path.join(TIFS_DIR, "_roads_out_rgb") 
ROAD_WIDTH_M = 6.0

os.makedirs(OUT_DIR, exist_ok=True)
tile_re = re.compile(r"tile_(\d+)_(\d+)", re.IGNORECASE)

PAVED_TYPES = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'residential', 'living_street', 'unclassified', 'service']
UNPAVED_TYPES = ['track', 'path', 'footway', 'bridleway', 'cycleway', 'pedestrian', 'construction']

def compute_global_bbox(tif_paths):
    L = B = R = T = None
    for p in tif_paths:
        with rasterio.open(p) as src:
            left, bottom, right, top = src.bounds
        L = left  if L is None else min(L, left)
        B = bottom if B is None else min(B, bottom)
        R = right if R is None else max(R, right)
        T = top   if T is None else max(T, top)
    return (L, B, R, T)

def fetch_roads_once(global_bbox):
    left, bottom, right, top = global_bbox
    tags = {"highway": True}
    bbox = (left, bottom, right, top)
    try:
        try:
            gdf = ox.features_from_bbox(bbox=bbox, tags=tags)
        except TypeError:
            gdf = ox.features_from_bbox(bbox, tags)
    except InsufficientResponseError:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    
    gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    if gdf.crs is None: gdf = gdf.set_crs("EPSG:4326")
    return gdf

# --- BU FONKSİYON DÜZELTİLDİ ---
def make_rgb_mask_from_tif(tif_path, asphalt_gdf, dirt_gdf, road_width_m):
    with rasterio.open(tif_path) as src:
        left, bottom, right, top = src.bounds
        transform = src.transform
        out_shape = (src.height, src.width)

    # Boş bir RGB resim oluştur
    mask_rgb = np.zeros((out_shape[0], out_shape[1], 3), dtype=np.uint8)
    tile_poly = box(left, bottom, right, top)

    # --- 1. TOPRAK YOLLARI ÇİZ (YEŞİL KANAL) ---
    if len(dirt_gdf) > 0:
        try:
            clipped_dirt = gpd.clip(dirt_gdf, tile_poly)
        except:
            clipped_dirt = dirt_gdf[dirt_gdf.intersects(tile_poly)].copy()
        
        # DÜZELTME BURADA YAPILDI: .isEmpty YERİNE .empty
        if not clipped_dirt.empty:
            geom_dirt = clipped_dirt.geometry.union_all()
            buffered_dirt = ox.utils_geo.buffer_geometry(geom_dirt, dist=road_width_m / 2.0)
            mask_g = rasterize([(buffered_dirt, 255)], out_shape=out_shape, transform=transform, fill=0, dtype=np.uint8, all_touched=False)
            mask_rgb[:, :, 1] = mask_g

    # --- 2. ASFALT YOLLARI ÇİZ (KIRMIZI KANAL) ---
    if len(asphalt_gdf) > 0:
        try:
            clipped_asphalt = gpd.clip(asphalt_gdf, tile_poly)
        except:
            clipped_asphalt = asphalt_gdf[asphalt_gdf.intersects(tile_poly)].copy()

        # DÜZELTME BURADA YAPILDI: .isEmpty YERİNE .empty
        if not clipped_asphalt.empty:
            geom_asphalt = clipped_asphalt.geometry.union_all()
            buffered_asphalt = ox.utils_geo.buffer_geometry(geom_asphalt, dist=road_width_m / 2.0)
            mask_r = rasterize([(buffered_asphalt, 255)], out_shape=out_shape, transform=transform, fill=0, dtype=np.uint8, all_touched=False)
            mask_rgb[:, :, 0] = mask_r
            
            # Asfaltın olduğu yerden toprağı sil
            mask_rgb[:, :, 1] = np.where(mask_r > 0, 0, mask_rgb[:, :, 1])

    return mask_rgb

def main():
    tifs = [f for f in os.listdir(TIFS_DIR) if f.lower().endswith(".tif")]
    tifs.sort()
    
    if not tifs:
        print("TIF dosyasi bulunamadi!")
        return

    print(f"Toplam {len(tifs)} adet TIF bulundu. Koordinatlar analiz ediliyor...")

    # 1. KOORDINAT HARITALAMA
    all_x = set()
    all_y = set()
    file_coords = {}

    for fn in tifs:
        m = tile_re.search(fn)
        if m:
            val1 = int(m.group(1))
            val2 = int(m.group(2))
            all_x.add(val1)
            all_y.add(val2)
            file_coords[fn] = (val1, val2)

    sorted_x = sorted(list(all_x))
    sorted_y = sorted(list(all_y))

    map_x = {val: i for i, val in enumerate(sorted_x)}
    map_y = {val: i for i, val in enumerate(sorted_y)}

    # 2. VERİ ÇEKME
    tif_paths = [os.path.join(TIFS_DIR, f) for f in tifs]
    global_bbox = compute_global_bbox(tif_paths)
    print("OSM verisi indiriliyor...")
    roads_gdf = fetch_roads_once(global_bbox)
    
    # AYRIŞTIRMA
    if len(roads_gdf) > 0:
        roads_gdf['is_paved'] = roads_gdf['highway'].apply(lambda x: any(t in str(x) for t in PAVED_TYPES))
        asphalt_gdf = roads_gdf[roads_gdf['is_paved']].copy()
        dirt_gdf = roads_gdf[~roads_gdf['is_paved']].copy()
        print(f"Toplam Yol: {len(roads_gdf)} -> Asfalt: {len(asphalt_gdf)}, Toprak: {len(dirt_gdf)}")
    else:
        asphalt_gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        dirt_gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    for fn in tifs:
        if fn not in file_coords: continue

        real_1, real_2 = file_coords[fn]
        
        idx_1 = map_x[real_1]
        idx_2 = map_y[real_2]

        # Unity Swap
        unity_x = idx_2  
        unity_y = idx_1 

        print(f"tif: {fn} - mask png: tile_{unity_x}_{unity_y}_mask.png")

        tif_path = os.path.join(TIFS_DIR, fn)
        rgb_mask = make_rgb_mask_from_tif(tif_path, asphalt_gdf, dirt_gdf, ROAD_WIDTH_M)

        mask_name = f"tile_{unity_x}_{unity_y}_mask.png"
        mask_path = os.path.join(OUT_DIR, mask_name)
        
        Image.fromarray(rgb_mask).save(mask_path)

    print("\nmaskeler '_roads_out_rgb' klasorune kaydedildi.")

if __name__ == "__main__":
    main()
