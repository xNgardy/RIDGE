using System;
using System.Collections.Generic;
using UnityEngine;

#if UNITY_EDITOR
using UnityEditor;
#endif

[ExecuteInEditMode]
public class NDVITreePlacer : MonoBehaviour
{
    [Header("References")]
    [SerializeField] private TilePlacer tilePlacer;
    
    [Header("Folder Settings")]
    [SerializeField] private string tilesFolder = "Terrain_Tiles";
    [SerializeField] private string treesFolder = "tiles_trees";
    
    [Header("Tree Prefabs")]
    [SerializeField] private GameObject[] treePrefabs;
    [SerializeField] private bool useTerrainTrees = true; 
    
    [Header("Placement Settings")]
    [Range(0f, 1f)]
    [SerializeField] private float densityMultiplier = 1f;
    [SerializeField] private float minScale = 0.8f;
    [SerializeField] private float maxScale = 1.2f;
    
    [Header("Advanced Settings")]
    [SerializeField] private bool useMaskTextures = false; 
    [SerializeField] private int maskSampleStep = 4; 
    [Range(0, 255)]
    [SerializeField] private int maskThreshold = 128; 
    
    [Header("Debug")]
    [SerializeField] private bool showDebugInfo = true;
    
    private int totalTreesPlaced = 0;
    private int treeLayer;
    
    public void PlaceAllTrees()
    {
        treeLayer = LayerMask.NameToLayer("Tree");
        if (tilePlacer == null)
        {
            Debug.LogError("NDVITreePlacer: TilePlacer reference is not set!");
            return;
        }
        
        if (tilePlacer.tiles == null || tilePlacer.tiles.Count == 0)
        {
            Debug.LogError("NDVITreePlacer: No tiles found in TilePlacer. Run ReadJson first.");
            return;
        }
        
        if (treePrefabs == null || treePrefabs.Length == 0)
        {
            Debug.LogError("NDVITreePlacer: No tree prefabs assigned!");
            return;
        }
        
        totalTreesPlaced = 0;
        
        if (useMaskTextures)
        {
            PlaceTreesFromMasks();
        }
        else
        {
            PlaceTreesFromJSON();
        }
        
        Debug.Log($"NDVITreePlacer: Placed {totalTreesPlaced} trees total.");
    }
    

    private void PlaceTreesFromJSON()
    {
        string jsonPath = $"{tilesFolder}/{treesFolder}/tree_positions".Replace(".json", string.Empty);
        TextAsset jsonFile = Resources.Load<TextAsset>(jsonPath);

        if (jsonFile == null)
        {
            Debug.LogError($"NDVITreePlacer: Could not load Resources/{jsonPath}.json. Set Trees Folder to 'tiles_trees' for the current project data.");
            return;
        }

        Debug.LogWarning("Loaded tree_positions.json bytes: " + jsonFile.text.Length);
        
        var positionsDict = ParseTreePositionsJSON(jsonFile.text);
        
        foreach (var tile in tilePlacer.tiles)
        {
            string tileName = $"tile_{tile.terrain.name.Split('_')[1]}_{tile.terrain.name.Split('_')[2]}";
            
            if (!positionsDict.ContainsKey(tileName))
            {
                tileName = tile.terrain.name;
            }
            
            if (positionsDict.ContainsKey(tileName))
            {
                var positions = positionsDict[tileName];
                PlaceTreesOnTile(tile, positions);
            }
            else if (showDebugInfo)
            {
                Debug.LogWarning($"NDVITreePlacer: No tree data found for {tileName}");
            }
            Debug.Log("Terrain name in scene: " + tile.terrain.name);
        }
    }
    
    private Dictionary<string, List<Vector2>> ParseTreePositionsJSON(string json)
    {
        var result = new Dictionary<string, List<Vector2>>();

        json = json.Trim();
        if (json.StartsWith("{")) json = json.Substring(1);
        if (json.EndsWith("}")) json = json.Substring(0, json.Length - 1);
        
        int depth = 0;
        int lastSplit = 0;
        List<string> entries = new List<string>();
        
        for (int i = 0; i < json.Length; i++)
        {
            char c = json[i];
            if (c == '[') depth++;
            else if (c == ']') depth--;
            else if (c == ',' && depth == 0)
            {
                entries.Add(json.Substring(lastSplit, i - lastSplit));
                lastSplit = i + 1;
            }
        }
        if (lastSplit < json.Length)
            entries.Add(json.Substring(lastSplit));
        
        foreach (var entry in entries)
        {
            int colonIdx = entry.IndexOf(':');
            if (colonIdx < 0) continue;
            
            string key = entry.Substring(0, colonIdx).Trim().Trim('"');
            string value = entry.Substring(colonIdx + 1).Trim();
            
            var positions = ParsePositionsArray(value);
            result[key] = positions;
        }
        
        return result;
    }
    
    private List<Vector2> ParsePositionsArray(string arrayJson)
    {
        var positions = new List<Vector2>();
        
        arrayJson = arrayJson.Trim();
        if (arrayJson.StartsWith("[")) arrayJson = arrayJson.Substring(1);
        if (arrayJson.EndsWith("]")) arrayJson = arrayJson.Substring(0, arrayJson.Length - 1);
        
        if (string.IsNullOrWhiteSpace(arrayJson))
            return positions;
        
        int start = 0;
        while (start < arrayJson.Length)
        {
            int objStart = arrayJson.IndexOf('{', start);
            if (objStart < 0) break;
            
            int objEnd = arrayJson.IndexOf('}', objStart);
            if (objEnd < 0) break;
            
            string obj = arrayJson.Substring(objStart + 1, objEnd - objStart - 1);
            
            float x = 0, y = 0;
            var parts = obj.Split(',');
            foreach (var part in parts)
            {
                var kv = part.Split(':');
                if (kv.Length == 2)
                {
                    string k = kv[0].Trim().Trim('"');
                    float v = float.Parse(kv[1].Trim(), System.Globalization.CultureInfo.InvariantCulture);
                    if (k == "x") x = v;
                    else if (k == "y") y = v;
                }
            }
            
            positions.Add(new Vector2(x, y));
            start = objEnd + 1;
        }
        
        return positions;
    }
    
    private void PlaceTreesFromMasks()
    {
        foreach (var tile in tilePlacer.tiles)
        {
            string tileName = tile.terrain.name;
            string maskPath = $"{tilesFolder}/{treesFolder}/{tileName}_mask";
            
            Texture2D mask = Resources.Load<Texture2D>(maskPath);
            
            if (mask == null)
            {
                if (showDebugInfo)
                    Debug.LogWarning($"NDVITreePlacer: No mask found at {maskPath}");
                continue;
            }
            
            var positions = SamplePositionsFromMask(mask);
            PlaceTreesOnTile(tile, positions);
        }
    }
    
    private List<Vector2> SamplePositionsFromMask(Texture2D mask)
    {
        var positions = new List<Vector2>();
        
        int width = mask.width;
        int height = mask.height;
        
        for (int y = 0; y < height; y += maskSampleStep)
        {
            for (int x = 0; x < width; x += maskSampleStep)
            {
                Color pixel = mask.GetPixel(x, y);
                int value = (int)(pixel.grayscale * 255);
                
                if (value >= maskThreshold)
                {
                    float normX = (x + UnityEngine.Random.Range(-maskSampleStep * 0.5f, maskSampleStep * 0.5f)) / width;
                    float normY = (y + UnityEngine.Random.Range(-maskSampleStep * 0.5f, maskSampleStep * 0.5f)) / height;
                    
                    normX = Mathf.Clamp01(normX);
                    normY = Mathf.Clamp01(normY);
                    
                    positions.Add(new Vector2(normX, normY));
                }
            }
        }
        
        return positions;
    }
    
    private void PlaceTreesOnTile(TilePlacer.Tile tile, List<Vector2> normalizedPositions)
    {
        if (tile.terrain == null || tile.terrainData == null)
        {
            Debug.LogWarning($"NDVITreePlacer: Terrain or TerrainData is null for tile");
            return;
        }
        
        Terrain terrain = tile.terrain;
        TerrainData terrainData = tile.terrainData;
        
        if (useTerrainTrees)
        {
            SetupTreePrototypes(terrainData);
        }
        
        List<TreeInstance> treeInstances = new List<TreeInstance>();
        int placedCount = 0;
        
        foreach (var pos in normalizedPositions)
        {
            if (UnityEngine.Random.value > densityMultiplier)
                continue;
            
            float worldX = pos.x;
            float worldZ = pos.y; 
            
            float terrainHeight = terrainData.GetInterpolatedHeight(worldX, worldZ) / terrainData.size.y;
            
            if (useTerrainTrees)
            {
                TreeInstance tree = new TreeInstance();
                tree.position = new Vector3(worldX, terrainHeight, worldZ);
                tree.widthScale = UnityEngine.Random.Range(minScale, maxScale);
                tree.heightScale = UnityEngine.Random.Range(minScale, maxScale);
                tree.rotation = UnityEngine.Random.Range(0f, 360f) * Mathf.Deg2Rad;
                tree.color = Color.white;
                tree.lightmapColor = Color.white;
                tree.prototypeIndex = UnityEngine.Random.Range(0, treePrefabs.Length);
                
                treeInstances.Add(tree);
            }
            else
            {
                Vector3 worldPos = terrain.transform.position + new Vector3(
                    worldX * terrainData.size.x,
                    terrainData.GetInterpolatedHeight(worldX, worldZ),
                    worldZ * terrainData.size.z
                );
                
                GameObject prefab = treePrefabs[UnityEngine.Random.Range(0, treePrefabs.Length)];
                GameObject treeObj = Instantiate(prefab, worldPos, Quaternion.Euler(0, UnityEngine.Random.Range(0f, 360f), 0));
                treeObj.transform.SetParent(terrain.transform);
                treeObj.layer = treeLayer;
                float scale = UnityEngine.Random.Range(minScale, maxScale);
                treeObj.transform.localScale = Vector3.one * scale;
            }
            
            placedCount++;
        }
        
        if (useTerrainTrees && treeInstances.Count > 0)
        {
            terrainData.SetTreeInstances(treeInstances.ToArray(), true);
        }
        
        totalTreesPlaced += placedCount;
        
        if (showDebugInfo)
            Debug.Log($"NDVITreePlacer: Placed {placedCount} trees on {terrain.name}");
    }

    private void SetupTreePrototypes(TerrainData terrainData)
    {
        TreePrototype[] prototypes = new TreePrototype[treePrefabs.Length];
        
        for (int i = 0; i < treePrefabs.Length; i++)
        {
            prototypes[i] = new TreePrototype();
            prototypes[i].prefab = treePrefabs[i];
        }
        
        terrainData.treePrototypes = prototypes;
    }

    public void ClearAllTrees()
    {
        if (tilePlacer == null || tilePlacer.tiles == null)
            return;
        
        foreach (var tile in tilePlacer.tiles)
        {
            if (tile.terrain != null && tile.terrainData != null)
            {
                tile.terrainData.SetTreeInstances(new TreeInstance[0], true);
                
                for (int i = tile.terrain.transform.childCount - 1; i >= 0; i--)
                {
                    var child = tile.terrain.transform.GetChild(i);
                    if (IsTreeObject(child.gameObject))
                    {
                        DestroyImmediate(child.gameObject);
                    }
                }
            }
        }
        
        totalTreesPlaced = 0;
        Debug.Log("NDVITreePlacer: Cleared all trees.");
    }
    
    private bool IsTreeObject(GameObject obj)
    {
        if (treePrefabs == null) return false;
        
        foreach (var prefab in treePrefabs)
        {
            if (prefab != null && obj.name.StartsWith(prefab.name))
                return true;
        }
        return false;
    }
 
    public void SetTerrainTreesVisible(bool visible)
    {
        if (tilePlacer == null || tilePlacer.tiles == null)
            return;

        foreach (var tile in tilePlacer.tiles)
        {
            if (tile.terrain != null)
            {
                tile.terrain.drawTreesAndFoliage = visible;
            }
        }
    }
    
    #if UNITY_EDITOR
    private void Reset()
    {
        if (tilePlacer == null)
            tilePlacer = FindObjectOfType<TilePlacer>();
    }
    #endif
}
