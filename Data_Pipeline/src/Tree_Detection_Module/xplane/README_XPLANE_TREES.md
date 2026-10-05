# RIDGE X-Plane Forest Export

`export_xplane_forest_masks.py` converts tree-mask PNGs and matching reference
GeoTIFFs into forest polygons in DSF text format. Compilation and installation
are separate steps. Generated `RIDGE_Trees_Strict` packages are local artifacts,
not included in a fresh clone.

Run Python examples from the repository root with an activated environment;
see the [root setup guide](../../../../README.MD#python-setup). Multiline examples
use Bash syntax.

## Setup

```bash
python -m pip install numpy pillow opencv-python
```

Obtain DSFTool for your platform from the official
[X-Plane tools page](https://developer.x-plane.com/tools/xptools/). Use its actual
local path below; no downloaded `xptools_mac_24-5` directory is assumed to exist.

## Inputs

The first argument is a generated Unity intermediate or final package directory:

```text
unity_output/
├── tiles_trees/
│   └── tile_X_Y_mask.png
└── tiles_height_tif/
    └── tile_X_Y.tif
```

Masks must match their reference tiles. References must use longitude/latitude
coordinates and north-up GeoTIFF tiepoint/pixel-scale tags: this exporter reads
the tags directly and does not reproject arbitrary CRS or rotated rasters.
Missing reference tiles are skipped. A tree-position JSON alone is not enough.
Generate inputs with the [Unity pipeline](../../Automated_Mask_Pipeline/README.md)
or supply compatible existing outputs.

## Export DSF text

```bash
python Data_Pipeline/src/Tree_Detection_Module/xplane/export_xplane_forest_masks.py \
  Data_Pipeline/outputs/unity_ready/Terrain_Tiles \
  Data_Pipeline/outputs/xplane_forests \
  --exclude-objects
```

The directory form writes coordinate-named text files, such as
`Data_Pipeline/outputs/xplane_forests/ridge_forests_+37+036.txt`. The exporter groups polygons
into DSF tiles and prints filenames and installation folders.
Defaults include `--forest lib/g8/mixed_tmp_sdry.for`, `--density 255`,
`--min-area-px 40`, and `--min-hole-area-px 40`. Use `--help` for all options.

## Compile and install

For an exported `ridge_forests_+37+036.txt`, create and compile into the package:

```bash
mkdir -p "Data_Pipeline/outputs/RIDGE_Trees_Strict/Earth nav data/+30+030"
/path/to/DSFTool --text2dsf \
  Data_Pipeline/outputs/xplane_forests/ridge_forests_+37+036.txt \
  "Data_Pipeline/outputs/RIDGE_Trees_Strict/Earth nav data/+30+030/+37+036.dsf"
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force "Data_Pipeline/outputs/RIDGE_Trees_Strict/Earth nav data/+30+030"
& "C:\path\to\DSFTool.exe" --text2dsf "Data_Pipeline/outputs/xplane_forests/ridge_forests_+37+036.txt" "Data_Pipeline/outputs/RIDGE_Trees_Strict/Earth nav data/+30+030/+37+036.dsf"
```

Repeat for every exported tile using the names printed by the exporter.
`+30+030/+37+036.dsf` is an example, not fixed coverage. Copy the compiled
`RIDGE_Trees_Strict` folder into `X-Plane 12/Custom Scenery/`.

## Scenery priority and exclusions

Put the entry in `Custom Scenery/scenery_packs.ini` above scenery whose forests
should be replaced:

```text
SCENERY_PACK Custom Scenery/RIDGE_Trees_Strict/
SCENERY_PACK Custom Scenery/yOrtho4XP_Overlays/
```

By default `sim/exclude_for` hides lower-priority forests across each whole DSF
tile. `--exclude-objects` also adds tile-wide `sim/exclude_obj`, hiding
object-based trees **and other lower-priority objects, including buildings**.
Omit it if those objects should remain. Keep RIDGE building packages above the
strict tree package when needed. `--no-exclude-default-forests` omits forest exclusions.

The source directory's `ridge_forests_strict.txt` is a study-area export;
regenerate it from your own masks rather than assuming its coverage matches.
