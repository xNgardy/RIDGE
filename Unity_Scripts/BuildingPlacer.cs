using System;
using UnityEditor;
using UnityEngine;

public class BuildingPlacer
{
    [Serializable]
    public class TilesBuildingList
    {
        public TileBuildingData[] tileBuildingsList;
        [Serializable]
        public class TileBuildingData
        {
            public int tile_x, tile_y, total_buildings;
            public int image_width, image_height;
            public BuildingData[] buildings;
            [Serializable]
            public class BuildingData
            {
                public int id;
                public float center_x, center_y, width, height, rotation_degrees, confidence;
            }
        }
    }

    private TilePlacer tilePlacer;
    private string tilesFolder, buildingMetadataFile;
    private TilesBuildingList tilesBuildingList;
    private int buildingLayer = LayerMask.NameToLayer("Building");

    public BuildingPlacer(TilePlacer tilePlacer, string tilesFolder, string buildingMetadataFile)
    {
        this.tilePlacer = tilePlacer;
        this.tilesFolder = tilesFolder;
        this.buildingMetadataFile = buildingMetadataFile;
    }

    public void ReadJson()
    {
        tilesBuildingList = new TilesBuildingList();

        TextAsset json = Resources.Load<TextAsset>($"{tilesFolder}/{buildingMetadataFile}");

        Debug.Log(json.text);
        EditorJsonUtility.FromJsonOverwrite(json.text, tilesBuildingList);
    }

    public void PlaceBuildings()
    {
        if (tilesBuildingList == null)
        {
            Debug.LogError("JSON wasn't read yet. Call ReadJson() first.");
            return;
        }

        foreach (var tileBuildingData in tilesBuildingList.tileBuildingsList)
        {
            int tileIndex = tileBuildingData.tile_y * tilePlacer.xTileCount + tileBuildingData.tile_x;

            if (tileIndex < 0 || tileIndex >= tilePlacer.TileCount)
            {
                Debug.LogWarning($"Tile index {tileIndex} is out of bounds.");
                continue;
            }

            TilePlacer.Tile tile = tilePlacer.tiles[tileIndex];

            foreach (Transform child in tile.terrain.transform)
            {
                GameObject.DestroyImmediate(child.gameObject);
            }

            // Get terrain size in world units (meters)
            float terrainWidth = tile.terrain.terrainData.size.x;
            float terrainHeight = tile.terrain.terrainData.size.z;

            // Get image size in pixels
            float imageWidth = tileBuildingData.image_width;
            float imageHeight = tileBuildingData.image_height;

            // Calculate scale factors (meters per pixel)
            float scaleX = terrainWidth / imageWidth;
            float scaleZ = terrainHeight / imageHeight;

            foreach (var building in tileBuildingData.buildings)
            {
                // Convert pixel coordinates to world coordinates
                float worldX = building.center_x * scaleX;
                float worldZ = terrainHeight - (building.center_y * scaleZ);  // Flip Y axis

                Vector3 buildingPosition = new Vector3(worldX, 0, worldZ);
                buildingPosition = buildingPosition + tile.terrain.transform.position;
                buildingPosition.y = tile.terrain.SampleHeight(buildingPosition);

                GameObject buildingObject = GameObject.CreatePrimitive(PrimitiveType.Cube);
                buildingObject.transform.position = buildingPosition;
                buildingObject.layer = buildingLayer;

                // Scale building dimensions from pixels to meters
                float buildingWidth = building.width * scaleX;
                float buildingDepth = building.height * scaleZ;
                buildingObject.transform.localScale = new Vector3(buildingWidth, 10, buildingDepth);

                buildingObject.transform.Rotate(Vector3.up, building.rotation_degrees);
                buildingObject.name = $"Building_{building.id}";
                buildingObject.transform.parent = tile.terrain.transform;

                Debug.Log($"Placed Building ID {building.id} on Tile ({tileBuildingData.tile_x}, {tileBuildingData.tile_y}).");
            }
        }
    }
}