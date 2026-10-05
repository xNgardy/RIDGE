# Automated Unity Pipeline

This pipeline slices RGB/DEM/NDVI GeoTIFFs, extracts buildings, roads, and trees,
cleans overlapping masks, and exports a Unity-ready `Terrain_Tiles` directory.
It does not call the X-Plane scripts.

Run commands from the repository root with an activated environment; see the
[root setup guide](../../../README.MD#python-setup). Multiline examples use Bash syntax.

## Setup

Install the RAMP, road, tree, and terrain dependencies:

```bash
python -m pip install numpy pillow rasterio pyproj opencv-python shapely geopandas osmnx onnxruntime
```

For optional local Roboflow inference, also install:

```bash
python -m pip install inference python-dotenv
```

The GUI requires Tkinter. Road mask and road JSON generation query OSM and need
internet access unless relevant responses are already cached.

### Building backends

| Backend | Requirements |
| --- | --- |
| `ramp` | Local Buildings Segmentation XUNet ONNX weights from the [Deepness Model Zoo](https://qgis-plugin-deepness.readthedocs.io/en/latest/main/main_model_zoo.html); no API key |
| `roboflow` | Model `building-footprint-extract/3`; first download needs network access and an authorized Roboflow key; later runs are designed to use the local cache |

The CLI defaults to `roboflow`; the GUI defaults to `ramp`. For RAMP, select the
model in the GUI or pass `--ramp-building-model`. Its default path is
`Data_Pipeline/src/Building_Detection_Module/models/building-footprint-extract/3/weights.onnx`.
Weights are not committed. Do not substitute Roboflow instance-segmentation
weights for the RAMP segmentation model.

The automated pipeline does not load `.env` files. For Roboflow, use the GUI key
field or set the variable before launching:

```bash
export ROBOFLOW_API_KEY='YOUR_ROBOFLOW_API_KEY'
```

Windows PowerShell:

```powershell
$env:ROBOFLOW_API_KEY = 'YOUR_ROBOFLOW_API_KEY'
```

Never commit real keys. `--building-confidence` is 0–100 for Roboflow; RAMP uses
that value divided by 100 as its fill-ratio threshold.

## Input modes

### Raw GeoTIFF mode

Provide RGB, DEM, and NDVI GeoTIFFs covering your study area, with valid CRS
metadata and elevations in metres. Use north-up EPSG:4326 RGB imagery: the terrain
tiler calculates ground dimensions from longitude/latitude bounds. DEM and NDVI
are reprojected to the RGB tile grid during preparation.

Raw mode rebuilds `RGB_tifs` and `unity_output` inside `--work-dir` on every run.
Keep source files outside these generated directories. Skip options are rejected
in raw mode. Tile size must be a positive power of two, such as 256, 512, or 1024.

### Prepared mode

Provide existing RGB GeoTIFF tiles and a matching Unity intermediate directory:

```text
RGB_tifs/
  tile_*.tif
unity_output/
  tile_metadata.json
  tiles_rgb/
  tiles_height/
  tiles_height_tif/
```

Use `--ndvi-file` to tile an NDVI source, or reuse `unity_output/tiles_ndvi` with
`--skip-ndvi-tiling`. Skip options can reuse existing masks or JSON; use `--help`
for the corresponding input paths.

## GUI

```bash
python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_gui.py
```

Choose raw/prepared mode, fill in inputs and outputs, select the building
backend, and supply its model or key. Click `Run Pipeline` to launch processing
with the selected Python interpreter and view its output.

The GUI initially enables `low_is_tree`. Check this against your NDVI encoding:
standard NDVI generally has higher values for vegetation. Enable that option
only when lower values select your desired tree regions.

## Command line

Raw inputs with RAMP:

```bash
python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_runner.py \
  --input-mode raw \
  --raw-rgb-file /path/to/rgb.tif \
  --dem-file /path/to/dem.tif \
  --ndvi-file /path/to/ndvi.tif \
  --work-dir Data_Pipeline/outputs/automatic_run \
  --tile-size 512 \
  --building-detector ramp \
  --ramp-building-model /path/to/ramp_XUnet_256.onnx
```

Prepared inputs with a new NDVI source:

```bash
python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_runner.py \
  --input-mode prepared \
  --rgb-tifs Data_Pipeline/outputs/RGB_tifs \
  --unity-output Data_Pipeline/outputs/unity_output \
  --ndvi-file /path/to/ndvi.tif \
  --building-detector ramp \
  --ramp-building-model /path/to/ramp_XUnet_256.onnx
```

To reuse existing NDVI tiles, replace `--ndvi-file /path/to/ndvi.tif` with
`--skip-ndvi-tiling`. For Roboflow, set the environment variable and replace the
two RAMP options with `--building-detector roboflow`. Tune trees using
`--tree-threshold`, `--min-ndvi`, `--ndvi-band`, and, where appropriate, `--low-is-tree`.

## Outputs

Paths follow the configured intermediate directories. Prepared-mode defaults:

| Artifact | Default path |
| --- | --- |
| Road masks | `Data_Pipeline/outputs/RGB_tifs/_roads_out_rgb` |
| Road JSON | `Data_Pipeline/outputs/unity_output/roads` |
| NDVI tiles | `Data_Pipeline/outputs/unity_output/tiles_ndvi` |
| Tree masks and positions | `Data_Pipeline/outputs/unity_output/tiles_trees` |
| Buildings / cleaned buildings | `Data_Pipeline/outputs/unity_output/buildings.json` / `buildings_cleaned.json` |
| Building masks | `Data_Pipeline/outputs/unity_output/tiles_buildings` |
| Final package | `Data_Pipeline/outputs/unity_ready/Terrain_Tiles` |

Raw-mode intermediates instead live under `--work-dir`. Final output has the
same default in either mode; change it with `--unity-package-dir`. Export
replaces matching destination subdirectories.

The pipeline preserves the Unity grid, including empty masks and JSON entries
for tiles with no detected features. The final package contains:

```text
Terrain_Tiles/
├── tile_metadata.json
├── buildings.json
├── Roads/
├── road_masks/
├── tiles_buildings/
├── tiles_height/
├── tiles_height_raw/     # copied when present
├── tiles_height_tif/     # copied when present
├── tiles_rgb/
└── tiles_trees/
```

## Unity import and placement

1. Copy the package to `Assets/Resources/Terrain_Tiles`. Copy `Unity_Scripts` to
   `Assets/Scripts`, preserving its `Editor` folder.
2. Add `TilePlacer` to a scene object. Set `tilesFolder = Terrain_Tiles`,
   `heightFolder = tiles_height`, `textureFolder = tiles_rgb`,
   `metadataFile = tile_metadata`, and `buildingsMetadataFile = buildings`.
   Set `xTileCount` and `yTileCount` to your grid dimensions. Resources names
   omit extensions. Use the controls in order: `Read Json`,
   `Change Setup`, `Read Building Json`, `Place Buildings`. Add a Unity layer
   named `Building` for building placement.
3. Add `NDVITreePlacer`, assign the `TilePlacer` and tree prefabs, and set
   `tilesFolder = Terrain_Tiles`, `treesFolder = tiles_trees`. Click `Place Trees`.
4. Add `GlobalRoadManager`, assign the terrain root and materials, and use its
   `Build Roads` control. JSON is in `Terrain_Tiles/Roads`, with files named
   `tile_X_Y_roads.json`.

Placement includes Unity Editor APIs; generate the scene in the editor before
using it in a build. Scripts and data do not supply materials, tree prefabs, or
a ready-made Unity scene.
