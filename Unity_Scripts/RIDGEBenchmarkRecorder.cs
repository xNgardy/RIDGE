using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Profiling;

public class RIDGEBenchmarkRecorder : MonoBehaviour
{
    [Header("Benchmark Window")]
    [SerializeField] private float warmupSeconds = 10f;
    [SerializeField] private float sampleSeconds = 60f;
    [SerializeField] private bool quitAfterWrite = false;

    private readonly List<float> frameTimes = new List<float>();
    private float startTime;
    private bool collecting;
    private bool wroteResult;
    private long peakAllocatedMemory;
    private long peakReservedMemory;
    private long peakGraphicsDriverMemory;

    private void Awake()
    {
        startTime = Time.realtimeSinceStartup;
        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = -1;
    }

    private void Update()
    {
        float elapsed = Time.realtimeSinceStartup - startTime;

        if (!collecting && elapsed >= warmupSeconds)
        {
            collecting = true;
            frameTimes.Clear();
        }

        if (collecting && elapsed < warmupSeconds + sampleSeconds)
        {
            frameTimes.Add(Time.unscaledDeltaTime);
            peakAllocatedMemory = Math.Max(peakAllocatedMemory, Profiler.GetTotalAllocatedMemoryLong());
            peakReservedMemory = Math.Max(peakReservedMemory, Profiler.GetTotalReservedMemoryLong());
            peakGraphicsDriverMemory = Math.Max(peakGraphicsDriverMemory, Profiler.GetAllocatedMemoryForGraphicsDriver());
            return;
        }

        if (!wroteResult && collecting && elapsed >= warmupSeconds + sampleSeconds)
        {
            wroteResult = true;
            WriteResult(elapsed);
            if (quitAfterWrite)
            {
                Application.Quit();
            }
        }
    }

    private void WriteResult(float elapsedAtWrite)
    {
        BenchmarkResult result = BuildResult(elapsedAtWrite);
        string json = JsonUtility.ToJson(result, true);
        string fileName = $"RIDGE_Benchmark_{DateTime.Now:yyyyMMdd_HHmmss}.json";

        WriteJson(Path.Combine(Application.persistentDataPath, fileName), json);

        string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (!string.IsNullOrWhiteSpace(desktop) && Directory.Exists(desktop))
        {
            WriteJson(Path.Combine(desktop, fileName), json);
        }

        Debug.Log($"RIDGE benchmark completed. Average FPS: {result.averageFps:F2}, 1% low FPS: {result.onePercentLowFps:F2}");
        Debug.Log(json);
    }

    private static void WriteJson(string path, string json)
    {
        File.WriteAllText(path, json);
        Debug.Log($"RIDGE benchmark written to {path}");
    }

    private BenchmarkResult BuildResult(float elapsedAtWrite)
    {
        Terrain[] terrains = FindObjectsOfType<Terrain>();
        MeshRenderer[] meshRenderers = FindObjectsOfType<MeshRenderer>();
        MeshFilter[] meshFilters = FindObjectsOfType<MeshFilter>();

        int buildingCount = meshRenderers.Count(r => r.gameObject.name.StartsWith("Building_", StringComparison.OrdinalIgnoreCase)
            || r.gameObject.layer == LayerMask.NameToLayer("Building"));

        int roadRendererCount = meshRenderers.Count(r => r.gameObject.name.IndexOf("Road", StringComparison.OrdinalIgnoreCase) >= 0
            || r.gameObject.layer == LayerMask.NameToLayer("Road"));

        int roadTriangleCount = meshFilters
            .Where(f => f.sharedMesh != null && f.gameObject.name.IndexOf("Road", StringComparison.OrdinalIgnoreCase) >= 0)
            .Sum(f => f.sharedMesh.triangles.Length / 3);

        int totalTreeInstances = terrains.Sum(t => t.terrainData != null ? t.terrainData.treeInstanceCount : 0);
        int totalTriangles = meshFilters.Where(f => f.sharedMesh != null).Sum(f => f.sharedMesh.triangles.Length / 3);

        TerrainSummary terrainSummary = SummarizeTerrains(terrains);

        return new BenchmarkResult
        {
            unityVersion = Application.unityVersion,
            platform = Application.platform.ToString(),
            deviceModel = SystemInfo.deviceModel,
            processorType = SystemInfo.processorType,
            processorCount = SystemInfo.processorCount,
            systemMemoryMb = SystemInfo.systemMemorySize,
            graphicsDeviceName = SystemInfo.graphicsDeviceName,
            graphicsDeviceType = SystemInfo.graphicsDeviceType.ToString(),
            graphicsMemoryMb = SystemInfo.graphicsMemorySize,
            operatingSystem = SystemInfo.operatingSystem,
            benchmarkWarmupSeconds = warmupSeconds,
            benchmarkSampleSeconds = sampleSeconds,
            elapsedSecondsAtWrite = elapsedAtWrite,
            frameCount = frameTimes.Count,
            averageFps = CalculateAverageFps(frameTimes),
            onePercentLowFps = CalculateOnePercentLowFps(frameTimes),
            minFps = frameTimes.Count > 0 ? 1f / frameTimes.Max() : 0f,
            maxFps = frameTimes.Count > 0 ? 1f / frameTimes.Min() : 0f,
            peakAllocatedMemoryMb = BytesToMb(peakAllocatedMemory),
            peakReservedMemoryMb = BytesToMb(peakReservedMemory),
            peakGraphicsDriverMemoryMb = BytesToMb(peakGraphicsDriverMemory),
            terrainTileCount = terrains.Length,
            terrain = terrainSummary,
            buildingCount = buildingCount,
            terrainTreeInstanceCount = totalTreeInstances,
            roadRendererCount = roadRendererCount,
            roadTriangleCount = roadTriangleCount,
            meshRendererCount = meshRenderers.Length,
            meshTriangleCount = totalTriangles
        };
    }

    private static TerrainSummary SummarizeTerrains(Terrain[] terrains)
    {
        if (terrains.Length == 0)
        {
            return new TerrainSummary();
        }

        TerrainData[] data = terrains.Where(t => t.terrainData != null).Select(t => t.terrainData).ToArray();
        return new TerrainSummary
        {
            minWidthMeters = data.Min(d => d.size.x),
            maxWidthMeters = data.Max(d => d.size.x),
            averageWidthMeters = data.Average(d => d.size.x),
            minHeightMeters = data.Min(d => d.size.z),
            maxHeightMeters = data.Max(d => d.size.z),
            averageHeightMeters = data.Average(d => d.size.z),
            minHeightmapResolution = data.Min(d => d.heightmapResolution),
            maxHeightmapResolution = data.Max(d => d.heightmapResolution)
        };
    }

    private static float CalculateAverageFps(List<float> samples)
    {
        if (samples.Count == 0)
        {
            return 0f;
        }

        return samples.Count / samples.Sum();
    }

    private static float CalculateOnePercentLowFps(List<float> samples)
    {
        if (samples.Count == 0)
        {
            return 0f;
        }

        List<float> sorted = samples.OrderByDescending(v => v).ToList();
        int count = Math.Max(1, Mathf.CeilToInt(sorted.Count * 0.01f));
        float slowFrameAverage = sorted.Take(count).Average();
        return 1f / slowFrameAverage;
    }

    private static float BytesToMb(long bytes)
    {
        return bytes / (1024f * 1024f);
    }

    [Serializable]
    private class BenchmarkResult
    {
        public string unityVersion;
        public string platform;
        public string deviceModel;
        public string processorType;
        public int processorCount;
        public int systemMemoryMb;
        public string graphicsDeviceName;
        public string graphicsDeviceType;
        public int graphicsMemoryMb;
        public string operatingSystem;
        public float benchmarkWarmupSeconds;
        public float benchmarkSampleSeconds;
        public float elapsedSecondsAtWrite;
        public int frameCount;
        public float averageFps;
        public float onePercentLowFps;
        public float minFps;
        public float maxFps;
        public float peakAllocatedMemoryMb;
        public float peakReservedMemoryMb;
        public float peakGraphicsDriverMemoryMb;
        public int terrainTileCount;
        public TerrainSummary terrain;
        public int buildingCount;
        public int terrainTreeInstanceCount;
        public int roadRendererCount;
        public int roadTriangleCount;
        public int meshRendererCount;
        public int meshTriangleCount;
    }

    [Serializable]
    private class TerrainSummary
    {
        public float minWidthMeters;
        public float maxWidthMeters;
        public double averageWidthMeters;
        public float minHeightMeters;
        public float maxHeightMeters;
        public double averageHeightMeters;
        public int minHeightmapResolution;
        public int maxHeightmapResolution;
    }
}
