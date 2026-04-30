"""
Offline Building Footprint Detection using Deepness RAMP XUNet ONNX model
With binary mask output per tile.

Model: ramp_xunet_*.onnx  (from Deepness Model Zoo)
Classes: 0=Background, 1=Building
Expected input resolution: 50 cm/px satellite imagery
Tile size: 256x256 px  |  Overlap: 25 px  |  Seg threshold: 0.2
"""

import cv2
import numpy as np
import onnxruntime as ort
import json
import argparse
import os
from pathlib import Path

# ── Model constants from ONNX metadata ───────────────────────────────────────
BUILDING_CLASS_ID = 1
TILE_SIZE         = 256
TILE_OVERLAP      = 25
SEG_THRESH        = 0.4   # minimum building probability to count as building
MIN_CONTOUR_AREA  = 400    # seg_small_segment from metadata — drop blobs smaller than this


class BuildingDetector:
    def __init__(self, model_path: str, masks_dir: str = "masks"):
        """
        Args:
            model_path: Path to ramp_xunet_*.onnx
            masks_dir:  Folder where mask images will be saved
        """
        self.model_path = model_path
        self.masks_dir = Path(masks_dir)
        self.masks_dir.mkdir(parents=True, exist_ok=True)
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
        """
        BGR tile -> (1, 3, 256, 256) float32 tensor, normalized to [0, 1].
        """
        rgb        = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2RGB)
        resized    = cv2.resize(rgb, (TILE_SIZE, TILE_SIZE))
        normalized = resized.astype(np.float32) / 255.0
        chw        = np.transpose(normalized, (2, 0, 1))
        return np.expand_dims(chw, axis=0)

    # ── Tiled inference ───────────────────────────────────────────────────────

    def run_inference(self, image: np.ndarray) -> np.ndarray:
        """
        Run tiled inference over a full image with overlap blending.
        Tiles are extracted with TILE_OVERLAP px padding, inferred individually,
        and the building-probability channel is stitched back via an accumulator
        so overlapping regions are averaged rather than overwritten.

        Returns:
            building_prob: float32 array (H, W) with values in [0, 1]
        """
        orig_h, orig_w = image.shape[:2]
        step = TILE_SIZE - TILE_OVERLAP

        accum  = np.zeros((orig_h, orig_w), dtype=np.float32)  # sum of probabilities
        counts = np.zeros((orig_h, orig_w), dtype=np.float32)  # how many tiles covered each pixel

        y_starts = list(range(0, orig_h, step))
        x_starts = list(range(0, orig_w, step))

        # Make sure the last tile always reaches the image edge
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

                tile = image[y0:y1, x0:x1]
                tensor = self._preprocess_tile(tile)

                output = self.session.run([self.output_name], {self.input_name: tensor})[0]
                # output shape may be (1, 2, H, W) logits or (1, 1, H, W) sigmoid
                if output.shape[1] == 2:
                    # Two-class logits — softmax, take building channel
                    exp = np.exp(output[0] - output[0].max(axis=0, keepdims=True))
                    prob = (exp / exp.sum(axis=0))[BUILDING_CLASS_ID]
                elif output.shape[1] == 1:
                    # Single-channel sigmoid output
                    prob = 1.0 / (1.0 + np.exp(-output[0, 0]))
                else:
                    prob = np.argmax(output[0], axis=0).astype(np.float32)

                # Resize prob back to tile pixel size (should already match, but be safe)
                prob_resized = cv2.resize(prob, (x1 - x0, y1 - y0))

                accum[y0:y1, x0:x1]  += prob_resized
                counts[y0:y1, x0:x1] += 1.0

        counts = np.maximum(counts, 1.0)
        return accum / counts

    # ── Mask generation ───────────────────────────────────────────────────────

    def probability_to_mask(self, building_prob: np.ndarray) -> np.ndarray:
        """
        Apply seg_thresh and remove small segments (seg_small_segment = 11 px²).

        Returns:
            binary mask uint8 (0 / 255) at original image resolution
        """
        binary = (building_prob >= SEG_THRESH).astype(np.uint8) * 255

        # Remove blobs smaller than MIN_CONTOUR_AREA
        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        cleaned = np.zeros_like(binary)
        for label in range(1, n_labels):
            if stats[label, cv2.CC_STAT_AREA] >= MIN_CONTOUR_AREA:
                cleaned[labels == label] = 255

        return cleaned

    # ── Contour / rectangle extraction ───────────────────────────────────────

    def extract_contours(self, building_mask: np.ndarray):
        """Extract contours from the cleaned binary mask."""
        contours, _ = cv2.findContours(
            building_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        return contours

    def polygon_to_rectangle(self, contour: np.ndarray) -> dict:
        """Fit a minimum-area rectangle around a contour."""
        rect  = cv2.minAreaRect(contour)
        box   = np.int32(cv2.boxPoints(rect))
        return {'box': box, 'center': rect[0], 'size': rect[1], 'angle': rect[2]}

    def contours_to_rectangles(self, contours, confidence_thresh: float = 0.0) -> list:
        """
        Convert contours to rectangle dicts, filtered by fill ratio.

        Args:
            contours:          Output of extract_contours()
            confidence_thresh: Minimum contour-area / box-area ratio to keep (0-1)
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

            rectangles.append({
                'id':               idx,
                'center_x':         float(rd['center'][0]),
                'center_y':         float(rd['center'][1]),
                'width':            float(w),
                'height':           float(h),
                'rotation_degrees': float(rd['angle']),
                'confidence':       round(float(fill), 4),
                'class':            'Building',
                'corner_points':    rd['box'].tolist(),
            })
        return rectangles

    # ── Mask visualisation ────────────────────────────────────────────────────

    def save_masks(self, image: np.ndarray, building_mask: np.ndarray,
                   building_prob: np.ndarray, tile_name: str,
                   contours: list, rectangles: list):
        """
        Save three outputs per tile:
          1. <tile>_mask_binary.png   — white buildings on black
          2. <tile>_mask_overlay.png  — original + green fill + orange rect outlines
          3. <tile>_mask_prob.png     — heatmap of raw building probability
        """
        # 1. Binary mask
        cv2.imwrite(str(self.masks_dir / f"{tile_name}_mask_binary.png"), building_mask)

        # 2. Overlay
        overlay      = image.copy()
        green_layer  = np.zeros_like(image)
        green_layer[building_mask == 255] = (0, 200, 0)
        overlay = cv2.addWeighted(overlay, 1.0, green_layer, 0.45, 0)
        cv2.drawContours(overlay, contours, -1, (0, 255, 0), 1)
        for rect in rectangles:
            box = np.array(rect['corner_points'], dtype=np.int32)
            cv2.drawContours(overlay, [box], 0, (0, 80, 255), 2)
        cv2.imwrite(str(self.masks_dir / f"{tile_name}_mask_overlay.png"), overlay)

        # 3. Probability heatmap (JET colormap, brighter = more confident building)
        prob_norm  = (np.clip(building_prob, 0, 1) * 255).astype(np.uint8)
        prob_color = cv2.applyColorMap(prob_norm, cv2.COLORMAP_JET)
        cv2.imwrite(str(self.masks_dir / f"{tile_name}_mask_prob.png"), prob_color)

        print(f"  Masks saved → {tile_name}_mask_{{binary,overlay,prob}}.png")

    # ── Per-tile pipeline ─────────────────────────────────────────────────────

    def process_image_with_mask(self, image_path: Path, confidence: float = 0.0):
        """Full pipeline for one tile: infer → mask → contours → rectangles → save."""
        print(f"Processing: {image_path.name}")

        image = cv2.imread(str(image_path))
        if image is None:
            print(f"  Could not read image, skipping.")
            return

        building_prob = self.run_inference(image)
        building_mask = self.probability_to_mask(building_prob)
        contours      = self.extract_contours(building_mask)
        rectangles    = self.contours_to_rectangles(contours, confidence_thresh=confidence)

        # Always save masks even when no buildings found
        self.save_masks(image, building_mask, building_prob,
                        image_path.stem, contours, rectangles)

        if not rectangles:
            print(f"  No buildings detected.")
            return

        # Build JSON entry
        tokens = image_path.stem.split('_')
        try:
            json_data = {
                'tile_x':          int(tokens[1]),
                'tile_y':          int(tokens[2]),
                'total_buildings': len(rectangles),
                'buildings':       rectangles,
            }
        except (ValueError, IndexError):
            print(f"  Warning: could not parse tile coords from '{image_path.stem}'.")
            json_data = {
                'total_buildings': len(rectangles),
                'buildings':       rectangles,
            }

        self.json_list.append(json_data)
        print(f"  {len(rectangles)} building(s) detected.")

    # ── Batch processing ──────────────────────────────────────────────────────

    def process_batch(self, image_folder: str, output_path: str = 'buildings.json',
                      confidence: float = 0.0):
        image_paths = sorted(
            f for f in Path(image_folder).iterdir()
            if f.suffix.lower() == '.png'
        )
        if not image_paths:
            print(f"No PNG files found in {image_folder}")
            return

        print(f"Processing {len(image_paths)} tile(s)... Masks → '{self.masks_dir}/'")
        for img_path in image_paths:
            self.process_image_with_mask(img_path, confidence=confidence)

        with open(output_path, 'w') as f:
            json.dump({"tileBuildingsList": self.json_list}, f, indent=2)
        print(f"\nDone. JSON saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Detect buildings using the Deepness RAMP XUNet ONNX model."
    )
    parser.add_argument("image_folder", help="Folder containing PNG image tiles")
    parser.add_argument(
        "--model", default="ramp_xunet.onnx",
        help="Path to the ONNX model file"
    )
    parser.add_argument(
        "--confidence", type=float, default=0.6,
        help="Minimum fill-ratio to keep a detection (0-1, default: 0.0)"
    )
    parser.add_argument(
        "--output", default="buildings.json",
        help="Output JSON path (default: buildings.json)"
    )
    parser.add_argument(
        "--masks-dir", default="masks",
        help="Directory to save mask images (default: masks/)"
    )
    args = parser.parse_args()

    detector = BuildingDetector(model_path=args.model, masks_dir=args.masks_dir)
    detector.process_batch(args.image_folder, output_path=args.output,
                           confidence=args.confidence)