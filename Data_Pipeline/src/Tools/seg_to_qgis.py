"""
seg_to_qgis.py
==============
Convert segmentation.json (from segment_buildings.py) into a GeoPackage
(.gpkg) for visualisation in QGIS.

Each detected building becomes a polygon feature with all attributes
(confidence, area, rotation, dimensions, center coords) attached as
fields so you can style/filter by them in QGIS.

Output: one .gpkg file containing a single layer "buildings"

Usage:
    py seg_to_qgis.py --segmentation segmentation.json --output buildings.gpkg

    # Keep only high-confidence detections
    py seg_to_qgis.py --segmentation segmentation.json --output buildings.gpkg --min_confidence 0.75

Dependencies:
    pip install geopandas shapely
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    import geopandas as gpd
    from shapely.geometry import Polygon
except ImportError:
    sys.exit("Install geopandas + shapely:  pip install geopandas shapely")


def load_segmentation(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    print(f"Loaded: {path}")
    print(f"  {data['total_images']} tile(s), {data['total_buildings']} building(s)")
    return data


def build_geodataframe(seg_data: dict, min_confidence: float = 0.0) -> gpd.GeoDataFrame:
    """
    Convert all buildings from all tiles into a single GeoDataFrame (WGS84).
    Uses polygon_wgs84 so it loads correctly in QGIS regardless of tile CRS.
    """
    rows = []

    for tile in seg_data.get('tiles', []):
        source = tile['source_file']
        for b in tile.get('buildings', []):
            if b['confidence'] < min_confidence:
                continue

            ring = b.get('polygon_wgs84', [])
            if len(ring) < 3:
                continue

            # polygon_wgs84 is [[lat, lon], ...] — Shapely needs (lon, lat)
            try:
                poly = Polygon([(pt[1], pt[0]) for pt in ring])
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.is_empty:
                    continue
            except Exception:
                continue

            rows.append({
                'geometry':         poly,
                'source_file':      source,
                'building_id':      b['id'],
                'confidence':       round(b['confidence'], 4),
                'area_px':          round(b['area_px'], 1),
                'width_px':         round(b['width_px'], 1),
                'height_px':        round(b['height_px'], 1),
                'rotation_deg':     round(b['rotation_degrees'], 2),
                'center_lat':       b['center_lat'],
                'center_lon':       b['center_lon'],
            })

    if not rows:
        print("No buildings passed the confidence filter — nothing to write.")
        sys.exit(0)

    geoms = [r.pop('geometry') for r in rows]
    gdf   = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    return gdf


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Convert segmentation.json to a GeoPackage for QGIS visualisation.\n"
            "Each building polygon is a feature with confidence, area, rotation, etc."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--segmentation", required=True,
        help="Path to segmentation.json from segment_buildings.py"
    )
    parser.add_argument(
        "--output", default="buildings.gpkg",
        help="Output GeoPackage path (default: buildings.gpkg)"
    )
    parser.add_argument(
        "--min_confidence", type=float, default=0.0,
        help="Drop buildings below this confidence (default: 0.0 — keep all)"
    )
    parser.add_argument(
        "--format", choices=["gpkg", "shp", "geojson"], default="gpkg",
        help="Output format: gpkg (default), shp, or geojson"
    )
    args = parser.parse_args()

    # Force correct extension
    out = Path(args.output)
    ext_map = {"gpkg": ".gpkg", "shp": ".shp", "geojson": ".geojson"}
    out = out.with_suffix(ext_map[args.format])

    seg_data = load_segmentation(args.segmentation)
    gdf      = build_geodataframe(seg_data, args.min_confidence)

    print(f"\n{len(gdf)} building(s) after confidence filter (≥ {args.min_confidence})")

    # Confidence breakdown
    bins   = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    labels = ["<0.5", "0.5–0.6", "0.6–0.7", "0.7–0.8", "0.8–0.9", "0.9–1.0"]
    counts = np.histogram(gdf['confidence'], bins=bins)[0]
    print("\n  Confidence distribution:")
    for label, count in zip(labels, counts):
        bar = "█" * (count * 30 // max(counts, default=1))
        print(f"    {label:>8}  {bar} {count}")

    # Write
    if args.format == "gpkg":
        gdf.to_file(str(out), layer="buildings", driver="GPKG")
    elif args.format == "shp":
        gdf.to_file(str(out), driver="ESRI Shapefile")
    elif args.format == "geojson":
        gdf.to_file(str(out), driver="GeoJSON")

    print(f"\nSaved → {out}")
    print("\nTo load in QGIS:")
    print("  Layer > Add Layer > Add Vector Layer, or drag the file into the QGIS window.")
    if args.format == "gpkg":
        print('  Select the "buildings" layer when prompted.')
    print("\nSuggested styling in QGIS:")
    print("  Right-click layer > Properties > Symbology")
    print('  Set to "Graduated" on the "confidence" field to colour by detection quality.')


if __name__ == "__main__":
    main()