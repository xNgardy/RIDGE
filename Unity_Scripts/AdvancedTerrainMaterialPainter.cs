using System;
using System.Collections.Generic;
using UnityEngine;

[ExecuteInEditMode]
public class AdvancedTerrainMaterialPainter : MonoBehaviour
{
    [Serializable]
    public class SurfaceRule
    {
        public string ruleName = "New Surface";
        public TerrainLayer terrainLayer;

        [Header("HSV Detection")]
        [Range(0f, 1f)] public float minHue = 0f;
        [Range(0f, 1f)] public float maxHue = 1f;
        [Range(0f, 1f)] public float minSaturation = 0f;
        [Range(0f, 1f)] public float maxSaturation = 1f;
        [Range(0f, 1f)] public float minValue = 0f;
        [Range(0f, 1f)] public float maxValue = 1f;

        [Header("Blend")]
        [Range(0f, 2f)] public float strength = 1f;
        [Range(0.001f, 0.25f)] public float edgeSoftness = 0.05f;
    }

    [Header("References")]
    public TilePlacer tilePlacer;

    [Header("Folder Settings")]
    public string tilesFolder = "Terrain_Tiles";
    public string textureFolder = "tiles_rgb";

    [Header("Fallback Layer")]
    [Tooltip("Used where no surface rule matches strongly enough.")]
    public TerrainLayer fallbackLayer;

    [Header("Surface Rules")]
    public SurfaceRule[] surfaceRules =
    {
        new()
        {
            ruleName = "Grass / Vegetation",
            minHue = 0.22f,
            maxHue = 0.46f,
            minSaturation = 0.16f,
            maxSaturation = 1f,
            minValue = 0.14f,
            maxValue = 0.78f,
            strength = 1.15f,
            edgeSoftness = 0.04f
        },
        new()
        {
            ruleName = "Dry Field / Yellow Farmland",
            minHue = 0.09f,
            maxHue = 0.18f,
            minSaturation = 0.20f,
            maxSaturation = 0.58f,
            minValue = 0.30f,
            maxValue = 0.78f,
            strength = 0.9f,
            edgeSoftness = 0.035f
        },
        new()
        {
            ruleName = "Concrete / Urban Ground",
            minHue = 0f,
            maxHue = 1f,
            minSaturation = 0f,
            maxSaturation = 0.16f,
            minValue = 0.48f,
            maxValue = 0.95f,
            strength = 0.85f,
            edgeSoftness = 0.03f
        },
        new()
        {
            ruleName = "Bare Soil / Brown Field",
            minHue = 0.00f,
            maxHue = 0.10f,
            minSaturation = 0.14f,
            maxSaturation = 0.55f,
            minValue = 0.20f,
            maxValue = 0.68f,
            strength = 0.65f,
            edgeSoftness = 0.04f
        }
    };

    [Header("Blend Settings")]
    [Range(0f, 1f)]
    public float fallbackMinimumWeight = 0.35f;

    [Range(0.001f, 0.5f)]
    public float minimumTotalRuleScore = 0.08f;

    private void Reset()
    {
        LoadIslahiyePreset();
    }

    [ContextMenu("Load Islahiye Preset")]
    public void LoadIslahiyePreset()
    {
        surfaceRules = new SurfaceRule[]
        {
            new()
            {
                ruleName = "Grass / Vegetation",
                minHue = 0.22f,
                maxHue = 0.46f,
                minSaturation = 0.16f,
                maxSaturation = 1f,
                minValue = 0.14f,
                maxValue = 0.78f,
                strength = 1.15f,
                edgeSoftness = 0.04f
            },
            new()
            {
                ruleName = "Dry Field / Yellow Farmland",
                minHue = 0.09f,
                maxHue = 0.18f,
                minSaturation = 0.20f,
                maxSaturation = 0.58f,
                minValue = 0.30f,
                maxValue = 0.78f,
                strength = 0.9f,
                edgeSoftness = 0.035f
            },
            new()
            {
                ruleName = "Concrete / Urban Ground",
                minHue = 0f,
                maxHue = 1f,
                minSaturation = 0f,
                maxSaturation = 0.16f,
                minValue = 0.48f,
                maxValue = 0.95f,
                strength = 0.85f,
                edgeSoftness = 0.03f
            },
            new()
            {
                ruleName = "Bare Soil / Brown Field",
                minHue = 0.00f,
                maxHue = 0.10f,
                minSaturation = 0.14f,
                maxSaturation = 0.55f,
                minValue = 0.20f,
                maxValue = 0.68f,
                strength = 0.65f,
                edgeSoftness = 0.04f
            }
        };

        fallbackMinimumWeight = 0.35f;
        minimumTotalRuleScore = 0.08f;
    }

    public void ApplyMaterialMasks()
    {
        if (tilePlacer == null || tilePlacer.tiles == null || tilePlacer.tiles.Count == 0)
        {
            Debug.LogError("AdvancedTerrainMaterialPainter: TilePlacer not found or terrains have not been created yet.");
            return;
        }

        if (fallbackLayer == null)
        {
            Debug.LogError("AdvancedTerrainMaterialPainter: Please assign a fallback Terrain Layer.");
            return;
        }

        List<SurfaceRule> activeRules = GetActiveRules();
        if (activeRules.Count == 0)
        {
            Debug.LogError("AdvancedTerrainMaterialPainter: Please assign at least one Surface Rule with a Terrain Layer.");
            return;
        }

        TerrainLayer[] terrainLayers = BuildTerrainLayers(activeRules);

        foreach (var tile in tilePlacer.tiles)
        {
            if (tile.terrain == null)
            {
                continue;
            }

            string texPath = $"{tilesFolder}/{textureFolder}/{tile.terrain.name}";
            Texture2D colorMap = Resources.Load<Texture2D>(texPath);

            if (colorMap == null)
            {
                Debug.LogWarning($"AdvancedTerrainMaterialPainter: Texture not found -> {texPath}");
                continue;
            }

            TerrainData terrainData = tile.terrain.terrainData;
            terrainData.terrainLayers = terrainLayers;

            int alphaWidth = terrainData.alphamapWidth;
            int alphaHeight = terrainData.alphamapHeight;
            int layerCount = terrainLayers.Length;
            float[,,] splatmapData = new float[alphaHeight, alphaWidth, layerCount];
            float[] ruleScores = new float[activeRules.Count];

            for (int y = 0; y < alphaHeight; y++)
            {
                for (int x = 0; x < alphaWidth; x++)
                {
                    float normX = (float)x / (alphaWidth - 1);
                    float normY = (float)y / (alphaHeight - 1);
                    Color pixel = colorMap.GetPixelBilinear(normX, normY);

                    Color.RGBToHSV(pixel, out float hue, out float saturation, out float value);
                    WriteSurfaceWeights(splatmapData, ruleScores, x, y, activeRules, hue, saturation, value);
                }
            }

            terrainData.SetAlphamaps(0, 0, splatmapData);
        }

        Debug.Log("AdvancedTerrainMaterialPainter: Terrain painted successfully with advanced surface rules.");
    }

    public void RevertToSatelliteImage()
    {
        if (tilePlacer == null || tilePlacer.tiles == null)
        {
            return;
        }

        foreach (var tile in tilePlacer.tiles)
        {
            if (tile.terrain == null)
            {
                continue;
            }

            string texPath = $"{tilesFolder}/{textureFolder}/{tile.terrain.name}";
            Texture2D colorMap = Resources.Load<Texture2D>(texPath);

            if (colorMap == null)
            {
                Debug.LogWarning($"AdvancedTerrainMaterialPainter: Texture not found -> {texPath}");
                continue;
            }

            TerrainData terrainData = tile.terrain.terrainData;
            TerrainLayer satelliteLayer = new()
            {
                diffuseTexture = colorMap,
                tileSize = new Vector2(terrainData.size.x, terrainData.size.z)
            };

            terrainData.terrainLayers = new[] { satelliteLayer };

            int alphaWidth = terrainData.alphamapWidth;
            int alphaHeight = terrainData.alphamapHeight;
            float[,,] splatmapData = new float[alphaHeight, alphaWidth, 1];

            for (int y = 0; y < alphaHeight; y++)
            {
                for (int x = 0; x < alphaWidth; x++)
                {
                    splatmapData[y, x, 0] = 1f;
                }
            }

            terrainData.SetAlphamaps(0, 0, splatmapData);
        }

        Debug.Log("AdvancedTerrainMaterialPainter: All terrains reverted to original satellite images.");
    }

    private List<SurfaceRule> GetActiveRules()
    {
        List<SurfaceRule> activeRules = new();

        if (surfaceRules == null)
        {
            return activeRules;
        }

        foreach (SurfaceRule rule in surfaceRules)
        {
            if (rule != null && rule.terrainLayer != null)
            {
                activeRules.Add(rule);
            }
        }

        return activeRules;
    }

    private TerrainLayer[] BuildTerrainLayers(List<SurfaceRule> activeRules)
    {
        TerrainLayer[] terrainLayers = new TerrainLayer[activeRules.Count + 1];
        terrainLayers[0] = fallbackLayer;

        for (int i = 0; i < activeRules.Count; i++)
        {
            terrainLayers[i + 1] = activeRules[i].terrainLayer;
        }

        return terrainLayers;
    }

    private void WriteSurfaceWeights(float[,,] splatmapData, float[] ruleScores, int x, int y, List<SurfaceRule> activeRules, float hue, float saturation, float value)
    {
        float totalScore = 0f;

        for (int i = 0; i < activeRules.Count; i++)
        {
            SurfaceRule rule = activeRules[i];
            float score = GetRuleScore(rule, hue, saturation, value) * rule.strength;
            ruleScores[i] = score;
            totalScore += score;
        }

        if (totalScore < minimumTotalRuleScore)
        {
            splatmapData[y, x, 0] = 1f;
            return;
        }

        float fallbackWeight = Mathf.Clamp01(fallbackMinimumWeight * (1f - Mathf.Clamp01(totalScore)));
        float ruleWeightSpace = 1f - fallbackWeight;

        splatmapData[y, x, 0] = fallbackWeight;

        for (int i = 0; i < activeRules.Count; i++)
        {
            splatmapData[y, x, i + 1] = (ruleScores[i] / totalScore) * ruleWeightSpace;
        }
    }

    private float GetRuleScore(SurfaceRule rule, float hue, float saturation, float value)
    {
        float hueScore = GetHueScore(hue, rule.minHue, rule.maxHue, rule.edgeSoftness);
        float saturationScore = GetRangeScore(saturation, rule.minSaturation, rule.maxSaturation, rule.edgeSoftness);
        float valueScore = GetRangeScore(value, rule.minValue, rule.maxValue, rule.edgeSoftness);

        return hueScore * saturationScore * valueScore;
    }

    private float GetHueScore(float hue, float minHue, float maxHue, float softness)
    {
        if (minHue <= maxHue)
        {
            return GetRangeScore(hue, minHue, maxHue, softness);
        }

        float lowerRangeScore = GetRangeScore(hue, minHue, 1f, softness);
        float upperRangeScore = GetRangeScore(hue, 0f, maxHue, softness);
        return Mathf.Max(lowerRangeScore, upperRangeScore);
    }

    private float GetRangeScore(float value, float min, float max, float softness)
    {
        float lower = Mathf.InverseLerp(min - softness, min + softness, value);
        float upper = 1f - Mathf.InverseLerp(max - softness, max + softness, value);

        return Mathf.Clamp01(Mathf.Min(lower, upper));
    }
}
