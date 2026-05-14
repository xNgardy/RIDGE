# RIDGE X-Plane Tree Package

The final X-Plane tree package is:

- `RIDGE_Trees_Strict`: RIDGE mask forests plus `sim/exclude_for` and `sim/exclude_obj`.

Everything X-Plane-related for this tree workflow lives in this folder:

```text
Data_Pipeline/src/Tree_Detection_Module/xplane/
```

This hides lower-priority forest trees and object-based trees across the whole
`+37+036` tile, so only the RIDGE mask trees should remain visible. The tradeoff
is that lower-priority non-tree objects in the same tile can also be hidden.

## Install

Copy this package folder into:

```text
X-Plane 12/Custom Scenery/
```

The final layout must be:

```text
X-Plane 12/Custom Scenery/RIDGE_Trees_Strict/
  Earth nav data/
    +30+030/
      +37+036.dsf
```

## scenery_packs.ini

After launching X-Plane once, open:

```text
X-Plane 12/Custom Scenery/scenery_packs.ini
```

Put the RIDGE package above default/global/orthophoto overlay packages whose
trees you want to suppress.

Example:

```text
SCENERY_PACK Custom Scenery/RIDGE_Trees_Strict/
SCENERY_PACK Custom Scenery/yOrtho4XP_Overlays/
SCENERY_PACK Custom Scenery/Global Airports/
SCENERY_PACK Custom Scenery/X-Plane Landmarks - ...
```

## Rebuild

From the project root:

```bash
Data_Pipeline/venv/bin/python Data_Pipeline/src/Tree_Detection_Module/xplane/export_xplane_forest_masks.py Data_Pipeline/outputs/unity_output Data_Pipeline/src/Tree_Detection_Module/xplane/ridge_forests_strict.txt --exclude-objects
Data_Pipeline/src/Tree_Detection_Module/xplane/xptools_mac_24-5/tools/DSFTool --text2dsf Data_Pipeline/src/Tree_Detection_Module/xplane/ridge_forests_strict.txt Data_Pipeline/src/Tree_Detection_Module/xplane/+37+036_strict.dsf
cp Data_Pipeline/src/Tree_Detection_Module/xplane/+37+036_strict.dsf "Data_Pipeline/src/Tree_Detection_Module/xplane/RIDGE_Trees_Strict/Earth nav data/+30+030/+37+036.dsf"
```
