# RIDGE Windows Reproducibility Snapshot

Collected on 2026-07-11.

## Hardware

Source log: `C:\Program Files (x86)\Steam\steamapps\common\X-Plane 12\Log.txt`.

| Item | Value |
|---|---|
| Computer | Windows desktop |
| CPU | AMD Ryzen 5 5600X 6-Core Processor |
| CPU speed | 3.6-4.0 GHz |
| CPU threads reported by X-Plane | 12 |
| RAM | 16 GB class; 17,102,516,224 bytes reported by X-Plane |
| GPU | NVIDIA GeForce RTX 3070 |
| GPU memory reported by Vulkan heap | 7.83 GB device-local heap |
| Graphics API support | Vulkan with async compute |

## Software

| Item | Value |
|---|---|
| Operating system | Windows 10.0 |
| OS build | 19045/2 |
| X-Plane | X-Plane 12.4.3-r2-15ff1e4d |
| X-Plane build | 124311 Intel 64-bit, Vulkan d50c1d1e582274be2ba7099464743271b8900da8 |
| Vulkan device | NVIDIA GeForce RTX 3070 |
| Vulkan version | 1.4.341 |
| Vulkan driver | 610.47.0 |
| Graphics backend | Vulkan |
| Resolution | 2560 x 1440 swapchain and monitor |
| X-Plane install path | `C:\Program Files (x86)\Steam\steamapps\common\X-Plane 12\` |

## Unity Benchmark Run

Source file: `/Users/pelinsukaleli/RIDGE_Final_Project/benchmarks/unity/windows/RIDGE_Benchmark_20260712_134920.json`.

Unity Game view was set to 1920 x 1080. Vertical synchronization was disabled and the target frame rate was uncapped.

| Metric | Value |
|---|---:|
| Unity version / platform | Unity 2022.3.62f1 / WindowsEditor |
| Warm-up + sample window | 10 s + 60 s |
| Frame samples | 7,412 |
| Average FPS | 123.54 |
| 1% low FPS | 76.92 |
| Minimum instantaneous FPS | 28.13 |
| Maximum instantaneous FPS | 142.04 |
| Loaded terrain tiles | 729 |
| Tile width | 142.14-142.22 m |
| Tile height | 178.09 m |
| Heightmap resolution | 513 x 513 samples |
| Building objects | 2,392 |
| Terrain tree instances | 1,253,626 |
| Road renderers | 628 |
| Road mesh triangles | 557,168 |
| Total mesh renderers | 3,020 |
| Total mesh triangles | 585,872 |
| Peak allocated memory | 3,851.42 MB |
| Peak reserved memory | 8,991.68 MB |
| Peak graphics-driver memory | 2,872.00 MB |
| Scene loading time | Not recorded |

## X-Plane Terrain and Overlay Load Validation

The expected RIDGE custom scenery packages were the first four packages discovered by X-Plane.

| Priority | Scenery package |
|---:|---|
| 0 | `Custom Scenery/RIDGE_Roads_37_36/` |
| 1 | `Custom Scenery/RIDGE_Trees_Retry_37_36/` |
| 2 | `Custom Scenery/RIDGE_Buildings_37_36/` |
| 3 | `Custom Scenery/zRIDGE4XP_+37+036/` |

| Item | Value |
|---|---|
| Road DSF | `Custom Scenery/RIDGE_Roads_37_36/Earth nav data/+30+030/+37+036.dsf` |
| Road DSF load-time counter | 1,872 |
| Tree DSF | `Custom Scenery/RIDGE_Trees_Retry_37_36/Earth nav data/+30+030/+37+036.dsf` |
| Tree DSF load-time counter | 1,909 |
| Building DSF | `Custom Scenery/RIDGE_Buildings_37_36/Earth nav data/+30+030/+37+036.dsf` |
| Building DSF load-time counter | 11,866 |
| Terrain DSF | `Custom Scenery/zRIDGE4XP_+37+036/Earth nav data/+30+030/+37+036.dsf` |
| Terrain DSF load-time counter | 4,302,439 |
| Terrain triangles reported by X-Plane | 2,432,375 |
| Terrain skipped triangles area | 11 skipped for -20,470.1 m^2 |
| Validation status | Road, tree, building and terrain packages were discovered by X-Plane and their `+37+036.dsf` files loaded during the Windows flight scenario |

## X-Plane FPS Benchmark

Source files:

- `/Users/pelinsukaleli/RIDGE_Final_Project/benchmarks/xplane/windows/xplane_fps_data_windows_20260711.txt`
- `/Users/pelinsukaleli/RIDGE_Final_Project/benchmarks/xplane/windows/xplane_fps_summary_windows_20260711.csv`
- `/Users/pelinsukaleli/RIDGE_Final_Project/benchmarks/xplane/windows/xplane_fps_summary_windows_full_20260711.csv`

The protocol summary excludes the first 30 s warm-up interval by accumulating X-Plane's `frame,_time` column before summarizing `f-act,_/sec`.

| Metric | Value |
|---|---:|
| X-Plane FPS column | `f-act,_/sec` |
| Warm-up excluded | 30.0 s |
| Skipped warm-up samples | 511 |
| Frame samples | 1,440 |
| Average FPS | 54.67 |
| 1% low FPS | 48.34 |
| Minimum instantaneous FPS | 47.67 |
| Maximum instantaneous FPS | 65.98 |
| Loaded RIDGE terrain triangles | 2,432,375 |

The full raw Data Output file contained 1,951 samples with average FPS 56.10, 1% low FPS 5.45, minimum instantaneous FPS 0.22 and maximum instantaneous FPS 77.32. The very low full-run minimum and 1% low values came from the initial disk-output/startup hitch and are preserved in `xplane_fps_summary_windows_full_20260711.csv`; the post-warm-up protocol summary is used for paper interpretation.
