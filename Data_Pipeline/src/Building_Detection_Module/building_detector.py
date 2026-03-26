"""
Offline Building Footprint Detection with Mask Generation and Rectangle Polygonization
This script downloads and uses the building-footprint-extract model locally,
creates binary masks, and converts detections to rectangular polygons
"""

import cv2
import numpy as np
from roboflow import Roboflow
import json
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

class BuildingDetector:
    def __init__(self, api_key, workspace="robotrial", project="building-footprint-extract", version=3):
        """
        Initialize the building detector

        Args:
            api_key: Your Roboflow API key
            workspace: Workspace name (default: robotrial)
            project: Project name (default: building-footprint-extract)
            version: Model version (default: 3)
        """
        self.api_key = api_key
        self.workspace = workspace
        self.project = project
        self.version = version
        self.model = None
        self.json_list = []
        self.load_model()

    def load_model(self):
        """Load the model for inference"""
        if self.model is None:
            rf = Roboflow(api_key=self.api_key)
            project = rf.workspace(self.workspace).project(self.project)
            self.model = project.version(self.version).model
            print("Model loaded successfully")

    def detect_buildings(self, image_path, confidence=40):
        """
        Detect buildings in an image

        Args:
            image_path: Path to the input image
            confidence: Confidence threshold (0-100)

        Returns:
            Dictionary containing predictions
        """
        if self.model is None:
            self.load_model()

        print(f"Processing image: {image_path}")
        predictions = self.model.predict(
            image_path,
            confidence=confidence
        ).json()

        return predictions

    def polygon_to_rectangle(self, points):
        """
        Convert polygon points to a minimum area rectangle

        Args:
            points: List of points [(x1, y1), (x2, y2), ...]

        Returns:
            Dictionary containing:
                - box: Four corner points of the rectangle as numpy array
                - center: (x, y) center position
                - size: (width, height) dimensions
                - angle: rotation angle in degrees
        """
        points_array = np.array(points, dtype=np.float32)

        rect = cv2.minAreaRect(points_array)
        box = cv2.boxPoints(rect)
        box = np.int32(box)

        center = rect[0]  # (x, y)
        size = rect[1]    # (width, height)
        angle = rect[2]   # rotation angle in degrees

        return {
            'box': box,
            'center': center,
            'size': size,
            'angle': angle
        }

    def get_rectangle_polygons(self, predictions):
        """
        Extract rectangle polygons from predictions with detailed metadata

        Args:
            predictions: Prediction results from detect_buildings

        Returns:
            List of rectangle data, each containing position, dimensions, rotation, and corners
        """
        rectangles = []

        if predictions and 'predictions' in predictions:
            for idx, pred in enumerate(predictions['predictions']):
                if 'points' in pred:
                    # Instance segmentation - convert to rectangle
                    points = np.array([[p['x'], p['y']] for p in pred['points']], np.int32)
                    rect_data = self.polygon_to_rectangle(points)

                    rectangles.append({
                        'id': idx,
                        'center_x': float(rect_data['center'][0]),
                        'center_y': float(rect_data['center'][1]),
                        'width': float(rect_data['size'][0]),
                        'height': float(rect_data['size'][1]),
                        'rotation_degrees': float(rect_data['angle']),
                        'confidence': float(pred['confidence']),
                        'class': pred['class'],
                        'corner_points': rect_data['box'].tolist()
                    })
                else:
                    # Bounding box - already a rectangle
                    x = int(pred['x'])
                    y = int(pred['y'])
                    w = int(pred['width'])
                    h = int(pred['height'])

                    x1 = int(x - w/2)
                    y1 = int(y - h/2)
                    x2 = int(x + w/2)
                    y2 = int(y + h/2)

                    corner_points = [
                        [x1, y1],
                        [x2, y1],
                        [x2, y2],
                        [x1, y2]
                    ]

                    rectangles.append({
                        'id': idx,
                        'center_x': float(x),
                        'center_y': float(y),
                        'width': float(w),
                        'height': float(h),
                        'rotation_degrees': 0.0,
                        'confidence': float(pred['confidence']),
                        'class': pred['class'],
                        'corner_points': corner_points
                    })

        return rectangles

    def add_tile_rectangles_to_json_list(self, rectangles, tile_name):
        """
        Add rectangle data to a JSON list

        Args:
            rectangles: List of rectangle data dictionaries
            tile_name: Name of the processed tile/image
        """

        tile_name_tokens = tile_name.split('_')

        try:
            # Prepare data for JSON
            json_data = {
                'tile_x': int(tile_name_tokens[1]), 'tile_y': int(tile_name_tokens[2]),
                'total_buildings': len(rectangles),
                'buildings': rectangles
            }

        except ValueError:
            print("Error parsing tile coordinates from filename for" + tile_name + ".")

            json_data = {
                'total_buildings': len(rectangles),
                'buildings': rectangles
            }

        self.json_list.append(json_data)

        print(f"Rectangle data of {tile_name} added to JSON list.")

    def process_image_with_mask(self, image_path: Path, confidence=40):
        """
        Process image and generate mask, rectangle visualization, JSON data, and rectangle data

        Args:
            image_path: Path to the input image
            confidence: Confidence threshold
        """
        # Detect buildings
        predictions = self.detect_buildings(str(image_path), confidence=confidence)

        # Get rectangle polygons
        rectangles = self.get_rectangle_polygons(predictions)
        if not rectangles:
            print(f"No buildings detected in {image_path.name}.")
            return

        self.add_tile_rectangles_to_json_list(rectangles, image_path.stem)


    def process_batch(self, image_folder, output_path='buildings.json', confidence=40):
        """
        Process multiple images in a folder

        Args:
            image_folder: Path to folder containing images
            output_path: Path to save results (optional)
            confidence: Confidence threshold
        """

        image_paths = [
            f for f in Path(image_folder).iterdir()
            if f.suffix.lower() == '.png'
        ]

        for img_path in image_paths:
            self.process_image_with_mask(
                img_path,
                confidence=confidence# ,
            )

        json_object = {"tileBuildingsList": self.json_list}

        with open(output_path, 'w') as f:
            json.dump(json_object, f, indent=2)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process a folder of images with BuildingDetector")
    parser.add_argument("image_folder", help="Path to folder containing images (tiles)")
    args = parser.parse_args()

    # Load .env (if present) and prefer CLI arg over env variable
    load_dotenv()

    api_key = "5bH01GX0jHfdgfkHe0zW"

    if not api_key:
        raise SystemExit(
            "Roboflow API key not provided. Set ROBOFLOW_API_KEY in a .env file"
        )

    detector = BuildingDetector(api_key)
    detector.process_batch(args.image_folder)
    print("Saved results to buildings.json")