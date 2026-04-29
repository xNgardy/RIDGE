using UnityEngine;
using System.Collections.Generic;

[ExecuteInEditMode]
public class MaskToRoad : MonoBehaviour
{
    public Terrain targetTerrain;
    public Texture2D roadMask;

    [Header("Materyaller")]
    public Material asphaltMaterial;
    public Material dirtMaterial;

    [Header("3D Ayarlarý")]
    [Tooltip("Asfaltýn yerden yüksekliði (Kalýnlýðý)")]
    public float asphaltThickness = 0.3f;

    [Tooltip("Topraðýn yerden yüksekliði")]
    public float dirtThickness = 0.05f;

    [Header("Diðer Ayarlar")]
    public float roadWidthScale = 1.0f;
    [Range(0.01f, 1f)] public float threshold = 0.5f;

    private int roadLayer;

    public void ClearRoads()
    {
        // Eski isimleri ve yeni isimleri kontrol edip siliyoruz
        if (transform.Find("Road_Mesh")) DestroyImmediate(transform.Find("Road_Mesh").gameObject);
        if (transform.Find("Road_Asphalt")) DestroyImmediate(transform.Find("Road_Asphalt").gameObject);
        if (transform.Find("Road_Dirt")) DestroyImmediate(transform.Find("Road_Dirt").gameObject);
        if (transform.Find("Road_From_Mask")) DestroyImmediate(transform.Find("Road_From_Mask").gameObject);
    }

    public void GenerateMeshFromMask()
    {
        roadLayer = LayerMask.NameToLayer("Road");

        // Temizlik
        if (transform.Find("Road_Asphalt")) DestroyImmediate(transform.Find("Road_Asphalt").gameObject);
        if (transform.Find("Road_Dirt")) DestroyImmediate(transform.Find("Road_Dirt").gameObject);
        if (transform.Find("Road_From_Mask")) DestroyImmediate(transform.Find("Road_From_Mask").gameObject);

        if (targetTerrain == null || roadMask == null) return;
        if (!roadMask.isReadable) return;

        TerrainData tData = targetTerrain.terrainData;
        float tWidth = tData.size.x;
        float tLength = tData.size.z;
        Vector3 tPos = targetTerrain.transform.position;

        int w = roadMask.width;
        int h = roadMask.height;

        // Asfalt ve Toprak için ayrý listeler
        List<Vector3> vertsAsphalt = new List<Vector3>();
        List<int> trisAsphalt = new List<int>();
        List<Vector2> uvsAsphalt = new List<Vector2>();

        List<Vector3> vertsDirt = new List<Vector3>();
        List<int> trisDirt = new List<int>();
        List<Vector2> uvsDirt = new List<Vector2>();

        // Piksel boyutu (Dünya koordinatlarýnda)
        float pixelSizeX = (tWidth / w) * roadWidthScale;
        float pixelSizeZ = (tLength / h) * roadWidthScale;

        int step = 1;

        for (int y = 0; y < h; y += step)
        {
            for (int x = 0; x < w; x += step)
            {
                Color pixelColor = roadMask.GetPixel(x, y);
                bool isAsphalt = pixelColor.r > threshold;
                bool isDirt = pixelColor.g > threshold;

                if (!isAsphalt && !isDirt) continue;

                // --- MERKEZ KOORDÝNAT HESABI ---
                float normX = (float)x / w;
                float normY = (float)y / h;
                float worldX = normX * tWidth;
                float worldZ = normY * tLength;

                // Kenar Korumasý
                if (worldX < 1 || worldX > tWidth - 1) continue;
                if (worldZ < 1 || worldZ > tLength - 1) continue;

                Vector3 worldPosSample = tPos + new Vector3(worldX, 0, worldZ);
                float terrainY = targetTerrain.SampleHeight(worldPosSample);

                // Hangi listeyi kullanacaðýz?
                List<Vector3> vList = isAsphalt ? vertsAsphalt : vertsDirt;
                List<int> tList = isAsphalt ? trisAsphalt : trisDirt;
                List<Vector2> uvList = isAsphalt ? uvsAsphalt : uvsDirt;

                // Kalýnlýk ne olacak?
                float thickness = isAsphalt ? asphaltThickness : dirtThickness;

                // Bloðun Merkezi (Tabaný arazide, tavaný thickness kadar yukarýda)
                Vector3 basePos = new Vector3(worldX, terrainY, worldZ);

                // --- 1. TAVAN (ÜST YÜZEY) ---
                // Burasý her zaman çizilir
                AddFaceUp(vList, tList, uvList, basePos, thickness, pixelSizeX, pixelSizeZ);

                // --- 2. YAN DUVARLAR (Sadece komþu boþsa çizilir - OPTÝMÝZASYON) ---
                // Sað taraf boþ mu?
                if (ShouldDrawWall(x + 1, y, w, h, isAsphalt))
                    AddFaceRight(vList, tList, uvList, basePos, thickness, pixelSizeX, pixelSizeZ);

                // Sol taraf boþ mu?
                if (ShouldDrawWall(x - 1, y, w, h, isAsphalt))
                    AddFaceLeft(vList, tList, uvList, basePos, thickness, pixelSizeX, pixelSizeZ);

                // Ýleri taraf boþ mu?
                if (ShouldDrawWall(x, y + 1, w, h, isAsphalt))
                    AddFaceForward(vList, tList, uvList, basePos, thickness, pixelSizeX, pixelSizeZ);

                // Geri taraf boþ mu?
                if (ShouldDrawWall(x, y - 1, w, h, isAsphalt))
                    AddFaceBack(vList, tList, uvList, basePos, thickness, pixelSizeX, pixelSizeZ);
            }
        }

        CreateMeshObj("Road_Asphalt", vertsAsphalt, trisAsphalt, uvsAsphalt, asphaltMaterial);
        CreateMeshObj("Road_Dirt", vertsDirt, trisDirt, uvsDirt, dirtMaterial);

        Debug.Log($"{name}: 3D Yol tamamlandý!");
    }

    // Komþu kontrolü: Eðer komþu pikselde yol yoksa, oraya duvar ör.
    bool ShouldDrawWall(int x, int y, int w, int h, bool lookingForAsphalt)
    {
        if (x < 0 || x >= w || y < 0 || y >= h) return true; // Harita dýþýysa duvar ör
        Color c = roadMask.GetPixel(x, y);

        // Eðer ben Asfaltsam, yanýmda Asfalt yoksa duvar ör.
        if (lookingForAsphalt) return !(c.r > threshold);

        // Eðer ben Topraksam, yanýmda Toprak yoksa duvar ör.
        else return !(c.g > threshold);
    }

    // --- YÜZEY ÇÝZME FONKSÝYONLARI ---
    void AddFaceUp(List<Vector3> v, List<int> t, List<Vector2> uv, Vector3 center, float h, float sx, float sz)
    {
        Vector3 c = center + Vector3.up * h; // Tavana çýk
        Vector3 v0 = c + new Vector3(-sx / 2, 0, -sz / 2);
        Vector3 v1 = c + new Vector3(sx / 2, 0, -sz / 2);
        Vector3 v2 = c + new Vector3(-sx / 2, 0, sz / 2);
        Vector3 v3 = c + new Vector3(sx / 2, 0, sz / 2);
        AddQuad(v, t, uv, v0, v1, v2, v3);
    }

    void AddFaceRight(List<Vector3> v, List<int> t, List<Vector2> uv, Vector3 center, float h, float sx, float sz)
    {
        Vector3 baseR = center + new Vector3(sx / 2, 0, 0);
        Vector3 v0 = baseR + new Vector3(0, 0, -sz / 2);      // Alt Arka
        Vector3 v1 = baseR + new Vector3(0, 0, sz / 2);      // Alt Ön
        Vector3 v2 = baseR + new Vector3(0, h, -sz / 2);      // Üst Arka
        Vector3 v3 = baseR + new Vector3(0, h, sz / 2);      // Üst Ön
        AddQuad(v, t, uv, v0, v1, v2, v3);
    }

    void AddFaceLeft(List<Vector3> v, List<int> t, List<Vector2> uv, Vector3 center, float h, float sx, float sz)
    {
        Vector3 baseL = center + new Vector3(-sx / 2, 0, 0);
        Vector3 v0 = baseL + new Vector3(0, 0, sz / 2);
        Vector3 v1 = baseL + new Vector3(0, 0, -sz / 2);
        Vector3 v2 = baseL + new Vector3(0, h, sz / 2);
        Vector3 v3 = baseL + new Vector3(0, h, -sz / 2);
        AddQuad(v, t, uv, v0, v1, v2, v3);
    }

    void AddFaceForward(List<Vector3> v, List<int> t, List<Vector2> uv, Vector3 center, float h, float sx, float sz)
    {
        Vector3 baseF = center + new Vector3(0, 0, sz / 2);
        Vector3 v0 = baseF + new Vector3(sx / 2, 0, 0);
        Vector3 v1 = baseF + new Vector3(-sx / 2, 0, 0);
        Vector3 v2 = baseF + new Vector3(sx / 2, h, 0);
        Vector3 v3 = baseF + new Vector3(-sx / 2, h, 0);
        AddQuad(v, t, uv, v0, v1, v2, v3);
    }

    void AddFaceBack(List<Vector3> v, List<int> t, List<Vector2> uv, Vector3 center, float h, float sx, float sz)
    {
        Vector3 baseB = center + new Vector3(0, 0, -sz / 2);
        Vector3 v0 = baseB + new Vector3(-sx / 2, 0, 0);
        Vector3 v1 = baseB + new Vector3(sx / 2, 0, 0);
        Vector3 v2 = baseB + new Vector3(-sx / 2, h, 0);
        Vector3 v3 = baseB + new Vector3(sx / 2, h, 0);
        AddQuad(v, t, uv, v0, v1, v2, v3);
    }

    void AddQuad(List<Vector3> v, List<int> t, List<Vector2> uv, Vector3 v0, Vector3 v1, Vector3 v2, Vector3 v3)
    {
        int idx = v.Count;
        v.Add(v0); v.Add(v1); v.Add(v2); v.Add(v3);
        t.Add(idx + 0); t.Add(idx + 2); t.Add(idx + 1);
        t.Add(idx + 2); t.Add(idx + 3); t.Add(idx + 1);
        uv.Add(new Vector2(0, 0)); uv.Add(new Vector2(1, 0));
        uv.Add(new Vector2(0, 1)); uv.Add(new Vector2(1, 1));
    }

    void CreateMeshObj(string name, List<Vector3> v, List<int> t, List<Vector2> uv, Material mat)
    {
        if (v.Count == 0) return;
        GameObject go = new GameObject(name);
        go.transform.parent = this.transform;
        go.transform.localPosition = Vector3.zero;

        MeshFilter mf = go.AddComponent<MeshFilter>();
        MeshRenderer mr = go.AddComponent<MeshRenderer>();
        mr.material = mat;

        go.layer = roadLayer;

        Mesh m = new Mesh();
        if (v.Count > 65000) m.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
        m.vertices = v.ToArray(); m.triangles = t.ToArray(); m.uv = uv.ToArray();
        m.RecalculateNormals();
        mf.mesh = m;
    }
}