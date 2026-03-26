"""
Offline Building Footprint Detection with Mask Generation and Rectangle Polygonization
Downloads the model into a local ./models/ folder on first run, then works fully offline.
"""

import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
LOCAL_MODELS_DIR = SCRIPT_DIR / "models"
LOCAL_MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Set all possible env vars the SDK might read
os.environ["INFERENCE_MODELS_CACHE_DIR"] = str(LOCAL_MODELS_DIR)
os.environ["MODEL_CACHE_DIR"] = str(LOCAL_MODELS_DIR)
os.environ["ROBOFLOW_MODEL_CACHE_DIR"] = str(LOCAL_MODELS_DIR)
# Now it is safe to import inference — it will respect the env var above.
from inference import get_model  # noqa: E402  (import not at top of file intentionally)

import cv2
import numpy as np
import json
import argparse
import tempfile
from dotenv import load_dotenv


class BuildingDetector:
    def __init__(self, api_key=None, workspace="robotrial", project="building-footprint-extract", version=3):
        """
        Initialize the building detector.

        On first run (model not yet cached) an api_key is required so the weights
        can be downloaded from Roboflow.  On subsequent runs the model is loaded
        entirely from disk and api_key may be None / empty.

        Args:
            api_key:   Roboflow API key (only needed for the initial download)
            workspace: Workspace name  (default: robotrial)
            project:   Project name    (default: building-footprint-extract)
            version:   Model version   (default: 3)
        """
        self.api_key = api_key
        self.model_id = f"{project}/{version}"
        self.model_cache_dir = LOCAL_MODELS_DIR / self.model_id.replace("/", "--")
        self.model = None
        self.json_list = []
        self._load_model()

    # ------------------------------------------------------------------
    # Model loading — download once, cache locally, reload from disk
    # ------------------------------------------------------------------

    def _is_model_cached(self) -> bool:
        """Return True when the local cache directory exists and is non-empty."""
        return self.model_cache_dir.exists() and any(self.model_cache_dir.iterdir())

    def _download_and_cache_model(self):
        """
        Pull the model from Roboflow (requires internet + api_key).
        The SDK writes directly into LOCAL_MODELS_DIR because INFERENCE_MODELS_CACHE_DIR
        was set at module load time (before the inference import).
        """
        if not self.api_key:
            raise RuntimeError(
                "Model not found in local cache and no API key was provided.\n"
                f"  Expected cache location: {self.model_cache_dir}\n"
                "  Set ROBOFLOW_API_KEY in a .env file (or pass --api-key) to "
                "download the model on first run."
            )

        print(f"Downloading '{self.model_id}' from Roboflow for the first time ...")
        model = get_model(model_id=self.model_id, api_key=self.api_key)
        print(f"Model saved to: {self.model_cache_dir}")
        return model

    def _load_model_from_cache(self):
        """
        Load the model purely from the local ./models/ cache — no network calls.
        INFERENCE_MODELS_CACHE_DIR is already pointing at LOCAL_MODELS_DIR from
        module initialisation, so get_model will find the weights there.
        """
        print(f"Loading model from local cache: {self.model_cache_dir}")
        model = get_model(
            model_id=self.model_id,
            api_key=self.api_key or "offline",
        )
        print("Model loaded (offline, from local cache).")
        return model

    def _load_model(self):
        """
        Entry point for model loading:
          1. If already in ./models/ → load from there directly.
          2. Otherwise              → download from Roboflow (writes into ./models/).
        """
        if self._is_model_cached():
            self.model = self._load_model_from_cache()
        else:
            self.model = self._download_and_cache_model()

    # ------------------------------------------------------------------
    # Detection logic (unchanged from original)
    # ------------------------------------------------------------------

    def detect_buildings(self, image_path, confidence=40):
        """
        Detect buildings in an image locally.

        Args:
            image_path: Path to the input image
            confidence: Confidence threshold (0-100)

        Returns:
            Dictionary containing predictions in a normalized format
        """
        print(f"Processing image: {image_path}")

        results = self.model.infer(
            image=image_path,
            confidence=confidence / 100.0
        )

        predictions = []
        for result in results:
            for pred in result.predictions:
                entry = {
                    "class": pred.class_name,
                    "confidence": pred.confidence,
                }

                if hasattr(pred, "points") and pred.points:
                    entry["points"] = [{"x": p.x, "y": p.y} for p in pred.points]
                else:
                    entry["x"] = pred.x
                    entry["y"] = pred.y
                    entry["width"] = pred.width
                    entry["height"] = pred.height

                predictions.append(entry)

        return {"predictions": predictions}

    def polygon_to_rectangle(self, points):
        """
        Convert polygon points to a minimum area rectangle.

        Args:
            points: List of points [(x1, y1), (x2, y2), ...]

        Returns:
            Dictionary containing box, center, size, and angle
        """
        points_array = np.array(points, dtype=np.float32)
        rect = cv2.minAreaRect(points_array)
        box = cv2.boxPoints(rect)
        box = np.int32(box)

        return {
            "box": box,
            "center": rect[0],
            "size": rect[1],
            "angle": rect[2],
        }

    def get_rectangle_polygons(self, predictions):
        """
        Extract rectangle polygons from predictions with detailed metadata.

        Args:
            predictions: Prediction results from detect_buildings

        Returns:
            List of rectangle data dictionaries
        """
        rectangles = []

        if predictions and "predictions" in predictions:
            for idx, pred in enumerate(predictions["predictions"]):
                if "points" in pred:
                    points = np.array([[p["x"], p["y"]] for p in pred["points"]], np.int32)
                    rect_data = self.polygon_to_rectangle(points)

                    rectangles.append({
                        "id": idx,
                        "center_x": float(rect_data["center"][0]),
                        "center_y": float(rect_data["center"][1]),
                        "width": float(rect_data["size"][0]),
                        "height": float(rect_data["size"][1]),
                        "rotation_degrees": float(rect_data["angle"]),
                        "confidence": float(pred["confidence"]),
                        "class": pred["class"],
                        "corner_points": rect_data["box"].tolist(),
                    })
                else:
                    x = int(pred["x"])
                    y = int(pred["y"])
                    w = int(pred["width"])
                    h = int(pred["height"])

                    x1, y1 = int(x - w / 2), int(y - h / 2)
                    x2, y2 = int(x + w / 2), int(y + h / 2)

                    rectangles.append({
                        "id": idx,
                        "center_x": float(x),
                        "center_y": float(y),
                        "width": float(w),
                        "height": float(h),
                        "rotation_degrees": 0.0,
                        "confidence": float(pred["confidence"]),
                        "class": pred["class"],
                        "corner_points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                    })

        return rectangles

    def add_tile_rectangles_to_json_list(self, rectangles, tile_name, image_width, image_height):
        """
        Add rectangle data to the running JSON list.

        Args:
            rectangles: List of rectangle data dictionaries
            tile_name:  Stem of the processed tile filename
            image_width: Width of the source image in pixels
            image_height: Height of the source image in pixels
        """
        tile_name_tokens = tile_name.split("_")

        try:
            json_data = {
                "tile_x": int(tile_name_tokens[1]),
                "tile_y": int(tile_name_tokens[2]),
                "image_width": image_width,
                "image_height": image_height,
                "total_buildings": len(rectangles),
                "buildings": rectangles,
            }
        except (ValueError, IndexError):
            print(f"Error parsing tile coordinates from filename: {tile_name}")
            json_data = {
                "image_width": image_width,
                "image_height": image_height,
                "total_buildings": len(rectangles),
                "buildings": rectangles,
            }

        self.json_list.append(json_data)
        print(f"Rectangle data of {tile_name} added to JSON list.")

    def process_image_with_mask(self, image_path: Path, confidence=40):
        """
        Process a single image and accumulate its rectangle data.

        Args:
            image_path: Path to the input image
            confidence: Confidence threshold
        """
        predictions = self.detect_buildings(str(image_path), confidence=confidence)

        # Get image dimensions
        img = cv2.imread(str(image_path))
        image_height, image_width = img.shape[:2]

        rectangles = self.get_rectangle_polygons(predictions)

        if not rectangles:
            print(f"No buildings detected in {image_path.name}.")
            return

        self.add_tile_rectangles_to_json_list(rectangles, image_path.stem, image_width, image_height)

    def process_batch(self, image_folder, output_path="buildings.json", confidence=40):
        """
        Process all PNG images in a folder and write results to JSON.

        Args:
            image_folder: Path to folder containing images
            output_path:  Destination path for the output JSON file
            confidence:   Confidence threshold
        """
        image_paths = [f for f in Path(image_folder).iterdir() if f.suffix.lower() == ".png"]

        if not image_paths:
            print(f"No PNG images found in {image_folder}")
            return

        for img_path in image_paths:
            self.process_image_with_mask(img_path, confidence=confidence)

        with open(output_path, "w") as f:
            json.dump({"tileBuildingsList": self.json_list}, f, indent=2)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process a folder of images with BuildingDetector (offline-capable)"
    )
    parser.add_argument("image_folder", help="Path to folder containing PNG tile images")
    parser.add_argument(
        "--api-key",
        default=None,
        help="Roboflow API key (only needed on first run to download the model)",
    )
    args = parser.parse_args()

    load_dotenv()
    api_key = args.api_key or os.getenv("ROBOFLOW_API_KEY")

    detector = BuildingDetector(api_key=api_key)
    detector.process_batch(args.image_folder)
    print("Saved results to buildings.json")