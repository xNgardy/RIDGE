"""
segment_buildings.py
====================
Run the RAMP XUNet ONNX model over a folder of GeoTIFFs and save
segmentation results (polygons in native CRS + WGS84) to a JSON file.

The output JSON is consumed by evaluate_buildings.py for metric computation.

Usage:
    python segment_buildings.py \
        --image_folder /path/to/geotiffs \
        --model        ramp_xunet.onnx \
        --output       segmentation.json \
        --confidence   0.0

Dependencies:
    pip install onnxruntime opencv-python numpy rasterio pyproj
"""

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

try:
    import onnxruntime as ort
except ImportError:
    sys.exit("Install onnxruntime:  pip install onnxruntime")

# ── Geo backend ───────────────────────────────────────────────────────────────
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

# ── Constants ─────────────────────────────────────────────────────────────────
BUILDING_CLASS_ID = 1
TILE_SIZE         = 256
TILE_OVERLAP      = 100
SEG_THRESH        = 0.4
MIN_CONTOUR_AREA  = 400


# ══════════════════════════════════════════════════════════════════════════════
# GeoTIFF reader
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
# Inference engine
# ══════════════════════════════════════════════════════════════════════════════

class BuildingInferenceEngine:
    def __init__(self, model_path: str):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ONNX model not found: '{model_path}'")
        self.session = ort.InferenceSession(
            model_path,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        self.input_name  = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        print(f"Model loaded: {model_path}")

    def _preprocess(self, tile_bgr):
        rgb  = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2RGB)
        res  = cv2.resize(rgb, (TILE_SIZE, TILE_SIZE))
        norm = res.astype(np.float32) / 255.0
        chw  = np.transpose(norm, (2, 0, 1))
        return np.expand_dims(chw, axis=0)

    def run(self, image: np.ndarray) -> np.ndarray:
        """Return (H, W) float32 probability map in [0, 1]."""
        orig_h, orig_w = image.shape[:2]
        step = TILE_SIZE - TILE_OVERLAP

        accum  = np.zeros((orig_h, orig_w), dtype=np.float32)
        counts = np.zeros((orig_h, orig_w), dtype=np.float32)

        y_starts = list(range(0, orig_h, step))
        x_starts = list(range(0, orig_w, step))
        if not y_starts or y_starts[-1] + TILE_SIZE < orig_h:
            y_starts.append(max(orig_h - TILE_SIZE, 0))
        if not x_starts or x_starts[-1] + TILE_SIZE < orig_w:
            x_starts.append(max(orig_w - TILE_SIZE, 0))

        for y0 in y_starts:
            y1 = min(y0 + TILE_SIZE, orig_h)
            y0 = max(y1 - TILE_SIZE, 0)
            for x0 in x_starts:
                x1 = min(x0 + TILE_SIZE, orig_w)
                x0 = max(x1 - TILE_SIZE, 0)

                tile   = image[y0:y1, x0:x1]
                tensor = self._preprocess(tile)
                output = self.session.run(
                    [self.output_name], {self.input_name: tensor}
                )[0]

                if output.shape[1] == 2:
                    exp  = np.exp(output[0] - output[0].max(axis=0, keepdims=True))
                    prob = (exp / exp.sum(axis=0))[BUILDING_CLASS_ID]
                elif output.shape[1] == 1:
                    prob = 1.0 / (1.0 + np.exp(-output[0, 0]))
                else:
                    prob = np.argmax(output[0], axis=0).astype(np.float32)

                prob_resized = cv2.resize(prob, (x1 - x0, y1 - y0))
                accum[y0:y1, x0:x1]  += prob_resized
                counts[y0:y1, x0:x1] += 1.0

        return accum / np.maximum(counts, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# Segmentation extraction
# ══════════════════════════════════════════════════════════════════════════════

def extract_building_polygons(
    prob_map: np.ndarray,
    geo: GeoTiffReader,
    confidence_threshold: float = 0.0,
) -> list[dict]:
    """
    Threshold → clean → contours → per-building dicts containing:
        polygon_native_crs : [[x, y], ...] ring in image's native CRS
        polygon_wgs84      : [[lat, lon], ...] ring in WGS84
        confidence         : float fill ratio
        area_px            : float contour area in pixels
    """
    binary = (prob_map >= SEG_THRESH).astype(np.uint8) * 255

    # Remove small blobs
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    cleaned = np.zeros_like(binary)
    for lbl in range(1, n_labels):
        if stats[lbl, cv2.CC_STAT_AREA] >= MIN_CONTOUR_AREA:
            cleaned[labels == lbl] = 255

    contours, _ = cv2.findContours(
        cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    buildings = []
    for idx, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < MIN_CONTOUR_AREA:
            continue

        rect     = cv2.minAreaRect(cnt)
        w, h     = rect[1]
        box_area = w * h if w * h > 0 else 1
        confidence = float(area) / float(box_area)

        if confidence < confidence_threshold:
            continue

        px_pts = cnt.squeeze()
        if px_pts.ndim == 1:
            px_pts = px_pts[np.newaxis, :]
        if len(px_pts) < 3:
            continue

        native_ring = [
            list(geo.pixel_to_native_crs(float(p[0]), float(p[1])))
            for p in px_pts
        ]
        wgs84_ring = [
            list(geo.pixel_to_wgs84(float(p[0]), float(p[1])))
            for p in px_pts
        ]

        # Min-area bounding box corners (WGS84) for X-Plane compatibility
        box_px    = np.int32(cv2.boxPoints(rect))
        box_wgs84 = [list(geo.pixel_to_wgs84(float(p[0]), float(p[1])))
                     for p in box_px]

        cx_lat, cx_lon = geo.pixel_to_wgs84(rect[0][0], rect[0][1])

        buildings.append({
            'id':                  idx,
            'confidence':          round(confidence, 4),
            'area_px':             round(float(area), 1),
            'rotation_degrees':    round(float(rect[2]), 2),
            'width_px':            round(float(w), 1),
            'height_px':           round(float(h), 1),
            'center_lat':          cx_lat,
            'center_lon':          cx_lon,
            # Full polygon rings
            'polygon_native_crs':  native_ring,  # [[x, y], ...]
            'polygon_wgs84':       wgs84_ring,   # [[lat, lon], ...]
            # Oriented bounding box (4 corners)
            'bbox_wgs84':          box_wgs84,    # [[lat, lon], ...]
        })

    return buildings


# ══════════════════════════════════════════════════════════════════════════════
# Per-image pipeline
# ══════════════════════════════════════════════════════════════════════════════

def process_image(
    image_path: Path,
    engine: BuildingInferenceEngine,
    confidence_threshold: float = 0.0,
) -> dict | None:
    print(f"  {image_path.name}", end=" ... ", flush=True)

    try:
        geo = GeoTiffReader(str(image_path))
    except Exception as e:
        print(f"SKIP ({e})")
        return None

    prob_map  = engine.run(geo.image_bgr)
    buildings = extract_building_polygons(prob_map, geo, confidence_threshold)

    w, h = geo.image_size()
    print(f"{len(buildings)} building(s)")

    return {
        'source_file':    image_path.name,
        'image_width_px': w,
        'image_height_px': h,
        'crs_wkt':        geo.crs_wkt,
        'image_bounds_wgs84': geo.image_bounds(),
        'total_buildings': len(buildings),
        'buildings':       buildings,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run RAMP XUNet ONNX building segmentation over a folder of GeoTIFFs\n"
            "and save polygon results to a JSON file for downstream evaluation."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--image_folder", required=True,
        help="Folder containing GeoTIFF (.tif/.tiff) files"
    )
    parser.add_argument(
        "--model", default="ramp_xunet.onnx",
        help="Path to ONNX model file (default: ramp_xunet.onnx)"
    )
    parser.add_argument(
        "--confidence", type=float, default=0.0,
        help="Minimum fill-ratio confidence to keep a detection (0–1, default: 0.0)"
    )
    parser.add_argument(
        "--output", default="segmentation.json",
        help="Output JSON path (default: segmentation.json)"
    )
    args = parser.parse_args()

    image_paths = sorted(
        f for f in Path(args.image_folder).iterdir()
        if f.suffix.lower() in {'.tif', '.tiff'}
    )
    if not image_paths:
        sys.exit(f"No TIFF files found in {args.image_folder}")

    engine = BuildingInferenceEngine(args.model)

    print(f"\nProcessing {len(image_paths)} GeoTIFF(s)...")
    results = []
    for img_path in image_paths:
        result = process_image(img_path, engine, args.confidence)
        if result:
            results.append(result)

    total_buildings = sum(r['total_buildings'] for r in results)
    print(f"\nTotal buildings detected: {total_buildings}")

    output = {
        'config': {
            'model':            args.model,
            'seg_threshold':    SEG_THRESH,
            'min_contour_area': MIN_CONTOUR_AREA,
            'confidence':       args.confidence,
        },
        'total_images':    len(results),
        'total_buildings': total_buildings,
        'tiles':           results,
    }

    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Segmentation JSON saved → {args.output}")


if __name__ == "__main__":
    main()