#!/usr/bin/env python3

from __future__ import annotations

import shutil
from pathlib import Path


def export_unity_package(
    unity_output: Path,
    package_dir: Path,
    *,
    road_masks_dir: Path | None = None,
    road_json_dir: Path | None = None,
    tree_dir: Path | None = None,
    buildings_json: Path | None = None,
    building_masks_dir: Path | None = None,
) -> dict:
    unity_output = Path(unity_output)
    package_dir = Path(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    _copy_file(unity_output / "tile_metadata.json", package_dir / "tile_metadata.json", copied)
    _copy_dir(unity_output / "tiles_rgb", package_dir / "tiles_rgb", copied)
    _copy_dir(unity_output / "tiles_height", package_dir / "tiles_height", copied)
    _copy_dir(unity_output / "tiles_height_raw", package_dir / "tiles_height_raw", copied, optional=True)
    _copy_dir(unity_output / "tiles_height_tif", package_dir / "tiles_height_tif", copied, optional=True)

    if tree_dir:
        _copy_dir(Path(tree_dir), package_dir / "tiles_trees", copied, optional=True)
    if buildings_json:
        _copy_file(Path(buildings_json), package_dir / "buildings.json", copied, optional=True)
    if building_masks_dir:
        _copy_dir(Path(building_masks_dir), package_dir / "tiles_buildings", copied, optional=True)
    if road_masks_dir:
        _copy_dir(Path(road_masks_dir), package_dir / "road_masks", copied, optional=True)
    if road_json_dir:
        legacy_roads_dir = package_dir / "roads"
        if legacy_roads_dir.exists():
            shutil.rmtree(legacy_roads_dir)
        _copy_dir(Path(road_json_dir), package_dir / "Roads", copied, optional=True)

    return {"package_dir": str(package_dir), "copied_items": copied}


def _copy_file(src: Path, dst: Path, copied: list[str], optional: bool = False) -> None:
    if not src.exists():
        if optional:
            return
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied.append(str(dst))


def _copy_dir(src: Path, dst: Path, copied: list[str], optional: bool = False) -> None:
    if not src.exists():
        if optional:
            return
        raise FileNotFoundError(src)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    copied.append(str(dst))
