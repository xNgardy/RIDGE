using UnityEngine;
using System.Collections.Generic;

[ExecuteInEditMode]
public class GlobalRoadManager : MonoBehaviour
{
    [Header("Tile Root")]
    public Transform tileRoot;

    [Header("Materials")]
    public Material asphaltMaterial;
    public Material dirtMaterial;

    [Header("3D Road Thicknesses")]
    public float asphaltThickness = 0.3f;
    public float dirtThickness = 0.05f;

    [Header("Settings")]
    public float widthScale = 1.0f;
    public float yOffset = 0.02f;
    public float sampleSpacingM = 2.0f;

    public void BuildAllRoads()
    {
        if (tileRoot == null) { Debug.LogError("Tile Root is empty"); return; }

        Terrain[] allTerrains = tileRoot.GetComponentsInChildren<Terrain>();
        int successCount = 0;

        foreach (Terrain t in allTerrains)
        {
            int x, y;
            if (!ParseTileName(t.gameObject.name, out x, out y)) continue;

            string searchName = "tile_" + x + "_" + y + "_roads";

#if UNITY_EDITOR
            // JSON'u ara (TextAsset olarak import edilmiş olmalı)
            string[] guids = UnityEditor.AssetDatabase.FindAssets(searchName + " t:TextAsset");
            if (guids.Length == 0)
            {
                Debug.LogWarning($"JSON bulunamadı: {searchName}");
                continue;
            }

            string assetPath = UnityEditor.AssetDatabase.GUIDToAssetPath(guids[0]);
            TextAsset jsonAsset = UnityEditor.AssetDatabase.LoadAssetAtPath<TextAsset>(assetPath);
            if (jsonAsset == null) continue;

            RoadLineBuilder rb = t.gameObject.GetComponent<RoadLineBuilder>();
            if (rb == null) rb = t.gameObject.AddComponent<RoadLineBuilder>();

            rb.targetTerrain     = t;
            rb.roadsJson         = jsonAsset;
            rb.asphaltMaterial   = asphaltMaterial;
            rb.dirtMaterial      = dirtMaterial;
            rb.asphaltThickness  = asphaltThickness;
            rb.dirtThickness     = dirtThickness;
            rb.widthScale        = widthScale;
            rb.yOffset           = yOffset;
            rb.sampleSpacingM    = sampleSpacingM;

            rb.BuildRoads();
            successCount++;
#endif
        }

        Debug.Log("Done " + successCount);
    }

    public void DeleteAllRoads()
    {
        if (tileRoot == null) return;
        RoadLineBuilder[] all = tileRoot.GetComponentsInChildren<RoadLineBuilder>();
        foreach (var r in all) r.ClearRoads();
        Debug.Log("Roads cleared");
    }

    private bool ParseTileName(string name, out int x, out int y)
    {
        x = 0; y = 0;
        try
        {
            string[] parts = name.Split(new char[] { '_', ' ' });
            if (parts.Length >= 3)
            {
                x = int.Parse(parts[parts.Length - 2]);
                y = int.Parse(parts[parts.Length - 1]);
                return true;
            }
            return false;
        }
        catch { return false; }
    }
}
