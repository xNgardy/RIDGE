#!/usr/bin/env python3
"""Convert Unity-ready RIDGE building detections to X-Plane exporter JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import rasterio


def px_to_wgs84(transform, col: float, row: float) -> list[float]:
    lon, lat = transform * (col, row)
    return [round(float(lat), 8), round(float(lon), 8)]


def convert_buildings(unity_json: Path, rgb_tif: Path, out_json: Path, tile_size: int) -> dict[str, int]:
    data = json.loads(unity_json.read_text(encoding="utf-8"))

    with rasterio.open(rgb_tif) as src:
        transform = src.transform
        raster_w = src.width
        raster_h = src.height

    converted_tiles = []
    input_count = 0
    output_count = 0

    for tile in data.get("tileBuildingsList", []):
        tile_x = int(tile["tile_x"])
        tile_y = int(tile["tile_y"])
        converted_buildings = []

        for building in tile.get("buildings", []):
            input_count += 1
            corners_px = building.get("corner_points", [])
            if len(corners_px) < 3:
                continue

            global_corners = []
            for col, row in corners_px:
                global_col = min(max(tile_x * tile_size + float(col), 0.0), raster_w - 1.0)
                global_row = min(max(tile_y * tile_size + float(row), 0.0), raster_h - 1.0)
                global_corners.append(px_to_wgs84(transform, global_col, global_row))

            center_col = min(max(tile_x * tile_size + float(building.get("center_x", 0.0)), 0.0), raster_w - 1.0)
            center_row = min(max(tile_y * tile_size + float(building.get("center_y", 0.0)), 0.0), raster_h - 1.0)
            center_lat, center_lon = px_to_wgs84(transform, center_col, center_row)

            converted_buildings.append(
                {
                    "id": int(building.get("id", output_count)),
                    "center_lat": center_lat,
                    "center_lon": center_lon,
                    "width_px": float(building.get("width", building.get("width_px", 0.0))),
                    "height_px": float(building.get("height", building.get("height_px", 0.0))),
                    "rotation_degrees": float(building.get("rotation_degrees", 0.0)),
                    "confidence": float(building.get("confidence", 0.0)),
                    "class": building.get("class", "Building"),
                    "corner_points_wgs84": global_corners,
                }
            )
            output_count += 1

        converted_tiles.append(
            {
                "tile_x": tile_x,
                "tile_y": tile_y,
                "image_width": tile.get("image_width", tile_size),
                "image_height": tile.get("image_height", tile_size),
                "total_buildings": len(converted_buildings),
                "buildings": converted_buildings,
            }
        )

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"tileBuildingsList": converted_tiles}, indent=2), encoding="utf-8")
    return {
        "input_buildings": input_count,
        "output_buildings": output_count,
        "tiles": len(converted_tiles),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unity-json", type=Path, required=True)
    parser.add_argument("--rgb-tif", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tile-size", type=int, default=512)
    args = parser.parse_args()

    summary = convert_buildings(args.unity_json, args.rgb_tif, args.out, args.tile_size)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
