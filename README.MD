<!--
Quick tip: Right-click this README.md file in VS Code and choose "Open Preview" (or press Ctrl+K V)
for a nicer rendered view.
-->

Usage: python script.py ./my_tiles --model model_path
Install the model from : https://chmura.put.poznan.pl/s/MwhgQNhyQF3fuBs?opendetails=

# Heightmap and Texture Tile Generator

Toolset to:
- combine 16-bit satellite bands into an RGB GeoTIFF,
- align/reproject texture + DEM to a common grid,
- slice color tiles (2^n) and height tiles (2^n + 1) for Unity,
- export 8-bit PNG textures and 16-bit RAW heightmaps with metadata.

Prerequisites
- Python 3.8+
- The requirements.txt file

Quick setup (Windows PowerShell)
1. Create & activate a virtual environment
    ```powershell
    python -m venv venv
    .\venv\Scripts\activate
    ```
    To quickly write the activation command you can just type:
    - 'v' + TAB + '\\'
    - 's' + TAB + '\\'
    - 'a' + TAB

2. Install requirements
    ```powershell
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    ```

# Files and purpose
- tile_dem_for_unity.py — Slices the large DEM file into appropriate pieces for the RGB images.

# Basic workflow
0. Make sure you have activated your virtual environment. If not, run this command:
    ```powershell
    .\venv\Scripts\activate
    ```
1. Create RGB from bands:
    ```powershell
    python tile_dem_for_unity.py "C:\path\to\rgb_tiles" "C:\path\to\AP_12483_FBD_F0730_RT1.dem.tif"
    # produces unity_output folder
    ```
