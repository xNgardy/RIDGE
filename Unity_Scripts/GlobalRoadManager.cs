using UnityEngine;
using System.Collections.Generic;

[ExecuteInEditMode]
public class GlobalRoadManager : MonoBehaviour
{
    [Header("Temel Ayarlar")]
    public Transform tileRoot;

    [Header("Materyaller")]
    public Material asphaltMaterial; // Siyah Asfalt
    public Material dirtMaterial;    // Kahverengi Toprak

    [Header("3D Yol Kalınlıkları (YENİ)")]
    [Tooltip("Asfalt ne kadar kabarık olsun? (Metre)")]
    public float asphaltThickness = 0.3f;

    [Tooltip("Toprak ne kadar kabarık olsun?")]
    public float dirtThickness = 0.05f;

    [Header("Genel Ayarlar")]
    public float roadWidthScale = 1.0f;
    [Range(0.01f, 1f)] public float threshold = 0.5f;

    [Header("--- KONTROL ---")]
    [Tooltip("Tik atinca calisir!")]
    public bool TIKLA_VE_INSA_ET = false;

    void OnValidate()
    {
        if (TIKLA_VE_INSA_ET)
        {
            BuildAllRoads();
            TIKLA_VE_INSA_ET = false;
        }
    }

    public void BuildAllRoads()
    {
        Debug.Log("🚀 3D YOL İNŞAATI BAŞLADI...");

        if (tileRoot == null) { Debug.LogError("Tile Root bos!"); return; }

        Terrain[] allTerrains = tileRoot.GetComponentsInChildren<Terrain>();
        int successCount = 0;

        foreach (Terrain t in allTerrains)
        {
            string tName = t.gameObject.name;
            int x = 0; int y = 0;

            if (!ParseTileName(tName, out x, out y)) continue;

            string searchName = "tile_" + x + "_" + y + "_mask";

#if UNITY_EDITOR
            string[] guids = UnityEditor.AssetDatabase.FindAssets(searchName + " t:Texture2D");
            
            if (guids.Length == 0) continue; 

            string assetPath = UnityEditor.AssetDatabase.GUIDToAssetPath(guids[0]);
            Texture2D maskTexture = UnityEditor.AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);

            EnsureReadWriteEnabled(assetPath);

            MaskToRoad script = t.gameObject.GetComponent<MaskToRoad>();
            if (script == null) script = t.gameObject.AddComponent<MaskToRoad>();

            // --- DEĞERLERİ AKTAR ---
            script.targetTerrain = t;
            script.roadMask = maskTexture;
            
            // Materyalleri gönder
            script.asphaltMaterial = asphaltMaterial;
            script.dirtMaterial = dirtMaterial;
            
            // --- YENİ EKLENEN KALINLIKLARI GÖNDER ---
            script.asphaltThickness = asphaltThickness; // Burası eksikti, şimdi geldi!
            script.dirtThickness = dirtThickness;       // Burası eksikti!
            
            // Diğer ayarlar
            script.roadWidthScale = roadWidthScale;
            script.threshold = threshold;

            script.GenerateMeshFromMask();
            successCount++;
#endif
        }

        Debug.Log("✅ İŞLEM TAMAM! " + successCount + " adet araziye 3D Yollar yapıldı.");
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

    private void EnsureReadWriteEnabled(string path)
    {
#if UNITY_EDITOR
        UnityEditor.TextureImporter importer = UnityEditor.AssetImporter.GetAtPath(path) as UnityEditor.TextureImporter;
        if (importer != null && !importer.isReadable)
        {
            importer.isReadable = true;
            UnityEditor.AssetDatabase.ImportAsset(path); 
        }
#endif
    }
    public void DeleteAllRoads()
    {
        Debug.Log("🗑️ Yollar siliniyor...");
        if (tileRoot == null) return;

        MaskToRoad[] allScripts = tileRoot.GetComponentsInChildren<MaskToRoad>();
        foreach (MaskToRoad script in allScripts)
        {
            script.ClearRoads();
        }
        Debug.Log("✅ TEMİZLİK TAMAM!");
    }
}