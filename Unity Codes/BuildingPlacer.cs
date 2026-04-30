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

            foreach (var building in tileBuildingData.buildings)
            {
                Vector3 buildingPosition = new Vector3(building.center_x, 0, tile.terrain.terrainData.size.z - building.center_y);

                GameObject buildingObject = GameObject.CreatePrimitive(PrimitiveType.Cube);

                buildingPosition = buildingPosition + tile.terrain.transform.position;
                buildingPosition.y = tile.terrain.SampleHeight(buildingPosition);

                buildingObject.transform.position = buildingPosition;
                buildingObject.transform.localScale = new Vector3(building.width, 10, building.height);
                buildingObject.transform.Rotate(Vector3.up, building.rotation_degrees);
                buildingObject.name = $"Building_{building.id}";
                buildingObject.transform.parent = tile.terrain.transform;

                Debug.Log($"Placed Building ID {building.id} on Tile ({tileBuildingData.tile_x}, {tileBuildingData.tile_y}).");
            }
        }
    }

}
