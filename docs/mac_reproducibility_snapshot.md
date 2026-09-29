# RIDGE macOS Reproducibility Snapshot

Collected on 2026-07-07.

## Hardware

| Item | Value |
|---|---|
| Computer | MacBook Pro |
| Model identifier | Mac14,9 |
| CPU / SoC | Apple M2 Pro |
| CPU cores | 10 total: 6 performance cores and 4 efficiency cores |
| RAM | 16 GB LPDDR5 |
| GPU | Apple M2 Pro integrated GPU |
| GPU cores | 16 |
| Graphics API support | Metal supported |

## Software

| Item | Value |
|---|---|
| Operating system | macOS 26.5.2 |
| OS build | 25F84 |
| Python | Python 3.12.9 |
| Unity editor installed | Unity 2022.3.62f1, build 4af31df58517 |
| Unity editor installed | Unity 6000.3.9f1, build 7a9955a4f2fa |
| X-Plane | X-Plane 12.4.3-r2-15ff1e4d |
| X-Plane build | 124311 Apple Silicon, Metal d50c1d1e582274be2ba7099464743271b8900da8 |
| X-Plane install path | `/Users/pelinsukaleli/Library/Application Support/Steam/steamapps/common/X-Plane 12/` |

## Current Unity Export Static Counts

These counts were read from `Data_Pipeline/outputs/unity_ready/Terrain_Tiles`.

| Item | Value |
|---|---:|
| Terrain tiles | 784 |
| Texture tile size | 512 x 512 px for interior tiles; 196 px edge tiles also present |
| Heightmap size | 513 x 513 samples for interior tiles; 197-sample edge heightmaps also present |
| Building detections in Unity-ready `buildings.json` | 2,429 |
| Tree positions in `tree_positions.json` | 1,334,433 |
| Road JSON files | 784 |
| Road mask files | 784 |
| Unity-ready package size | 1.8 GB |

Use the Unity benchmark recorder for final paper values because it measures the actual generated scene after terrain, buildings, roads and trees are loaded.

## Unity Benchmark Run

Source file: `/Users/pelinsukaleli/Desktop/RIDGE_Benchmark_20260707_203921.json`.

| Metric | Value |
|---|---:|
| Unity version / platform | Unity 2022.3.62f1 / OSXEditor |
| Warm-up + sample window | 10 s + 60 s |
| Frame samples | 16,129 |
| Average FPS | 268.82 |
| 1% low FPS | 130.67 |
| Minimum instantaneous FPS | 19.81 |
| Maximum instantaneous FPS | 303.54 |
| Loaded terrain tiles | 729 |
| Tile width | 142.14-142.22 m |
| Tile height | 178.09 m |
| Heightmap resolution | 513 x 513 samples |
| Building objects | 2,392 |
| Terrain tree instances | 1,007,833 |
| Road renderers | 675 |
| Road mesh triangles | 557,088 |
| Peak allocated memory | 3,536.11 MB |
| Peak reserved memory | 6,039.16 MB |
| Peak graphics-driver memory | 2,747.23 MB |
| Scene loading time | Not recorded |

## Pipeline Output Artifact Summary

| Metric | Value |
|---|---:|
| Unity-ready output package size | 1.8 GB |
| X-Plane tile package size | 7.4 GB |
| Unity building detections in `buildings.json` | 2,429 |
| Unity benchmark building objects | 2,392 |
| X-Plane building detections exported | 2,429 |
| X-Plane DDS terrain textures | 690 |
| X-Plane terrain definition files | 690 |
| X-Plane terrain triangles | 2,432,375 |
| X-Plane road vectors exported from OSM | 693 |
| X-Plane loaded RIDGE scenery packages | 4 |

## X-Plane FPS Benchmark

Source files:

- `/Users/pelinsukaleli/RIDGE_Final_Project/benchmarks/xplane/xplane_fps_data_mac_20260708.txt`
- `/Users/pelinsukaleli/RIDGE_Final_Project/benchmarks/xplane/xplane_fps_summary_mac_20260708.csv`

| Metric | Value |
|---|---:|
| X-Plane FPS column | `f-act,_/sec` |
| Frame samples | 2,046 |
| Average FPS | 61.30 |
| 1% low FPS | 47.31 |
| Minimum instantaneous FPS | 0.39 |
| Maximum instantaneous FPS | 70.04 |
| Loaded RIDGE terrain triangles | 2,432,375 |
| RIDGE building detections exported to X-Plane | 2,429 |
| Scene loading time | Not recorded |

## X-Plane Terrain and Overlay Load Validation

Source log: `/Users/pelinsukaleli/.codex/attachments/c5bb27ab-9edc-4e30-a616-2e7ceed3d7bd/pasted-text.txt`.

| Item | Value |
|---|---|
| X-Plane version | X-Plane 12.4.3-r2-15ff1e4d, build 124311 Apple Silicon |
| Road scenery package | `Custom Scenery/RIDGE_Roads_37_36/` |
| Road scenery priority | 0 |
| Road DSF | `Custom Scenery/RIDGE_Roads_37_36/Earth nav data/+30+030/+37+036.dsf` |
| Road DSF load-time counter | 1282 |
| Tree scenery package | `Custom Scenery/RIDGE_Trees_Retry_37_36/` |
| Tree scenery priority | 1 |
| Tree DSF | `Custom Scenery/RIDGE_Trees_Retry_37_36/Earth nav data/+30+030/+37+036.dsf` |
| Tree DSF load-time counter | 988 |
| Building scenery package | `Custom Scenery/RIDGE_Buildings_37_36/` |
| Building scenery priority | 3 |
| Building DSF | `Custom Scenery/RIDGE_Buildings_37_36/Earth nav data/+30+030/+37+036.dsf` |
| Building DSF load-time counter | 4001 |
| Building detections exported to X-Plane | 2,429 |
| Terrain scenery package | `Custom Scenery/zRIDGE4XP_+37+036/` |
| Terrain scenery priority | 4 |
| Terrain DSF | `Custom Scenery/zRIDGE4XP_+37+036/Earth nav data/+30+030/+37+036.dsf` |
| Terrain DSF load-time counter | 2412706 |
| Terrain triangles reported by X-Plane | 2,432,375 |
| Validation status | Road, tree, building and terrain packages were discovered by X-Plane and their DSF files loaded during the flight scenario |
