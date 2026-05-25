# Automatic Mask Pipeline

This folder contains the non-XPlane automation pipeline for generating and cleaning:

1. road masks
2. tree masks
3. building masks and building JSON

The collision order is:

1. roads are generated first
2. tree masks are generated, then road pixels are removed from tree masks and `tree_positions.json`
3. buildings are detected, then building masks are generated with road and tree pixels removed
4. the cleaned Unity building JSON removes buildings that collide with roads or trees, because Unity places buildings from rectangles
5. a Unity-ready `Terrain_Tiles` package is exported

The pipeline preserves the full Unity tile grid. If a tile has no roads, trees,
or buildings after cleanup, it still receives an empty mask or empty JSON entry
instead of being omitted.

## GUI

From the repository root:

```bash
Data_Pipeline/venv/bin/python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_gui.py
```

Fill in:

- `RGB GeoTIFF folder`: usually `Data_Pipeline/outputs/RGB_tifs`
- `Unity output folder`: usually `Data_Pipeline/outputs/unity_output`
- `NDVI TIFF`: source NDVI file if `tiles_ndvi` has not already been created
- `Building image tiles`: usually `Data_Pipeline/outputs/unity_output/tiles_rgb`
- `Roboflow API key`: only needed if the building model is not already cached locally

Click `Run Pipeline`.

## Command Line

```bash
Data_Pipeline/venv/bin/python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_runner.py \
  --rgb-tifs Data_Pipeline/outputs/RGB_tifs \
  --unity-output Data_Pipeline/outputs/unity_output \
  --ndvi-file Data_Pipeline/inputs/your_ndvi_file.tiff \
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

Copy the Unity-ready `Terrain_Tiles` folder into:

```text
Unity_Engine/Assets/Resources/Terrain_Tiles
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
  - the generated files are in `Terrain_Tiles/roads`
  - files are named `tile_X_Y_roads.json`
- older `MaskToRoad` workflows can use `Terrain_Tiles/road_masks`

No XPlane scripts are called by this pipeline.
