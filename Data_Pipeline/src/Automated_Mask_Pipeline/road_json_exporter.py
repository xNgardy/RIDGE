#!/usr/bin/env python3
"""Export per-tile vector road JSON files for Unity RoadLineBuilder."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import osmnx as ox
import rasterio
from shapely.geometry import LineString, MultiLineString, box


PAVED_TYPES = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "living_street",
    "unclassified",
    "service",
}


def export_road_jsons(
    tifs_dir: Path,
    output_dir: Path,
    *,
    road_width_m: float = 6.0,
) -> dict:
    tifs_dir = Path(tifs_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tif_paths = sorted(tifs_dir.glob("tile_*.tif"))
    if not tif_paths:
        raise FileNotFoundError(f"No tile_*.tif files found in {tifs_dir}")

    bbox = _global_bbox(tif_paths)
    roads_gdf = _fetch_roads(bbox)
    unity_name_map = _unity_name_map(tif_paths)
    tiles_written = 0
    roads_exported = 0
    for tif_path in tif_paths:
        tile_x, tile_y = unity_name_map[tif_path]
        with rasterio.open(tif_path) as src:
            left, bottom, right, top = src.bounds

        tile_poly = box(left, bottom, right, top)

        road_entries = []
        if not roads_gdf.empty:
            try:
                clipped = gpd.clip(roads_gdf, tile_poly)
            except Exception:
                clipped = roads_gdf[roads_gdf.intersects(tile_poly)].copy()

            for _, row in clipped.iterrows():
                road_type = _road_type(row.get("highway"))
                for line in _iter_lines(row.geometry):
                    clipped_line = line.intersection(tile_poly)
                    for part in _iter_lines(clipped_line):
                        points = _line_to_normalized_points(part, left, bottom, right, top)
                        if len(points) >= 2:
                            road_entries.append({
                                "type": road_type,
                                "width_m": road_width_m,
                                "points": points,
                            })

        out = {
            "tile_x": tile_x,
            "tile_y": tile_y,
            "width_m": road_width_m,
            "height_m": road_width_m,
            "roads": road_entries,
        }
        with open(output_dir / f"tile_{tile_x}_{tile_y}_roads.json", "w") as f:
            json.dump(out, f, indent=2)

        tiles_written += 1
        roads_exported += len(road_entries)

    return {
        "tiles_checked": len(tif_paths),
        "tiles_written": tiles_written,
        "roads_exported": roads_exported,
    }


def _global_bbox(tif_paths: list[Path]) -> tuple[float, float, float, float]:
    left = bottom = right = top = None
    for path in tif_paths:
        with rasterio.open(path) as src:
            b = src.bounds
        left = b.left if left is None else min(left, b.left)
        bottom = b.bottom if bottom is None else min(bottom, b.bottom)
        right = b.right if right is None else max(right, b.right)
        top = b.top if top is None else max(top, b.top)
    return left, bottom, right, top


def _fetch_roads(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    left, bottom, right, top = bbox
    try:
        gdf = ox.features_from_bbox(bbox=(left, bottom, right, top), tags={"highway": True})
    except TypeError:
        gdf = ox.features_from_bbox((left, bottom, right, top), {"highway": True})
    gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf


def _parse_tile_name(name: str) -> tuple[int, int]:
    _, x, y = name.split("_")
    return int(x), int(y)


def _unity_name_map(tif_paths: list[Path]) -> dict[Path, tuple[int, int]]:
    """Match Road_rgb_mask.py's raw tile coordinate -> Unity tile index swap."""
    raw_coords = {path: _parse_tile_name(path.stem) for path in tif_paths}
    xs = sorted({coord[0] for coord in raw_coords.values()})
    ys = sorted({coord[1] for coord in raw_coords.values()})
    x_index = {value: index for index, value in enumerate(xs)}
    y_index = {value: index for index, value in enumerate(ys)}

    mapping = {}
    for path, (raw_x, raw_y) in raw_coords.items():
        mapping[path] = (y_index[raw_y], x_index[raw_x])
    return mapping


def _road_type(highway_value) -> str:
    value = str(highway_value)
    return "asphalt" if any(road_type in value for road_type in PAVED_TYPES) else "dirt"


def _iter_lines(geometry):
    if geometry.is_empty:
        return
    if isinstance(geometry, LineString):
        yield geometry
    elif isinstance(geometry, MultiLineString):
        yield from geometry.geoms
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _iter_lines(part)


def _line_to_normalized_points(
    line: LineString,
    left: float,
    bottom: float,
    right: float,
    top: float,
) -> list[dict[str, float]]:
    width = right - left
    height = top - bottom
    points = []
    last = None
    for x, y in line.coords:
        u = min(1.0, max(0.0, (x - left) / width))
        v = min(1.0, max(0.0, (y - bottom) / height))
        point = {"u": float(u), "v": float(v)}
        if point != last:
            points.append(point)
            last = point
    return points
