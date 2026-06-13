#!/usr/bin/env python3
"""
Export RIDGE tree mask PNG to X-Plane DSF Text forest polygons.

This is the faster X-Plane path for dense vegetation: instead of writing one
OBJECT per detected tree, it converts each binary mask region into a forest
polygon that X-Plane fills at runtime from a .for resource.

Usage:
    python export_xplane_forest_masks.py <mask_file> <rgb_tif> [output_txt_file]

Example:
    python export_xplane_forest_masks.py mask.png reference.tif ridge_forests_strict.txt --exclude-objects
    xptools_mac_24-5/tools/DSFTool --text2dsf ridge_forests_strict.txt +37+036_strict.dsf
"""

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
import warnings

import cv2
import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning

@dataclass
class Polygon:
    tile_name: str
    windings: list[list[tuple[float, float]]]


def read_geotiff_transform(tif_path: Path):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)
        with rasterio.open(tif_path) as src:
            # src.transform contains the affine transform matrix
            # c is origin_lon, f is origin_lat, a is scale_x, e is scale_y (negative)
            origin_lon = src.transform.c
            origin_lat = src.transform.f
            scale_x = src.transform.a
            scale_y = -src.transform.e  # Negated because pixel_to_lonlat expects a positive value to subtract
            
            width = src.width
            height = src.height
        
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

    # Drop a duplicate closing point if OpenCV ever returns one. DSF windings
    # are implicitly closed.
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
    tile_name = mask_path.stem.replace("_mask", "")
    transform = read_geotiff_transform(ref_tif_path)

    with rasterio.open(mask_path) as src:
        # Read the first band (index 1 in rasterio)
        mask = src.read(1) 

    mask = (mask > 0).astype(np.uint8) * 255
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

    # X-Plane requires the bounds properties to be the last PROPERTY commands.
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


def export_forest_masks(
    mask_file: Path,
    rgb_tif: Path,
    output_file: Path,
    forest: str = "lib/g8/mixed_tmp_sdry.for",
    density: int = 255,
    min_area_px: float = 40.0,
    min_hole_area_px: float = 40.0,
    simplify_px: float = 2.0,
    open_radius_px: int = 0,
    close_radius_px: int = 1,
    exclude_default_forests: bool = True,
    exclude_objects: bool = False,
):
    if density < 0 or density > 255:
        raise ValueError("Error: density must be between 0 and 255.")

    if not mask_file.exists():
        raise FileNotFoundError(f"Error: mask file not found: {mask_file}")
    if not rgb_tif.exists():
        raise FileNotFoundError(f"Error: reference GeoTIFF file not found: {rgb_tif}")

    grouped: dict[tuple[int, int], list[Polygon]] = {}
    total_polygons = 0

    print(f"Processing mask file: {mask_file.name}")
    
    polygons = extract_polygons(
        mask_path=mask_file,
        ref_tif_path=rgb_tif,
        min_area_px=min_area_px,
        min_hole_area_px=min_hole_area_px,
        simplify_px=simplify_px,
        open_radius_px=open_radius_px,
        close_radius_px=close_radius_px,
    )

    for poly in polygons:
        grouped.setdefault(dsf_key_for_polygon(poly), []).append(poly)

    total_polygons += len(polygons)
    print(f"  Generated {len(polygons)} forest polygons")

    if not grouped:
        print("Warning: no forest polygons were generated from masks.")
        return

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
            forest_resource=forest,
            density=density,
            exclude_default_forests=exclude_default_forests,
            exclude_lower_priority_objects=exclude_objects,
        )

        dsf_name = format_dsf_name(south, west)
        dsf_folder = format_dsf_folder(south, west)
        print(f"  Text: {out_path}")
        print(f"  DSF : {dsf_name}")


def main():
    parser = argparse.ArgumentParser(
        description="Export a RIDGE tree mask PNG as X-Plane forest polygon DSF Text using an RGB TIFF for geo-referencing."
    )
    parser.add_argument("mask_file", help="Path to the tree mask PNG file")
    parser.add_argument("rgb_tif", help="Path to the reference RGB GeoTIFF file")
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
    args = parser.parse_args()

    try:
        export_forest_masks(
            mask_file=Path(args.mask_file),
            rgb_tif=Path(args.rgb_tif),
            output_file=Path(args.output_file),
            forest=args.forest,
            density=args.density,
            min_area_px=args.min_area_px,
            min_hole_area_px=args.min_hole_area_px,
            simplify_px=args.simplify_px,
            open_radius_px=args.open_radius_px,
            close_radius_px=args.close_radius_px,
            exclude_default_forests=not args.no_exclude_default_forests,
            exclude_objects=args.exclude_objects,
        )
    except Exception as e:
        raise SystemExit(str(e))

if __name__ == "__main__":
    main()
