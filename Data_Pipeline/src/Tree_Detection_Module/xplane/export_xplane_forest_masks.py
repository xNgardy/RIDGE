#!/usr/bin/env python3

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


_TAG_TIEPOINT = 33922
_TAG_PIXEL_SCALE = 33550


@dataclass
class Polygon:
    tile_name: str
    windings: list[list[tuple[float, float]]]


def read_geotiff_transform(tif_path: Path):
    with Image.open(tif_path) as img:
        tags = getattr(img, "tag_v2", None) or getattr(img, "tag", None)

        if tags is None or _TAG_TIEPOINT not in tags or _TAG_PIXEL_SCALE not in tags:
            raise RuntimeError(f"Cannot read GeoTIFF transform tags from {tif_path}")

        tiepoint = tags[_TAG_TIEPOINT]
        pixel_scale = tags[_TAG_PIXEL_SCALE]
        width, height = img.size

    origin_lon = float(tiepoint[3])
    origin_lat = float(tiepoint[4])
    scale_x = float(pixel_scale[0])
    scale_y = float(pixel_scale[1])
    return origin_lon, origin_lat, scale_x, scale_y, width, height


def pixel_to_lonlat(col: float, row: float, transform) -> tuple[float, float]:
    origin_lon, origin_lat, scale_x, scale_y, _width, _height = transform
    lon = origin_lon + col * scale_x
    lat = origin_lat - row * scale_y
    return lon, lat


def signed_area(points: list[tuple[float, float]]) -> float:
    area = 0.0
    for idx, (x1, y1) in enumerate(points):
        x2, y2 = points[(idx + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def orient(points: list[tuple[float, float]], ccw: bool) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    is_ccw = signed_area(points) > 0
    if is_ccw != ccw:
        return list(reversed(points))
    return points


def contour_to_points(contour, transform, simplify_px: float, ccw: bool):
    if simplify_px > 0:
        contour = cv2.approxPolyDP(contour, simplify_px, True)

    pts = contour.reshape(-1, 2)
    if len(pts) < 3:
        return None

    lonlat = [pixel_to_lonlat(float(col), float(row), transform) for col, row in pts]

    if len(lonlat) > 1 and lonlat[0] == lonlat[-1]:
        lonlat = lonlat[:-1]

    if len(lonlat) < 3:
        return None
    return orient(lonlat, ccw=ccw)


def apply_morphology(mask: np.ndarray, open_radius: int, close_radius: int) -> np.ndarray:
    out = mask
    if open_radius > 0:
        size = open_radius * 2 + 1
        kernel = np.ones((size, size), dtype=np.uint8)
        out = cv2.morphologyEx(out, cv2.MORPH_OPEN, kernel)
    if close_radius > 0:
        size = close_radius * 2 + 1
        kernel = np.ones((size, size), dtype=np.uint8)
        out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, kernel)
    return out


def extract_polygons(
    mask_path: Path,
    ref_tif_path: Path,
    min_area_px: float,
    min_hole_area_px: float,
    simplify_px: float,
    open_radius_px: int,
    close_radius_px: int,
) -> list[Polygon]:
    tile_name = mask_path.name.replace("_mask.png", "")
    transform = read_geotiff_transform(ref_tif_path)

    mask_img = Image.open(mask_path).convert("L")
    mask = (np.array(mask_img) > 0).astype(np.uint8) * 255
    mask = apply_morphology(mask, open_radius_px, close_radius_px)

    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []

    hierarchy = hierarchy[0]
    polygons: list[Polygon] = []

    for idx, contour in enumerate(contours):
        parent = hierarchy[idx][3]
        if parent != -1:
            continue

        if cv2.contourArea(contour) < min_area_px:
            continue

        outer = contour_to_points(contour, transform, simplify_px, ccw=True)
        if not outer:
            continue

        windings = [outer]
        child = hierarchy[idx][2]
        while child != -1:
            hole = contours[child]
            if cv2.contourArea(hole) >= min_hole_area_px:
                hole_points = contour_to_points(hole, transform, simplify_px, ccw=False)
                if hole_points:
                    windings.append(hole_points)
            child = hierarchy[child][0]

        polygons.append(Polygon(tile_name=tile_name, windings=windings))

    return polygons


def dsf_key_for_polygon(poly: Polygon) -> tuple[int, int]:
    points = poly.windings[0]
    west = math.floor(min(lon for lon, _lat in points))
    south = math.floor(min(lat for _lon, lat in points))
    return west, south


def format_dsf_name(south: int, west: int) -> str:
    return f"{south:+03d}{west:+04d}.dsf"


def format_dsf_folder(south: int, west: int) -> str:
    folder_south = math.floor(south / 10) * 10
    folder_west = math.floor(west / 10) * 10
    return f"{folder_south:+03d}{folder_west:+04d}"


def output_path_for_key(base_output: Path, west: int, south: int, multiple: bool) -> Path:
    if base_output.suffix.lower() == ".txt" and not multiple:
        return base_output

    out_dir = base_output if base_output.suffix == "" else base_output.parent
    stem = base_output.stem if base_output.suffix else "ridge_forests"
    return out_dir / f"{stem}_{format_dsf_name(south, west).replace('.dsf', '')}.txt"


def write_dsf_text(
    out_path: Path,
    west: int,
    south: int,
    polygons: list[Polygon],
    forest_resource: str,
    density: int,
    exclude_default_forests: bool,
    exclude_lower_priority_objects: bool,
) -> None:
    east = west + 1
    north = south + 1
    exclusion = f"{west:.6f}/{south:.6f}/{east:.6f}/{north:.6f}"

    lines = [
        "A",
        "800",
        "DSF2TEXT",
        "",
        "DIVISIONS 32",
        "",
        "PROPERTY sim/planet earth",
        "PROPERTY sim/overlay 1",
    ]

    if exclude_default_forests:
        lines.append(f"PROPERTY sim/exclude_for {exclusion}")
    if exclude_lower_priority_objects:
        lines.append(f"PROPERTY sim/exclude_obj {exclusion}")

    lines.extend(
        [
            f"PROPERTY sim/west {west}",
            f"PROPERTY sim/east {east}",
            f"PROPERTY sim/south {south}",
            f"PROPERTY sim/north {north}",
            "",
            "# RIDGE Project - mask-based forest export",
            f"POLYGON_DEF {forest_resource}",
            "",
        ]
    )

    current_tile = None
    for poly in polygons:
        if poly.tile_name != current_tile:
            current_tile = poly.tile_name
            lines.append(f"# Forest polygons for {current_tile}")

        lines.append(f"BEGIN_POLYGON 0 {density} 2")
        for winding in poly.windings:
            lines.append("BEGIN_WINDING")
            for lon, lat in winding:
                lines.append(f"POLYGON_POINT {lon:.8f} {lat:.8f}")
            lines.append("END_WINDING")
        lines.append("END_POLYGON")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Export RIDGE tree mask PNGs as X-Plane forest polygon DSF Text."
    )
    parser.add_argument("unity_output", help="Path to Data_Pipeline/outputs/unity_output")
    parser.add_argument(
        "output_file",
        nargs="?",
        default="ridge_forests.txt",
        help="Output DSF Text file or output directory (default: ridge_forests.txt)",
    )
    parser.add_argument(
        "--forest",
        default="lib/g8/mixed_tmp_sdry.for",
        help="X-Plane .for library path (default: lib/g8/mixed_tmp_sdry.for)",
    )
    parser.add_argument(
        "--density",
        type=int,
        default=255,
        help="Forest density parameter, 0-255 (default: 255)",
    )
    parser.add_argument(
        "--min-area-px",
        type=float,
        default=40,
        help="Skip mask islands smaller than this pixel area (default: 40)",
    )
    parser.add_argument(
        "--min-hole-area-px",
        type=float,
        default=40,
        help="Skip holes smaller than this pixel area (default: 40)",
    )
    parser.add_argument(
        "--simplify-px",
        type=float,
        default=2.0,
        help="Contour simplification tolerance in pixels (default: 2.0)",
    )
    parser.add_argument(
        "--open-radius-px",
        type=int,
        default=0,
        help="Morphological opening radius to remove speckles (default: 0)",
    )
    parser.add_argument(
        "--close-radius-px",
        type=int,
        default=1,
        help="Morphological closing radius to bridge tiny gaps (default: 1)",
    )
    parser.add_argument(
        "--no-exclude-default-forests",
        action="store_true",
        help="Do not emit sim/exclude_for for the whole DSF tile.",
    )
    parser.add_argument(
        "--exclude-objects",
        action="store_true",
        help=(
            "Also emit sim/exclude_obj for the whole DSF tile. This can remove "
            "object-based trees from lower-priority scenery, but also removes "
            "other lower-priority objects such as buildings."
        ),
    )
    parser.add_argument(
        "--max-tiles",
        type=int,
        default=None,
        help="Debug option: process only the first N mask tiles.",
    )
    args = parser.parse_args()

    if args.density < 0 or args.density > 255:
        raise SystemExit("Error: --density must be between 0 and 255.")

    unity_output = Path(args.unity_output)
    masks_dir = unity_output / "tiles_trees"
    ref_tifs_dir = unity_output / "tiles_height_tif"
    output_file = Path(args.output_file)

    if not masks_dir.exists():
        raise SystemExit(f"Error: mask directory not found: {masks_dir}")
    if not ref_tifs_dir.exists():
        raise SystemExit(f"Error: reference GeoTIFF directory not found: {ref_tifs_dir}")

    mask_paths = sorted(masks_dir.glob("tile_*_*_mask.png"))
    if args.max_tiles is not None:
        mask_paths = mask_paths[: args.max_tiles]
    if not mask_paths:
        raise SystemExit(f"Error: no mask PNG files found in {masks_dir}")

    grouped: dict[tuple[int, int], list[Polygon]] = {}
    skipped = 0
    total_polygons = 0

    print(f"Found {len(mask_paths)} mask tiles")
    for mask_path in mask_paths:
        tile_name = mask_path.name.replace("_mask.png", "")
        ref_tif_path = ref_tifs_dir / f"{tile_name}.tif"
        if not ref_tif_path.exists():
            print(f"  Skipping {tile_name}: missing reference GeoTIFF")
            skipped += 1
            continue

        polygons = extract_polygons(
            mask_path=mask_path,
            ref_tif_path=ref_tif_path,
            min_area_px=args.min_area_px,
            min_hole_area_px=args.min_hole_area_px,
            simplify_px=args.simplify_px,
            open_radius_px=args.open_radius_px,
            close_radius_px=args.close_radius_px,
        )

        for poly in polygons:
            grouped.setdefault(dsf_key_for_polygon(poly), []).append(poly)

        total_polygons += len(polygons)
        print(f"  {tile_name}: {len(polygons)} forest polygons")

    if not grouped:
        raise SystemExit("Error: no forest polygons were generated from masks.")

    multiple = len(grouped) > 1
    print()
    print(f"Writing {total_polygons} forest polygons into {len(grouped)} DSF text file(s)")

    for (west, south), polygons in sorted(grouped.items()):
        out_path = output_path_for_key(output_file, west, south, multiple)
        write_dsf_text(
            out_path=out_path,
            west=west,
            south=south,
            polygons=polygons,
            forest_resource=args.forest,
            density=args.density,
            exclude_default_forests=not args.no_exclude_default_forests,
            exclude_lower_priority_objects=args.exclude_objects,
        )

        dsf_name = format_dsf_name(south, west)
        dsf_folder = format_dsf_folder(south, west)
        print(f"  Text: {out_path}")
        print(f"  DSF : {dsf_name}")
        print(f"  Put : Custom Scenery/<package>/Earth nav data/{dsf_folder}/{dsf_name}")
        print(f"  Run : DSFTool --text2dsf {out_path.name} {dsf_name}")

    if skipped:
        print(f"Skipped tiles: {skipped}")


if __name__ == "__main__":
    main()
