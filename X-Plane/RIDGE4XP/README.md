# RIDGE4XP

RIDGE4XP is a modified fork of [Ortho4XP](https://github.com/oscarpilote/Ortho4XP)
by Oscar Pilote. It builds terrain from local DEM, RGB imagery, and water vectors,
with optional road, tree, and building overlays. It includes a CLI
(`RIDGE4XP.py`) and a Tkinter configuration GUI (`RIDGE4XP-gui.py`).

Terrain, trees, and RAMP building inference use local inputs. Roads query OSM
through OSMnx: a run with roads is not fully offline unless responses are cached.

## Setup

Create and activate an environment using the
[root setup guide](../../README.MD#python-setup). For CPU-based processing:

```bash
python -m pip install numpy pillow pyproj rtree shapely rasterio fiona scikit-fmm opencv-python onnxruntime geopandas osmnx
```

The local `requirements.txt` lists `onnxruntime-gpu` for compatible GPU setups;
the command above uses CPU `onnxruntime` instead. The GUI requires Tkinter.

Native tools under `Utils/` include Triangle4XP and nvcompress; overlays use
DSFTool. Check executable permissions and OS/CPU compatibility. Obtain a current
DSFTool from the [official X-Plane tools page](https://developer.x-plane.com/tools/xptools/)
if the bundled binary is unsuitable. Older bundled tools may need replacement
or rebuilding on your platform.

The CLI relies on relative paths. Run it from this directory:

```bash
cd X-Plane/RIDGE4XP
python -c "from pathlib import Path; Path('data').mkdir(exist_ok=True)"
```

The CLI checks for local `data/` even when `local_data_root` points elsewhere;
keep that directory in place when using an external input directory.

## Input data

For tile `37, 36`, use this structure under `local_data_root`:

```text
/path/to/local_data/
└── 37/
    └── 36/
        ├── dem.tif
        ├── rgb.tif
        ├── water.shp
        ├── water.shx
        ├── water.dbf
        ├── water.prj
        └── ndvi.tif       # for trees; ndvi.tiff is also accepted
```

- DEM: georeferenced elevation in metres with valid NoData metadata.
- RGB: georeferenced 8-bit imagery. Overlays require `rgb.tif`; terrain loading
  also accepts `imagery.tif` or `ortho.tif`.
- Water: polygon features and associated shapefile files. Missing water data
  leaves no local water features for the terrain vector stage.
- NDVI: georeferenced raster overlapping RGB, configured for its band and encoding.

Use EPSG:4326 inputs for the local terrain/vector workflow and matching coverage
for your intended tile. Assigning a CRS label with `-a_srs` alone does not
transform coordinates. With GDAL command-line tools installed separately,
actual reprojection examples are:

```bash
gdalwarp -t_srs EPSG:4326 input_dem.tif dem.tif
gdalwarp -t_srs EPSG:4326 input_rgb.tif rgb.tif
ogr2ogr -t_srs EPSG:4326 water.shp source_water.geojson
```

## Configuration and CLI

Create the global `RIDGE4XP.cfg` in this directory. A terrain-only starting config:

```ini
local_data_root=/absolute/path/to/local_data
mesh_zl=17
curvature_tol=2
default_zl=17
mask_zl=14
generated_overlays=[]
clean_overlays=False
generate_terrain=True
cleaning_level=1
verbosity=1
```

Use forward slashes in Windows paths, for example `C:/RIDGE/data`. Choose
settings for your input coverage and desired quality. `EXAMPLE_CONFIG.cfg`
contains additional terrain settings.

```bash
python RIDGE4XP.py 37 36
```

Global configuration loads at startup. Terrain settings may also be read from
`Tiles/zRIDGE4XP_+37+036/RIDGE4XP_+37+036.cfg`, falling back to
`Tiles/zRIDGE4XP_+37+036/RIDGE4XP.cfg`. Without a tile config the CLI warns and
uses global/default values. Put overlay settings in the global config because
the generators read their module settings.

## GUI

From this directory:

```bash
python RIDGE4XP-gui.py
```

Enter integer latitude/longitude, add `local_data_root` and the desired settings,
then click `Generate & Run`. The GUI writes global `RIDGE4XP.cfg`, starts the CLI,
and displays its log. It replaces the config with the selected GUI values;
add all settings needed for your run. Advanced configuration exposes more
variables. `Stop` requests termination of the running CLI process.

## Overlays

`generated_overlays` defaults to `['Roads', 'Trees', 'Buildings']`. The terrain-only
example overrides it to `[]`, so it needs neither NDVI nor model weights.
To enable overlays, update the global config, for example:

```ini
generated_overlays=['Roads', 'Trees', 'Buildings']
separate_overlays=False
clean_overlays=False
model_name=ramp_XUnet_256.onnx
confidence=0.6
threshold=0.55
min_ndvi=0.4
low_is_tree=False
```

| Overlay | Required inputs |
| --- | --- |
| Roads | Georeferenced `rgb.tif` and OSM network access/cache |
| Trees | `rgb.tif` and `ndvi.tif` or `ndvi.tiff` |
| Buildings | `rgb.tif` and a local RAMP XUNet ONNX model |

Download the Buildings Segmentation model from the
[Deepness Model Zoo](https://qgis-plugin-deepness.readthedocs.io/en/latest/main/main_model_zoo.html),
create `Overlay/building/models/`, and place it there as `ramp_XUnet_256.onnx`,
or set `model_name` to its actual filename. This differs from the Data Pipeline
model location. RIDGE4XP does not use a Roboflow API key.

Choose `low_is_tree` for your NDVI encoding. `clean_overlays=True` requests all
three types and performs overlap cleanup, regardless of the selected subset.

The current separate-overlay compiler contains a `Path + str` construction
error. Keep `separate_overlays=False` to use combined compilation. Individual
overlay text directories are still generated and can be compiled manually
with DSFTool when separate installed packages are needed.

## Output and installation

For tile `37, 36`, output is organized as:

```text
Tiles/zRIDGE4XP_+37+036/
├── Earth nav data/
│   └── +30+030/
│       └── +37+036.dsf
├── terrain/
├── textures/
├── Roads/          # when generated
├── Trees/          # when generated
├── Buildings/      # when generated
└── Overlays/       # combined overlay output
```

Terrain generation writes binary DSF. Overlays first write DSF text, then the
integrated compiler calls DSFTool. Check the expected `.dsf` files before
installation. The complete terrain package is not installed automatically.

Copy the terrain's `Earth nav data`, `terrain`, and `textures` directories into
`X-Plane 12/Custom Scenery/zRIDGE4XP_+37+036/`. Copy the contents of `Overlays/`
into a separate package such as `Custom Scenery/RIDGE_Overlays_37_36/`.
Place overlays above base terrain in `Custom Scenery/scenery_packs.ini`:

```text
SCENERY_PACK Custom Scenery/RIDGE_Overlays_37_36/
SCENERY_PACK Custom Scenery/Global Airports/
SCENERY_PACK Custom Scenery/zRIDGE4XP_+37+036/
```

Keep unrelated scenery entries and choose their priority for your setup.
The optional building `xplane_root` setting copies a package before final
compilation; check the installed DSF or copy the compiled package again.

## Troubleshooting

- Missing `data/`: create it here, even when using an external data root.
- `local_data_root not configured`: set an existing absolute input root.
- Missing model: check `Overlay/building/models/<model_name>`; weights are not in Git.
- Missing rasters: check the `lat/lon` directories and exact input names.
- Road download errors: check network access and OSM service availability.
- Native tool failure: check permissions, architecture, and platform tool paths.
- Overlay text but no visible scenery: check DSF compilation, package structure,
  and scenery priority.

## Credits and notices

See [Licence/copyright.txt](Licence/copyright.txt) for RIDGE4XP, Ortho4XP, and
bundled tool notices, and [Licence/gpl.txt](Licence/gpl.txt) for the GPL text.
Inherited `Documents/` files describe Ortho4XP concepts; this README documents
the current RIDGE4XP entry points and local-data workflow.
