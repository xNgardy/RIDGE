using System;
using System.Collections.Generic;
using UnityEditor;

using UnityEngine;

[ExecuteInEditMode]
public class TilePlacer : MonoBehaviour
{
    [Serializable]
    public class Tile
    {
        [SerializeField]
        private int x, y, size;
        [SerializeField]
        private float max_height;
        [SerializeField]
        private float ground_width, ground_height;

        [HideInInspector]
        public Terrain terrain;
        [HideInInspector]
        public TerrainData terrainData;

        private GameObject gameObject;
        private string name;

        private float globalMin = 0f;
        private int globalNodata = 0;
        public void SetGlobalMin(float v) => globalMin = v;
        public void SetGlobalNodata(int v) => globalNodata = v;

        public Tile(int x, int y, int size, float max_height, float ground_width, float ground_height)
        {
            SetFields(x, y, size, max_height, ground_width, ground_height);

            var newTerrainData = new TerrainData();
            newTerrainData.heightmapResolution = size + 1;
            // Use ground dimensions directly - mathematically correct from georeferenced data
            newTerrainData.size = new Vector3(ground_width, max_height, ground_height);

            gameObject = Terrain.CreateTerrainGameObject(newTerrainData);
            gameObject.name = name;

            terrainData = newTerrainData;
            terrain = gameObject.GetComponent<Terrain>();
        }

        public void SetFields(int x, int y, int size, float max_height, float ground_width, float ground_height)
        {
            this.x = x;
            this.y = y;
            this.size = size;
            this.max_height = max_height;
            this.ground_width = ground_width;
            this.ground_height = ground_height;

            name = $"tile_{x}_{y}";
        }

        public void SetHeightmap(TextAsset rawFile)
        {
            byte[] fileData = rawFile.bytes;

            int width = size + 1;
            int height = size + 1;
            float[,] heightMap = new float[height, width]; // note: Unity expects [y,x]

            // Each height sample is 2 bytes (16-bit)
            int index = 0;
            for (int yy = 0; yy < height; yy++)
            {
                for (int xx = 0; xx < width; xx++)
                {
                    if (index + 1 >= fileData.Length)
                    {
                        heightMap[yy, xx] = 0f;
                        index += 2;
                        continue;
                    }

                    // Read UNSIGNED 16-bit little-endian
                    ushort uval = System.BitConverter.ToUInt16(fileData, index);

                    // handle nodata (should be 0 now)
                    if (uval == 0)
                    {
                        heightMap[yy, xx] = 0f;
                    }
                    else
                    {
                        // Exporter stores uint16 scaled to full 0..65535 representing normalized 0..1
                        // Decode to normalized [0..1] by dividing by 65535f.
                        float norm = (float)uval / 65535f;
                        heightMap[yy, xx] = Mathf.Clamp01(norm);
                    }
                    index += 2;
                }
            }

            // Apply to terrain - size already set in constructor, but ensure consistency
            terrain.terrainData.heightmapResolution = width;
            terrain.terrainData.size = new Vector3(ground_width, max_height, ground_height);
            terrain.terrainData.SetHeights(0, 0, heightMap);
        }

        public void SetTerrainTexture(Texture2D texture)
        {
            if (texture == null)
                throw new ArgumentNullException(nameof(texture));

            texture.wrapMode = TextureWrapMode.Clamp;

            TerrainLayer layer = new TerrainLayer { diffuseTexture = texture, tileSize = new Vector2(ground_width, ground_height) };
            TerrainLayer[] layers = new TerrainLayer[] { layer };
            Debug.Log("Terrain: " + (terrain != null));
            terrain.terrainData.terrainLayers = layers;
        }

        public void SetGameObjectParent(Transform parent)
        {
            gameObject.transform.SetParent(parent);
        }
    }

    [Serializable]
    public class TileDataPackage
    {
        public float global_min_elevation;
        public float global_max_elevation;
        public float global_max_height_after_scale;
        public int global_nodata;
        [Serializable]
        public class TileData
        {
            public int tile_x, tile_y, texture_width, heightmap_width;
            public float tile_max_height, ground_width_meters, ground_height_meters;
        }
        public TileData[] tiles;
    }

    [HideInInspector] public int TileCount => tiles.Count;

    [SerializeField]
    public List<Tile> tiles;

    [SerializeField]
    public int xTileCount, yTileCount;

    // REMOVED: pixelResolution field - no longer needed!

    [SerializeField]
    string tilesFolder, heightFolder, textureFolder, metadataFile, buildingsMetadataFile;

    [HideInInspector]
    public BuildingPlacer buildingPlacer;

    public void PlaceTiles()
    {
        Debug.Log("Started Placing");
        for (int i = 0; i < tiles.Count; i++)
        {
            tiles[i].terrain.transform.position = new Vector3((i % xTileCount) * tiles[i].terrain.terrainData.size.x, 0, (i / xTileCount) * -tiles[i].terrain.terrainData.size.z);
            Debug.Log($"Placed {tiles[i].terrain.name}.");

            tiles[i].terrain.SetNeighbors((i % xTileCount == 0) ? null : tiles[i - 1].terrain,
                                    (i < xTileCount) ? null : tiles[i - xTileCount].terrain,
                                    (i % xTileCount == xTileCount - 1) ? null : tiles[i + 1].terrain,
                                    (i >= xTileCount * (yTileCount - 1)) ? null : tiles[i + xTileCount].terrain);
            Debug.Log($"Set the Neighbours of {tiles[i].terrain.name}.");

            tiles[i].terrain.Flush();
        }
        Debug.Log("Finished placing.");
    }

    public void ReadJson()
    {
        var tileDataPackage = new TileDataPackage();

        Debug.Log("Tiles Folder: " + tilesFolder);
        Debug.Log("Metadata File: " + metadataFile);

        TextAsset json = Resources.Load<TextAsset>($"{tilesFolder}/{metadataFile}");

        Debug.Log(json.text);

        EditorJsonUtility.FromJsonOverwrite(json.text, tileDataPackage);

        float globalMin = tileDataPackage.global_min_elevation;
        int globalNodata = tileDataPackage.global_nodata;

        Debug.Log("!!!!!!!! Tile data list !!!!!!!!");

        foreach (var tile in tileDataPackage.tiles)
        {
            // No more pixelResolution - using ground dimensions directly
            Tile tilePiece = new(
                tile.tile_x,
                tile.tile_y,
                tile.texture_width,
                tile.tile_max_height,
                tile.ground_width_meters,
                tile.ground_height_meters
            );

            tilePiece.SetGameObjectParent(transform);
            tilePiece.SetGlobalMin(globalMin);
            tilePiece.SetGlobalNodata(globalNodata);

            if (tilePiece.terrain == null)
            {
                Debug.Log("Terrain is null");
                throw new NullReferenceException();
            }

            Debug.Log("Terrain: " + tilePiece.terrain);

            Debug.Log(textureFolder);
            Texture2D texture = Resources.Load<Texture2D>($"{tilesFolder}/{textureFolder}/tile_{tile.tile_x}_{tile.tile_y}");
            tilePiece.SetTerrainTexture(texture);

            Debug.Log(heightFolder);
            Debug.Log($"{tile.tile_x}");
            Debug.Log($"{tile.tile_y}");

            TextAsset rawFile = Resources.Load<TextAsset>($"{tilesFolder}/{heightFolder}/tile_{tile.tile_x}_{tile.tile_y}");

            Debug.Log("Raw File: " + (rawFile != null) + "\n\n" + rawFile.text);

            tilePiece.SetHeightmap(rawFile);

            tiles.Add(tilePiece);
            Debug.Log($"Added tile_{tile.tile_x}_{tile.tile_y}.");
        }
    }

    public void DeleteTiles()
    {
        tiles.Clear();

        for (int i = transform.childCount - 1; i >= 0; i--)
        {
            var child = transform.GetChild(i).gameObject;
            DestroyImmediate(child);
        }

        EditorUtility.SetDirty(this);
        SceneView.RepaintAll();

    }

    [Serializable]
    private class DictionaryWrapper { public int global_nodata; }

    #region Editor Initialization
    private void Reset()
    {
        InitializeInEditor();
    }

    private void OnEnable()
    {
#if UNITY_EDITOR
        UnityEditor.EditorApplication.delayCall += InitializeInEditor;
#else
        InitializeInEditor();
#endif
    }

    private void OnValidate()
    {
        InitializeInEditor();
    }

    private void InitializeInEditor()
    {
        if (buildingPlacer == null)
        {
            buildingPlacer = new BuildingPlacer(this, tilesFolder, buildingsMetadataFile);
        }

        if (tiles == null)
        {
            tiles = new List<Tile>();
        }
    }
    #endregion
}