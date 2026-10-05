# RIDGE

RIDGE converts geospatial imagery and elevation data into terrain, buildings,
roads, and vegetation for Unity and X-Plane 12. It contains a Python data
pipeline, Unity placement scripts, and RIDGE4XP, a modified fork of
[Ortho4XP](https://github.com/oscarpilote/Ortho4XP) by Oscar Pilote.

Source imagery, trained model weights, complete Unity scenes, and generated
scenery packages must be supplied or generated separately.

## Repository layout

| Directory | Contents |
| --- | --- |
| `Data_Pipeline/src/Core_Terrain_Module/` | RGB tiling and DEM-to-Unity terrain conversion |
| `Data_Pipeline/src/Automated_Mask_Pipeline/` | Raw/prepared input pipeline, GUI, mask cleanup, and Unity export |
| `Data_Pipeline/src/Building_Detection_Module/` | RAMP/Roboflow building detection and standalone X-Plane export |
| `Data_Pipeline/src/Road_Detection_Module/` | OSM road extraction, masks, and X-Plane road export |
| `Data_Pipeline/src/Tree_Detection_Module/` | NDVI processing, tree positions, masks, and forest export |
| `Data_Pipeline/src/Evaluation/` | Building and forest segmentation evaluation |
| `Unity_Scripts/` | Terrain, building, road, tree, material, and benchmark scripts |
| `X-Plane/RIDGE4XP/` | Terrain and overlay generation, CLI, and configuration GUI |
| `benchmarks/` | Recorded Unity and X-Plane measurements for macOS and Windows |
| `docs/` | Benchmark protocol and platform reproducibility snapshots |
| `tools/` | Building conversion and X-Plane FPS parsing utilities |

## Python setup

The recorded macOS setup used Python 3.12.9; the pipeline source requires Python
3.10 or newer. Use separate environments when workflows need different package
versions. Run examples from the repository root unless indicated otherwise.
After activation, `python` refers to the environment's interpreter.

macOS / Linux:

```bash
python3 -m venv Data_Pipeline/venv
source Data_Pipeline/venv/bin/activate
python -m pip install --upgrade pip
```

Windows PowerShell:

```powershell
py -m venv Data_Pipeline/venv
.\Data_Pipeline\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Install dependencies for the selected workflow:

- [Unity pipeline setup](Data_Pipeline/src/Automated_Mask_Pipeline/README.md#setup)
- [RIDGE4XP setup](X-Plane/RIDGE4XP/README.md#setup)
- [Forest export setup](Data_Pipeline/src/Tree_Detection_Module/xplane/README_XPLANE_TREES.md#setup)

The requirements files describe different environments. The root
`requirements.txt` covers standalone RAMP/geospatial tools;
`Data_Pipeline/requirements.txt` captures a larger pinned environment;
`Data_Pipeline/src/Building_Detection_Module/buildings-requirements.txt` covers
hosted Roboflow detection. Do not combine these files indiscriminately. The
workflow guides below provide focused package installation commands.
GUI applications require Python with Tkinter.

Multiline command examples use Bash continuation syntax. In PowerShell, put the
command on one line or replace trailing `\` with a backtick.

## Models and credentials

### RAMP XUNet

Download the Buildings Segmentation XUNet ONNX model from the
[Deepness Model Zoo](https://qgis-plugin-deepness.readthedocs.io/en/latest/main/main_model_zoo.html).
RAMP inference is local and does not require a Roboflow key. Use `--model` for
standalone detectors or `--ramp-building-model` for the Unity pipeline.

The Data Pipeline default model path is:

```text
Data_Pipeline/src/Building_Detection_Module/models/building-footprint-extract/3/weights.onnx
```

RIDGE4XP uses a different [model location](X-Plane/RIDGE4XP/README.md#overlays).
RAMP segmentation weights and Roboflow instance-segmentation weights are
separate models; do not substitute one for the other, even if filenames match.
Model weights are excluded from Git and must be obtained separately.

### Roboflow

For standalone `building_detector.py` or `building_detector_local.py`, create
`Data_Pipeline/src/Building_Detection_Module/.env` with:

```dotenv
ROBOFLOW_API_KEY=YOUR_ROBOFLOW_API_KEY
```

These scripts call `load_dotenv()`. The automated pipeline does not load `.env`
itself: use its GUI key field or set `ROBOFLOW_API_KEY` in the environment.
Never commit real keys. The hosted detector needs network access and a key.
The local Roboflow backend is designed to download/cache model
`building-footprint-extract/3` on first use and load the cache on later runs;
your key must be authorized to access that model.

## Unity workflow

Provide georeferenced RGB, DEM, and NDVI inputs (north-up EPSG:4326 RGB), install the
[Unity pipeline dependencies](Data_Pipeline/src/Automated_Mask_Pipeline/README.md#setup),
and download the RAMP model. Start the GUI:

```bash
python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_gui.py
```

Or run the raw-input pipeline:

```bash
python Data_Pipeline/src/Automated_Mask_Pipeline/pipeline_runner.py \
  --input-mode raw \
  --raw-rgb-file /path/to/rgb.tif \
  --dem-file /path/to/dem.tif \
  --ndvi-file /path/to/ndvi.tif \
  --work-dir Data_Pipeline/outputs/automatic_run \
  --building-detector ramp \
  --ramp-building-model /path/to/ramp_XUnet_256.onnx
```

Road generation queries OpenStreetMap, requiring network access unless responses
are cached. Raw mode rebuilds its generated RGB and Unity intermediate folders;
keep source inputs outside those folders. Add `--low-is-tree` only when lower
values in your NDVI encoding represent the tree regions you want to select.

The default final package is `Data_Pipeline/outputs/unity_ready/Terrain_Tiles`.
Copy it into `Assets/Resources/Terrain_Tiles` in your Unity project. Copy
`Unity_Scripts` into `Assets/Scripts`, preserving the `Editor` subdirectory.
See the [Unity guide](Data_Pipeline/src/Automated_Mask_Pipeline/README.md) for
prepared-input mode, output paths, Inspector settings, and placement steps.
Materials, tree prefabs, and a complete Unity scene are not included. Placement
includes editor workflows; not every script is suitable unchanged for a player build.

## X-Plane 12 workflows

### Terrain and integrated overlays

Follow the [RIDGE4XP guide](X-Plane/RIDGE4XP/README.md) for dependencies, local
input organization, CLI/GUI configuration, generation, and installation.

### Standalone buildings

Use the WGS84 detector for X-Plane, rather than the pixel-coordinate PNG detector
used by Unity. Install its dependencies:

```bash
python -m pip install numpy opencv-python onnxruntime rasterio pyproj
```

Detect buildings from a folder of RGB GeoTIFFs with valid CRS metadata:

```bash
python Data_Pipeline/src/Building_Detection_Module/Ramp_Building_Detector_WGS84.py \
  /path/to/rgb_geotiffs \
  --model /path/to/ramp_XUnet_256.onnx \
  --output buildings.json
```

Export the JSON to a scenery package:

```bash
python Data_Pipeline/src/Building_Detection_Module/XPlaneExporter.py \
  buildings.json --out XP12_Buildings --name RIDGE_Buildings --exclude-autogen
```

This creates DSF **text**, not compiled scenery. Obtain DSFTool from the official
[X-Plane tools page](https://developer.x-plane.com/tools/xptools/), then compile
every `.txt` inside the package's `Earth nav data` directory.

macOS / Linux:

```bash
find "XP12_Buildings/Earth nav data" -name '*.txt' | while IFS= read -r f; do
  /path/to/DSFTool --text2dsf "$f" "${f%.txt}.dsf"
done
```

Windows PowerShell:

```powershell
Get-ChildItem "XP12_Buildings/Earth nav data" -Filter "*.txt" -Recurse | ForEach-Object {
  & "C:\path\to\DSFTool.exe" --text2dsf $_.FullName ($_.FullName -replace '\.txt$', '.dsf')
}
```

Copy the compiled package into `X-Plane 12/Custom Scenery/RIDGE_Buildings/` and
add its entry above scenery it should override in `Custom Scenery/scenery_packs.ini`:

```text
SCENERY_PACK Custom Scenery/RIDGE_Buildings/
```

The optional `--xplane` argument copies the package immediately but does not
compile DSF. If you use it, compile the installed copy before launching X-Plane,
or reinstall after compiling the source package. Use `--help` for options such
as `--gsd` and `--min-area`. Compilation time depends on the package and machine.

### Standalone trees

The [forest export guide](Data_Pipeline/src/Tree_Detection_Module/xplane/README_XPLANE_TREES.md)
explains mask inputs, DSF compilation, installation, and forest/object exclusions.

## Evaluation and benchmarks

- Building evaluation: `Data_Pipeline/src/Evaluation/Buildings/evaluate_buildings.py`.
  Requires `--evaluation-boundary`, `--gt`, and `--pred`; use `--help` for options.
- Forest evaluation: `Data_Pipeline/src/Evaluation/Forests/evaluate_forests.py`.
  It currently imports the building helper by module name; include
  `Data_Pipeline/src/Evaluation/Buildings` in `PYTHONPATH` when running it.
- Unity recording: `Unity_Scripts/RIDGEBenchmarkRecorder.cs`.
- X-Plane FPS parsing: `python tools/parse_xplane_fps_data.py /path/to/Data.txt --out /path/to/summary.csv`.
- [Rendering benchmark protocol](docs/rendering_benchmark_protocol.md)
- [macOS reproducibility snapshot](docs/mac_reproducibility_snapshot.md)
- [Windows reproducibility snapshot](docs/windows_reproducibility_snapshot.md)

Platform snapshots and committed measurements document historical runs, not
minimum system requirements or performance guarantees.

## Third-party notices

RIDGE4XP and bundled tool notices are in
[Licence/copyright.txt](X-Plane/RIDGE4XP/Licence/copyright.txt), with the GPL text
in [Licence/gpl.txt](X-Plane/RIDGE4XP/Licence/gpl.txt). Preserve notices in bundled
tools and source files. Models and source datasets have their own usage terms.
