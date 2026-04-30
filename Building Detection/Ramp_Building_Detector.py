"""
Offline Building Footprint Detection using Deepness RAMP XUNet ONNX model
GeoTIFF input, WGS84 (lat/lon) coordinate output — compatible with X-Plane.

Model: ramp_xunet_*.onnx  (from Deepness Model Zoo)
Classes: 0=Background, 1=Building
Expected input resolution: 50 cm/px satellite imagery
Tile size: 256x256 px  |  Overlap: 25 px  |  Seg threshold: 0.2

Geo dependencies (tried in order):
    1. rasterio  (pip install rasterio)
    2. GDAL/osgeo (pip install gdal)
"""

import cv2
import numpy as np
import onnxruntime as ort
import json
import argparse
import os
from pathlib import Path

# ── Geo backend (rasterio preferred, GDAL fallback) ───────────────────────────

_GEO_BACKEND = None  # set by _init_geo_backend()

def _init_geo_backend():
    global _GEO_BACKEND
    if _GEO_BACKEND is not None:
        return
    try:
        import rasterio  # noqa: F401
        _GEO_BACKEND = "rasterio"
        return
    except ImportError:
        pass
    try:
        from osgeo import gdal  # noqa: F401
        _GEO_BACKEND = "gdal"
        return
    except ImportError:
        pass
    raise ImportError(
        "No geo library found. Install rasterio (pip install rasterio) "
        "or GDAL (pip install gdal)."
    )


class GeoTiffReader:
    """
    Thin wrapper that reads a GeoTIFF and exposes:
      - image_bgr : np.ndarray  (H, W, 3) uint8
      - transform : affine or tuple for pixel→CRS conversion
      - crs_to_wgs84 : callable(x, y) -> (lon, lat)
    """

    def __init__(self, path: str):
        _init_geo_backend()
        self.path = path
        self._transform = None
        self._crs_to_wgs84 = None
        self.image_bgr = None
        self._load()

    def _load(self):
        if _GEO_BACKEND == "rasterio":
            self._load_rasterio()
        else:
            self._load_gdal()

    # ── rasterio path ─────────────────────────────────────────────────────────

    def _load_rasterio(self):
        import rasterio
        from rasterio.crs import CRS
        from pyproj import Transformer

        with rasterio.open(self.path) as src:
            self._transform = src.transform
            src_crs = src.crs

            # Read first three bands as BGR
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
            if src_crs and src_crs != wgs84:
                transformer = Transformer.from_crs(
                    src_crs, wgs84, always_xy=True
                )
                self._crs_to_wgs84 = transformer.transform
            else:
                # Already WGS84 — identity
                self._crs_to_wgs84 = lambda x, y: (x, y)

            self._pixel_to_crs = self._pixel_to_crs_rasterio

    def _pixel_to_crs_rasterio(self, col: float, row: float):
        """Convert pixel (col, row) → CRS (x, y) using affine transform."""
        t = self._transform
        x = t.c + col * t.a + row * t.b
        y = t.f + col * t.d + row * t.e
        return x, y

    # ── GDAL path ─────────────────────────────────────────────────────────────

    def _load_gdal(self):
        from osgeo import gdal, osr

        ds = gdal.Open(self.path, gdal.GA_ReadOnly)
        if ds is None:
            raise FileNotFoundError(f"GDAL could not open '{self.path}'")

        self._gt = ds.GetGeoTransform()  # (x0, dx, 0, y0, 0, dy)

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

        src_srs = osr.SpatialReference()
        src_srs.ImportFromWkt(ds.GetProjection())
        tgt_srs = osr.SpatialReference()
        tgt_srs.ImportFromEPSG(4326)
        tgt_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

        coord_transform = osr.CoordinateTransformation(src_srs, tgt_srs)

        def _to_wgs84(x, y):
            lon, lat, _ = coord_transform.TransformPoint(x, y)
            return lon, lat

        if src_srs.IsGeographic() and src_srs.GetAttrValue("AUTHORITY", 1) == "4326":
            self._crs_to_wgs84 = lambda x, y: (x, y)
        else:
            self._crs_to_wgs84 = _to_wgs84

        ds = None  # close dataset
        self._pixel_to_crs = self._pixel_to_crs_gdal

    def _pixel_to_crs_gdal(self, col: float, row: float):
        gt = self._gt
        x = gt[0] + col * gt[1] + row * gt[2]
        y = gt[3] + col * gt[4] + row * gt[5]
        return x, y

    # ── Public API ────────────────────────────────────────────────────────────

    def pixel_to_wgs84(self, col: float, row: float) -> tuple:
        """
        Convert pixel coordinates (col=x, row=y) to (lat, lon) WGS84.
        X-Plane convention: latitude first, then longitude.
        """
        crs_x, crs_y = self._pixel_to_crs(col, row)
        lon, lat = self._crs_to_wgs84(crs_x, crs_y)
        return round(lat, 8), round(lon, 8)

    def pixels_to_wgs84_list(self, pixel_points: list) -> list:
        """Convert a list of [col, row] pixel pairs to [[lat, lon], ...] WGS84."""
        return [list(self.pixel_to_wgs84(pt[0], pt[1])) for pt in pixel_points]


# ── Model constants from ONNX metadata ───────────────────────────────────────

BUILDING_CLASS_ID = 1
TILE_SIZE         = 256
TILE_OVERLAP      = 25
SEG_THRESH        = 0.4   # minimum building probability to count as building
MIN_CONTOUR_AREA  = 400   # drop blobs smaller than this (px²)


class BuildingDetector:
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.session = None
        self.json_list = []
        self.load_model()

    def load_model(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"ONNX model not found at '{self.model_path}'.")
        self.session = ort.InferenceSession(
            self.model_path,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        self.input_name  = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        print(f"Model loaded: {self.model_path}")

    # ── Preprocessing ─────────────────────────────────────────────────────────

    def _preprocess_tile(self, tile_bgr: np.ndarray) -> np.ndarray:
        """BGR tile → (1, 3, 256, 256) float32 tensor, normalized to [0, 1]."""
        rgb        = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2RGB)
        resized    = cv2.resize(rgb, (TILE_SIZE, TILE_SIZE))
        normalized = resized.astype(np.float32) / 255.0
        chw        = np.transpose(normalized, (2, 0, 1))
        return np.expand_dims(chw, axis=0)

    # ── Tiled inference ───────────────────────────────────────────────────────

    def run_inference(self, image: np.ndarray) -> np.ndarray:
        """
        Run tiled inference over a full image with overlap blending.

        Returns:
            building_prob: float32 array (H, W) with values in [0, 1]
        """
        orig_h, orig_w = image.shape[:2]
        step = TILE_SIZE - TILE_OVERLAP

        accum  = np.zeros((orig_h, orig_w), dtype=np.float32)
        counts = np.zeros((orig_h, orig_w), dtype=np.float32)

        y_starts = list(range(0, orig_h, step))
        x_starts = list(range(0, orig_w, step))

        if y_starts[-1] + TILE_SIZE < orig_h:
            y_starts.append(orig_h - TILE_SIZE)
        if x_starts[-1] + TILE_SIZE < orig_w:
            x_starts.append(orig_w - TILE_SIZE)

        for y0 in y_starts:
            y1 = min(y0 + TILE_SIZE, orig_h)
            y0 = max(y1 - TILE_SIZE, 0)

            for x0 in x_starts:
                x1 = min(x0 + TILE_SIZE, orig_w)
                x0 = max(x1 - TILE_SIZE, 0)

                tile   = image[y0:y1, x0:x1]
                tensor = self._preprocess_tile(tile)

                output = self.session.run([self.output_name], {self.input_name: tensor})[0]
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

        counts = np.maximum(counts, 1.0)
        return accum / counts

    # ── Mask generation ───────────────────────────────────────────────────────

    def probability_to_mask(self, building_prob: np.ndarray) -> np.ndarray:
        """Apply seg_thresh and remove small segments. Returns uint8 mask (0/255)."""
        binary = (building_prob >= SEG_THRESH).astype(np.uint8) * 255

        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        cleaned = np.zeros_like(binary)
        for label in range(1, n_labels):
            if stats[label, cv2.CC_STAT_AREA] >= MIN_CONTOUR_AREA:
                cleaned[labels == label] = 255

        return cleaned

    # ── Contour / rectangle extraction ───────────────────────────────────────

    def extract_contours(self, building_mask: np.ndarray):
        contours, _ = cv2.findContours(
            building_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        return contours

    def polygon_to_rectangle(self, contour: np.ndarray) -> dict:
        rect = cv2.minAreaRect(contour)
        box  = np.int32(cv2.boxPoints(rect))
        return {'box': box, 'center': rect[0], 'size': rect[1], 'angle': rect[2]}

    def contours_to_rectangles(
        self,
        contours,
        geo: GeoTiffReader,
        confidence_thresh: float = 0.0,
    ) -> list:
        """
        Convert contours to rectangle dicts with WGS84 coordinates.

        corner_points: four [[lat, lon], ...] pairs (WGS84, X-Plane order)
        center_lat/center_lon: WGS84 centroid
        """
        rectangles = []
        for idx, cnt in enumerate(contours):
            area = cv2.contourArea(cnt)
            if area < MIN_CONTOUR_AREA:
                continue

            rd       = self.polygon_to_rectangle(cnt)
            w, h     = rd['size']
            box_area = w * h if w * h > 0 else 1
            fill     = area / box_area

            if fill < confidence_thresh:
                continue

            # Pixel corners → WGS84
            pixel_corners   = rd['box'].tolist()            # [[col, row], ...]
            wgs84_corners   = geo.pixels_to_wgs84_list(pixel_corners)

            # Pixel center → WGS84
            cx_px, cy_px    = rd['center']
            center_lat, center_lon = geo.pixel_to_wgs84(cx_px, cy_px)

            rectangles.append({
                'id':               idx,
                'center_lat':       center_lat,
                'center_lon':       center_lon,
                'width_px':         float(w),
                'height_px':        float(h),
                'rotation_degrees': float(rd['angle']),
                'confidence':       round(float(fill), 4),
                'class':            'Building',
                # Four corners as [lat, lon] pairs — WGS84, X-Plane convention
                'corner_points_wgs84': wgs84_corners,
            })
        return rectangles

    # ── Per-file pipeline ─────────────────────────────────────────────────────

    def process_image(self, image_path: Path, confidence: float = 0.0):
        """Full pipeline for one GeoTIFF: read → infer → mask → contours → geo JSON."""
        print(f"Processing: {image_path.name}")

        try:
            geo = GeoTiffReader(str(image_path))
        except Exception as e:
            print(f"  Could not read GeoTIFF: {e}")
            return

        image = geo.image_bgr
        if image is None:
            print(f"  Empty image data, skipping.")
            return

        building_prob = self.run_inference(image)
        building_mask = self.probability_to_mask(building_prob)
        contours      = self.extract_contours(building_mask)
        rectangles    = self.contours_to_rectangles(
            contours, geo, confidence_thresh=confidence
        )

        if not rectangles:
            print(f"  No buildings detected.")
            return

        # Compute image-level bounding box in WGS84 for context
        h, w = image.shape[:2]
        tl_lat, tl_lon = geo.pixel_to_wgs84(0,   0)
        br_lat, br_lon = geo.pixel_to_wgs84(w-1, h-1)

        json_data = {
            'source_file':     image_path.name,
            'image_bounds_wgs84': {
                'top_left':     [tl_lat, tl_lon],
                'bottom_right': [br_lat, br_lon],
            },
            'total_buildings': len(rectangles),
            'buildings':       rectangles,
        }

        self.json_list.append(json_data)
        print(f"  {len(rectangles)} building(s) detected.")

    # ── Batch processing ──────────────────────────────────────────────────────

    def process_batch(
        self,
        image_folder: str,
        output_path: str = 'buildings.json',
        confidence: float = 0.0,
    ):
        image_paths = sorted(
            f for f in Path(image_folder).iterdir()
            if f.suffix.lower() in {'.tif', '.tiff'}
        )
        if not image_paths:
            print(f"No TIFF files found in {image_folder}")
            return

        print(f"Processing {len(image_paths)} GeoTIFF(s)...")
        for img_path in image_paths:
            self.process_image(img_path, confidence=confidence)

        with open(output_path, 'w') as f:
            json.dump({"tileBuildingsList": self.json_list}, f, indent=2)
        print(f"\nDone. JSON saved to {output_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Detect buildings in GeoTIFF imagery using the Deepness RAMP XUNet ONNX model.\n"
            "Outputs WGS84 (lat/lon) coordinates compatible with X-Plane."
        )
    )
    parser.add_argument("image_folder", help="Folder containing GeoTIFF (.tif/.tiff) files")
    parser.add_argument(
        "--model", default="ramp_xunet.onnx",
        help="Path to the ONNX model file"
    )
    parser.add_argument(
        "--confidence", type=float, default=0.6,
        help="Minimum fill-ratio to keep a detection (0–1, default: 0.6)"
    )
    parser.add_argument(
        "--output", default="buildings.json",
        help="Output JSON path (default: buildings.json)"
    )
    args = parser.parse_args()

    detector = BuildingDetector(model_path=args.model)
    detector.process_batch(
        args.image_folder,
        output_path=args.output,
        confidence=args.confidence,
    )