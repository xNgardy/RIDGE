using UnityEngine;
using System.Collections.Generic;

[ExecuteInEditMode]
public class TerrainMaterialPainter : MonoBehaviour
{
    [Header("References")]
    public TilePlacer tilePlacer;
    
    [Header("Folder Settings")]
    public string tilesFolder = "Terrain_Tiles";
    public string textureFolder = "tiles_rgb"; // Folder containing PNGs output by tiler.py

    [Header("Materials (Splatmap)")]
    public TerrainLayer dirtLayer;  // Dirt/Rock texture
    public TerrainLayer grassLayer; // Grass/Vegetation texture

    [Header("Advanced Color Settings (HSV)")]
    [Range(0f, 1f)]
    [Tooltip("Starting hue for green detection. Lower values (e.g. 0.08) include yellowing grass.")]
    public float minGreenHue = 0.08f; 

    [Range(0f, 1f)]
    [Tooltip("Ending hue for green detection. Higher values include bluish/dark forests.")]
    public float maxGreenHue = 0.45f;

    [Range(0f, 1f)]
    [Tooltip("Minimum saturation threshold. Prevents grey concrete/asphalt from being detected as green.")]
    public float minSaturation = 0.15f;
    
    [Range(1f, 10f)]
    [Tooltip("Smoothness of the blend transition between dirt and grass.")]
    public float blendSoftness = 5f;

    /// <summary>
    /// Paints Dirt and Grass materials based on satellite image colors.
    /// </summary>
    public void ApplyMaterialMasks()
    {
        if (tilePlacer == null || tilePlacer.tiles == null || tilePlacer.tiles.Count == 0)
        {
            Debug.LogError("TerrainMaterialPainter: TilePlacer not found or terrains have not been created yet.");
            return;
        }

        if (dirtLayer == null || grassLayer == null)
        {
            Debug.LogError("TerrainMaterialPainter: Please assign Dirt and Grass Terrain Layers in the Inspector.");
            return;
        }

        foreach (var tile in tilePlacer.tiles)
        {
            if (tile.terrain == null) continue;

            // Load satellite image from Resources folder
            string texPath = $"{tilesFolder}/{textureFolder}/{tile.terrain.name}";
            Texture2D colorMap = Resources.Load<Texture2D>(texPath);
            
            if (colorMap == null)
            {
                Debug.LogWarning($"TerrainMaterialPainter: Texture not found -> {texPath}");
                continue;
            }

            TerrainData tData = tile.terrain.terrainData;
            
            // Assign the 2 material layers to the terrain
            tData.terrainLayers = new TerrainLayer[] { dirtLayer, grassLayer };

            int alphaWidth = tData.alphamapWidth;
            int alphaHeight = tData.alphamapHeight;
            float[,,] splatmapData = new float[alphaHeight, alphaWidth, 2];

            for (int y = 0; y < alphaHeight; y++)
            {
                for (int x = 0; x < alphaWidth; x++)
                {
                    float normX = (float)x / (alphaWidth - 1);
                    float normY = (float)y / (alphaHeight - 1);

                    // Sample the satellite pixel at this point
                    Color pixel = colorMap.GetPixelBilinear(normX, normY);

                    // Convert RGB to HSV (H=Hue, S=Saturation, V=Brightness)
                    float h, s, v;
                    Color.RGBToHSV(pixel, out h, out s, out v);

                    float grassWeight = 0f;

                    // If the pixel falls within the green/yellow hue range and is not too faded/grey
                    if (h >= minGreenHue && h <= maxGreenHue && s >= minSaturation)
                    {
                        // Increase grass weight based on saturation and brightness
                        grassWeight = Mathf.Clamp01(s * v * blendSoftness); 
                    }

                    // Write weights to the splatmap (index 0 = Dirt, index 1 = Grass)
                    splatmapData[y, x, 0] = 1f - grassWeight; 
                    splatmapData[y, x, 1] = grassWeight;      
                }
            }

            // Apply the splatmap to the terrain
            tData.SetAlphamaps(0, 0, splatmapData);
        }
        
        Debug.Log("TerrainMaterialPainter: Terrain painted successfully based on satellite colors!");
    }

    /// <summary>
    /// Reverts all terrains back to the original satellite image texture.
    /// </summary>
    public void RevertToSatelliteImage()
    {
        if (tilePlacer == null || tilePlacer.tiles == null) return;

        foreach (var tile in tilePlacer.tiles)
        {
            if (tile.terrain == null) continue;

            string texPath = $"{tilesFolder}/{textureFolder}/{tile.terrain.name}";
            Texture2D colorMap = Resources.Load<Texture2D>(texPath);
            
            if (colorMap == null) continue;

            TerrainData tData = tile.terrain.terrainData;

            TerrainLayer satLayer = new TerrainLayer 
            { 
                diffuseTexture = colorMap, 
                tileSize = new Vector2(tData.size.x, tData.size.z) 
            };
            
            // Replace terrain layers with the single satellite layer
            tData.terrainLayers = new TerrainLayer[] { satLayer };

            // Reset the alphamap so the single layer gets full weight everywhere.
            // Without this, the old splatmap data from ApplyMaterialMasks would persist,
            // causing areas that had partial weights for the (now removed) second layer
            // to render incorrectly (black patches or missing textures).
            int alphaWidth = tData.alphamapWidth;
            int alphaHeight = tData.alphamapHeight;
            float[,,] splatmapData = new float[alphaHeight, alphaWidth, 1];

            for (int y = 0; y < alphaHeight; y++)
            {
                for (int x = 0; x < alphaWidth; x++)
                {
                    splatmapData[y, x, 0] = 1f; // 100% weight to the satellite layer
                }
            }

            tData.SetAlphamaps(0, 0, splatmapData);
        }
        Debug.Log("TerrainMaterialPainter: All terrains reverted to original satellite image.");
    }
}