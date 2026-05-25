<!--
Quick tip: Right-click this README.md file in VS Code and choose "Open Preview" (or press Ctrl+K V)
for a nicer rendered view.
-->

Usage: python script.py ./my_tiles --model model_path
Install the model from : https://chmura.put.poznan.pl/s/MwhgQNhyQF3fuBs?opendetails=

# X-Plane 12 Building Export & Installation

Detect buildings from aerial imagery and export them as a ready-to-install X-Plane 12 scenery package.

---

## Prerequisites

- Python 3.x
- [DSFTool](https://developer.x-plane.com/tools/xptools/) (for compiling scenery files)
- X-Plane 12

---

## Step 1 — Run Building Detection

```bash
python script.py ./my_tiles --model model_path
```

Download the detection model:
**[Download model](https://chmura.put.poznan.pl/s/MwhgQNhyQF3fuBs?opendetails=)**

This produces a `buildings.json` file used in the next step.

---

## Step 2 — Export to X-Plane 12

Convert `buildings.json` into a scenery package:

```bash
python xplane_exporter.py buildings.json \
  --out XP12_Buildings \
  --name My_City_Buildings \
  --exclude-autogen
```

### Options

| Option | Default | Description |
|---|---|---|
| `--out` | `XP12_Buildings` | Output folder name |
| `--name` | same as `--out` | Package name shown in X-Plane |
| `--gsd` | `0.5` | Metres per pixel (adjust if imagery differs) |
| `--exclude-autogen` | off | Removes default buildings where yours are placed *(recommended)* |
| `--min-area` | `25` | Minimum building footprint in m² |
| `--xplane` | — | Path to X-Plane 12 install for auto-install |

### Auto-install example

```bash
python xplane_exporter.py buildings.json \
  --out XP12_Buildings \
  --name My_City_Buildings \
  --exclude-autogen \
  --xplane "D:\SteamLibrary\steamapps\common\X-Plane 12"
```

---

## Step 3 — Generated Folder Structure

```
XP12_Buildings/
├── Earth nav data/
│   └── +30+030/
│       └── +39+032.txt    ← needs compilation (see Step 4)
├── apt.dat
├── library.txt
├── scenery_pack.ini
└── README.txt
```

---

## Step 4 — Compile DSF Files

X-Plane cannot read `.txt` scenery files directly. They must be compiled to `.dsf` using **DSFTool**.

### Download DSFTool

| Platform | Link |
|---|---|
| Windows | https://files.x-plane.com/public/xptools/xptools_win_24-5.zip |
| macOS | https://files.x-plane.com/public/xptools/xptools_mac_24-5.zip |
| Linux | https://files.x-plane.com/public/xptools/xptools_lin_24-5.zip |

Extract the archive and use `DSFTool.exe` (Windows) or `DSFTool` (macOS/Linux).

### Compile — Windows (PowerShell)

```powershell
Get-ChildItem "XP12_Buildings\Earth nav data" -Filter "*.txt" -Recurse | ForEach-Object {
    .\DSFTool.exe --text2dsf $_.FullName ($_.FullName -replace '\.txt$','.dsf')
}
```

### Compile — macOS / Linux

```bash
find "XP12_Buildings/Earth nav data" -name "*.txt" | while read f; do
    ./DSFTool --text2dsf "$f" "${f%.txt}.dsf"
done
```

> [!NOTE]
> DSFTool is slow — expect **5–15 minutes per file**. It may appear unresponsive during compilation. This is normal.

---

## Step 5 — Install in X-Plane 12

### Option A: Automatic (recommended)

If you passed `--xplane` in Step 2, installation is already done. Skip to [launching](#launch).

### Option B: Manual

1. Copy the output folder into your Custom Scenery directory:

   ```
   XP12_Buildings/  →  X-Plane 12/Custom Scenery/XP12_Buildings/
   ```

2. Open `X-Plane 12/Custom Scenery/scenery_packs.ini` and add your package **near the top**, before `Global Airports`:

   ```
   I
   1000 Version
   SCENERY

   SCENERY_PACK Custom Scenery/XP12_Buildings/
   SCENERY_PACK Custom Scenery/Global Airports/
   ```

---

## Launch

Start X-Plane 12 and search for your package name (e.g. `My_City_Buildings`) in the location menu.

