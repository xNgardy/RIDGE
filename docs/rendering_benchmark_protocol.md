# RIDGE Rendering Benchmark Protocol

Use this protocol before finalizing Section 5.4.

## Unity benchmark

1. Copy or keep `Unity_Scripts/RIDGEBenchmarkRecorder.cs` in the Unity project's `Assets/Scripts` folder.
2. Open the final RIDGE Unity scene with the same Unity version that will be reported in the paper.
3. Generate or load the final terrain tiles, buildings, roads and vegetation.
4. Add `RIDGEBenchmarkRecorder` to an always-active scene object, such as the main camera or an empty object named `RIDGE_Benchmark`.
5. In the Inspector, use `Warmup Seconds = 10` and `Sample Seconds = 60`.
6. Maximize the Game view, set the target resolution, disable VSync, keep the target frame rate uncapped and keep the camera path/view fixed for all benchmark runs.
7. Press Play and do not interact with the scene until the benchmark finishes.
8. Collect the JSON file from the Desktop or from Unity's `Application.persistentDataPath`.
9. Run at least three identical trials. Report the mean average FPS, mean 1% low FPS, peak memory, loading time, tile size and object counts.

## What the recorder outputs

The JSON includes:

- Unity version, platform, CPU, RAM, GPU and operating system.
- Average FPS over the measurement window.
- 1% low FPS, calculated from the slowest 1% frame times.
- Terrain tile count and terrain tile dimensions in metres.
- Heightmap resolution range.
- Building count, terrain tree instance count, road renderer count and road triangle count.
- Mesh renderer count and total mesh triangle count.
- Peak allocated memory, reserved memory and graphics-driver memory reported by Unity.

## X-Plane benchmark

X-Plane's own `Log.txt` already records simulator version, hardware, loaded scenery and DSF load-time lines. For the paper, use the simulator's built-in frame-rate output or Data Output screen during a fixed camera/flight scenario, then record:

- X-Plane version and build.
- Scenario location and camera/aircraft state.
- Average FPS across a fixed post-warm-up interval.
- 1% low FPS from the same post-warm-up interval.
- Loaded RIDGE scenery package name.
- Relevant `Log.txt` DSF load-time lines for the RIDGE package.
- Memory use from Activity Monitor during the same 60 s interval.

Keep the Unity and X-Plane benchmark conditions separate in Section 5.4 unless both engines use exactly the same loaded area and object density.
