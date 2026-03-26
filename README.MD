# RIDGE Project

End-to-end workflow for generating geospatial terrain tiles in Python and importing them into Unity.

This repository includes:
- **Data_Pipeline**: terrain tile generation, NDVI processing, tree mask generation, and building detection outputs.
- **Unity_Engine**: Unity project and editor tools for terrain placement, building placement, and NDVI-based tree placement.

---

## Repository Structure

```text
RIDGE-Project/
├── Data_Pipeline/
│   ├── requirements.txt
│   ├── inputs/
│   ├── outputs/
│   │   └── unity_output/
│   └── src/
│       ├── Core_Terrain_Module/
│       ├── Tree_Detection_Module/
│       └── Building_Detection_Module/
├── Unity_Engine/
│   ├── Assets/
│   ├── Packages/
│   └── ProjectSettings/
├── README_Python.md
└── README_Unity.md
```

---

## Prerequisites

- Python 3.8+
- Unity **2022.3.40f1** (recommended; nearby 2022 LTS versions should also work)

---

## Python Setup

From project root:

```powershell
cd Data_Pipeline
python -m venv venv
.\venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

## Data Pipeline Workflow (Python)

### 1) Generate Terrain Tiles (RGB + Height)

Run from `Data_Pipeline/src/Core_Terrain_Module`:

```powershell
cd Data_Pipeline\src\Core_Terrain_Module
python tiler.py "C:\path\to\rgb_tiles" "C:\path\to\dem.tif"
```

Expected output under `Data_Pipeline/outputs/unity_output`:
- `tile_metadata.json`
- `tiles_rgb/`
- `tiles_height/`
- `tiles_height_tif/`

### 2) (Optional) Process NDVI Tiles

Run from `Data_Pipeline/src/Tree_Detection_Module`:

```powershell
cd ..\Tree_Detection_Module
python crop_and_tile_ndvi.py "C:\path\to\ndvi.tiff" "C:\path\to\Data_Pipeline\outputs\unity_output"
```

Creates `tiles_ndvi/` (GeoTIFF + preview PNGs + `ndvi_stats.json`).

### 3) (Optional) Generate Tree Masks / Positions

```powershell
python generate_tree_masks.py "C:\path\to\Data_Pipeline\outputs\unity_output" --threshold 0.4 --low-is-tree --density 0.05
```

Creates `tiles_trees/` including:
- `tile_X_Y_mask.png`
- `tile_X_Y_density.png`
- `tree_data.json`
- `tree_positions.json`

### 4) (Optional) Building Detection

Run from `Data_Pipeline/src/Building_Detection_Module`:

```powershell
cd ..\Building_Detection_Module
python building_detector.py "C:\path\to\Data_Pipeline\outputs\unity_output\tiles_rgb"
```

Produces building metadata (for Unity building placement).

---

## Unity Import Workflow

### 1) Open Unity Project

Open `Unity_Engine` with Unity Hub.

### 2) Copy Python Outputs into Resources

Copy these into:

`Unity_Engine/Assets/Resources/Terrain_Tiles/`

Required:
- `tiles_height/`
- `tiles_rgb/`
- `tile_metadata.json`

Optional:
- `tiles_trees/` (for NDVI tree placement)
- `buildings.json` (for building placement)

### 3) Terrain Generation

1. Add `TilePlacer` component.
2. Set tile counts / folder names.
3. Click **Read Json**.
4. Click **Change Setup**.

### 4) Building Placement (Optional)

1. Ensure `buildings.json` exists under `Resources/Terrain_Tiles`.
2. In `TilePlacer`, set Buildings Metadata File = `buildings`.
3. Click **Read Building Json** then **Place Buildings**.

### 5) NDVI Tree Placement (Optional)

1. Add `NDVITreePlacer` component.
2. Assign `TilePlacer` reference and tree prefabs.
3. Use `tree_positions.json` or mask textures.
4. Click **Place Trees**.

For terrain trees, prefer compatible shaders such as **Nature/SpeedTree Billboard** on tree materials.

---

## Common Commands (Quick Reference)

```powershell
# Activate environment
cd Data_Pipeline
.\venv\Scripts\activate

# Terrain tiles
cd src\Core_Terrain_Module
python tiler.py "<rgb_tiles_folder>" "<dem_file>"

# NDVI tiles + tree data
cd ..\Tree_Detection_Module
python crop_and_tile_ndvi.py "<ndvi_file>" "..\..\outputs\unity_output"
python generate_tree_masks.py "..\..\outputs\unity_output" --threshold 0.4 --low-is-tree --density 0.05
```

---

## Troubleshooting

- **NDVI trees appear in wrong places**: use `--low-is-tree` for Copernicus NDVI exports.
- **Trees too dense/sparse**: adjust `--density` and `--threshold`.
- **Trees not visible in Unity**: verify tree prefab shader and terrain-tree compatibility.
- **Tile alignment issues**: ensure input rasters use matching CRS or reprojection is correctly applied.

---

## Note

This is the single source of documentation for this repository.
