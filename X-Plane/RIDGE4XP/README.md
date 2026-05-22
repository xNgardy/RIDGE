# RIDGE4XP
RIDGE4XP is a modified fork of Ortho4XP, made by Oscar Pilote, that works with RIDGE. This fork works **exclusively with local data**. No internet connectivity required. No GUI.

Ortho4XP: https://github.com/oscarpilote/Ortho4XP

## Quick Start

### 1. Prepare your local data

Create a directory structure with your data:

```
/my/data/
├── 40/
│   ├── -74/
│   │   ├── dem.tif              (elevation, GeoTIFF)
│   │   ├── rgb.tif              (imagery, GeoTIFF)
│   │   ├── water.shp            (water/coastlines, Shapefile + .shx + .dbf)
│   │   ├── water.shx
│   │   └── water.dbf
│   └── -73/
│       ├── dem.tif
│       ├── rgb.tif
│       ├── water.shp
│       ├── water.shx
│       └── water.dbf
```

### 2. Create a tile configuration file

Create `Tiles/zRIDGE4XP_40-74/RIDGE4XP.cfg`:

```ini
# REQUIRED: Point to your local data
local_data_root=/my/data

# Optional: Customize mesh generation
mesh_zl=19
curvature_tol=2
```

See `EXAMPLE_CONFIG.cfg` for all available options.

### 3. Run RIDGE4XP

```bash
python RIDGE4XP.py 40 -74
```

Output will be in `Tiles/zRIDGE4XP_40-74/` with DSF and texture files ready for X-Plane.

## Data Format Requirements

### Digital Elevation Model (dem.tif)
- **Format:** GeoTIFF with WGS84 coordinates (EPSG:4326)
- **Bands:** Single band (elevation in meters)
- **Coverage:** Should cover the full 1°×1° tile
- **Resolution:** Any resolution is fine, will be automatically processed
- **Example Creation:**
  ```bash
  gdal_translate -of GTiff -a_srs EPSG:4326 input.tif dem.tif
  ```

### RGB Imagery (rgb.tif)
- **Format:** GeoTIFF with WGS84 coordinates (EPSG:4326)
- **Bands:** 3 (RGB) or 4 (RGBA)
- **Coverage:** Full 1°×1° tile
- **Resolution:** 4096×4096 recommended for zoom level 16
- **Example Creation:**
  ```bash
  gdal_translate -of GTiff -a_srs EPSG:4326 input.tif rgb.tif
  ```

### Water/Coastline (water.shp)
- **Format:** ESRI Shapefile
- **Geometry Type:** Polygons (water bodies)
- **Coverage:** Full 1°×1° tile
- **Includes:** Coastlines, lakes, rivers - any water features
- **Supporting Files:** Must include .shx and .dbf files
- **Example Creation:** Use QGIS or ogr2ogr to convert from OSM or use other sources
- **Example Source:** https://www.hydrosheds.org/products/hydrobasins#downloads
  ```bash
  ogr2ogr -f "ESRI Shapefile" water.shp source.geojson -nln water
  ```

## Configuration Options

### Required
- `local_data_root` - Root directory for your local data

### Mesh Generation
- `mesh_zl` (default: 19) - Zoom level for mesh preprocessing (16-20)
- `curvature_tol` (default: 2) - Terrain curvature tolerance for mesh refinement
- `min_angle` (default: 10) - Minimum triangle angle in degrees
- `limit_tris` (default: 3) - Max triangles in millions (0 for 5M limit)

### Masking
- `mask_zl` (default: 14) - Zoom level for water masks (14-16)
- `masking_mode` (default: sand) - Masking algorithm: sand, rocks, or 3steps
- `masks_width` (default: 100) - Width of mask in meters
- `ratio_water` (default: 0.25) - Water transparency (0-1)
- `use_masks_for_inland` (default: False) - Applies water masks to inland water bodies

### Textures & Overlays
- `default_zl` (default: 17) - Default zoom level for generated textures
- `custom_overlay_src` - Path to X-Plane Global Scenery directory for extracting custom overlays

### Processing
- `fill_nodata` (default: True) - Fill missing elevation values
- `normal_map_strength` (default: 1.0) - Strength of the generated normal maps
- `cleaning_level` (default: 1) - Temporary file cleanup level (0-3)
- `verbosity` (default: 1) - Output verbosity (0-3)

## Output

After running, you'll find in `Tiles/zRIDGE4XP_lat_lon/`:
- `Earth nav data/lat_lon/lat_lon.dsf` - X-Plane scenery file
- `terrain/*.ter` - Terrain definition files
- `textures/` - Texture files

Copy the `Earth nav data/`, `terrain/` and `textures/` directories into a custom scenery directory and place that directory inside X-Plane's Custom Scenery folder.

## Troubleshooting

### "local_data_root not configured"
→ Add `local_data_root=/path/to/data` to your .cfg file

### "ERROR loading local DEM"
→ Verify dem.tif exists at: `local_data_root/lat/lon/dem.tif`
→ Check the GeoTIFF is valid with: `gdalinfo dem.tif`

### "White tiles generated"
→ Imagery file not found, check rgb.tif location and format

### "No water features found"
→ water.shp missing or has no geometries; process continues without water

## Architecture

```
RIDGE4XP.py (CLI-only, no GUI)
    ↓
Load config → set UI.local_data_root
    ↓
build_poly_file() → load water.shp
    ↓
build_mesh() → load dem.tif → Triangle4XP
    ↓
build_masks() → water masks
    ↓
build_tile() → load rgb.tif → create DSF
```
