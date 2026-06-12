"""
detect_buildings_geo.py
=======================
Run the Roboflow building-footprint-extract model over a folder of GeoTIFFs
and save results in the same JSON schema produced by segment_buildings.py.

Output JSON structure (mirrors segment_buildings.py exactly):
    {
      "config": { ... },
      "total_images": N,
      "total_buildings": N,
      "tiles": [
        {
          "source_file": "tile_0_1.tif",
          "image_width_px": 512,
          "image_height_px": 512,
          "crs_wkt": "...",
          "image_bounds_wgs84": { "top_left": [lat, lon], "bottom_right": [lat, lon] },
          "total_buildings": N,
          "buildings": [
            {
              "id": 0,
              "confidence": 0.87,
              "area_px": 1234.5,
              "rotation_degrees": -12.3,
              "width_px": 45.0,
              "height_px": 30.0,
              "center_lat": 39.123,
              "center_lon": 32.456,
              "polygon_native_crs": [[x, y], ...],
              "polygon_wgs84":      [[lat, lon], ...],
              "bbox_wgs84":         [[lat, lon], ...]   # 4 oriented-box corners
            }, ...
          ]
        }, ...
      ]
    }

Usage:
    python detect_buildings_geo.py \\
        --image_folder /path/to/geotiffs \\
        --output       detections.json \\
        --confidence   40 \\
        --workspace    robotrial \\
        --project      building-footprint-extract \\
        --version      3

Dependencies:
    pip install roboflow opencv-python numpy rasterio pyproj python-dotenv
    # or: pip install roboflow opencv-python numpy gdal pyproj python-dotenv
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# ── Roboflow ──────────────────────────────────────────────────────────────────
try:
    from roboflow import Roboflow
except ImportError:
    sys.exit("Install roboflow:  pip install roboflow")

# ── Geo backend (rasterio preferred, GDAL fallback) ───────────────────────────
try:
    import rasterio
    from rasterio.crs import CRS
    from pyproj import Transformer
    _GEO_BACKEND = "rasterio"
except ImportError:
    try:
        from osgeo import gdal, osr
        _GEO_BACKEND = "gdal"
    except ImportError:
        sys.exit("Install rasterio (pip install rasterio) or GDAL (pip install gdal).")


# ══════════════════════════════════════════════════════════════════════════════
# GeoTIFF reader  (identical to segment_buildings.py)
# ══════════════════════════════════════════════════════════════════════════════

class GeoTiffReader:
    def __init__(self, path: str):
        self.path = path
        self.image_bgr = None
        self.crs_wkt   = None
        self._load()

    def _load(self):
        if _GEO_BACKEND == "rasterio":
            self._load_rasterio()
        else:
            self._load_gdal()

    def _load_rasterio(self):
        with rasterio.open(self.path) as src:
            self._transform = src.transform
            self.crs_wkt = src.crs.to_wkt() if src.crs else None

            bands = src.count
            if bands >= 3:
                r = src.read(1).astype(np.uint8)
                g = src.read(2).astype(np.uint8)
                b = src.read(3).astype(np.uint8)
                self.image_bgr = cv2.merge([b, g, r])
            elif bands == 1:
                gray = src.read(1).astype(np.uint8)
                self.image_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            else:
                raise ValueError(f"Unsupported band count: {bands}")

            wgs84 = CRS.from_epsg(4326)
            if src.crs and src.crs != wgs84:
                t = Transformer.from_crs(src.crs, wgs84, always_xy=True)
                self._crs_to_wgs84 = t.transform
            else:
                self._crs_to_wgs84 = lambda x, y: (x, y)

            self._pixel_to_crs = self._ptc_rasterio

    def _ptc_rasterio(self, col, row):
        t = self._transform
        return t.c + col * t.a + row * t.b, t.f + col * t.d + row * t.e

    def _load_gdal(self):
        ds = gdal.Open(self.path, gdal.GA_ReadOnly)
        if ds is None:
            raise FileNotFoundError(f"GDAL could not open '{self.path}'")
        self._gt = ds.GetGeoTransform()

        src_srs = osr.SpatialReference()
        src_srs.ImportFromWkt(ds.GetProjection())
        self.crs_wkt = src_srs.ExportToWkt()

        bands = ds.RasterCount
        if bands >= 3:
            r = ds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
            g = ds.GetRasterBand(2).ReadAsArray().astype(np.uint8)
            b = ds.GetRasterBand(3).ReadAsArray().astype(np.uint8)
            self.image_bgr = cv2.merge([b, g, r])
        elif bands == 1:
            gray = ds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
            self.image_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        else:
            raise ValueError(f"Unsupported band count: {bands}")

        tgt_srs = osr.SpatialReference()
        tgt_srs.ImportFromEPSG(4326)
        tgt_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ct = osr.CoordinateTransformation(src_srs, tgt_srs)

        if src_srs.IsGeographic() and src_srs.GetAttrValue("AUTHORITY", 1) == "4326":
            self._crs_to_wgs84 = lambda x, y: (x, y)
        else:
            self._crs_to_wgs84 = lambda x, y: (ct.TransformPoint(x, y)[0],
                                                ct.TransformPoint(x, y)[1])
        ds = None
        self._pixel_to_crs = self._ptc_gdal

    def _ptc_gdal(self, col, row):
        gt = self._gt
        return (gt[0] + col * gt[1] + row * gt[2],
                gt[3] + col * gt[4] + row * gt[5])

    def pixel_to_native_crs(self, col, row):
        return self._pixel_to_crs(float(col), float(row))

    def pixel_to_wgs84(self, col, row):
        x, y = self._pixel_to_crs(float(col), float(row))
        lon, lat = self._crs_to_wgs84(x, y)
        return round(lat, 8), round(lon, 8)

    def image_bounds(self):
        h, w = self.image_bgr.shape[:2]
        return {
            'top_left':     list(self.pixel_to_wgs84(0,   0)),
            'bottom_right': list(self.pixel_to_wgs84(w-1, h-1)),
        }

    def image_size(self):
        h, w = self.image_bgr.shape[:2]
        return w, h


# ══════════════════════════════════════════════════════════════════════════════
# Roboflow detection engine
# ══════════════════════════════════════════════════════════════════════════════

class RoboflowEngine:
    def __init__(self, api_key: str, workspace: str, project: str, version: int):
        rf = Roboflow(api_key=api_key)
        proj = rf.workspace(workspace).project(project)
        self.model = proj.version(version).model
        print(f"Roboflow model loaded  ({workspace}/{project} v{version})")

    def predict(self, image_path: str, confidence: int) -> dict:
        """Return raw Roboflow JSON predictions for a single image."""
        return self.model.predict(image_path, confidence=confidence).json()


# ══════════════════════════════════════════════════════════════════════════════
# Prediction → geo-referenced buildings
# ══════════════════════════════════════════════════════════════════════════════

def _polygon_points(pred: dict) -> np.ndarray | None:
    """
    Return pixel-space polygon as (N, 2) int32 array.
    Handles both instance-segmentation ('points') and bounding-box predictions.
    """
    if 'points' in pred:
        pts = np.array([[p['x'], p['y']] for p in pred['points']], dtype=np.int32)
        return pts if len(pts) >= 3 else None

    # Bounding box fallback → synthesise 4-corner polygon
    x, y = int(pred['x']), int(pred['y'])
    w, h = int(pred['width']), int(pred['height'])
    x1, y1 = x - w // 2, y - h // 2
    x2, y2 = x + w // 2, y + h // 2
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.int32)


def predictions_to_buildings(predictions: dict, geo: GeoTiffReader) -> list[dict]:
    """
    Convert Roboflow predictions into the same per-building dict schema that
    segment_buildings.py produces.
    """
    buildings = []
    raw_preds = predictions.get('predictions', [])

    for idx, pred in enumerate(raw_preds):
        pts = _polygon_points(pred)
        if pts is None:
            continue

        # Pixel-space geometry
        area_px  = float(cv2.contourArea(pts))
        rect     = cv2.minAreaRect(pts)          # ((cx, cy), (w, h), angle)
        box_pts  = np.int32(cv2.boxPoints(rect)) # 4 oriented-box corners

        cx_px, cy_px = rect[0]
        w_px, h_px   = rect[1]
        angle        = rect[2]

        box_area  = w_px * h_px if w_px * h_px > 0 else 1.0
        # Use Roboflow confidence when available; supplement with fill ratio
        rf_conf   = float(pred.get('confidence', 0.0))

        # --- Geo conversion ---
        cx_lat, cx_lon = geo.pixel_to_wgs84(cx_px, cy_px)

        polygon_native = [
            list(geo.pixel_to_native_crs(float(p[0]), float(p[1])))
            for p in pts
        ]
        polygon_wgs84 = [
            list(geo.pixel_to_wgs84(float(p[0]), float(p[1])))
            for p in pts
        ]
        bbox_wgs84 = [
            list(geo.pixel_to_wgs84(float(p[0]), float(p[1])))
            for p in box_pts
        ]

        buildings.append({
            'id':                 idx,
            'confidence':         round(rf_conf, 4),
            'area_px':            round(area_px, 1),
            'rotation_degrees':   round(float(angle), 2),
            'width_px':           round(float(w_px), 1),
            'height_px':          round(float(h_px), 1),
            'center_lat':         cx_lat,
            'center_lon':         cx_lon,
            'class':              pred.get('class', 'building'),
            # Full polygon rings
            'polygon_native_crs': polygon_native,  # [[x, y], ...]
            'polygon_wgs84':      polygon_wgs84,   # [[lat, lon], ...]
            # Oriented bounding box (4 corners)
            'bbox_wgs84':         bbox_wgs84,      # [[lat, lon], ...]
        })

    return buildings


# ══════════════════════════════════════════════════════════════════════════════
# Per-image pipeline
# ══════════════════════════════════════════════════════════════════════════════

def process_image(
    image_path: Path,
    engine: RoboflowEngine,
    confidence: int,
) -> dict | None:
    print(f"  {image_path.name}", end=" ... ", flush=True)

    try:
        geo = GeoTiffReader(str(image_path))
    except Exception as e:
        print(f"SKIP ({e})")
        return None

    try:
        raw = engine.predict(str(image_path), confidence=confidence)
    except Exception as e:
        print(f"SKIP — Roboflow error ({e})")
        return None

    buildings = predictions_to_buildings(raw, geo)
    w, h = geo.image_size()
    print(f"{len(buildings)} building(s)")

    return {
        'source_file':        image_path.name,
        'image_width_px':     w,
        'image_height_px':    h,
        'crs_wkt':            geo.crs_wkt,
        'image_bounds_wgs84': geo.image_bounds(),
        'total_buildings':    len(buildings),
        'buildings':          buildings,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run Roboflow building detection over a folder of GeoTIFFs and save\n"
            "polygon results to a JSON file compatible with segment_buildings.py."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--image_folder", required=True,
                        help="Folder containing GeoTIFF (.tif/.tiff/.png) files")
    parser.add_argument("--output", default="detections.json",
                        help="Output JSON path (default: detections.json)")
    parser.add_argument("--confidence", type=int, default=40,
                        help="Roboflow confidence threshold 0-100 (default: 40)")
    parser.add_argument("--api_key", default=None,
                        help="Roboflow API key (overrides ROBOFLOW_API_KEY env var)")
    parser.add_argument("--workspace", default="robotrial",
                        help="Roboflow workspace slug (default: robotrial)")
    parser.add_argument("--project", default="building-footprint-extract",
                        help="Roboflow project slug (default: building-footprint-extract)")
    parser.add_argument("--version", type=int, default=3,
                        help="Model version number (default: 3)")
    args = parser.parse_args()

    # API key resolution: CLI > env var > hardcoded fallback (remove in prod)
    api_key = args.api_key or os.environ.get("ROBOFLOW_API_KEY", "")
    if not api_key:
        sys.exit(
            "Roboflow API key required.\n"
            "  Pass --api_key KEY  or  set ROBOFLOW_API_KEY=KEY in environment."
        )

    image_extensions = {'.tif', '.tiff', '.png', '.jpg', '.jpeg'}
    image_paths = sorted(
        f for f in Path(args.image_folder).iterdir()
        if f.suffix.lower() in image_extensions
    )
    if not image_paths:
        sys.exit(f"No supported image files found in: {args.image_folder}")

    engine = RoboflowEngine(api_key, args.workspace, args.project, args.version)

    print(f"\nProcessing {len(image_paths)} image(s)  "
          f"(confidence ≥ {args.confidence})...\n")

    results = []
    for img_path in image_paths:
        result = process_image(img_path, engine, args.confidence)
        if result:
            results.append(result)

    total_buildings = sum(r['total_buildings'] for r in results)
    print(f"\nTotal buildings detected: {total_buildings}")

    output = {
        'config': {
            'backend':    'roboflow',
            'workspace':  args.workspace,
            'project':    args.project,
            'version':    args.version,
            'confidence': args.confidence,
        },
        'total_images':    len(results),
        'total_buildings': total_buildings,
        'tiles':           results,
    }

    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Detection JSON saved → {args.output}")


# ── missing import (os) added at module level ─────────────────────────────────
import os  # noqa: E402  (intentionally placed after class defs for readability)

if __name__ == "__main__":
    main()