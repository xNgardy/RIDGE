#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _load_occupancy(mask_path: Path, size: tuple[int, int]) -> np.ndarray:
    if not mask_path.exists():
        return np.zeros((size[1], size[0]), dtype=bool)

    image = Image.open(mask_path)
    if image.size != size:
        image = image.resize(size, Image.Resampling.NEAREST)

    arr = np.asarray(image)
    if arr.ndim == 3:
        return np.any(arr[:, :, :3] > 0, axis=2)
    return arr > 0


def _save_binary_mask(path: Path, mask: np.ndarray) -> None:
    Image.fromarray((mask.astype(np.uint8) * 255)).save(path)


def _tile_name_from_coords(tile_x: int, tile_y: int) -> str:
    return f"tile_{tile_x}_{tile_y}"


def complete_buildings_json_from_images(
    buildings_json_path: Path,
    image_dir: Path,
) -> dict:
    buildings_json_path = Path(buildings_json_path)
    image_dir = Path(image_dir)

    if buildings_json_path.exists():
        with open(buildings_json_path, "r") as f:
            building_data = json.load(f)
    else:
        building_data = {"tileBuildingsList": []}

    entries = building_data.get("tileBuildingsList", [])
    by_tile = {
        (int(entry["tile_x"]), int(entry["tile_y"])): entry
        for entry in entries
        if "tile_x" in entry and "tile_y" in entry
    }

    added_entries = 0
    normalized_entries = []
    for image_path in sorted(image_dir.glob("tile_*_*.png")):
        tile_x, tile_y = _parse_tile_image_name(image_path.stem)
        key = (tile_x, tile_y)
        width, height = Image.open(image_path).size

        entry = by_tile.get(key)
        if entry is None:
            entry = {
                "tile_x": tile_x,
                "tile_y": tile_y,
                "image_width": width,
                "image_height": height,
                "total_buildings": 0,
                "buildings": [],
            }
            added_entries += 1
        else:
            entry = dict(entry)
            entry["image_width"] = int(entry.get("image_width", width))
            entry["image_height"] = int(entry.get("image_height", height))
            entry["buildings"] = entry.get("buildings", [])
            entry["total_buildings"] = len(entry["buildings"])

        normalized_entries.append(entry)

    building_data["tileBuildingsList"] = normalized_entries
    with open(buildings_json_path, "w") as f:
        json.dump(building_data, f, indent=2)

    return {
        "building_image_tiles": len(normalized_entries),
        "empty_building_entries_added": added_entries,
    }


def _parse_tile_image_name(name: str) -> tuple[int, int]:
    _, tile_x, tile_y = name.split("_")
    return int(tile_x), int(tile_y)


def clean_tree_masks_against_roads(
    tree_dir: Path,
    road_dir: Path,
    *,
    update_json: bool = True,
) -> dict:
    tree_dir = Path(tree_dir)
    road_dir = Path(road_dir)

    cleaned_tiles = 0
    removed_tree_pixels = 0

    tree_masks = sorted(tree_dir.glob("tile_*_*_mask.png"))
    for tree_mask_path in tree_masks:
        tile_name = tree_mask_path.stem.removesuffix("_mask")
        road_mask_path = road_dir / f"{tile_name}_mask.png"

        image = Image.open(tree_mask_path).convert("L")
        tree_mask = np.asarray(image) > 0
        road_occupied = _load_occupancy(road_mask_path, image.size)

        before = int(tree_mask.sum())
        cleaned = tree_mask & ~road_occupied
        removed = before - int(cleaned.sum())

        if removed:
            _save_binary_mask(tree_mask_path, cleaned)
            cleaned_tiles += 1
            removed_tree_pixels += removed

    removed_positions = 0
    if update_json:
        removed_positions = _clean_tree_position_json(tree_dir, road_dir)
        _refresh_tree_data_json(tree_dir)

    return {
        "tree_masks_checked": len(tree_masks),
        "tree_masks_changed": cleaned_tiles,
        "tree_pixels_removed": removed_tree_pixels,
        "tree_positions_removed": removed_positions,
    }


def complete_tree_outputs_from_images(tree_dir: Path, image_dir: Path) -> dict:
    tree_dir = Path(tree_dir)
    image_dir = Path(image_dir)
    ensure_dir(tree_dir)

    positions_path = tree_dir / "tree_positions.json"
    if positions_path.exists():
        with open(positions_path, "r") as f:
            positions_by_tile = json.load(f)
    else:
        positions_by_tile = {}

    masks_added = 0
    positions_added = 0
    tile_count = 0
    for image_path in sorted(image_dir.glob("tile_*_*.png")):
        tile_count += 1
        tile_name = image_path.stem
        size = Image.open(image_path).size
        mask_path = tree_dir / f"{tile_name}_mask.png"
        if not mask_path.exists():
            blank = np.zeros((size[1], size[0]), dtype=bool)
            _save_binary_mask(mask_path, blank)
            masks_added += 1
        if tile_name not in positions_by_tile:
            positions_by_tile[tile_name] = []
            positions_added += 1

    with open(positions_path, "w") as f:
        json.dump(positions_by_tile, f, indent=2)

    _refresh_tree_data_json(tree_dir)
    return {
        "tree_image_tiles": tile_count,
        "empty_tree_masks_added": masks_added,
        "empty_tree_position_entries_added": positions_added,
    }


def complete_road_masks_from_images(road_dir: Path, image_dir: Path) -> dict:
    road_dir = Path(road_dir)
    image_dir = Path(image_dir)
    ensure_dir(road_dir)

    masks_added = 0
    tile_count = 0
    for image_path in sorted(image_dir.glob("tile_*_*.png")):
        tile_count += 1
        tile_name = image_path.stem
        mask_path = road_dir / f"{tile_name}_mask.png"
        if mask_path.exists():
            continue

        size = Image.open(image_path).size
        blank = np.zeros((size[1], size[0]), dtype=bool)
        _save_binary_mask(mask_path, blank)
        masks_added += 1

    return {
        "road_image_tiles": tile_count,
        "empty_road_masks_added": masks_added,
    }


def complete_road_jsons_from_images(road_json_dir: Path, image_dir: Path, road_width_m: float) -> dict:
    road_json_dir = Path(road_json_dir)
    image_dir = Path(image_dir)
    ensure_dir(road_json_dir)

    jsons_added = 0
    tile_count = 0
    for image_path in sorted(image_dir.glob("tile_*_*.png")):
        tile_count += 1
        tile_x, tile_y = _parse_tile_image_name(image_path.stem)
        json_path = road_json_dir / f"tile_{tile_x}_{tile_y}_roads.json"
        if json_path.exists():
            continue

        with open(json_path, "w") as f:
            json.dump({
                "tile_x": tile_x,
                "tile_y": tile_y,
                "width_m": road_width_m,
                "height_m": road_width_m,
                "roads": [],
            }, f, indent=2)
        jsons_added += 1

    return {
        "road_json_image_tiles": tile_count,
        "empty_road_jsons_added": jsons_added,
    }


def _clean_tree_position_json(tree_dir: Path, road_dir: Path) -> int:
    positions_path = tree_dir / "tree_positions.json"
    if not positions_path.exists():
        return 0

    with open(positions_path, "r") as f:
        positions_by_tile = json.load(f)

    removed_positions = 0
    cleaned_positions_by_tile = {}

    for tile_name, positions in positions_by_tile.items():
        tree_mask_path = tree_dir / f"{tile_name}_mask.png"
        if not tree_mask_path.exists():
            cleaned_positions_by_tile[tile_name] = positions
            continue

        tree_image = Image.open(tree_mask_path).convert("L")
        tree_mask = np.asarray(tree_image) > 0
        road_occupied = _load_occupancy(road_dir / f"{tile_name}_mask.png", tree_image.size)
        blocked = road_occupied | ~tree_mask

        width, height = tree_image.size
        kept = []
        for position in positions:
            px = min(width - 1, max(0, int(float(position["x"]) * width)))
            py = min(height - 1, max(0, int(float(position["y"]) * height)))
            if blocked[py, px]:
                removed_positions += 1
            else:
                kept.append(position)

        cleaned_positions_by_tile[tile_name] = kept

    with open(positions_path, "w") as f:
        json.dump(cleaned_positions_by_tile, f, indent=2)

    return removed_positions


def _refresh_tree_data_json(tree_dir: Path) -> None:
    data_path = tree_dir / "tree_data.json"
    positions_path = tree_dir / "tree_positions.json"
    if not data_path.exists() or not positions_path.exists():
        return

    with open(data_path, "r") as f:
        tree_data = json.load(f)
    with open(positions_path, "r") as f:
        positions_by_tile = json.load(f)

    total_trees = 0
    for tile in tree_data.get("tiles", []):
        tile_name = tile.get("tile_name")
        mask_path = tree_dir / f"{tile_name}_mask.png"
        positions = positions_by_tile.get(tile_name, [])
        total_trees += len(positions)
        tile["tree_positions"] = positions
        tile["tree_count"] = len(positions)

        if mask_path.exists():
            mask = np.asarray(Image.open(mask_path).convert("L")) > 0
            tile["tree_pixel_count"] = int(mask.sum())
            tile["tree_pixel_percent"] = float(100 * mask.sum() / mask.size)

    tree_data.setdefault("summary", {})["total_trees"] = total_trees
    with open(data_path, "w") as f:
        json.dump(tree_data, f, indent=2)


def create_clean_building_masks(
    buildings_json_path: Path,
    output_dir: Path,
    road_dir: Path,
    tree_dir: Path | None = None,
    *,
    cleaned_buildings_json_path: Path | None = None,
    remove_colliding_buildings_from_json: bool = True,
) -> dict:
    buildings_json_path = Path(buildings_json_path)
    output_dir = Path(output_dir)
    road_dir = Path(road_dir)
    tree_dir = Path(tree_dir) if tree_dir else None
    ensure_dir(output_dir)

    if not buildings_json_path.exists():
        raise FileNotFoundError(f"Building JSON not found: {buildings_json_path}")

    with open(buildings_json_path, "r") as f:
        building_data = json.load(f)

    tile_entries = building_data.get("tileBuildingsList", [])
    masks_written = 0
    removed_pixels = 0
    removed_buildings = 0

    cleaned_tile_entries = []
    for tile_entry in tile_entries:
        tile_x = tile_entry.get("tile_x")
        tile_y = tile_entry.get("tile_y")
        if tile_x is None or tile_y is None:
            continue

        tile_name = _tile_name_from_coords(int(tile_x), int(tile_y))
        width = int(tile_entry.get("image_width", 512))
        height = int(tile_entry.get("image_height", 512))
        size = (width, height)

        road_occupied = _load_occupancy(road_dir / f"{tile_name}_mask.png", size)
        blocked = road_occupied.copy()
        if tree_dir is not None:
            blocked |= _load_occupancy(tree_dir / f"{tile_name}_mask.png", size)

        tile_mask = np.zeros((height, width), dtype=bool)
        kept_buildings = []

        for building in tile_entry.get("buildings", []):
            building_mask = _building_polygon_mask(building, size)
            collides = bool((building_mask & blocked).any())
            cleaned_building = building_mask & ~blocked
            removed_pixels += int(building_mask.sum() - cleaned_building.sum())

            if cleaned_building.sum() == 0:
                removed_buildings += 1
                continue

            tile_mask |= cleaned_building
            if remove_colliding_buildings_from_json and collides:
                removed_buildings += 1
            else:
                kept_buildings.append(building)

        _save_binary_mask(output_dir / f"{tile_name}_building_mask.png", tile_mask)
        masks_written += 1

        cleaned_entry = dict(tile_entry)
        cleaned_entry["buildings"] = kept_buildings
        cleaned_entry["total_buildings"] = len(kept_buildings)
        cleaned_tile_entries.append(cleaned_entry)

    if cleaned_buildings_json_path is not None:
        cleaned_data = dict(building_data)
        cleaned_data["tileBuildingsList"] = cleaned_tile_entries
        with open(cleaned_buildings_json_path, "w") as f:
            json.dump(cleaned_data, f, indent=2)

    return {
        "building_tiles_checked": len(tile_entries),
        "building_masks_written": masks_written,
        "building_pixels_removed": removed_pixels,
        "buildings_removed": removed_buildings,
    }


def _building_polygon_mask(building: dict, size: tuple[int, int]) -> np.ndarray:
    image = Image.new("L", size, 0)
    draw = ImageDraw.Draw(image)
    points = building.get("corner_points") or _bbox_points(building)
    draw.polygon([(float(x), float(y)) for x, y in points], fill=255)
    return np.asarray(image) > 0


def _bbox_points(building: dict) -> Iterable[tuple[float, float]]:
    cx = float(building.get("center_x", 0))
    cy = float(building.get("center_y", 0))
    width = float(building.get("width", 0))
    height = float(building.get("height", 0))
    return [
        (cx - width / 2, cy - height / 2),
        (cx + width / 2, cy - height / 2),
        (cx + width / 2, cy + height / 2),
        (cx - width / 2, cy + height / 2),
    ]
