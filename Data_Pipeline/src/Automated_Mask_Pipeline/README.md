# Fully Automatic Unity Pipeline

This folder contains the non-XPlane pipeline for:

1. slicing a raw RGB GeoTIFF into georeferenced tiles
2. generating Unity RGB, height, and metadata files from a raw DEM
3. slicing a raw NDVI GeoTIFF to the same tile grid
4. generating and cleaning building, road, and tree data
5. exporting a Unity-ready `Terrain_Tiles` folder

The pipeline has two input modes:

- `raw`: accepts one RGB GeoTIFF, one DEM GeoTIFF, and one NDVI GeoTIFF
- `prepared`: uses existing `RGB_tifs` and `unity_output` folders

The building detector can be selected at runtime:

- `roboflow`: uses `building_detector_local.py`, which loads the cached Roboflow model or downloads it on first run with a Roboflow API key
- `ramp`: uses `Ramp_Building_Detector.py` with a local RAMP XUNet ONNX model

The pipeline preserves the full Unity tile grid. If a tile has no roads, trees,
or buildings after cleanup, it still receives an empty mask or empty JSON entry
instead of being omitted.

## GUI

From the repository root:

```bash
Data_Pipeline/venv/bin/python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_gui.py
```

### Raw GeoTIFF mode

Select:

- `Raw RGB GeoTIFF`
- `Raw DEM GeoTIFF`
- `Raw NDVI GeoTIFF`
- `Intermediate workspace`
- `Final Terrain_Tiles folder`

The intermediate workspace is rebuilt on every raw-mode run. Do not place source
GeoTIFFs inside it.

### Prepared mode

Select:

- `RGB GeoTIFF tiles folder`: usually `Data_Pipeline/outputs/RGB_tifs`
- `Prepared Unity data folder`: usually `Data_Pipeline/outputs/unity_output`

Prepared mode reads NDVI tiles directly from `unity_output/tiles_ndvi`.

Click `Run Pipeline`.

## Command Line

Raw GeoTIFF mode:

```bash
Data_Pipeline/venv/bin/python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_runner.py \
  --input-mode raw \
  --raw-rgb-file /path/to/rgb.tif \
  --dem-file /path/to/dem.tif \
  --ndvi-file /path/to/ndvi.tif \
  --work-dir Data_Pipeline/outputs/automatic_run \
  --tile-size 512 \
  --building-detector ramp \
  --low-is-tree
```

Prepared mode:

```bash
Data_Pipeline/venv/bin/python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_runner.py \
  --input-mode prepared \
  --rgb-tifs Data_Pipeline/outputs/RGB_tifs \
  --unity-output Data_Pipeline/outputs/unity_output \
  --ndvi-file Data_Pipeline/inputs/your_ndvi_file.tiff \
  --building-detector ramp \
  --low-is-tree
```

If `tiles_ndvi` already exists, skip NDVI tiling:

```bash
Data_Pipeline/venv/bin/python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_runner.py \
  --skip-ndvi-tiling \
  --low-is-tree
```

## Outputs

- roads: `Data_Pipeline/outputs/RGB_tifs/_roads_out_rgb`
- road JSON for `RoadLineBuilder`: `Data_Pipeline/outputs/unity_output/roads`
- trees: `Data_Pipeline/outputs/unity_output/tiles_trees`
- buildings JSON: `Data_Pipeline/outputs/unity_output/buildings.json`
- cleaned buildings JSON: `Data_Pipeline/outputs/unity_output/buildings_cleaned.json`
- building masks: `Data_Pipeline/outputs/unity_output/tiles_buildings`
- Unity-ready package: `Data_Pipeline/outputs/unity_ready/Terrain_Tiles`

The final package uses the Unity project names directly:

```text
Terrain_Tiles/
├── tile_metadata.json
├── buildings.json
├── Roads/
├── road_masks/
├── tiles_buildings/
├── tiles_height/
├── tiles_height_raw/
├── tiles_height_tif/
├── tiles_rgb/
└── tiles_trees/
```

Unity usage:

- `TilePlacer`
  - `tilesFolder`: `Terrain_Tiles`
  - `heightFolder`: `tiles_height`
  - `textureFolder`: `tiles_rgb`
  - `metadataFile`: `tile_metadata`
  - `buildingsMetadataFile`: `buildings`
- `NDVITreePlacer`
  - `tilesFolder`: `Terrain_Tiles`
  - `treesFolder`: `tiles_trees`
- `GlobalRoadManager` with `RoadLineBuilder`
  - the generated files are in `Terrain_Tiles/Roads`
  - files are named `tile_X_Y_roads.json`
- older `MaskToRoad` workflows can use `Terrain_Tiles/road_masks`

No XPlane scripts are called by this pipeline.
