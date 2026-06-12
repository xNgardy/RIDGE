"""
Offline Building Footprint Detection using Deepness RAMP XUNet ONNX model
JSON-only output (no mask images saved).

Model: RAMP XUNet or YOLOv8 segmentation ONNX
Classes: 0=Background, 1=Building
Expected input resolution: 50 cm/px satellite imagery
Tile size: read from model input  |  Overlap: 25 px  |  Seg threshold: 0.4
"""

import cv2
import numpy as np
import onnxruntime as ort
import json
import argparse
import os
from pathlib import Path

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "building-footprint-extract" / "3" / "weights.onnx"

# ── Model constants from ONNX metadata ───────────────────────────────────────
BUILDING_CLASS_ID = 1
TILE_OVERLAP      = 25
SEG_THRESH        = 0.4   # minimum building probability to count as building
MIN_CONTOUR_AREA  = 400    # seg_small_segment from metadata — drop blobs smaller than this
YOLO_NMS_IOU      = 0.45


class BuildingDetector:
    def __init__(self, model_path: str):
        """
        Args:
            model_path: Path to ramp_xunet_*.onnx
        """
        self.model_path = model_path
        self.session = None
        self.json_list = []
        self.input_name = None
        self.output_names = []
        self.input_width = None
        self.input_height = None
        self.load_model()

    def load_model(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"ONNX model not found at '{self.model_path}'.")
        self.session = ort.InferenceSession(
            self.model_path,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        self.output_names = [output.name for output in self.session.get_outputs()]
        self.input_height, self.input_width = self._read_input_size(model_input.shape)
        print(f"Model loaded: {self.model_path}")
        print(f"Model input size: {self.input_width}x{self.input_height}")

    def _read_input_size(self, input_shape) -> tuple[int, int]:
        """Return static model input size as (height, width)."""
        if len(input_shape) != 4 or not all(isinstance(v, int) for v in input_shape[2:4]):
            raise ValueError(
                f"Unsupported dynamic ONNX input shape {input_shape}; expected static NCHW dimensions."
            )
        return input_shape[2], input_shape[3]

    # ── Preprocessing ─────────────────────────────────────────────────────────

    def _preprocess_tile(self, tile_bgr: np.ndarray) -> np.ndarray:
        """
        BGR tile -> model-sized NCHW float32 tensor, normalized to [0, 1].
        """
        rgb        = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2RGB)
        resized    = cv2.resize(rgb, (self.input_width, self.input_height))
        normalized = resized.astype(np.float32) / 255.0
        chw        = np.transpose(normalized, (2, 0, 1))
        return np.expand_dims(chw, axis=0)

    def _sigmoid(self, values: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-values))

    def _is_yolo_seg_output(self, outputs: list[np.ndarray]) -> bool:
        return (
            len(outputs) == 2
            and outputs[0].ndim == 3
            and outputs[1].ndim == 4
            and outputs[1].shape[1] == outputs[0].shape[1] - 5
        )

    def _decode_yolo_segmentation(self, outputs: list[np.ndarray], tile_shape: tuple[int, int]) -> np.ndarray:
        """
        Decode YOLOv8 instance segmentation outputs into a per-pixel building probability map.
        Assumes a single building class and mask coefficients after x/y/w/h/class_score.
        """
        tile_h, tile_w = tile_shape
        pred = outputs[0][0]
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T

        boxes_xywh = pred[:, :4]
        scores = pred[:, 4]
        coeffs = pred[:, 5:]
        keep = scores >= SEG_THRESH
        if not np.any(keep):
            return np.zeros((tile_h, tile_w), dtype=np.float32)

        boxes_xywh = boxes_xywh[keep]
        scores = scores[keep]
        coeffs = coeffs[keep]

        boxes_xyxy = np.empty_like(boxes_xywh)
        boxes_xyxy[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
        boxes_xyxy[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
        boxes_xyxy[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
        boxes_xyxy[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2
        boxes_xyxy[:, [0, 2]] = np.clip(boxes_xyxy[:, [0, 2]], 0, self.input_width)
        boxes_xyxy[:, [1, 3]] = np.clip(boxes_xyxy[:, [1, 3]], 0, self.input_height)

        nms_boxes = [
            [float(x1), float(y1), float(x2 - x1), float(y2 - y1)]
            for x1, y1, x2, y2 in boxes_xyxy
        ]
        indices = cv2.dnn.NMSBoxes(nms_boxes, scores.tolist(), SEG_THRESH, YOLO_NMS_IOU)
        if len(indices) == 0:
            return np.zeros((tile_h, tile_w), dtype=np.float32)
        indices = np.array(indices).reshape(-1)

        protos = outputs[1][0]
        proto_h, proto_w = protos.shape[1:]
        mask_logits = coeffs[indices] @ protos.reshape(protos.shape[0], -1)
        masks = self._sigmoid(mask_logits).reshape(-1, proto_h, proto_w)

        prob = np.zeros((self.input_height, self.input_width), dtype=np.float32)
        scale_x = proto_w / self.input_width
        scale_y = proto_h / self.input_height

        for mask, box, score in zip(masks, boxes_xyxy[indices], scores[indices]):
            x1, y1, x2, y2 = box.astype(int)
            if x2 <= x1 or y2 <= y1:
                continue

            px1 = int(np.clip(np.floor(x1 * scale_x), 0, proto_w))
            py1 = int(np.clip(np.floor(y1 * scale_y), 0, proto_h))
            px2 = int(np.clip(np.ceil(x2 * scale_x), 0, proto_w))
            py2 = int(np.clip(np.ceil(y2 * scale_y), 0, proto_h))
            if px2 <= px1 or py2 <= py1:
                continue

            cropped = mask[py1:py2, px1:px2]
            resized = cv2.resize(cropped, (x2 - x1, y2 - y1))
            prob[y1:y2, x1:x2] = np.maximum(prob[y1:y2, x1:x2], resized * float(score))

        return cv2.resize(prob, (tile_w, tile_h))

    def _decode_dense_segmentation(self, output: np.ndarray) -> np.ndarray:
        if output.shape[1] == 2:
            exp = np.exp(output[0] - output[0].max(axis=0, keepdims=True))
            return (exp / exp.sum(axis=0))[BUILDING_CLASS_ID]
        if output.shape[1] == 1:
            return self._sigmoid(output[0, 0])
        return np.argmax(output[0], axis=0).astype(np.float32)

    # ── Tiled inference ───────────────────────────────────────────────────────

    def run_inference(self, image: np.ndarray) -> np.ndarray:
        """
        Run tiled inference over a full image with overlap blending.

        Returns:
            building_prob: float32 array (H, W) with values in [0, 1]
        """
        orig_h, orig_w = image.shape[:2]
        tile_size = max(self.input_width, self.input_height)
        step = tile_size - TILE_OVERLAP

        accum  = np.zeros((orig_h, orig_w), dtype=np.float32)
        counts = np.zeros((orig_h, orig_w), dtype=np.float32)

        y_starts = list(range(0, orig_h, step))
        x_starts = list(range(0, orig_w, step))

        if y_starts[-1] + tile_size < orig_h:
            y_starts.append(orig_h - tile_size)
        if x_starts[-1] + tile_size < orig_w:
            x_starts.append(orig_w - tile_size)

        for y0 in y_starts:
            y1 = min(y0 + tile_size, orig_h)
            y0 = max(y1 - tile_size, 0)

            for x0 in x_starts:
                x1 = min(x0 + tile_size, orig_w)
                x0 = max(x1 - tile_size, 0)

                tile = image[y0:y1, x0:x1]
                tensor = self._preprocess_tile(tile)

                outputs = self.session.run(self.output_names, {self.input_name: tensor})
                if self._is_yolo_seg_output(outputs):
                    prob_resized = self._decode_yolo_segmentation(outputs, tile.shape[:2])
                else:
                    prob = self._decode_dense_segmentation(outputs[0])
                    prob_resized = cv2.resize(prob, (x1 - x0, y1 - y0))

                accum[y0:y1, x0:x1]  += prob_resized
                counts[y0:y1, x0:x1] += 1.0

        counts = np.maximum(counts, 1.0)
        return accum / counts

    # ── Mask generation ───────────────────────────────────────────────────────

    def probability_to_mask(self, building_prob: np.ndarray) -> np.ndarray:
        """
        Apply seg_thresh and remove small segments.

        Returns:
            binary mask uint8 (0 / 255) at original image resolution
        """
        binary = (building_prob >= SEG_THRESH).astype(np.uint8) * 255

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
        rect = cv2.minAreaRect(contour)
        box  = np.int32(cv2.boxPoints(rect))
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

    # ── Per-tile pipeline ─────────────────────────────────────────────────────

    def process_image(self, image_path: Path, confidence: float = 0.0):
        """Full pipeline for one tile: infer → mask → contours → rectangles."""
        print(f"Processing: {image_path.name}")

        image = cv2.imread(str(image_path))
        if image is None:
            print(f"  Could not read image, skipping.")
            return

        building_prob = self.run_inference(image)
        building_mask = self.probability_to_mask(building_prob)
        contours      = self.extract_contours(building_mask)
        rectangles    = self.contours_to_rectangles(contours, confidence_thresh=confidence)

        if not rectangles:
            print(f"  No buildings detected.")
            return

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

        print(f"Processing {len(image_paths)} tile(s)...")
        for img_path in image_paths:
            self.process_image(img_path, confidence=confidence)

        with open(output_path, 'w') as f:
            json.dump({"tileBuildingsList": self.json_list}, f, indent=2)
        print(f"\nDone. JSON saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Detect buildings using the Deepness RAMP XUNet ONNX model."
    )
    parser.add_argument("image_folder", help="Folder containing PNG image tiles")
    parser.add_argument(
        "--model", default=str(DEFAULT_MODEL_PATH),
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
    args = parser.parse_args()

    detector = BuildingDetector(model_path=args.model)
    detector.process_batch(args.image_folder, output_path=args.output,
                           confidence=args.confidence)
