using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

/// <summary>
/// Python'dan gelen polyline JSON'larını okur ve her yol için DÜZ mesh şeridi üretir.
/// Pikselli görünüm olmaz çünkü artık pixel değil, vektör çizgi işliyoruz.
/// GlobalRoadManager'daki MaskToRoad yerine bunu çağır.
/// </summary>
[ExecuteInEditMode]
public class RoadLineBuilder : MonoBehaviour
{
    [Header("Refs (GlobalRoadManager doldurur)")]
    public Terrain targetTerrain;
    public TextAsset roadsJson;   // tile_x_y_roads.json

    [Header("Materials")]
    public Material asphaltMaterial;
    public Material dirtMaterial;

    [Header("3D Settings")]
    public float asphaltThickness = 0.3f;
    public float dirtThickness = 0.05f;

    [Header("Width")]
    public float widthScale = 1.0f;       // Python'dan gelen genişliği çarpan
    public float yOffset = 0.02f;         // Terrain'e gömülmesin diye küçük offset

    [Header("Sampling")]
    [Tooltip("Yol boyunca her kaç metrede bir terrain yüksekliği örneklensin")]
    public float sampleSpacingM = 2.0f;

    [Serializable] public class RoadPoint  { public float u; public float v; }
    [Serializable] public class RoadEntry  { public string type; public float width_m; public RoadPoint[] points; }
    [Serializable] public class RoadsFile  { public int tile_x; public int tile_y; public float width_m; public float height_m; public RoadEntry[] roads; }

    int roadLayer;

    public void ClearRoads()
    {
        foreach (string n in new[] { "Road_Asphalt", "Road_Dirt",
                                     "Road_Mesh", "Road_From_Mask" })
        {
            var t = transform.Find(n);
            if (t) DestroyImmediate(t.gameObject);
        }
    }

    public void BuildRoads()
    {
        roadLayer = LayerMask.NameToLayer("Road");
        ClearRoads();

        if (targetTerrain == null || roadsJson == null) return;

        RoadsFile data = JsonUtility.FromJson<RoadsFile>(roadsJson.text);
        if (data == null || data.roads == null || data.roads.Length == 0) return;

        TerrainData td = targetTerrain.terrainData;
        float tW = td.size.x;
        float tL = td.size.z;

        // Her tip için vertex buffer
        var vA = new List<Vector3>(); var tA = new List<int>(); var uA = new List<Vector2>();
        var vD = new List<Vector3>(); var tD = new List<int>(); var uD = new List<Vector2>();

        foreach (var road in data.roads)
        {
            if (road.points == null || road.points.Length < 2) continue;
            bool isAsphalt = road.type == "asphalt";
            float halfW = (road.width_m * widthScale) * 0.5f;
            float thick = isAsphalt ? asphaltThickness : dirtThickness;

            // 1) Normalize (u,v) -> dünya koordinatı + terrain üzerinde resample
            List<Vector3> poly = BuildWorldPolyline(road.points, tW, tL, sampleSpacingM);
            if (poly.Count < 2) continue;

            var v = isAsphalt ? vA : vD;
            var t = isAsphalt ? tA : tD;
            var uv = isAsphalt ? uA : uD;

            EmitRibbon(poly, halfW, thick, v, t, uv);
        }

        CreateMesh("Road_Asphalt", vA, tA, uA, asphaltMaterial);
        CreateMesh("Road_Dirt",    vD, tD, uD, dirtMaterial);
    }

    // --- polyline -> world-space (terrain yüksekliği örneklenmiş, eşit aralıklarla) ---
    List<Vector3> BuildWorldPolyline(RoadPoint[] pts, float tW, float tL, float spacing)
    {
        // Önce raw world noktaları (y=0)
        var raw = new List<Vector3>(pts.Length);
        Vector3 tPos = targetTerrain.transform.position;
        for (int i = 0; i < pts.Length; i++)
        {
            float wx = pts[i].u * tW;
            float wz = pts[i].v * tL;
            raw.Add(new Vector3(wx, 0f, wz));
        }

        // Sonra eşit aralıklarla resample et (köşeleri de koru)
        var resampled = new List<Vector3> { raw[0] };
        for (int i = 1; i < raw.Count; i++)
        {
            Vector3 a = raw[i - 1];
            Vector3 b = raw[i];
            float dist = Vector3.Distance(a, b);
            int steps = Mathf.Max(1, Mathf.FloorToInt(dist / spacing));
            for (int s = 1; s <= steps; s++)
            {
                float t = (float)s / steps;
                resampled.Add(Vector3.Lerp(a, b, t));
            }
        }

        // Terrain yüksekliğini örnekle
        for (int i = 0; i < resampled.Count; i++)
        {
            Vector3 p = resampled[i];
            Vector3 world = tPos + p;
            float h = targetTerrain.SampleHeight(world);
            // Yerel koordinat döndür (mesh parent = bu obje = terrain GO)
            resampled[i] = new Vector3(p.x, h + yOffset, p.z);
        }
        return resampled;
    }

    // --- Polyline boyunca "miter join"li şerit (üst yüzey + yan duvarlar) ---
    void EmitRibbon(List<Vector3> poly, float halfW, float thickness,
                    List<Vector3> verts, List<int> tris, List<Vector2> uvs)
    {
        int n = poly.Count;

        // Her nokta için "right" yönü (yatay düzlemde perpendicular)
        Vector3[] leftTop  = new Vector3[n];
        Vector3[] rightTop = new Vector3[n];

        for (int i = 0; i < n; i++)
        {
            Vector3 fwd;
            if (i == 0)       fwd = poly[1] - poly[0];
            else if (i == n-1) fwd = poly[n-1] - poly[n-2];
            else
            {
                Vector3 a = (poly[i]   - poly[i-1]).normalized;
                Vector3 b = (poly[i+1] - poly[i]  ).normalized;
                fwd = (a + b); // miter (ortalaması)
            }
            fwd.y = 0f;
            if (fwd.sqrMagnitude < 1e-6f) fwd = Vector3.forward;
            fwd.Normalize();

            // Yatay sağ = fwd'yi +Y etrafında 90° döndür
            Vector3 right = new Vector3(fwd.z, 0f, -fwd.x);

            // Miter uzunluğu düzeltmesi (keskin köşelerde şişmesin)
            float miterLen = halfW;
            if (i > 0 && i < n-1)
            {
                Vector3 a = (poly[i]   - poly[i-1]).normalized; a.y = 0; a.Normalize();
                Vector3 b = (poly[i+1] - poly[i]  ).normalized; b.y = 0; b.Normalize();
                float dot = Vector3.Dot(a, b);
                float denom = Mathf.Max(0.2f, Mathf.Sqrt((1f + dot) * 0.5f));
                miterLen = halfW / denom;
                miterLen = Mathf.Min(miterLen, halfW * 3f);
            }

            Vector3 top = poly[i] + Vector3.up * thickness;
            leftTop[i]  = top - right * miterLen;
            rightTop[i] = top + right * miterLen;
        }

        // --- Üst yüzey (top strip) ---
        int baseIdx = verts.Count;
        for (int i = 0; i < n; i++)
        {
            verts.Add(leftTop[i]);
            verts.Add(rightTop[i]);
            float v = (float)i / Mathf.Max(1, n - 1);
            uvs.Add(new Vector2(0f, v));
            uvs.Add(new Vector2(1f, v));
        }
        for (int i = 0; i < n - 1; i++)
        {
            int a = baseIdx + i * 2;
            int b = a + 1;
            int c = a + 2;
            int d = a + 3;
            // iki üçgen
            tris.Add(a); tris.Add(c); tris.Add(b);
            tris.Add(b); tris.Add(c); tris.Add(d);
        }

        // --- Yan duvarlar (sol ve sağ) ---
        Vector3 down = Vector3.down * thickness;

        // Sol duvar
        int leftBase = verts.Count;
        for (int i = 0; i < n; i++)
        {
            verts.Add(leftTop[i]);
            verts.Add(leftTop[i] + down);
            float v = (float)i / Mathf.Max(1, n - 1);
            uvs.Add(new Vector2(0f, v));
            uvs.Add(new Vector2(1f, v));
        }
        for (int i = 0; i < n - 1; i++)
        {
            int a = leftBase + i * 2;
            int b = a + 1;
            int c = a + 2;
            int d = a + 3;
            // normal dışa dönük olsun (sol tarafa)
            tris.Add(a); tris.Add(b); tris.Add(c);
            tris.Add(b); tris.Add(d); tris.Add(c);
        }

        // Sağ duvar
        int rightBase = verts.Count;
        for (int i = 0; i < n; i++)
        {
            verts.Add(rightTop[i]);
            verts.Add(rightTop[i] + down);
            float v = (float)i / Mathf.Max(1, n - 1);
            uvs.Add(new Vector2(0f, v));
            uvs.Add(new Vector2(1f, v));
        }
        for (int i = 0; i < n - 1; i++)
        {
            int a = rightBase + i * 2;
            int b = a + 1;
            int c = a + 2;
            int d = a + 3;
            // ters winding (dışa bakan taraf diğer yön)
            tris.Add(a); tris.Add(c); tris.Add(b);
            tris.Add(b); tris.Add(c); tris.Add(d);
        }

        // Uç kapakları (başlangıç + bitiş) - isteğe bağlı, şerit açıkta kalmasın
        AddEndCap(verts, tris, uvs, leftTop[0],       rightTop[0],       down, true);
        AddEndCap(verts, tris, uvs, leftTop[n - 1],   rightTop[n - 1],   down, false);
    }

    void AddEndCap(List<Vector3> v, List<int> t, List<Vector2> uv,
                   Vector3 lt, Vector3 rt, Vector3 down, bool start)
    {
        int idx = v.Count;
        v.Add(lt);          // 0
        v.Add(rt);          // 1
        v.Add(lt + down);   // 2
        v.Add(rt + down);   // 3
        uv.Add(new Vector2(0,1)); uv.Add(new Vector2(1,1));
        uv.Add(new Vector2(0,0)); uv.Add(new Vector2(1,0));
        if (start)
        {
            t.Add(idx); t.Add(idx + 2); t.Add(idx + 1);
            t.Add(idx + 1); t.Add(idx + 2); t.Add(idx + 3);
        }
        else
        {
            t.Add(idx); t.Add(idx + 1); t.Add(idx + 2);
            t.Add(idx + 1); t.Add(idx + 3); t.Add(idx + 2);
        }
    }

    void CreateMesh(string name, List<Vector3> v, List<int> t, List<Vector2> uv, Material mat)
    {
        if (v.Count == 0) return;
        GameObject go = new GameObject(name);
        go.transform.parent = transform;
        go.transform.localPosition = Vector3.zero;
        go.layer = roadLayer;

        var mf = go.AddComponent<MeshFilter>();
        var mr = go.AddComponent<MeshRenderer>();
        mr.sharedMaterial = mat;

        var m = new Mesh();
        if (v.Count > 65000) m.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
        m.SetVertices(v);
        m.SetTriangles(t, 0);
        m.SetUVs(0, uv);
        m.RecalculateNormals();
        m.RecalculateBounds();
        mf.sharedMesh = m;
    }
}
