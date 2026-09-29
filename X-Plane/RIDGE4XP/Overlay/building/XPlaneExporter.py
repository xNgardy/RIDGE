"""
X-Plane 12 Scenery Exporter
============================
Reads the buildings.json produced by building_detector.py and generates a
complete, ready-to-install X-Plane 12 custom scenery package containing:

  MyBuildingScenery/
  ├── Earth nav data/
  │   └── +<lat>+<lon>/          (one subfolder per 1°×1° DSF tile)
  │       └── +<lat>+<lon>.txt   (DSF text → convert with DSFTool)
  ├── apt.dat                    (dummy helipad so X-Plane's location search finds the area)
  ├── library.txt                (exports the virtual facade paths used)
  └── scenery_pack.ini           (marks it as a custom scenery pack)

The DSF text files can be compiled to binary with Laminar's DSFTool:
    DSFTool --text2dsf  +40+28.txt  +40+28.dsf

Facade selection
----------------
Buildings are categorised by footprint area into three size buckets (small /
medium / large) and a height is estimated from width/height pixel dims plus the
GeoTIFF resolution.  Each bucket maps to a curated list of X-Plane 12 default
library facades (lib/buildings/facades/…) that ship with every XP12 installation – no third-
party libraries are required.

Usage
-----
    python xplane_exporter.py buildings.json  --xplane /path/to/X-Plane-12
    python xplane_exporter.py buildings.json  --out /tmp/MyBuildingScenery
    python xplane_exporter.py buildings.json  --out ./pkg  --name "OSM_Buildings_Istanbul"
    python xplane_exporter.py buildings.json  --out ./pkg  --gsd 0.5   # metres/pixel
    python xplane_exporter.py buildings.json  --out ./pkg  --exclude-autogen

Options
-------
  --out        Output folder for the scenery package (default: ./XP12_Buildings)
  --name       Package display name (default: folder basename)
  --xplane     X-Plane 12 root – if given, the package is installed directly into
               Custom Scenery and scenery_packs.ini is updated automatically.
  --gsd        Ground sampling distance in metres/pixel of the source imagery
               (default: 0.5 – the 50 cm/px that the RAMP model expects).
               Used to convert pixel width/height to real-world metres for
               facade height estimation.
  --exclude-autogen
               Add a sim/exclude_autogen rectangle for each DSF tile so X-Plane
               won't double-up with its own procedural buildings.
  --min-area   Minimum building footprint in m² to export (default: 25).
"""

import json
import math
import os
import sys
import argparse
import shutil
import random
from pathlib import Path
from collections import defaultdict
import O4_UI_Utils as UI

from shapely.geometry import Polygon as ShapelyPolygon
from shapely.strtree import STRtree
import geopandas as gpd

# ── Facade catalogue (all ship with X-Plane 12, no extra libraries needed) ──
#
# Paths are virtual library keys exactly as they appear in X-Plane's own DSFs.
# Divided into three footprint-area buckets so the visual result is reasonable.
#
# "small"  < 100 m²   – houses / garages / small shops
# "medium" 100–800 m² – mid-rise blocks, warehouses, small offices
# "large"  > 800 m²   – commercial / industrial / tall residential
#
# Facade virtual paths from:
#   Resources/default scenery/1000 autogen/library.txt
# These are the real XP12 paths — .
#
# Buckets by footprint area:
#   small  < 100 m²   – low commercial / small blocks
#   medium 100–800 m² – mid-rise, classic, modern mid
#   large  > 800 m²   – high-rise, glass towers, large commercial
FACADES = {
    "small": [
        "lib/buildings/facades/commercial/low_commercial_01.fac",
        "lib/buildings/facades/commercial/low_commercial_02.fac",
        "lib/buildings/facades/commercial/low_commercial_03.fac",
        "lib/buildings/facades/commercial/low_commercial_04.fac",
        "lib/buildings/facades/commercial/low_commercial_05.fac",
        "lib/buildings/facades/generic/low_modern_01.fac",
    ],
    "medium": [
        "lib/buildings/facades/generic/mid_classic_01.fac",
        "lib/buildings/facades/generic/mid_classic_02.fac",
        "lib/buildings/facades/generic/mid_modern_01.fac",
        "lib/buildings/facades/generic/mid_modern_02.fac",
        "lib/buildings/facades/generic/mid_modern_03.fac",
        "lib/buildings/facades/generic/mid_modern_04.fac",
        "lib/buildings/facades/generic/mid_modern_05.fac",
        "lib/buildings/facades/commercial/low_commercial_06.fac",
        "lib/buildings/facades/commercial/low_commercial_07.fac",
        "lib/buildings/facades/commercial/low_commercial_08.fac",
    ],
    "large": [
        "lib/buildings/facades/generic/high_classic_01.fac",
        "lib/buildings/facades/generic/high_classic_02.fac",
        "lib/buildings/facades/generic/high_modern_01.fac",
        "lib/buildings/facades/generic/high_modern_02.fac",
        "lib/buildings/facades/generic/high_modern_03.fac",
        "lib/buildings/facades/generic/high_modern_04.fac",
        "lib/buildings/facades/generic/high_modern_05.fac",
        "lib/buildings/facades/generic/high_universal_01.fac",
        "lib/buildings/facades/generic/high_universal_02.fac",
        "lib/buildings/facades/generic/high_glass_01.fac",
        "lib/buildings/facades/generic/high_glass_02.fac",
        "lib/buildings/facades/generic/high_glass_03.fac",
        "lib/buildings/facades/generic/high_metallic_01.fac",
    ],
}

# Typical storey height in metres.
FLOOR_HEIGHT_M = 3.5

# ── Helpers ───────────────────────────────────────────────────────────────────

def _tile_key(lat: float, lon: float) -> tuple[int, int]:
    """Return the integer (floor_lat, floor_lon) for the DSF tile that contains lat/lon."""
    return math.floor(lat), math.floor(lon)


def _tile_folder_name(floor_lat: int, floor_lon: int) -> str:
    """'+37+036' style 1°×1° tile name."""
    lat_str = f"+{floor_lat:02d}" if floor_lat >= 0 else f"{floor_lat:03d}"
    lon_str = f"+{floor_lon:03d}" if floor_lon >= 0 else f"{floor_lon:04d}"
    return lat_str + lon_str


def _parent_folder_name(floor_lat: int, floor_lon: int) -> str:
    """'+30+030' style 10°×10° parent folder name (floor to nearest 10)."""
    p_lat = (floor_lat // 10) * 10
    p_lon = (floor_lon // 10) * 10
    lat_str = f"+{p_lat:02d}" if p_lat >= 0 else f"{p_lat:03d}"
    lon_str = f"+{p_lon:03d}" if p_lon >= 0 else f"{p_lon:04d}"
    return lat_str + lon_str


def _pixels_to_metres(px: float, gsd: float) -> float:
    return px * gsd


def _estimate_height(w_px: float, h_px: float, gsd: float) -> float:
    """
    Estimate a plausible building height from its pixel footprint.
    Uses a simple empirical rule: floor(longest_side_m / 10) floors,
    clamped to [1 floor, 12 floors], then converted to metres.
    """
    longest_m = max(_pixels_to_metres(w_px, gsd), _pixels_to_metres(h_px, gsd))
    floors = max(1, min(12, round(longest_m / 10)))
    return floors * FLOOR_HEIGHT_M


def _footprint_area_m2(w_px: float, h_px: float, gsd: float) -> float:
    return _pixels_to_metres(w_px, gsd) * _pixels_to_metres(h_px, gsd)


def _facade_bucket(area_m2: float) -> str:
    if area_m2 < 100:
        return "small"
    elif area_m2 < 800:
        return "medium"
    else:
        return "large"


def _pick_facade(bucket: str) -> str:
    return random.choice(FACADES[bucket])


def _ensure_ccw(points: list[list[float]]) -> list[list[float]]:
    """
    Ensure polygon winding is counter-clockwise (required by X-Plane DSF spec).
    Points are [[lat, lon], ...].  Uses the shoelace formula sign on lon/lat.
    """
    # Use lon as x, lat as y for the signed area test
    n = len(points)
    signed_area = 0.0
    for i in range(n):
        x0, y0 = points[i][1], points[i][0]
        x1, y1 = points[(i + 1) % n][1], points[(i + 1) % n][0]
        signed_area += (x0 * y1 - x1 * y0)
    # Positive area → CCW in standard coords (lon east = +x, lat north = +y)
    if signed_area < 0:
        points = list(reversed(points))
    return points


# ── DSF text generation ───────────────────────────────────────────────────────

def _dsf_text(
    floor_lat: int,
    floor_lon: int,
    buildings: list[dict],
    facade_index: dict[str, int],
    exclude_autogen: bool,
) -> str:
    """
    Build the complete DSF text for one 1°×1° tile.

    buildings     – list of building dicts as they appear in the JSON
    facade_index  – mapping facade_path → integer index in POLYGON_DEF order
    """

    lines = []

    # ── Header properties ─────────────────────────────────────────────────────
    lines.append("# X-Plane DSF overlay – generated by xplane_exporter.py")
    lines.append(f"PROPERTY sim/west  {floor_lon}")
    lines.append(f"PROPERTY sim/east  {floor_lon + 1}")
    lines.append(f"PROPERTY sim/south {floor_lat}")
    lines.append(f"PROPERTY sim/north {floor_lat + 1}")
    lines.append("PROPERTY sim/planet earth")
    lines.append("PROPERTY sim/creation_agent xplane_exporter.py/1.0")
    lines.append("PROPERTY sim/overlay 1")

    if exclude_autogen:
        # Exclusion zones tell X-Plane to suppress lower-priority scenery
        # in a given lon/lat rectangle. We need separate properties for each
        # type of scenery we want to suppress.
        # Format: west/south/east/north  (all lon/lat decimal degrees)
        excl = f"{floor_lon}/{floor_lat}/{floor_lon + 1}/{floor_lat + 1}"
        # Suppress autogen buildings (facades placed by the global scenery)
        lines.append(f"PROPERTY sim/exclude_obj {excl}")
        lines.append(f"PROPERTY sim/exclude_fac {excl}")

    lines.append("")

    # ── Polygon definitions (facade declarations) ─────────────────────────────
    # Sort by index so the order matches the BEGIN_POLYGON ptype references.
    sorted_facades = sorted(facade_index.items(), key=lambda kv: kv[1])
    for path, _ in sorted_facades:
        lines.append(f"POLYGON_DEF {path}")

    lines.append("")

    # ── Polygon placements (one per building) ─────────────────────────────────
    for b in buildings:
        corners = b.get("corner_points_wgs84")
        if not corners or len(corners) < 3:
            continue

        # Ensure corners are within this tile (clip cross-tile buildings)
        for lat, lon in corners:
            if not (floor_lat <= lat <= floor_lat + 1 and
                    floor_lon <= lon <= floor_lon + 1):
                break  # skip buildings that straddle tile boundaries
        else:
            # All corners inside tile – proceed
            corners = _ensure_ccw(corners)

            w_px    = b.get("width_px", 20)
            h_px    = b.get("height_px", 20)
            gsd     = b.get("_gsd", 0.5)          # injected by exporter
            area    = _footprint_area_m2(w_px, h_px, gsd)
            height  = _ensure_height(b, gsd)
            bucket  = _facade_bucket(area)
            facade  = b.get("_facade_path")        # injected by exporter
            ptype   = facade_index[facade]
            param   = int(round(height))           # DSF param = height in metres

            # Per-building exclusion rectangle — suppresses autogen objects
            # (objects, facades) from lower-priority packs within this footprint.
            # Using a small pad (0.00003° ≈ 3m) so exclusion fully covers the footprint.
            lats = [p[0] for p in corners]
            lons = [p[1] for p in corners]
            pad  = 0.00003
            excl_w = min(lons) - pad
            excl_s = min(lats) - pad
            excl_e = max(lons) + pad
            excl_n = max(lats) + pad
            lines.append(
                f"PROPERTY sim/exclude_obj "
                f"{excl_w:.7f}/{excl_s:.7f}/{excl_e:.7f}/{excl_n:.7f}"
            )

            # BEGIN_POLYGON <polygon_def_index> <param> <coord_depth>
            # coord_depth = 2  (lon, lat only – no elevation, no ST)
            lines.append(f"BEGIN_POLYGON {ptype} {param} 2")
            lines.append("BEGIN_WINDING")
            for lat, lon in corners:
                lines.append(f"POLYGON_POINT {lon:.9f} {lat:.9f}")
            lines.append("END_WINDING")
            lines.append("END_POLYGON")

    lines.append("")
    return "\n".join(lines)


def _ensure_height(b: dict, gsd: float) -> float:
    """Return or estimate building height in metres."""
    if "height_m" in b:
        return float(b["height_m"])
    w = b.get("width_px", 20)
    h = b.get("height_px", 20)
    return _estimate_height(w, h, gsd)


# ── apt.dat helipad (spawn point) ────────────────────────────────────────────

def _write_apt_dat(path: Path, package_name: str, center_lat: float, center_lon: float):
    """
    Write a minimal apt.dat containing a single helipad airport at the
    coverage center.  X-Plane indexes this so the area appears in the
    Location → search box by the package name.

    apt.dat row codes used:
      1   – Land airport header  (type 1)
      H   – Helipad
      99  – End of file
    """
    # ICAO codes must be ≤4 chars; derive a short slug from the package name.
    slug = "".join(c for c in package_name.upper() if c.isalpha())[:4] or "BLDG"

    # Elevation: 0 ft is fine for a dummy spawn point (X-Plane drapes it to terrain).
    elev_ft = 0

    lines = [
        "I",
        "1100 Generated by xplane_exporter.py",
        "",
        # Row 1: airport
        # 1  <elev_ft>  <has_tower>  <default_sign>  <ICAO>  <name>
        f"16  {elev_ft}  0  0  {slug}  {package_name} (Building Spawn)",
        "",
        # H  <name>  <lat>  <lon>  <heading>  <length_m>  <width_m>
        f"102  H1  {center_lat:.6f}  {center_lon:.6f}  0.00"
        f"  10.00  10.00  1  0  0  0.25  0",
        "",
        "99",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    UI.lvprint(1, f"  Wrote spawn helipad apt.dat  ({slug} @ {center_lat:.5f}, {center_lon:.5f})")


# ── Main export logic ─────────────────────────────────────────────────────────

def export(
    json_path: str,
    out_dir: str,
    package_name: str,
    xplane_root: str | None,
    gsd: float,
    exclude_autogen: bool,
    min_area_m2: float,
    polygon_dir: Path | None,
):
    try:
        from ..build_overlay_dsf import clean_overlays
    except ImportError:
        clean_overlays = False

    UI.lvprint(1, f"Reading {json_path} …")
    with open(json_path) as f:
        data = json.load(f)

    tile_list = data.get("tileBuildingsList", [])
    if not tile_list:
        UI.lvprint(1, "No buildings found in JSON. Nothing to export.")
        return

    # Flatten all buildings into a global list, stamping _gsd onto each
    all_buildings: list[dict] = []
    for tile in tile_list:
        for b in tile.get("buildings", []):
            b = dict(b)           # shallow copy so we don't mutate the original
            b["_gsd"] = gsd
            all_buildings.append(b)

    UI.lvprint(1, f"  {len(all_buildings)} total buildings loaded.")

    # Filter by minimum footprint area
    def _area(b):
        return _footprint_area_m2(b.get("width_px", 0), b.get("height_px", 0), gsd)

    all_buildings = [b for b in all_buildings if _area(b) >= min_area_m2]
    UI.lvprint(1, f"  {len(all_buildings)} buildings pass the minimum area filter ({min_area_m2} m²).")

    buffered_roads_file = polygon_dir / "road_buffer.gpkg" if polygon_dir else None
    tree_polygons_file = polygon_dir / "tree_buffer.gpkg" if polygon_dir else None

    # ═══════════════════════════════════════════════════════════════
    # Vector Slicing and Cleanup Layer (Roads & Trees)
    # ═══════════════════════════════════════════════════════════════
    if clean_overlays and buffered_roads_file and buffered_roads_file.exists() and tree_polygons_file and tree_polygons_file.exists():
        buffered_roads = []
        shapely_trees = []
        UI.lvprint(1, "  Evaluating spatial constraints against roads and trees...")
        initial_count = len(all_buildings)

        UI.lvprint(1, f"  Loading road constraints from {buffered_roads_file.name}...")
        road_gdf = gpd.read_file(buffered_roads_file)
        if not road_gdf.empty:
            buffered_roads = list(road_gdf.geometry)
    
        UI.lvprint(1, f"  Loading tree constraints from {tree_polygons_file.name}...")
        tree_gdf = gpd.read_file(tree_polygons_file)

        print(f"\nDEBUG: Coordinate check")
        print(f"  First tree exterior coords sample:")
        first_tree = tree_gdf.geometry.iloc[0]
        coords = list(first_tree.exterior.coords)[:3]
        for i, (lon, lat) in enumerate(coords):
            print(f"    Point {i}: lon={lon:.4f}, lat={lat:.4f}")
            
        print(f"\n  Bounds check:")
        print(f"  bounds = {tree_gdf.total_bounds}")

        if not tree_gdf.empty:
            shapely_trees = list(tree_gdf.geometry)

        if buffered_roads or shapely_trees:
            UI.lvprint(1, "  Evaluating spatial constraints against available layers...")
            initial_count = len(all_buildings)

            # Build spatial R-Trees for high performance slicing
            road_index = STRtree(buffered_roads) if buffered_roads else None
            tree_index = STRtree(shapely_trees) if shapely_trees else None
            
            cleaned_buildings = []
            for b in all_buildings:
                corners = b.get("corner_points_wgs84", [])
                if not corners or len(corners) < 3:
                    continue
                
                # JSON is [lat, lon] -> Shapely expects standard spatial (lon, lat) projection
                building_poly = ShapelyPolygon([(lon, lat) for lat, lon in corners])
                
                # Check for road collision
                if road_index and road_index.query(building_poly, predicate="intersects").size > 0:
                    continue  # Drops the building if it sits on a street
                    
                # Check for tree/forest canopy collision
                if tree_index and tree_index.query(building_poly, predicate="intersects").size > 0:
                    continue  # Drops the building if it collides with forest land
                    
                cleaned_buildings.append(b)
                
            all_buildings = cleaned_buildings
            UI.lvprint(1, f"  Dropped {initial_count - len(all_buildings)} buildings due to asset collisions.")
        else:
            UI.lvprint(1, "  Spatial cleaning skipped: No road_buffer.gpkg or tree_buffer.gpkg files found.")
            

    if not all_buildings:
        UI.lvprint(1, "No buildings to export after filtering.")
        return

    # Assign a deterministic facade to each building (seeded by id for repeatability)
    for b in all_buildings:
        area   = _area(b)
        bucket = _facade_bucket(area)
        rng    = random.Random(b.get("id", 0))
        b["_facade_path"] = rng.choice(FACADES[bucket])

    # Group buildings by DSF tile
    tiles: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for b in all_buildings:
        corners = b.get("corner_points_wgs84", [])
        if not corners:
            continue
        # Use the centroid's tile
        lat = b.get("center_lat") or corners[0][0]
        lon = b.get("center_lon") or corners[0][1]
        key = _tile_key(lat, lon)
        tiles[key].append(b)

    # Compute coverage center for the apt.dat spawn helipad
    all_lats = [b["center_lat"] for b in all_buildings if "center_lat" in b]
    all_lons = [b["center_lon"] for b in all_buildings if "center_lon" in b]
    center_lat = (min(all_lats) + max(all_lats)) / 2 if all_lats else 0.0
    center_lon = (min(all_lons) + max(all_lons)) / 2 if all_lons else 0.0

    # Build the output package directory tree
    pkg_root = Path(out_dir)
    pkg_root.mkdir(parents=True, exist_ok=True)
    end_root = pkg_root / "Earth nav data"

    # Write the dummy airport so the area shows up in X-Plane's location search
    _write_apt_dat(pkg_root / "apt.dat", package_name, center_lat, center_lon)

    # Collect every unique facade path used across the whole package
    all_facades: set[str] = set()
    for b in all_buildings:
        all_facades.add(b["_facade_path"])

    # Write one DSF text file per tile
    written = 0
    for (floor_lat, floor_lon), bldgs in sorted(tiles.items()):
        folder_name  = _tile_folder_name(floor_lat, floor_lon)
        parent_name  = _parent_folder_name(floor_lat, floor_lon)
        # X-Plane 12 expects: Earth nav data/<10x10>/<1x1>.dsf
        # The file sits DIRECTLY inside the 10x10 parent folder, not in its own subfolder
        tile_dir     = end_root / parent_name
        tile_dir.mkdir(parents=True, exist_ok=True)

        # Build per-tile facade index (only facades actually used in this tile)
        tile_facades = sorted({b["_facade_path"] for b in bldgs})
        facade_index = {path: idx for idx, path in enumerate(tile_facades)}

        dsf_txt = _dsf_text(
            floor_lat, floor_lon,
            bldgs, facade_index,
            exclude_autogen,
        )

        # Name follows XP convention: +37+036.txt (compile to .dsf with DSFTool)
        txt_name = folder_name + ".txt"
        txt_path = tile_dir / txt_name
        txt_path.write_text(dsf_txt, encoding="utf-8")
        UI.lvprint(1, f"  Wrote {txt_path}  ({len(bldgs)} buildings)")
        written += 1

    # ── library.txt ───────────────────────────────────────────────────────────
    # Exports our package's virtual paths so X-Plane can find them in the
    # built-in default scenery library.  For default lib/buildings paths this file is
    # technically not required, but including it makes the package self-
    # documenting and prevents "missing facade" warnings in X-Plane's log.
    lib_lines = [
        "A",
        "800",
        "LIBRARY",
        "",
        "# Facade paths used by this package (all from X-Plane 12 default library)",
    ]
    for path in sorted(all_facades):
        # EXPORT_RECURSIVE re-exports the whole subtree – not needed here;
        # just make the paths explicit for documentation.
        lib_lines.append(f"# {path}")
    lib_lines.append("")

    (pkg_root / "library.txt").write_text("\n".join(lib_lines), encoding="utf-8")

    # ── scenery_pack.ini ──────────────────────────────────────────────────────
    ini_lines = [
        "I",
        "1000 Version",
        "SCENERY",
        "",
        f"SCENERY_PACK Custom Scenery/{package_name}/",
    ]
    (pkg_root / "scenery_pack.ini").write_text("\n".join(ini_lines), encoding="utf-8")

    # ── README ────────────────────────────────────────────────────────────────
    readme = _build_readme(package_name, tiles, written, gsd, exclude_autogen)
    (pkg_root / "README.txt").write_text(readme, encoding="utf-8")

    UI.lvprint(1, f"\nPackage written to: {pkg_root.resolve()}")
    UI.lvprint(1, f"  Tiles: {written}  |  Buildings: {len(all_buildings)}")

    # ── Optional: install directly into X-Plane ───────────────────────────────
    if xplane_root:
        _install(pkg_root, package_name, xplane_root)


def _install(pkg_root: Path, package_name: str, xplane_root: str):
    """Copy the package into X-Plane's Custom Scenery and update the .ini."""
    xp = Path(xplane_root)
    custom = xp / "Custom Scenery"
    if not custom.is_dir():
        UI.lvprint(1, f"  WARNING: Custom Scenery folder not found at {custom}. Skipping install.")
        return

    dest = custom / package_name
    if dest.exists():
        UI.lvprint(1, f"  Removing existing {dest} …")
        shutil.rmtree(dest)
    shutil.copytree(pkg_root, dest)
    UI.lvprint(1, f"  Installed to: {dest}")

    # Update scenery_packs.ini – add as first non-comment line after header
    ini_path = custom / "scenery_packs.ini"
    entry    = f"SCENERY_PACK Custom Scenery/{package_name}/\n"
    if ini_path.exists():
        lines = ini_path.read_text(encoding="utf-8").splitlines(keepends=True)
        # Remove any existing entry for this package to avoid duplicates
        lines = [l for l in lines if package_name not in l]
        # Find insertion point: after the 'SCENERY' keyword line
        insert_at = 0
        for i, line in enumerate(lines):
            if line.strip() == "SCENERY":
                insert_at = i + 1
                break
        lines.insert(insert_at, entry)
        ini_path.write_text("".join(lines), encoding="utf-8")
        UI.lvprint(1, f"  Updated {ini_path}")
    else:
        ini_path.write_text(
            "I\n1000 Version\nSCENERY\n\n" + entry, encoding="utf-8"
        )
        UI.lvprint(1, f"  Created {ini_path}")

    UI.lvprint(1, "\n  ✓ Package installed. Launch X-Plane 12 to see your buildings.")
    UI.lvprint(1, "  NOTE: DSF text files must be compiled to binary with DSFTool first.")
    UI.lvprint(1, "  See README.txt for instructions.")


def _build_readme(name, tiles, n_tiles, gsd, exclude_autogen) -> str:
    total = sum(len(b) for b in tiles.values())
    return f"""X-Plane 12 Custom Scenery Package: {name}
{"=" * (37 + len(name))}

Generated by:  building_detector.py + xplane_exporter.py
Buildings:     {total}
Tiles:         {n_tiles}
GSD used:      {gsd} m/px
Excl. autogen: {exclude_autogen}

INSTALLATION
------------
1. Compile each DSF text file to binary using Laminar's DSFTool
   (download from https://developer.x-plane.com/tools/xptools/):

       DSFTool --text2dsf  +30+030/+37+036.txt  +30+030/+37+036.dsf

   The correct folder structure is:
       Earth nav data/+30+030/+37+036.dsf
                      ^10x10^  ^file^

   Run this command for every .txt file inside Earth nav data/**/.
   A helper shell script is shown below.

   Bash (Linux / macOS):
       find "Earth nav data" -name "*.txt" | while read f; do
           DSFTool --text2dsf "$f" "${{f%.txt}}.dsf"
       done

   PowerShell (Windows):
       Get-ChildItem "Earth nav data" -Filter "*.txt" -Recurse | ForEach-Object {{
           DSFTool --text2dsf $_.FullName ($_.FullName -replace '\.txt$','.dsf')
       }}

2. Delete the .txt files (optional – X-Plane only reads .dsf).

3. Copy this folder into:
       <X-Plane 12>/Custom Scenery/{name}/

4. Open  <X-Plane 12>/Custom Scenery/scenery_packs.ini  in a text editor
   and add this line near the top (high priority):
       SCENERY_PACK Custom Scenery/{name}/

5. Launch X-Plane 12.
   In the Location screen, search for "{name}".
   X-Plane will list it as a helipad placed at the center of your building
   coverage — spawn there and the buildings will be immediately around you.

NOTES
-----
- Facade assets (lib/buildings/facades/…) are part of X-Plane 12's built-in library –
  no third-party libraries are required.
- Building heights are estimated from footprint size. For more accurate
  heights, add a "height_m" field to each building entry in buildings.json
  before exporting.
- The --exclude-autogen flag ({"ON" if exclude_autogen else "OFF"}) controls whether X-Plane's
  procedural autogen buildings are suppressed in the covered tiles.
"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Export buildings.json to an X-Plane 12 custom scenery package."
    )
    p.add_argument("json", help="Path to buildings.json from building_detector.py")
    p.add_argument("--out",  default="XP12_Buildings",
                   help="Output folder for the scenery package (default: XP12_Buildings)")
    p.add_argument("--name", default=None,
                   help="Package/folder name (default: basename of --out)")
    p.add_argument("--xplane", default=None,
                   help="X-Plane 12 root directory – installs the package directly")
    p.add_argument("--gsd", type=float, default=0.5,
                   help="Ground sampling distance in m/px (default: 0.5)")
    p.add_argument("--exclude-autogen", action="store_true",
                   help="Suppress X-Plane autogen buildings in the covered tiles")
    p.add_argument("--min-area", type=float, default=25.0,
                   help="Minimum building footprint in m² (default: 25)")
    args = p.parse_args()

    package_name = args.name or Path(args.out).name

    export(
        json_path       = args.json,
        out_dir         = args.out,
        package_name    = package_name,
        xplane_root     = args.xplane,
        gsd             = args.gsd,
        exclude_autogen = args.exclude_autogen,
        min_area_m2     = args.min_area,
    )


if __name__ == "__main__":
    main()
