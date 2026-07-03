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
import os
from pathlib import Path
import warnings
import O4_UI_Utils as UI

import cv2
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from shapely.geometry import Polygon as ShapelyPolygon, MultiPolygon
from shapely.strtree import STRtree


@dataclass
class Polygon:
    tile_name: str
    windings: list[list[tuple[float, float]]]

# ═══════════════════════════════════════════════════════════════
# Vector Clipping & Translation Layer (Adapter)
# ═══════════════════════════════════════════════════════════════

def shapely_to_windings(shapely_poly: ShapelyPolygon) -> list[list[tuple[float, float]]]:
    """Translates a Shapely Polygon back into custom point-based windings loops."""
    exterior = list(shapely_poly.exterior.coords)
    interiors = [list(interior.coords) for interior in shapely_poly.interiors]
    return [exterior] + interiors


def clean_tree_polygons(custom_trees: list[Polygon], buffered_roads: list) -> list[Polygon]:
    """
    Subtracts 2D road footprints from point-based custom tree polygons.
    
    🔑 FIX: Merge all road buffers first to avoid GeometryCollection issues
    """
    from shapely.ops import unary_union
    
    if not buffered_roads:
        return custom_trees
    
    # Convert to list and merge ALL road buffers into one unified geometry
    road_geoms = list(buffered_roads) if not isinstance(buffered_roads, list) else buffered_roads
    
    if not road_geoms:
        return custom_trees
    
    # 🔑 CRITICAL: Merge all 686 individual road buffers into 1
    # This prevents GeometryCollection errors from sequential operations
    print(f"Merging {len(road_geoms)} road buffers into one unified geometry...")
    merged_roads = unary_union(road_geoms)
    print(f"Merged road geometry type: {type(merged_roads)}")
    
    # Check road coverage
    print(f"\nDEBUG: Road buffer coverage")
    print(f"  Merged roads area: {merged_roads.area:.2e} sq degrees")
    print(f"  Merged roads bounds: {merged_roads.bounds}")

    # Sample a tree to see if it's actually being subtracted
    sample_tree = custom_trees[7]  # Tree 7 was MODIFIED
    exterior = sample_tree.windings[0]
    interiors = sample_tree.windings[1:] if len(sample_tree.windings) > 1 else None
    tree_shapely = ShapelyPolygon(shell=exterior, holes=interiors)

    print(f"\n  Sample tree (Tree 7):")
    print(f"    Before subtraction area: {tree_shapely.area:.2e}")
    print(f"    Tree bounds: {tree_shapely.bounds}")

    result = tree_shapely.difference(merged_roads)
    print(f"    After subtraction area: {result.area:.2e}")
    print(f"    Area removed: {(1 - result.area/tree_shapely.area)*100:.1f}%")
    print(f"    Result type: {type(result)}")

    cleaned_tree_polygons = []
    
    for tree in custom_trees:
        if not tree.windings:
            continue
            
        exterior = tree.windings[0]
        interiors = tree.windings[1:] if len(tree.windings) > 1 else None
        tree_shapely = ShapelyPolygon(shell=exterior, holes=interiors)
        
        # Single unified subtraction (instead of 686 sequential operations)
        if merged_roads and not merged_roads.is_empty:
            geometry_cursor = tree_shapely.difference(merged_roads)
        else:
            geometry_cursor = tree_shapely
        
        if geometry_cursor.is_empty:
            continue
            
        if isinstance(geometry_cursor, ShapelyPolygon):
            cleaned_tree_polygons.append(
                Polygon(tile_name=tree.tile_name, windings=shapely_to_windings(geometry_cursor))
            )
        elif isinstance(geometry_cursor, MultiPolygon):
            for part in geometry_cursor.geoms:
                cleaned_tree_polygons.append(
                    Polygon(tile_name=tree.tile_name, windings=shapely_to_windings(part))
                )
        elif hasattr(geometry_cursor, 'geoms'):  # GeometryCollection
            # Handle mixed geometry types recursively
            for part in geometry_cursor.geoms:
                if isinstance(part, ShapelyPolygon):
                    cleaned_tree_polygons.append(
                        Polygon(tile_name=tree.tile_name, windings=shapely_to_windings(part))
                    )
                elif isinstance(part, MultiPolygon):
                    for subpart in part.geoms:
                        if isinstance(subpart, ShapelyPolygon):
                            cleaned_tree_polygons.append(
                                Polygon(tile_name=tree.tile_name, windings=shapely_to_windings(subpart))
                            )
                
    return cleaned_tree_polygons


def write_trees_to_gpkg(custom_trees: list[Polygon], gpkg_path: Path):
    """Translates your custom point-list tree structures into a standard GeoPackage file."""        
    if not custom_trees:
        UI.lvprint(1, "No tree polygons found to save to GPKG.")
        return
        
    geometries = []
    tile_names = []
    
    for tree in custom_trees:
        if not tree.windings:
            continue
        # Extract outer hull and any internal holes/clearings
        exterior = tree.windings[0]
        interiors = tree.windings[1:] if len(tree.windings) > 1 else None
        
        try:
            shapely_poly = ShapelyPolygon(shell=exterior, holes=interiors)
            geometries.append(shapely_poly)
            tile_names.append(tree.tile_name)
        except Exception as e:
            # Skip invalid loops gracefully
            continue
            
    # Compile dataframe into geographic coordinate system (WGS84)
    gdf = gpd.GeoDataFrame(
        {"tile_name": tile_names},
        geometry=geometries,
        crs="EPSG:4326"
    )
    
    gpkg_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(gpkg_path, driver="GPKG")
    UI.lvprint(1, f"  Successfully saved {len(gdf)} trees to spatial vector file: {gpkg_path}")


# ═══════════════════════════════════════════════════════════════
# Baseline Core Code Logic
# ═══════════════════════════════════════════════════════════════


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

    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=NotGeoreferencedWarning)
        with rasterio.open(mask_path) as src:
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
    polygon_dir: Path = None,
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
    from ..build_overlay_dsf import clean_overlays
    
    if density < 0 or density > 255:
        raise ValueError("Error: density must be between 0 and 255.")

    if not mask_file.exists():
        raise FileNotFoundError(f"Error: mask file not found: {mask_file}")
    if not rgb_tif.exists():
        raise FileNotFoundError(f"Error: reference GeoTIFF file not found: {rgb_tif}")

    grouped: dict[tuple[int, int], list[Polygon]] = {}
    total_polygons = 0

    UI.lvprint(1, f"Processing mask file: {mask_file.name}")
    
    polygons = extract_polygons(
        mask_path=mask_file,
        ref_tif_path=rgb_tif,
        min_area_px=min_area_px,
        min_hole_area_px=min_hole_area_px,
        simplify_px=simplify_px,
        open_radius_px=open_radius_px,
        close_radius_px=close_radius_px,
    )

    UI.lvprint(1, f"  Generated {len(polygons)} raw forest polygons from mask.")

    road_file = Path(os.path.join(polygon_dir, "road_buffer.gpkg"))

    # ─── Integrated Step: Custom Hook for Vector Road Slicing ───
    if clean_overlays and road_file.exists():
        original_tree_file =  Path(os.path.join(polygon_dir, "original_tree_buffer.gpkg"))
        write_trees_to_gpkg(polygons, original_tree_file)

        UI.lvprint(1, f"  Loading buffered roads from {road_file}...")
        road_gdf = gpd.read_file(road_file)
        buffered_roads = list(road_gdf.geometry)
        if buffered_roads:
            
            print(f"BEFORE clean_tree_polygons: {len(polygons)} trees")
            for i, poly in enumerate(polygons[:3]):  # Just first 3
                print(f"  Tree {i}: windings[0] sample: {poly.windings[0][:3]}")

            UI.lvprint(1, f"  Slicing forest assets against {len(buffered_roads)} road geometry constraints...")
            polygons = clean_tree_polygons(polygons, buffered_roads)
            UI.lvprint(1, f"  Remaining forest polygons after vector cleanup: {len(polygons)}")

            # After clean_tree_polygons() call, add:
            unchanged_count = len([p for p in polygons if p.tile_name == polygons[0].tile_name])  # rough check

            UI.lvprint(1, f"\nDEBUG: Forest polygon count change")
            UI.lvprint(1, f"  Before cleaning: 974 polygons")
            UI.lvprint(1, f"  After cleaning: {len(polygons)} polygons")
            UI.lvprint(1, f"  Increase factor: {len(polygons) / 974:.2f}x")
            UI.lvprint(1, f"  Unchanged count (rough check): {unchanged_count}\n")

        else:
            UI.lvprint(1, "No buffered roads file found. Proceeding without road cleanup.")
        
        tree_file = Path(os.path.join(polygon_dir, "tree_buffer.gpkg"))
        UI.lvprint(1, "  Exporting tree spatial vector data layer...")
        write_trees_to_gpkg(polygons, tree_file)

    for poly in polygons:
        grouped.setdefault(dsf_key_for_polygon(poly), []).append(poly)

    total_polygons += len(polygons)
    UI.lvprint(1, f"  Generated {len(polygons)} forest polygons")

    if not grouped:
        UI.lvprint(1, "Warning: no forest polygons were generated from masks.")
        return

    multiple = len(grouped) > 1
    UI.lvprint(1, "")
    UI.lvprint(1, f"Writing {total_polygons} forest polygons into {len(grouped)} DSF text file(s)")

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
        UI.lvprint(1, f"  Text: {out_path}")
        UI.lvprint(1, f"  DSF : {dsf_name}")


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
