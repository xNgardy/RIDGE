#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from .mask_postprocess import (
        clean_tree_masks_against_roads,
        complete_buildings_json_from_images,
        complete_road_masks_from_images,
        complete_road_jsons_from_images,
        complete_tree_outputs_from_images,
        create_clean_building_masks,
    )
    from .unity_export import export_unity_package
except ImportError:
    from mask_postprocess import (
        clean_tree_masks_against_roads,
        complete_buildings_json_from_images,
        complete_road_masks_from_images,
        complete_road_jsons_from_images,
        complete_tree_outputs_from_images,
        create_clean_building_masks,
    )
    from unity_export import export_unity_package


THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parents[2]
DATA_PIPELINE = PROJECT_ROOT / "Data_Pipeline"
SRC_DIR = DATA_PIPELINE / "src"
DEFAULT_RAMP_BUILDING_MODEL = (
    SRC_DIR
    / "Building_Detection_Module"
    / "models"
    / "building-footprint-extract"
    / "3"
    / "weights.onnx"
)
DEFAULT_PREPARED_RGB_TIFS = DATA_PIPELINE / "outputs" / "RGB_tifs"
DEFAULT_PREPARED_UNITY_OUTPUT = DATA_PIPELINE / "outputs" / "unity_output"
DEFAULT_RAW_WORK_DIR = DATA_PIPELINE / "outputs" / "automatic_run"
DEFAULT_UNITY_PACKAGE_DIR = DATA_PIPELINE / "outputs" / "unity_ready" / "Terrain_Tiles"
CONFLICTING_GEOSPATIAL_ENV_VARS = (
    "PROJ_DATA",
    "PROJ_LIB",
    "GDAL_DATA",
    "GDAL_DRIVER_PATH",
)


def run_command(command: list[str], *, env: dict | None = None) -> None:
    print("\n> " + " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, check=True, env=clean_subprocess_env(env))


def clean_subprocess_env(env: dict | None = None) -> dict:
    cleaned = dict(env or os.environ)
    for key in CONFLICTING_GEOSPATIAL_ENV_VARS:
        cleaned.pop(key, None)
    cache_root = Path(tempfile.gettempdir()) / "ridge-pipeline-cache"
    matplotlib_cache = cache_root / "matplotlib"
    matplotlib_cache.mkdir(parents=True, exist_ok=True)
    cleaned.setdefault("MPLCONFIGDIR", str(matplotlib_cache))
    cleaned.setdefault("XDG_CACHE_HOME", str(cache_root))
    return cleaned


def configure_runtime_environment() -> None:
    for key in CONFLICTING_GEOSPATIAL_ENV_VARS:
        os.environ.pop(key, None)


def configure_paths(args: argparse.Namespace) -> None:
    if args.input_mode == "raw":
        args.work_dir = (args.work_dir or DEFAULT_RAW_WORK_DIR).resolve()
        args.rgb_tifs = args.work_dir / "RGB_tifs"
        args.unity_output = args.work_dir / "unity_output"
    else:
        args.rgb_tifs = (args.rgb_tifs or DEFAULT_PREPARED_RGB_TIFS).resolve()
        args.unity_output = (args.unity_output or DEFAULT_PREPARED_UNITY_OUTPUT).resolve()

    args.building_images = (args.building_images or args.unity_output / "tiles_rgb").resolve()
    args.buildings_json = (args.buildings_json or args.unity_output / "buildings.json").resolve()
    args.cleaned_buildings_json = (
        args.cleaned_buildings_json or args.unity_output / "buildings_cleaned.json"
    ).resolve()
    args.building_masks_out = (
        args.building_masks_out or args.unity_output / "tiles_buildings"
    ).resolve()
    args.unity_package_dir = (args.unity_package_dir or DEFAULT_UNITY_PACKAGE_DIR).resolve()
    args.ramp_building_model = args.ramp_building_model.resolve()
    args.ndvi_file = args.ndvi_file.resolve() if args.ndvi_file else None
    args.raw_rgb_file = args.raw_rgb_file.resolve() if args.raw_rgb_file else None
    args.dem_file = args.dem_file.resolve() if args.dem_file else None
    args.road_masks = args.road_masks.resolve() if args.road_masks else args.rgb_tifs / "_roads_out_rgb"
    args.tree_masks = args.tree_masks.resolve() if args.tree_masks else args.unity_output / "tiles_trees"


def validate_inputs(args: argparse.Namespace) -> None:
    if not args.skip_buildings and args.building_detector == "ramp":
        if not args.ramp_building_model.is_file():
            raise FileNotFoundError(f"RAMP building model not found: {args.ramp_building_model}")

    if args.input_mode == "raw":
        missing = []
        if args.raw_rgb_file is None or not args.raw_rgb_file.is_file():
            missing.append("Raw RGB GeoTIFF")
        if args.dem_file is None or not args.dem_file.is_file():
            missing.append("DEM GeoTIFF")
        if not args.skip_trees and (args.ndvi_file is None or not args.ndvi_file.is_file()):
            missing.append("NDVI GeoTIFF")
        if missing:
            raise FileNotFoundError("Missing raw input(s): " + ", ".join(missing))
        if args.tile_size <= 0 or args.tile_size & (args.tile_size - 1):
            raise ValueError("Tile size must be a positive power of two, such as 256, 512, or 1024.")
        if (
            args.skip_roads
            or args.skip_road_json
            or args.skip_ndvi_tiling
            or args.skip_trees
            or args.skip_buildings
        ):
            raise ValueError(
                "Skip options cannot be used in raw mode because its working data is rebuilt from scratch."
            )
        if args.rgb_tifs == DEFAULT_PREPARED_RGB_TIFS.resolve() or (
            args.unity_output == DEFAULT_PREPARED_UNITY_OUTPUT.resolve()
        ):
            raise ValueError(
                "Raw mode cannot overwrite the default prepared-data folders. "
                "Choose a separate intermediate workspace."
            )
        generated_dirs = (args.rgb_tifs, args.unity_output)
        source_files = (args.raw_rgb_file, args.dem_file, args.ndvi_file)
        for source in source_files:
            if source and any(source.is_relative_to(directory) for directory in generated_dirs):
                raise ValueError(
                    f"Raw input {source} is inside a generated output folder and would be deleted."
                )
        return

    required = [
        args.rgb_tifs,
        args.unity_output / "tile_metadata.json",
        args.unity_output / "tiles_rgb",
        args.unity_output / "tiles_height",
        args.unity_output / "tiles_height_tif",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if not args.skip_trees and args.skip_ndvi_tiling:
        tiles_ndvi = args.unity_output / "tiles_ndvi"
        if not tiles_ndvi.exists() or not any(tiles_ndvi.glob("tile_*.tif")):
            missing.append(str(tiles_ndvi))
    if missing:
        raise FileNotFoundError(
            "Prepared mode is missing required files/folders:\n- " + "\n- ".join(missing)
        )


def prepare_raw_inputs(args: argparse.Namespace) -> None:
    print("\nPreparing Unity tile data from raw GeoTIFFs.")
    print(f"Raw RGB GeoTIFF: {args.raw_rgb_file}")
    print(f"Raw DEM GeoTIFF: {args.dem_file}")
    print(f"Raw-data workspace: {args.work_dir}")

    for path in (args.rgb_tifs, args.unity_output):
        if path.exists():
            shutil.rmtree(path)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    rgb_slicer = SRC_DIR / "Core_Terrain_Module" / "rgb_slicer.py"
    terrain_tiler = SRC_DIR / "Core_Terrain_Module" / "tiler.py"
    run_command([
        args.python,
        str(rgb_slicer),
        str(args.raw_rgb_file),
        str(args.rgb_tifs),
        "--tile-size",
        str(args.tile_size),
    ])
    run_command([
        args.python,
        str(terrain_tiler),
        str(args.rgb_tifs),
        str(args.dem_file),
        str(args.unity_output),
    ])
    print("Raw RGB and DEM preparation finished.")


def run_roads(args: argparse.Namespace) -> Path:
    road_script = SRC_DIR / "Road_Detection_Module" / "Road_rgb_mask.py"
    env = os.environ.copy()
    env["TIFS_DIR"] = str(args.rgb_tifs)
    run_command([args.python, str(road_script)], env=env)
    return args.rgb_tifs / "_roads_out_rgb"


def run_road_jsons(args: argparse.Namespace) -> Path:
    try:
        from .road_json_exporter import export_road_jsons
    except ImportError:
        from road_json_exporter import export_road_jsons

    road_json_dir = args.unity_output / "roads"
    summary = export_road_jsons(args.rgb_tifs, road_json_dir, road_width_m=args.road_width_m)
    print(f"Road JSON export summary: {summary}")
    return road_json_dir


def run_ndvi_tiling(args: argparse.Namespace) -> None:
    if args.ndvi_file is None:
        print("Skipping NDVI tiling: no NDVI file was provided.")
        return
    ndvi_script = SRC_DIR / "Tree_Detection_Module" / "crop_and_tile_ndvi.py"
    run_command([args.python, str(ndvi_script), str(args.ndvi_file), str(args.unity_output)])


def run_tree_masks(args: argparse.Namespace) -> Path:
    tree_script = SRC_DIR / "Tree_Detection_Module" / "generate_tree_masks.py"
    command = [
        args.python,
        str(tree_script),
        str(args.unity_output),
        "--threshold",
        str(args.tree_threshold),
        "--density",
        str(args.tree_density),
        "--min-ndvi",
        str(args.min_ndvi),
        "--seed",
        str(args.seed),
        "--band",
        str(args.ndvi_band),
    ]
    if args.invert_tree_mask:
        command.append("--invert")
    if args.low_is_tree:
        command.append("--low-is-tree")
    run_command(command)
    return args.unity_output / "tiles_trees"


def run_buildings(args: argparse.Namespace) -> Path:
    building_module_dir = SRC_DIR / "Building_Detection_Module"
    if args.building_detector == "roboflow":
        detector_path = building_module_dir / "building_detector_local.py"
        module = _load_module(detector_path)
        detector = module.BuildingDetector(api_key=args.roboflow_api_key or None)
        confidence = args.building_confidence
    elif args.building_detector == "ramp":
        detector_path = building_module_dir / "Ramp_Building_Detector.py"
        module = _load_module(detector_path)
        detector = module.BuildingDetector(model_path=str(args.ramp_building_model))
        confidence = args.building_confidence / 100.0
    else:
        raise ValueError(f"Unsupported building detector: {args.building_detector}")

    args.buildings_json.parent.mkdir(parents=True, exist_ok=True)
    print(f"Running {args.building_detector} building detector.")
    if args.building_detector == "ramp":
        print(f"RAMP model: {args.ramp_building_model}")

    detector.process_batch(
        args.building_images,
        output_path=args.buildings_json,
        confidence=confidence,
    )
    print(f"Saved building JSON to {args.buildings_json}")
    return args.buildings_json


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_pipeline(args: argparse.Namespace) -> None:
    configure_runtime_environment()
    configure_paths(args)
    validate_inputs(args)

    print("Automatic mask pipeline started.")
    print(f"Input mode: {args.input_mode}")
    print(f"RGB GeoTIFF folder: {args.rgb_tifs}")
    print(f"Unity output folder: {args.unity_output}")
    print(f"Building detector: {args.building_detector}")

    if args.input_mode == "raw":
        prepare_raw_inputs(args)

    road_masks = args.road_masks
    if not args.skip_roads:
        road_masks = run_roads(args)
    else:
        print(f"Skipping road extraction; using existing road masks: {road_masks}")
    road_mask_completion = complete_road_masks_from_images(road_masks, args.building_images)
    print(f"Road mask completion summary: {road_mask_completion}")

    road_json_dir = args.unity_output / "roads"
    if not args.skip_road_json:
        road_json_dir = run_road_jsons(args)
    else:
        print(f"Skipping road JSON export; using existing road JSON folder: {road_json_dir}")
    road_json_completion = complete_road_jsons_from_images(road_json_dir, args.building_images, args.road_width_m)
    print(f"Road JSON completion summary: {road_json_completion}")

    tree_masks = args.tree_masks
    if not args.skip_trees:
        if not args.skip_ndvi_tiling:
            run_ndvi_tiling(args)
        tree_masks = run_tree_masks(args)
        tree_summary = clean_tree_masks_against_roads(tree_masks, road_masks)
        print(f"Tree-road cleanup summary: {tree_summary}")
        tree_completion_summary = complete_tree_outputs_from_images(tree_masks, args.building_images)
        print(f"Tree output completion summary: {tree_completion_summary}")
    else:
        print(f"Skipping tree masks; using existing tree masks: {tree_masks}")
        tree_summary = clean_tree_masks_against_roads(tree_masks, road_masks)
        print(f"Tree-road cleanup summary: {tree_summary}")
        tree_completion_summary = complete_tree_outputs_from_images(tree_masks, args.building_images)
        print(f"Tree output completion summary: {tree_completion_summary}")

    buildings_json = args.buildings_json
    if not args.skip_buildings:
        buildings_json = run_buildings(args)
        completion_summary = complete_buildings_json_from_images(buildings_json, args.building_images)
        print(f"Building JSON completion summary: {completion_summary}")
    else:
        print(f"Skipping building detection; using existing building JSON: {buildings_json}")
        completion_summary = complete_buildings_json_from_images(buildings_json, args.building_images)
        print(f"Building JSON completion summary: {completion_summary}")

    building_summary = create_clean_building_masks(
        buildings_json,
        args.building_masks_out,
        road_masks,
        tree_masks,
        cleaned_buildings_json_path=args.cleaned_buildings_json,
    )
    print(f"Building cleanup summary: {building_summary}")

    package_summary = export_unity_package(
        args.unity_output,
        args.unity_package_dir,
        road_masks_dir=road_masks,
        road_json_dir=road_json_dir,
        tree_dir=tree_masks,
        buildings_json=args.cleaned_buildings_json if args.cleaned_buildings_json.exists() else buildings_json,
        building_masks_dir=args.building_masks_out,
    )
    print(f"Unity package summary: {package_summary}")

    print("\nAutomatic mask pipeline finished.")
    print(f"Road masks: {road_masks}")
    print(f"Tree masks: {tree_masks}")
    print(f"Building JSON: {buildings_json}")
    print(f"Clean building masks: {args.building_masks_out}")
    print(f"Clean building JSON: {args.cleaned_buildings_json}")
    print(f"Unity-ready package: {args.unity_package_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fully automatic raw GeoTIFF or prepared Unity tile pipeline"
    )
    parser.add_argument("--python", default=sys.executable, help="Python executable used for subprocess steps")
    parser.add_argument("--input-mode", choices=("prepared", "raw"), default="prepared")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Raw mode workspace; RGB_tifs and unity_output are rebuilt inside it",
    )
    parser.add_argument("--raw-rgb-file", type=Path, default=None, help="Uncropped RGB GeoTIFF")
    parser.add_argument("--dem-file", type=Path, default=None, help="Uncropped DEM GeoTIFF")
    parser.add_argument("--tile-size", type=int, default=512, help="Raw RGB tile size in pixels")
    parser.add_argument("--rgb-tifs", type=Path, default=None)
    parser.add_argument("--unity-output", type=Path, default=None)
    parser.add_argument("--ndvi-file", type=Path, default=None, help="Optional source NDVI TIFF")
    parser.add_argument("--building-images", type=Path, default=None)

    parser.add_argument("--road-masks", type=Path, default=None, help="Existing road mask folder when skipping roads")
    parser.add_argument("--tree-masks", type=Path, default=None, help="Existing tree mask folder when skipping trees")
    parser.add_argument("--buildings-json", type=Path, default=None)
    parser.add_argument("--cleaned-buildings-json", type=Path, default=None)
    parser.add_argument("--building-masks-out", type=Path, default=None)
    parser.add_argument("--unity-package-dir", type=Path, default=None)

    parser.add_argument("--tree-threshold", type=float, default=0.4)
    parser.add_argument("--tree-density", type=float, default=0.05)
    parser.add_argument("--min-ndvi", type=float, default=0.4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ndvi-band", type=int, default=1)
    parser.add_argument("--invert-tree-mask", action="store_true")
    parser.add_argument("--low-is-tree", action="store_true")

    parser.add_argument("--building-detector", choices=("roboflow", "ramp"), default="roboflow")
    parser.add_argument("--building-confidence", type=int, default=40, help="Roboflow confidence 0-100; RAMP fill-ratio threshold uses this value divided by 100")
    parser.add_argument("--roboflow-api-key", default=os.getenv("ROBOFLOW_API_KEY", ""))
    parser.add_argument(
        "--ramp-building-model",
        type=Path,
        default=DEFAULT_RAMP_BUILDING_MODEL,
        help="Path to the RAMP XUNet ONNX model when --building-detector ramp is selected",
    )
    parser.add_argument("--road-width-m", type=float, default=6.0)

    parser.add_argument("--skip-roads", action="store_true")
    parser.add_argument("--skip-road-json", action="store_true")
    parser.add_argument("--skip-ndvi-tiling", action="store_true")
    parser.add_argument("--skip-trees", action="store_true")
    parser.add_argument("--skip-buildings", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
